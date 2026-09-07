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
import urllib.error
import urllib.parse
import urllib.request

from ain_backend import settings

_LOG = logging.getLogger(__name__)

_OPTIONS = settings.get()
_BASE_URL = _OPTIONS.analytics_base_url


def configured() -> bool:
	"""Whether an analytics service is wired up at all."""
	return bool(_BASE_URL)


def get(
	path: str,
	params: dict[str, object],
	timeout: float | None = None,
) -> dict | None:
	"""Reads one endpoint.

	Args:
		path: The route, with its leading slash.
		params: Query parameters. `None` values are dropped, so a caller
			can pass an absent `end` without building the dict twice.
		timeout: Seconds to wait. The default suits a query; rendering a
			clip is decode, redraw and re-encode and needs far longer,
			so the clip route passes its own.

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
		with urllib.request.urlopen(
			url, timeout=timeout or _OPTIONS.analytics_timeout_seconds
		) as response:
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
