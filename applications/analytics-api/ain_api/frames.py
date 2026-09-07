"""One still frame per camera, for drawing zones on.

The geometry editor needs a backdrop to trace over, and a still is a better
backdrop than a live tile: a polygon is placed against a moment you can look
at, not against something that moves while you click.

MediaMTX serves no stills, so one is cut here with the ffmpeg that is already
in this image for the clips. Cached briefly, because opening an RTSP session
per page load is a lot of ceremony for a picture that barely changes.
"""

import logging
import subprocess
import threading
import time

from ain_analytics import settings

_LOG = logging.getLogger(__name__)

_OPTIONS = settings.get()

_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


class FrameError(Exception):
	"""No still could be taken from that stream."""


def still(stream: str) -> bytes:
	"""Returns one JPEG from a live camera.

	Args:
		stream: The MediaMTX path, which is not the camera id.

	Returns:
		The encoded frame.

	Raises:
		FrameError: The stream did not produce a frame in time.
	"""
	now = time.monotonic()
	with _lock:
		cached = _cache.get(stream)
		if cached and now - cached[0] < _OPTIONS.frame_ttl_seconds:
			return cached[1]

	command = [
		'ffmpeg', '-hide_banner', '-loglevel', 'error',
		# TCP for the same reason the pipeline uses it: over UDP this hop
		# drops packets even on loopback.
		'-rtsp_transport', 'tcp',
		'-i', f'{_OPTIONS.rtsp_url}/{stream}',
		'-frames:v', '1', '-q:v', '4',
		'-f', 'image2', 'pipe:1',
	]
	try:
		result = subprocess.run(
			command, capture_output=True, timeout=_OPTIONS.frame_timeout_seconds, check=False
		)
	except subprocess.TimeoutExpired as error:
		raise FrameError(f'{stream} did not answer in {_OPTIONS.frame_timeout_seconds:.0f}s') from error
	if result.returncode != 0 or not result.stdout:
		detail = result.stderr.decode('utf-8', 'replace').strip()[:200]
		raise FrameError(f'{stream}: {detail or "no frame"}')

	with _lock:
		_cache[stream] = (time.monotonic(), result.stdout)
	return result.stdout
