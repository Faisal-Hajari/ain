"""Measures how far detection timestamps sit from the video they describe.

Savant stamps a frame with when it believes the frame was captured; MediaMTX
stamps its recordings and its HLS segments with its own clock. Those two
clocks are the ones the overlay and the clips join on, and they do not agree:
a detection's `ts` runs a few seconds ahead of the picture it belongs to, so
the boxes land on where somebody WAS.

This finds the disagreement rather than assuming it. It needs no detector -
movement between consecutive frames is ground truth for where a person is.
For each candidate shift it asks what fraction of the frame's motion falls
inside the boxes stored at `frame_time + shift`; the shift that maximises it
is the offset.

    docker compose exec analytics-api python -m ain_api.calibrate
    docker compose exec analytics-api python -m ain_api.calibrate --camera 03

The number it prints is what `AIN_OVERLAY_CLOCK_OFFSET_MS` should be. Re-run
it after changing cameras, the transcode settings, or anything else that
changes how long a frame takes to reach the module.
"""

import argparse
import datetime
import logging
import pathlib
import sys
import tempfile

import cv2
import numpy

from ain_analytics import config
from ain_analytics import db
from ain_api import clips
from ain_api import queries

_LOG = logging.getLogger(__name__)

# Frames quieter than this are all noise and no signal; including them makes
# every shift look equally good.
_MIN_MOVING_PIXELS = 400
_MOTION_THRESHOLD = 18
# A camera whose best shift barely beats no shift at all has not measured
# anything. Camera 04 watches a glass frontage, so most of its movement is
# the street and reflections in it - the correlation is flat and its
# "winner" is noise. Without this it drags the median around.
_MIN_IMPROVEMENT = 0.10
# Above this, boxes already sit on the movement and there is nothing to
# correct - which is what a healthy stack looks like, not a failed measurement.
_ALIGNED_AGREEMENT = 0.40
# Wide enough to contain a badly mis-anchored session, coarse enough to walk
# in a few seconds. The fine pass then works either side of the winner.
_COARSE = range(-12_000, 4_001, 500)
_FINE_STEP = 100


def _motion(path: pathlib.Path) -> tuple[list[tuple[int, numpy.ndarray]], float, int, int]:
	"""Where each frame of a clip moved.

	Args:
		path: An mp4 with no boxes drawn on it.

	Returns:
		Per-frame `(millisecond offset, motion mask)` for the frames that
		moved at all, the frame rate, and the frame size.
	"""
	capture = cv2.VideoCapture(str(path))
	fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
	previous = None
	frames: list[tuple[int, numpy.ndarray]] = []
	index = 0
	while True:
		ok, frame = capture.read()
		if not ok:
			break
		grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
		if previous is not None:
			difference = cv2.absdiff(grey, previous)
			_, mask = cv2.threshold(
				difference, _MOTION_THRESHOLD, 1, cv2.THRESH_BINARY
			)
			if mask.sum() > _MIN_MOVING_PIXELS:
				frames.append((round(index * 1000 / fps), mask))
		previous = grey
		index += 1
	capture.release()
	if previous is None:
		raise clips.ClipError(f'{path.name} decoded no frames')
	height, width = previous.shape
	return frames, fps, width, height


def _agreement(
	frames: list[tuple[int, numpy.ndarray]],
	boxes: dict[int, list[dict]],
	offsets: list[int],
	size: tuple[int, int],
	shift: int,
) -> float:
	"""How much of the movement falls inside the boxes at one shift.

	Args:
		frames: Motion masks by millisecond offset.
		boxes: Detections by millisecond offset.
		offsets: `boxes` keys, ascending.
		size: The frame's `(width, height)`.
		shift: Milliseconds to add to a frame's time before looking a
			detection up.

	Returns:
		Moving pixels inside a box over moving pixels total, 0..1.
	"""
	width, height = size
	inside = total = 0
	for moment, mask in frames:
		nearest = clips._nearest(offsets, moment + shift)
		if nearest is None:
			continue
		covered = numpy.zeros_like(mask)
		for obj in boxes[nearest]:
			x1 = max(0, int((obj['xc'] - obj['w'] / 2) * width))
			y1 = max(0, int((obj['yc'] - obj['h'] / 2) * height))
			x2 = min(width, int((obj['xc'] + obj['w'] / 2) * width))
			y2 = min(height, int((obj['yc'] + obj['h'] / 2) * height))
			covered[y1:y2, x1:x2] = 1
		inside += int((mask & covered).sum())
		total += int(mask.sum())
	return inside / total if total else 0.0


def measure(camera: str, seconds: int = 60, back_off: int = 25) -> dict | None:
	"""Finds the offset for one camera.

	Args:
		camera: The camera id, as the catalogue names it.
		seconds: How much video to correlate over.
		back_off: How far behind the newest detection to start, so the
			window is not still filling.

	Returns:
		The measurement, or None when there is not enough to measure -
		a camera nobody walked past has nothing to correlate.
	"""
	client = db.client()
	stream = config.get().stream(camera)
	if stream is None:
		raise config.ConfigError(f'unknown camera: {camera}')

	newest = queries.latest_ts(client)
	if newest is None:
		return None
	end = newest - datetime.timedelta(seconds=back_off)
	scope = clips.available(
		stream,
		queries.Window(start=end - datetime.timedelta(seconds=seconds), end=end),
	)
	if scope is None:
		return None

	with tempfile.TemporaryDirectory(prefix='calibrate-') as scratch:
		source = pathlib.Path(scratch) / 'source.mp4'
		clips._fetch(stream, scope, source)
		boxes = clips._boxes_by_offset(client, camera, scope)
		if len(boxes) < 30:
			return None
		frames, _, width, height = _motion(source)
		if len(frames) < 30:
			return None

		offsets = sorted(boxes)
		size = (width, height)
		coarse = {
			shift: _agreement(frames, boxes, offsets, size, shift)
			for shift in _COARSE
		}
		peak = max(coarse, key=coarse.get)
		fine = {
			shift: _agreement(frames, boxes, offsets, size, shift)
			for shift in range(peak - 500, peak + 501, _FINE_STEP)
		}
		best = max(fine, key=fine.get)
		return {
			'camera': camera,
			'shift_ms': best,
			'agreement': round(fine[best], 3),
			'agreement_at_zero': round(coarse.get(0, 0.0), 3),
			'moving_frames': len(frames),
			'stored_frames': len(boxes),
		}


def main() -> int:
	"""Measures every camera, or one, and prints what to configure.

	Returns:
		A process exit code.
	"""
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument('--camera', help='measure only this one')
	parser.add_argument('--seconds', type=int, default=60)
	arguments = parser.parse_args()
	logging.basicConfig(level='INFO', format='%(message)s')

	cameras = [arguments.camera] if arguments.camera else sorted(config.get().cameras)
	results = []
	for camera in cameras:
		try:
			found = measure(camera, seconds=arguments.seconds)
		except Exception as error:  # noqa: BLE001 - one camera is not the run
			print(f'camera {camera}: {error}')
			continue
		if found is None:
			print(f'camera {camera}: not enough movement to measure')
			continue
		gain = found['agreement'] - found['agreement_at_zero']
		# A small gain means one of two very different things, and saying
		# "no signal" for both is how a green result reads as a failure.
		usable = gain >= _MIN_IMPROVEMENT
		aligned = not usable and found['agreement_at_zero'] >= _ALIGNED_AGREEMENT
		verdict = (
			'' if usable
			else '   ALREADY ALIGNED' if aligned
			else '   IGNORED: no usable signal'
		)
		if usable:
			results.append(found)
		print(
			f'camera {found["camera"]}: {found["shift_ms"]:+6} ms   '
			f'agreement {found["agreement"]:.3f} '
			f'(uncorrected {found["agreement_at_zero"]:.3f}, '
			f'gain {gain:+.3f})   '
			f'{found["moving_frames"]} moving frames{verdict}'
		)

	if not results:
		print()
		print('nothing to correct: no camera measured a shift worth applying.')
		return 0

	# The median of the cameras that actually measured something. One
	# camera watching a street through glass will happily report a
	# confident number about the traffic.
	shifts = sorted(result['shift_ms'] for result in results)
	median = shifts[len(shifts) // 2]
	spread = shifts[-1] - shifts[0]
	print()
	print(f'{len(shifts)} usable: {shifts}  spread {spread} ms')
	if spread > 1000:
		print(
			'  the cameras disagree by more than a second, so one constant '
			'will not fit them all - look at them individually'
		)
	print()
	print(f'AIN_OVERLAY_CLOCK_OFFSET_MS={-median}')
	print(
		f'  (detections run {-median} ms ahead of the picture; '
		'that many are added back when they are served for drawing)'
	)
	return 0


if __name__ == '__main__':
	sys.exit(main())
