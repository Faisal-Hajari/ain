"""Resolution of the dashboard's date-range filter into a time window."""

import datetime

from ain_backend import models

_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400

# Range id -> (days back the window starts, bucket width in seconds).
_RANGES: dict[str, tuple[int, int]] = {
	'today': (0, _HOUR_SECONDS),
	'yesterday': (1, _HOUR_SECONDS),
	'7d': (7, _DAY_SECONDS),
	'30d': (30, _DAY_SECONDS),
}


class UnknownRangeError(ValueError):
	"""The requested date range is not one the dashboard offers."""


def _bucket_for_span(span_seconds: float) -> int:
	"""Picks a bucket width that keeps a custom range readable."""
	if span_seconds <= 2 * _DAY_SECONDS:
		return _HOUR_SECONDS
	return _DAY_SECONDS


def resolve(
	range_id: str,
	now: datetime.datetime,
	start: datetime.datetime | None = None,
	end: datetime.datetime | None = None,
) -> models.TimeWindow:
	"""Turns a range filter into concrete window boundaries.

	Args:
		range_id: One of the ids in the filter catalogue.
		now: The moment the request is being served.
		start: Window start, required when range_id is 'custom'.
		end: Window end, required when range_id is 'custom'.

	Returns:
		The resolved window, including the bucket width graphs use.

	Raises:
		UnknownRangeError: The range id is unknown, or 'custom' was
			requested without a start and an end.
	"""
	if range_id == 'custom':
		if start is None or end is None:
			raise UnknownRangeError(
				'custom range needs both start and end'
			)
		span = (end - start).total_seconds()
		return models.TimeWindow(
			range_id=range_id,
			start=start,
			end=end,
			bucket_seconds=_bucket_for_span(span),
		)

	if range_id not in _RANGES:
		raise UnknownRangeError(f'unknown date range: {range_id!r}')

	days_back, bucket_seconds = _RANGES[range_id]
	if range_id == 'today':
		return models.TimeWindow(
			range_id=range_id,
			start=now.replace(hour=0, minute=0, second=0, microsecond=0),
			end=now,
			bucket_seconds=bucket_seconds,
		)
	if range_id == 'yesterday':
		midnight = now.replace(
			hour=0, minute=0, second=0, microsecond=0
		)
		return models.TimeWindow(
			range_id=range_id,
			start=midnight - datetime.timedelta(days=1),
			end=midnight,
			bucket_seconds=bucket_seconds,
		)
	# Multi-day ranges start at a midnight boundary so the daily buckets
	# line up whatever time of day the request arrives.
	midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
	return models.TimeWindow(
		range_id=range_id,
		start=midnight - datetime.timedelta(days=days_back - 1),
		end=now,
		bucket_seconds=bucket_seconds,
	)
