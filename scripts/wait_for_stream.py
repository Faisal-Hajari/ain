#!/usr/bin/env python3
"""Holds a Savant source adapter back until its stream is actually steady.

This exists because of a measurable, four-second bug. A source adapter maps
the RTSP stream onto wall-clock time once, when the session opens, and every
timestamp it emits for the life of that session is derived from that one
anchor. Anchor it while the encoder upstream is still starting - buffering,
catching up, pacing itself with `-re` - and the error is baked in until the
adapter restarts.

Measured on this stack: adapters that connected during MediaMTX's cold start
put every detection 3.5-3.7 seconds ahead of the frame it described, which
is where the browser overlay and the burnt-in clip boxes both got their
boxes from. The same adapters, reconnected to a stream that had been running
a while, measured -0.3 seconds. `applications/analytics-api/ain_api/
calibrate.py` is what measures it.

So: wait for the path to exist, and then wait for it to have been publishing
long enough to have settled. Never wait forever - a stuck adapter is worse
than a drifted box, so this gives up and lets the adapter start anyway.

    python3 wait_for_stream.py && exec /opt/savant/adapters/gst/sources/rtsp.sh
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

_API = os.environ.get('AIN_MEDIAMTX_API', 'http://cameras:9997')
_PATH = os.environ.get('AIN_WAIT_FOR_PATH', '')
# How long the stream must have been publishing before this lets go. The
# encoder is started by MediaMTX itself now, so this is only covering the
# seconds it takes ffmpeg to reach its pace.
_SETTLE = float(os.environ.get('AIN_STREAM_SETTLE_SECONDS', '20'))
# A ceiling on the whole wait. Past this the stream is not coming, and a
# detector that is running on a mis-timed stream still beats one that never
# starts.
_DEADLINE = float(os.environ.get('AIN_STREAM_WAIT_SECONDS', '180'))
_POLL = 2.0


def _ready_for(path: str) -> float | None:
	"""How long the path has been publishing.

	Args:
		path: The MediaMTX path name, which is not the camera id.

	Returns:
		Seconds since it became ready, or None if it is not ready or the
		API cannot be reached.
	"""
	try:
		with urllib.request.urlopen(
			f'{_API}/v3/paths/get/{path}', timeout=5
		) as response:
			body = json.loads(response.read())
	except (urllib.error.URLError, TimeoutError, OSError, ValueError):
		return None
	if not body.get('ready'):
		return None
	stamp = body.get('readyTime')
	if not stamp:
		# Ready, but this build does not say since when. Treat it as
		# settled rather than waiting out the deadline every start.
		return _SETTLE
	# Python before 3.11 will not parse a 'Z' suffix or nanoseconds.
	cleaned = stamp.replace('Z', '+00:00')
	if '.' in cleaned:
		head, _, tail = cleaned.partition('.')
		fraction, sign, offset = tail.partition('+')
		cleaned = f'{head}.{fraction[:6]}{sign}{offset}'
	try:
		import datetime

		ready_at = datetime.datetime.fromisoformat(cleaned)
	except ValueError:
		return _SETTLE
	now = datetime.datetime.now(datetime.timezone.utc)
	return (now - ready_at).total_seconds()


def main() -> int:
	"""Waits, then gets out of the way.

	Returns:
		Always 0. Every outcome ends with the adapter starting; the only
		question is whether it starts against a settled stream.
	"""
	if not _PATH:
		print('wait_for_stream: no AIN_WAIT_FOR_PATH set, starting now', flush=True)
		return 0

	giving_up_at = time.monotonic() + _DEADLINE
	said = False
	while time.monotonic() < giving_up_at:
		steady = _ready_for(_PATH)
		if steady is not None and steady >= _SETTLE:
			print(
				f'wait_for_stream: {_PATH} has been publishing {steady:.0f}s, '
				'starting the adapter',
				flush=True,
			)
			return 0
		if not said:
			print(
				f'wait_for_stream: waiting for {_PATH} to publish for '
				f'{_SETTLE:.0f}s before anchoring timestamps to it',
				flush=True,
			)
			said = True
		time.sleep(_POLL)

	print(
		f'wait_for_stream: {_PATH} never settled within {_DEADLINE:.0f}s - '
		'starting anyway, but its timestamps may be offset (measure with '
		'ain_api.calibrate)',
		flush=True,
	)
	return 0


if __name__ == '__main__':
	sys.exit(main())
