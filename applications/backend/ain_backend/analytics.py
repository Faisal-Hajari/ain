"""The client for the analytics service, and the fallback around it.

`analytics-api` returns numbers and units. Everything a person reads - the
formatting, the copy, the severity, the sentiment - is decided here, in the
service that ships both languages. That split is the reason the pipeline can
be replaced without touching a single Arabic string.

Every call in here answers `None` rather than raising. A card with no
detections behind it yet, a service still starting, a pipeline whose engine
is still building: all of those have to leave a readable dashboard, and the
generated data is what fills in until each KPI is proven. Nothing here
retries - the frontend is already polling.
"""

import datetime
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

_LOG = logging.getLogger(__name__)

_BASE_URL = os.environ.get('AIN_ANALYTICS_URL', '').rstrip('/')
_TIMEOUT = float(os.environ.get('AIN_ANALYTICS_TIMEOUT', '4'))
# A clip is decoded, redrawn and re-encoded on demand, which is not a
# four-second job.
_CLIP_TIMEOUT = float(os.environ.get('AIN_CLIP_TIMEOUT', '120'))


def configured() -> bool:
	"""Whether an analytics service is wired up at all."""
	return bool(_BASE_URL)


def get(path: str, params: dict[str, object]) -> dict | None:
	"""Reads one endpoint.

	Args:
		path: The route, with its leading slash.
		params: Query parameters. `None` values are dropped, so a caller
			can pass an absent `end` without building the dict twice.

	Returns:
		The decoded body, or None if the service is unset, unreachable,
		slow, or answered anything but a 200. A card falls back to
		generated data on None; it never shows an error.
	"""
	if not _BASE_URL:
		return None
	query = urllib.parse.urlencode(
		{key: value for key, value in params.items() if value is not None}
	)
	url = f'{_BASE_URL}{path}?{query}'
	try:
		with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:
			if response.status != 200:
				return None
			return json.loads(response.read())
	except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
		_LOG.info('analytics unavailable (%s): %s', path, error)
		return None


def window(
	range_key: str, today: datetime.date, tz: datetime.tzinfo
) -> dict[str, object]:
	"""Turns the range filter into the query parameters the API takes.

	Args:
		range_key: One of 'today', '7d' or '30d'.
		today: The branch's current date.
		tz: The branch's timezone.

	Returns:
		A `start` in ISO 8601 with an explicit offset, and no `end`. An
		omitted end means "the newest data there is" rather than "now":
		the pipeline runs a second or two behind, and asking for the
		future returns a trailing bucket that is empty for no reason a
		reader can see.
	"""
	days = {'7d': 6, '30d': 29}.get(range_key, 0)
	start = datetime.datetime.combine(
		today - datetime.timedelta(days=days),
		datetime.time.min,
		tzinfo=tz,
	)
	return {'start': start.isoformat()}


def stream(path: str, params: dict[str, object]):
	"""Opens one endpoint as a file object, for a response to pass through.

	Args:
		path: The route, with its leading slash.
		params: Query parameters.

	Returns:
		The open response, or None if the service is unset, unreachable
		or answered anything but a 200. The caller closes it.

	A clip is rendered on demand and can be megabytes, so it is streamed
	rather than read into memory here and written out again.
	"""
	if not _BASE_URL:
		return None
	query = urllib.parse.urlencode(
		{key: value for key, value in params.items() if value is not None}
	)
	try:
		response = urllib.request.urlopen(
			f'{_BASE_URL}{path}?{query}', timeout=_CLIP_TIMEOUT
		)
	except (urllib.error.URLError, TimeoutError, OSError) as error:
		_LOG.info('analytics unavailable (%s): %s', path, error)
		return None
	if response.status != 200:
		response.close()
		return None
	return response
