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
import os
import pathlib
import re
import subprocess
import threading

import cv2
import httpx
import numpy
from clickhouse_connect.driver import client as ch_client

from ain_analytics import config
from ain_api import feeds
from ain_api import queries

_LOG = logging.getLogger(__name__)

_PLAYBACK = os.environ.get('AIN_PLAYBACK_URL', 'http://cameras:9996')
_CACHE = pathlib.Path(os.environ.get('AIN_CLIP_DIR', '/clips'))

# Long enough to see what happened, short enough that a hundred alerts do
# not fill the disk.
MAX_SECONDS = 120
DEFAULT_SECONDS = 20

_BOX_COLOR = (64, 220, 64)
_TEXT_COLOR = (16, 16, 16)

# Rendering a clip decodes, redraws and re-encodes on the CPU, and the same
# host is running ten transcodes and a GPU pipeline. Two at a time keeps a
# burst of alert clicks from starving the thing the clips are of.
_RENDERS = threading.Semaphore(
	int(os.environ.get('AIN_CLIP_CONCURRENCY', '2'))
)

# Oldest clips are dropped past this. They are a cache of something that can
# always be rendered again, not a store.
_CACHE_LIMIT = int(os.environ.get('AIN_CLIP_CACHE_FILES', '200'))


# An event id becomes a filename, so it is allowed to be exactly what
# `events._event_id` produces and nothing else. FastAPI's path converter
# already refuses a slash, but "the router happens to stop it" is a weaker
# guarantee than "the name is checked where it is used as a path".
_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


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
		The range to fetch, capped at `MAX_SECONDS`.
	"""
	finish = end or start + datetime.timedelta(seconds=DEFAULT_SECONDS)
	longest = start + datetime.timedelta(seconds=MAX_SECONDS)
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
			'GET', f'{_PLAYBACK}/get', params=params, timeout=60.0
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
	"""
	frames = queries.overlay(client, camera, scope)
	origin = scope.start
	grouped: dict[int, list[dict]] = {}
	for frame in frames:
		moment = datetime.datetime.fromisoformat(frame['ts'])
		offset = round((moment - origin).total_seconds() * 1000)
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
) -> pathlib.Path:
	"""Produces the clip for one event, or returns the cached one.

	Args:
		client: A connected ClickHouse client.
		event_id: Used as the filename, so the same event renders once.
		camera: The camera id, as the catalogue names it.
		scope: The range to cut.

	Returns:
		The path of the annotated mp4.

	Raises:
		ClipError: The id is not one, there is no recording for the
			window, or it will not decode.

	A clip is rendered once and cached under its event id. Concurrent
	renders are capped, and the cache is pruned: it holds copies of
	something that can always be made again.
	"""
	if not _ID.match(event_id):
		raise ClipError(f'not an event id: {event_id!r}')
	_CACHE.mkdir(parents=True, exist_ok=True)
	target = _CACHE / f'{event_id}.mp4'
	if target.exists() and target.stat().st_size > 0:
		return target

	stream = config.get().stream(camera)
	if stream is None:
		raise ClipError(f'unknown camera: {camera}')

	# Everything is written to names of this attempt's own and moved into
	# place at the end. Two requests for the same clip would otherwise have
	# one serving the other's half-written file, and a render that failed
	# would leave a broken mp4 that the size check above accepts forever.
	# Trimmed to the video that is still there. An event older than the
	# recording window has none, and that is a 404 with a reason rather
	# than a broken player.
	scope = available(stream, scope) or _missing(event_id, scope)
	unique = f'{event_id}.{os.getpid()}.{threading.get_ident()}'
	raw = _CACHE / f'{unique}.raw.mp4'
	partial = _CACHE / f'{unique}.part.mp4'
	with _RENDERS:
		if target.exists() and target.stat().st_size > 0:
			return target
		try:
			_fetch(stream, scope, raw)
			_encode(raw, partial, _boxes_by_offset(client, camera, scope))
			os.replace(partial, target)
			_prune()
		finally:
			raw.unlink(missing_ok=True)
			partial.unlink(missing_ok=True)
	return target


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


def _prune() -> None:
	"""Drops the oldest clips once the cache grows past its limit.

	Called while holding the render semaphore, so two renders finishing
	together do not both walk the directory - and every stat is guarded
	anyway, because a file can still vanish underneath this one: sorting
	by `path.stat().st_mtime` raises from inside the sort key, which
	takes down the request that had already produced its clip.
	"""
	aged = []
	for path in _CACHE.glob('*.mp4'):
		if '.part.' in path.name or '.raw.' in path.name:
			continue
		try:
			aged.append((path.stat().st_mtime, path))
		except OSError:
			continue
	aged.sort()
	for _, path in aged[: max(0, len(aged) - _CACHE_LIMIT)]:
		path.unlink(missing_ok=True)
