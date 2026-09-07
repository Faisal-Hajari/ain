"""Which cameras are actually publishing.

This question does not belong in ClickHouse and never will: an empty room
and a dead camera both produce zero detections, so no query over stored
boxes can tell them apart. It belongs to the server that owns the stream,
which answers it directly.

A camera is live when cameras.yml declares it - so the pipeline is meant to
be watching it - and MediaMTX reports its path as ready, which under
`runOnDemand` means a reader is attached and ffmpeg is running. The Savant
source adapters are those readers, so "ready" and "the pipeline has it" are
the same fact.

A camera the branch has and cameras.yml does not is not an error. It is a
camera nothing is watching, and it reports as having no signal, which is
exactly what a viewer needs to know.
"""

import datetime
import logging
import os

import httpx

from ain_analytics import config

_LOG = logging.getLogger(__name__)

_MEDIAMTX = os.environ.get('AIN_MEDIAMTX_URL', 'http://cameras:9997')
_PLAYBACK = os.environ.get('AIN_PLAYBACK_URL', 'http://cameras:9996')
_TIMEOUT = float(os.environ.get('AIN_MEDIAMTX_TIMEOUT', '3'))


def ready_streams() -> set[str] | None:
	"""Asks MediaMTX which of its paths are publishing.

	Returns:
		The ready path names, or None when MediaMTX could not be asked -
		which is not the same as "nothing is ready" and must not be
		reported as though it were.
	"""
	try:
		response = httpx.get(
			f'{_MEDIAMTX}/v3/paths/list',
			params={'itemsPerPage': 1000},
			timeout=_TIMEOUT,
		)
		response.raise_for_status()
		items = response.json().get('items', [])
	except (httpx.HTTPError, ValueError) as error:
		_LOG.info('mediamtx unreachable: %s', error)
		return None
	return {item['name'] for item in items if item.get('ready')}


def recorded(stream: str) -> list[tuple[datetime.datetime, float]]:
	"""Lists the stretches of video MediaMTX still holds for one stream.

	Args:
		stream: The MediaMTX path, which is not the camera id.

	Returns:
		(start, seconds) per contiguous recording, oldest first, or an
		empty list when there is none or the server cannot be asked.
		Recording is a rolling window, so this shrinks from the front as
		the retention passes.
	"""
	try:
		response = httpx.get(
			f'{_PLAYBACK}/list', params={'path': stream}, timeout=_TIMEOUT
		)
		response.raise_for_status()
		items = response.json() or []
	except (httpx.HTTPError, ValueError) as error:
		_LOG.info('playback list unavailable for %s: %s', stream, error)
		return []
	ranges = []
	for item in items:
		try:
			start = datetime.datetime.fromisoformat(
				item['start'].replace('Z', '+00:00')
			)
		except (KeyError, ValueError):
			continue
		ranges.append((start, float(item.get('duration') or 0)))
	return sorted(ranges)


def recorded_from(stream: str) -> datetime.datetime | None:
	"""The oldest instant one stream still has video for."""
	ranges = recorded(stream)
	return ranges[0][0] if ranges else None


def status(settings: config.Config, ready: set[str] | None) -> list[dict]:
	"""Reports every camera the pipeline is configured for.

	Args:
		settings: The parsed cameras.yml.
		ready: Path names MediaMTX says are publishing, or None if it
			could not be asked.

	Returns:
		One entry per configured camera. `live` is None rather than
		False when MediaMTX is unreachable: "we could not check" is a
		third answer, and collapsing it into "it is down" would turn one
		unreachable control API into ten cameras reported dead.
	"""
	entries = []
	for camera_id, camera in settings.cameras.items():
		stream = camera.get('stream')
		oldest = recorded_from(stream) if stream else None
		entries.append(
			{
				'id': camera_id,
				'stream': stream,
				'description': camera.get('description'),
				'live': None if ready is None else stream in ready,
				# The oldest instant a clip can be cut from. Recording is a
				# rolling window, so an event older than this has no video
				# behind it and offering one is offering a dead link.
				'recorded_from': oldest.isoformat() if oldest else None,
			}
		)
	return entries
