"""Reads ingested detection events out of ClickHouse.

Events arrive on Kafka and ClickHouse is meant to consume them itself,
so nothing here consumes, produces or writes: this module only asks
questions over ClickHouse's HTTP interface, which is why it needs no
driver. The `ain.events` schema it reads is not written yet.

Every call is best-effort. With `AIN_CLICKHOUSE_URL` unset, the server
unreachable, or nothing ingested yet, these return empty and the caller
falls back to the generated payloads. That is what `pytest` and a bare
`uvicorn ain_backend.main:app` do, and it keeps the read routes pure
functions of the query string.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

_URL = os.environ.get('AIN_CLICKHOUSE_URL', '').rstrip('/')
_TIMEOUT_SECONDS = float(os.environ.get('AIN_CLICKHOUSE_TIMEOUT', '2'))

# ClickHouse's own auth headers rather than the URL or the query string,
# which is where it logs and where a proxy would keep them.
_AUTH = {
	'X-ClickHouse-User': os.environ.get('AIN_CLICKHOUSE_USER', 'default'),
	'X-ClickHouse-Key': os.environ.get('AIN_CLICKHOUSE_PASSWORD', ''),
}

_logger = logging.getLogger(__name__)


def query(sql: str, **params: str) -> list[dict]:
	"""Runs one read against ClickHouse.

	Args:
		sql: The statement, without a FORMAT clause.
		**params: Values for the `{name:Type}` placeholders in `sql`.
			ClickHouse binds these server-side, so no caller has to
			quote anything into the statement.

	Returns:
		One dict per row, or an empty list if ClickHouse is not
		configured, not reachable, or answers with an error.
	"""
	if not _URL:
		return []
	query_string = urllib.parse.urlencode(
		{f'param_{name}': value for name, value in params.items()}
	)
	request = urllib.request.Request(
		f'{_URL}/?{query_string}',
		data=f'{sql} FORMAT JSONEachRow'.encode(),
		headers=_AUTH,
		method='POST',
	)
	try:
		with urllib.request.urlopen(
			request, timeout=_TIMEOUT_SECONDS
		) as response:
			body = response.read().decode()
	except (OSError, urllib.error.URLError) as error:
		_logger.warning('clickhouse read failed: %s', error)
		return []
	return [json.loads(line) for line in body.splitlines() if line]


def recent_events(
	element_id: str, branch: str, venue: str, hours: int
) -> list[dict]:
	"""Reads the occurrences behind one card.

	Args:
		element_id: The catalogue id the events were published under.
		branch: The active branch filter.
		venue: The active venue filter.
		hours: How far back the active range reaches.

	Returns:
		Rows newest first, each with `timestamp`, `camera_id`,
		`severity`, `detail` and `clip_url`. The timestamp is formatted
		branch-side by ClickHouse, matching the generated log's
		`HH:MM`.
	"""
	return query(
		"""
		SELECT
			formatDateTime(ts, '%H:%i') AS timestamp,
			camera_id,
			severity,
			detail,
			clip_url
		FROM ain.events
		WHERE element_id = {element:String}
			AND branch = {branch:String}
			AND venue = {venue:String}
			AND ts >= now() - toIntervalHour({hours:UInt32})
		ORDER BY ts DESC
		LIMIT 200
		""",
		element=element_id,
		branch=branch,
		venue=venue,
		hours=str(hours),
	)
