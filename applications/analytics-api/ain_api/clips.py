"""Clips of what an alert saw, with the boxes drawn into the frames.

This is the one place server-side drawing is correct. The live view draws
its overlay in the browser - that is what makes it toggleable per viewer,
lets one stream serve everybody and costs no GPU - but a browser overlay is
a rendering, not a file. An mp4 pulled out of here and opened in VLC has to
carry its own annotation.

The frames come from MediaMTX's playback server, which serves the H.264 it
already re-encoded for the browser rather than the H.265 source, so a clip
needs no second transcode to be playable. Savant is not involved: it would
want the GPU, and the GPU is running inference.
"""

import bisect
import datetime
import logging
import pathlib
import re
import subprocess
import tempfile
import threading

import cv2
import httpx
import numpy
from clickhouse_connect.driver import client as ch_client

from ain_analytics import config
from ain_analytics import settings
from ain_api import feeds
from ain_api import objects
from ain_api import queries

_LOG = logging.getLogger(__name__)

_OPTIONS = settings.get()

_BOX_COLOR = (64, 220, 64)
_TEXT_COLOR = (16, 16, 16)

# Rendering a clip decodes, redraws and re-encodes on the CPU, and the same
# host is running the transcodes and a GPU pipeline.
_RENDERS = threading.Semaphore(_OPTIONS.clip_concurrency)


# An event id becomes a filename, so it is allowed to be exactly what
# `events._event_id` produces and nothing else. FastAPI's path converter
# already refuses a slash, but "the router happens to stop it" is a weaker
# guarantee than "the name is checked where it is used as a path".
_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


# Bumped whenever the drawing changes. Clips are kept in the bucket under
# their event id, so without this a re-render returns the copy made by the
# previous version of this code and the fix appears not to have worked. Old
# objects need no cleanup: the bucket's lifecycle rule expires them.
_RENDER_VERSION = 2


class ClipError(Exception):
	"""There is no video for the window asked for."""


def clip_window(
	start: datetime.datetime, end: datetime.datetime | None
) -> queries.Window:
	"""Bounds the range a clip is cut from.

	Args:
		start: When the event began.
		end: When it ended, or None for a fixed-length clip.

	Returns:
		The range to fetch, capped at `settings.clip_max_seconds`.

	The cap is twenty minutes rather than two, because a clip has to be
	able to contain the thing it is evidence of. A long-wait alert fires
	on a queue wait measured in minutes and its clip should cover the
	wait; a two-minute ceiling silently truncated exactly the events
	most worth watching.
	"""
	finish = end or start + datetime.timedelta(
		seconds=_OPTIONS.clip_default_seconds
	)
	longest = start + datetime.timedelta(seconds=_OPTIONS.clip_max_seconds)
	return queries.Window(start=start, end=min(finish, longest))


def available(stream: str, scope: queries.Window) -> queries.Window | None:
	"""Trims a wanted range to the video that still exists.

	Args:
		stream: The MediaMTX path, which is not the camera id.
		scope: The range the event covers.

	Returns:
		The overlap with a recording, or None when nothing overlaps.

	Recording is a rolling window, so an event that ran for twenty
	minutes may have its first ten already deleted. Asking for the whole
	thing gets a 404 and shows the viewer nothing; asking for the half
	that exists shows them the half that exists, which is the more
	useful answer and the honest one.
	"""
	for start, seconds in feeds.recorded(stream):
		finish = start + datetime.timedelta(seconds=seconds)
		overlap_start = max(start, scope.start)
		overlap_end = min(finish, scope.end)
		if overlap_end > overlap_start:
			return queries.Window(start=overlap_start, end=overlap_end)
	return None


def _fetch(stream: str, scope: queries.Window, into: pathlib.Path) -> None:
	"""Pulls one time range out of MediaMTX's recordings.

	Args:
		stream: The MediaMTX path, which is not the camera id.
		scope: The range to cut.
		into: Where to write the mp4.

	Raises:
		ClipError: MediaMTX has no recording covering the range - most
			often because it is older than `recordDeleteAfter`.
	"""
	params = {
		'path': stream,
		'start': scope.start.isoformat().replace('+00:00', 'Z'),
		'duration': f'{scope.seconds:.3f}',
		'format': 'mp4',
	}
	try:
		with httpx.stream(
			'GET', f'{_OPTIONS.playback_url}/get', params=params, timeout=60.0
		) as response:
			if response.status_code != 200:
				response.read()
				raise ClipError(
					f'no recording for {stream} at {params["start"]} '
					f'({response.status_code}: {response.text[:200]})'
				)
			with into.open('wb') as handle:
				for chunk in response.iter_bytes():
					handle.write(chunk)
	except httpx.HTTPError as error:
		raise ClipError(f'playback server unreachable: {error}') from error
	if into.stat().st_size == 0:
		raise ClipError(f'playback returned an empty clip for {stream}')


def _boxes_by_offset(
	client: ch_client.Client, camera: str, scope: queries.Window
) -> dict[int, list[dict]]:
	"""Groups stored detections by the millisecond they belong to.

	Args:
		client: A connected ClickHouse client.
		camera: The camera id.
		scope: The clip's range.

	Returns:
		Objects keyed by milliseconds since the clip started, so a frame
		can find the nearest set without searching.

	The key is shifted by `clip_box_lag_ms`, because the two ends of this
	function are on different clocks. A detection is stamped by the source
	adapter after it has pulled the frame over RTSP and decoded it; the
	recording this is drawn onto is stamped by MediaMTX's recorder. Treating
	them as one clock drew every box where its subject had been a third of a
	second earlier - invisible on somebody sitting down, and half a person
	wide on anybody walking.
	"""
	frames = queries.overlay(client, camera, scope)
	origin = scope.start
	lag = _OPTIONS.clip_box_lag_ms
	grouped: dict[int, list[dict]] = {}
	for frame in frames:
		moment = datetime.datetime.fromisoformat(frame['ts'])
		# Minus the lag: a detection stamped `lag` after the moment it
		# describes belongs on the frame `lag` earlier in the clip.
		offset = round((moment - origin).total_seconds() * 1000) - lag
		grouped[offset] = frame['objects']
	return grouped


def _nearest(offsets: list[int], target: int) -> int | None:
	"""Finds the stored frame closest in time to a decoded one.

	Args:
		offsets: Every stored offset, ascending.
		target: The decoded frame's offset, in milliseconds.

	Returns:
		The closest offset within 100 ms, or None. The two clocks are
		the same clock - absolute timestamps on one side, MediaMTX's
		segment times on the other - but they are not sampled together,
		so a frame is matched rather than looked up.
	"""
	if not offsets:
		return None
	index = bisect.bisect_left(offsets, target)
	candidates = [
		offsets[position]
		for position in (index - 1, index)
		if 0 <= position < len(offsets)
	]
	best = min(candidates, key=lambda offset: abs(offset - target))
	return best if abs(best - target) <= 100 else None


def _draw(frame: numpy.ndarray, objects: list[dict]) -> None:
	"""Draws one frame's boxes into it, in place.

	Args:
		frame: The decoded BGR image.
		objects: Detections in normalised coordinates.
	"""
	height, width = frame.shape[:2]
	for obj in objects:
		half_w = obj['w'] * width / 2
		half_h = obj['h'] * height / 2
		center_x, center_y = obj['xc'] * width, obj['yc'] * height
		left, top = int(center_x - half_w), int(center_y - half_h)
		right, bottom = int(center_x + half_w), int(center_y + half_h)
		cv2.rectangle(frame, (left, top), (right, bottom), _BOX_COLOR, 2)
		label = f'{obj["label"]} {obj["track_id"]}'
		(text_w, text_h), _ = cv2.getTextSize(
			label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
		)
		cv2.rectangle(
			frame,
			(left, max(0, top - text_h - 6)),
			(left + text_w + 6, top),
			_BOX_COLOR,
			-1,
		)
		cv2.putText(
			frame,
			label,
			(left + 3, max(text_h, top - 4)),
			cv2.FONT_HERSHEY_SIMPLEX,
			0.45,
			_TEXT_COLOR,
			1,
			cv2.LINE_AA,
		)


def _encode(
	source: pathlib.Path,
	target: pathlib.Path,
	boxes: dict[int, list[dict]],
) -> None:
	"""Redraws a clip with its boxes burnt in.

	Args:
		source: The mp4 pulled from MediaMTX.
		target: Where to write the annotated mp4.
		boxes: Detections keyed by millisecond offset.

	Raises:
		ClipError: The source has no decodable video.

	OpenCV writes MPEG-4 Part 2, which VLC plays and no browser does, so
	the frames go out through ffmpeg instead - and to H.264, the same
	codec the tiles already play.
	"""
	capture = cv2.VideoCapture(str(source))
	if not capture.isOpened():
		raise ClipError(f'cannot decode {source.name}')
	fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
	width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
	height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
	if not width or not height:
		capture.release()
		raise ClipError(f'{source.name} has no video stream')

	offsets = sorted(boxes)
	command = [
		'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
		'-f', 'rawvideo', '-pix_fmt', 'bgr24',
		'-s', f'{width}x{height}', '-r', f'{fps:.4f}',
		'-i', 'pipe:0',
		'-an', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
		# The source is already capped at 2.5 Mbit/s, and this is watched in
		# a dialog a few hundred pixels wide. At the default CRF a
		# two-minute clip came to 34 MB, which is a long wait for something
		# the viewer glances at.
		'-crf', '28', '-maxrate', '1500k', '-bufsize', '3000k',
		# The browser has to be able to start playing before it has the
		# whole file.
		'-movflags', '+faststart',
		str(target),
	]
	encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
	index = 0
	try:
		while True:
			ok, frame = capture.read()
			if not ok:
				break
			matched = _nearest(offsets, round(index * 1000 / fps))
			if matched is not None:
				_draw(frame, boxes[matched])
			encoder.stdin.write(frame.tobytes())
			index += 1
	finally:
		capture.release()
		encoder.stdin.close()
		encoder.wait()
	if encoder.returncode != 0 or not target.exists():
		raise ClipError('ffmpeg failed to encode the clip')
	_LOG.info('rendered %s: %s frames', target.name, index)


def render(
	client: ch_client.Client,
	event_id: str,
	camera: str,
	scope: queries.Window,
) -> tuple[str, datetime.datetime]:
	"""Produces the clip for one event and returns where to fetch it.

	Args:
		client: A connected ClickHouse client.
		event_id: Names the object, so the same event renders once.
		camera: The camera id, as the catalogue names it.
		scope: The range to cut.

	Returns:
		A presigned URL for the annotated mp4, and when it expires.

	Raises:
		ClipError: The id is not one, there is no recording for the
			window, or it will not decode.
		objects.StoreError: The object store would not answer.

	Rendered once and kept in the bucket under the event id. The bucket
	expires it, so there is nothing here that prunes - and the browser
	fetches it from the store rather than through this service and the
	backend behind it.
	"""
	if not _ID.match(event_id):
		raise ClipError(f'not an event id: {event_id!r}')
	key = f'{event_id}.v{_RENDER_VERSION}.mp4'
	if objects.exists(key):
		return objects.link(key)

	stream = config.get().stream(camera)
	if stream is None:
		raise ClipError(f'unknown camera: {camera}')

	# Trimmed to the video that is still there. An event older than the
	# recording window has none, and that is a 404 with a reason rather
	# than a broken player.
	scope = available(stream, scope) or _missing(event_id, scope)
	with _RENDERS:
		# Checked again inside the semaphore: two requests for the same
		# clip queue here, and the second should upload nothing.
		if objects.exists(key):
			return objects.link(key)
		# A directory of this attempt's own, removed whatever happens.
		# Nothing outlives the render locally - the artefact is the
		# object, and a half-written file cannot be mistaken for one.
		with tempfile.TemporaryDirectory(prefix='clip-') as scratch:
			workspace = pathlib.Path(scratch)
			raw = workspace / 'source.mp4'
			rendered = workspace / 'annotated.mp4'
			_fetch(stream, scope, raw)
			_encode(raw, rendered, _boxes_by_offset(client, camera, scope))
			objects.put(key, rendered)
	return objects.link(key)


def _missing(event_id: str, scope: queries.Window) -> queries.Window:
	"""Refuses a clip whose video is gone.

	Args:
		event_id: The event asked for, for the message.
		scope: The range that has no recording.

	Raises:
		ClipError: Always. This exists so the caller can write
			`available(...) or _missing(...)` and keep the happy path on
			one line.
	"""
	raise ClipError(
		f'no recording for {event_id} at {scope.start.isoformat()}; '
		'it is older than the recording window'
	)
