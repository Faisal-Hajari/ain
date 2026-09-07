"""Turning query strings into the things the query layer takes.

Everything here answers with an HTTP error rather than a Python one, which
is why it is separate from `queries` and from `config`: a bad timestamp is a
400 and an unknown zone is a 404, and neither belongs in a module that also
has to work when nobody is holding a request open.
"""

import datetime
from typing import Annotated

import fastapi

from ain_analytics import config
from ain_analytics import db
from ain_api import queries

# An omitted `start` reaches this far back. Not a setting: it is the shape of
# the default question ("the last hour"), not a tunable of the deployment.
_DEFAULT_WINDOW_SECONDS = 3600


def moment(raw: str | None, field: str) -> datetime.datetime | None:
	"""Reads one ISO 8601 timestamp from the query string.

	Args:
		raw: The raw value, or None.
		field: Which parameter it came from, for the error message.

	Returns:
		An aware UTC datetime, or None.

	Raises:
		fastapi.HTTPException: The value is not ISO 8601.
	"""
	if not raw:
		return None
	try:
		parsed = datetime.datetime.fromisoformat(raw)
	except ValueError as error:
		raise fastapi.HTTPException(
			status_code=400, detail=f'{field} is not ISO 8601: {raw!r}'
		) from error
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=datetime.timezone.utc)
	return parsed.astimezone(datetime.timezone.utc)


def span(
	start: str | None,
	end: str | None,
	default_seconds: int = _DEFAULT_WINDOW_SECONDS,
) -> queries.Window:
	"""Resolves a range, with a caller-chosen default width.

	Args:
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive. Defaults to the newest stored
			detection, or to now when there is none.
		default_seconds: How far back an omitted `start` reaches.

	Returns:
		The half-open range.

	Raises:
		fastapi.HTTPException: A timestamp is unparseable, or the range
			runs backwards.
	"""
	finish = moment(end, 'end') or queries.latest_ts(db.client()) or (
		datetime.datetime.now(datetime.timezone.utc)
	)
	begin = moment(start, 'start') or finish - datetime.timedelta(
		seconds=default_seconds
	)
	if begin >= finish:
		raise fastapi.HTTPException(
			status_code=400, detail='start must be before end'
		)
	return queries.Window(start=begin, end=finish)


def window(start: str | None = None, end: str | None = None) -> queries.Window:
	"""The time range every read route takes.

	Args:
		start: ISO 8601, inclusive. Defaults to an hour before the end.
		end: ISO 8601, exclusive.

	Returns:
		The half-open range.

	Every plain parameter of a FastAPI dependency becomes a query
	parameter, so this deliberately takes only the two that are meant to
	be public. A `default_seconds` here would appear in the schema of
	every route that depends on it, and a caller could widen any of them
	to the full retention window.
	"""
	return span(start, end)


Window = Annotated[queries.Window, fastapi.Depends(window)]


def zone(name: str) -> config.Zone:
	"""Looks up a zone.

	Args:
		name: The zone name from the query string.

	Returns:
		The zone.

	Raises:
		fastapi.HTTPException: cameras.yml declares no such zone.
	"""
	try:
		return config.get().zone(name)
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404,
			detail=f'unknown zone: {name}. Known: {sorted(config.get().zones)}',
		) from error


def line(name: str) -> config.Line:
	"""Looks up a counting line.

	Args:
		name: The line name from the query string.

	Returns:
		The line.

	Raises:
		fastapi.HTTPException: cameras.yml declares no such line.
	"""
	try:
		return config.get().line(name)
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404,
			detail=f'unknown line: {name}. Known: {sorted(config.get().lines)}',
		) from error


def camera(name: str) -> str:
	"""Checks that a camera exists, and returns its MediaMTX path.

	Args:
		name: The camera id, as the catalogue names it.

	Returns:
		The stream path, which is not the camera id.

	Raises:
		fastapi.HTTPException: cameras.yml declares no such camera.
	"""
	stream = config.get().stream(name)
	if stream is None:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown camera: {name}'
		)
	return stream
