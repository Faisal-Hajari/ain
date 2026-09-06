"""One threshold evaluator, and the named events defined in terms of it.

A custom alert rule built in the frontend has exactly the shape of
"congestion": a metric, an area, a comparator, a threshold and optionally a
duration. Writing the named events as bespoke SQL and custom rules as
something else means writing threshold crossing twice, and the two copies
will disagree about boundary inclusivity, about gaps, and about whether two
breaches seconds apart are one event or two. So there is one evaluator, and
`/events/congestion` is a query string.

Two families of metric go through it:

* a **series** metric - occupancy, footfall - is bucketed, and an event is a
  run of buckets where the test holds for at least `for_seconds`;
* a **visit** metric - dwell, queue wait - is per track, and an event is one
  visit whose own duration fails the test. `for_seconds` means nothing for
  these: the visit's length *is* the measurement.
"""

import dataclasses
import datetime
import hashlib
from collections.abc import Iterator

from clickhouse_connect.driver import client as ch_client

from ain_analytics import config
from ain_analytics import queries

# Buckets finer than this make an event out of one person walking past.
_EVENT_INTERVAL = 30

SERIES_METRICS = ('occupancy', 'footfall')
VISIT_METRICS = ('dwell',)
METRICS = SERIES_METRICS + VISIT_METRICS

COMPARATORS = ('above', 'below')


class UnknownMetricError(KeyError):
	"""No metric carries the requested name."""


@dataclasses.dataclass(frozen=True)
class Event:
	"""One occurrence, with the shape that produced it.

	The geometry rides along so the renderer needs no second lookup and
	the shape it draws is provably the one the event was raised on.
	"""

	id: str
	type: str
	metric: str
	target: str
	start: str
	end: str
	peak_value: float
	cameras: tuple[str, ...]
	geometry: dict
	detail: dict

	def as_dict(self) -> dict:
		"""Renders the event for the wire - numbers and units only."""
		return {
			'id': self.id,
			'type': self.type,
			'metric': self.metric,
			'target': self.target,
			'start': self.start,
			'end': self.end,
			'peak_value': self.peak_value,
			'cameras': list(self.cameras),
			'geometry': self.geometry,
			**self.detail,
		}


def _holds(value: float, comparator: str, threshold: float) -> bool:
	"""Applies one comparator.

	Args:
		value: The measurement.
		comparator: 'above' or 'below'.
		threshold: What to compare against.

	Returns:
		Whether the measurement breaches the threshold. Both are strict:
		a rule written "above 20" does not fire at exactly 20.
	"""
	return value > threshold if comparator == 'above' else value < threshold


def _runs(
	buckets: list[dict], key: str, comparator: str, threshold: float
) -> Iterator[tuple[int, int, float]]:
	"""Finds maximal runs of buckets where the test holds.

	Args:
		buckets: The series, in time order.
		key: Which field of a bucket carries the measurement.
		comparator: 'above' or 'below'.
		threshold: What to compare against.

	Yields:
		(first index, last index, peak value) per run. A single bucket
		that does not breach ends a run: two breaches with a quiet minute
		between them are two events, not one, which is the only reading
		that survives someone changing the bucket size.
	"""
	start: int | None = None
	peak = 0.0
	for index, bucket in enumerate(buckets):
		value = float(bucket[key])
		if _holds(value, comparator, threshold):
			if start is None:
				start, peak = index, value
			peak = max(peak, value) if comparator == 'above' else min(peak, value)
		elif start is not None:
			yield start, index - 1, peak
			start = None
	if start is not None:
		yield start, len(buckets) - 1, peak


def _event_id(kind: str, *parts: object) -> str:
	"""Builds an id that is stable across repeats of the same query.

	Args:
		kind: The event type, used as a readable prefix.
		*parts: Everything that identifies the occurrence.

	Returns:
		An id the frontend can cache on and a clip URL can be built
		from. Re-asking the same question must not produce new ids.
	"""
	digest = hashlib.blake2b(
		'|'.join(str(part) for part in parts).encode(), digest_size=4
	)
	return f'{kind}-{digest.hexdigest()}'


def _series_events(
	client: ch_client.Client,
	metric: str,
	target: str,
	comparator: str,
	threshold: float,
	for_seconds: int,
	window: queries.Window,
	kind: str,
	interval: int | None,
	tz: str,
) -> list[Event]:
	"""Evaluates a bucketed metric against a sustained threshold.

	Args:
		client: A connected ClickHouse client.
		metric: 'occupancy' or 'footfall'.
		target: A zone name, or a line name for footfall.
		comparator: 'above' or 'below'.
		threshold: What to compare against.
		for_seconds: How long the breach must hold to count.
		window: The range to evaluate over.
		kind: The event type to label the results with.
		interval: Bucket size in seconds, or None for the default. A
			threshold is authored in the units its metric is read in, so
			a rate like footfall - people per hour - has to be evaluated
			on hourly buckets or an hour's number is compared to half a
			minute's.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		One event per sustained run.

	Raises:
		config.UnknownZoneError: The target names nothing.
	"""
	settings = config.get()
	requested = interval or _EVENT_INTERVAL
	interval = max(requested, queries.bucket_seconds(window, requested))
	if metric == 'occupancy':
		zone = settings.zone(target)
		buckets = queries.occupancy(client, zone, window, interval, tz)
		key, cameras, geometry = 'mean', zone.cameras, zone.geometry()
	else:
		line = settings.line(target)
		buckets = queries.footfall(client, line, window, interval, tz)
		key = 'in'
		cameras, geometry = (line.camera,), line.geometry()

	events = []
	for first, last, peak in _runs(buckets, key, comparator, threshold):
		started = buckets[first]['ts']
		# The run covers buckets `first` through `last` inclusive, so it
		# ends one interval after the last bucket started - clamped to the
		# window, because the last bucket is usually partial and an event
		# must not be reported as running past the data it was found in.
		ended = _clamp(_shift(buckets[last]['ts'], interval), window.end)
		if _elapsed(started, ended) + 1e-6 < for_seconds:
			continue
		events.append(
			Event(
				id=_event_id(kind, metric, target, comparator, threshold, started),
				type=kind,
				metric=metric,
				target=target,
				start=started,
				end=ended,
				peak_value=round(peak, 2),
				cameras=tuple(cameras),
				geometry=geometry,
				detail={
					'comparator': comparator,
					'threshold': threshold,
					'for_seconds': for_seconds,
					'unit': 'people',
				},
			)
		)
	return events


def _visit_events(
	client: ch_client.Client,
	target: str,
	comparator: str,
	threshold: float,
	window: queries.Window,
	kind: str,
) -> list[Event]:
	"""Evaluates each individual visit against a duration threshold.

	Args:
		client: A connected ClickHouse client.
		target: The zone the visits happened in.
		comparator: 'above' or 'below'.
		threshold: Seconds to compare each visit against.
		window: The range to evaluate over.
		kind: The event type to label the results with.

	Returns:
		One event per visit that breaches.

	Raises:
		config.UnknownZoneError: The target names no zone.
	"""
	zone = config.get().zone(target)
	# Filtered in the query, not here: `visits` caps its result, so testing
	# afterwards would cap first and search second.
	matching = queries.visits(
		client,
		zone,
		window,
		longer_than=threshold if comparator == 'above' else None,
		shorter_than=threshold if comparator == 'below' else None,
	)
	events = []
	for visit in matching:
		events.append(
			Event(
				id=_event_id(
					kind, target, visit['camera'], visit['track_id'],
					visit['start'],
				),
				type=kind,
				metric='dwell',
				target=target,
				start=visit['start'],
				end=visit['end'],
				peak_value=visit['seconds'],
				cameras=(visit['camera'],),
				geometry=zone.geometry(),
				detail={
					'comparator': comparator,
					'threshold': threshold,
					'part': visit['part'],
					'track_id': visit['track_id'],
					'unit': 'seconds',
				},
			)
		)
	return events


def evaluate(
	client: ch_client.Client,
	metric: str,
	target: str,
	comparator: str,
	threshold: float,
	window: queries.Window,
	for_seconds: int = 0,
	kind: str = 'threshold',
	interval: int | None = None,
	tz: str = 'UTC',
) -> list[Event]:
	"""Runs one alert rule over one window.

	Args:
		client: A connected ClickHouse client.
		metric: One of `METRICS`.
		target: A zone name, or a line name when the metric is footfall.
		comparator: 'above' or 'below'.
		threshold: What to compare against - people for a series metric,
			seconds for a visit metric.
		window: The range to evaluate over.
		for_seconds: How long a series breach must hold. Ignored for
			visit metrics, where the visit's own length is the test.
		kind: The event type to label the results with.
		interval: Bucket size for a series metric, or None for the
			default. Ignored by a visit metric.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		The occurrences, oldest first.

	Raises:
		UnknownMetricError: The metric is not one this evaluates.
		config.UnknownZoneError: The target names nothing.
	"""
	if metric in SERIES_METRICS:
		return _series_events(
			client, metric, target, comparator, threshold, for_seconds,
			window, kind, interval, tz,
		)
	if metric in VISIT_METRICS:
		return _visit_events(client, target, comparator, threshold, window, kind)
	raise UnknownMetricError(metric)


def _shift(stamp: str, seconds: int) -> str:
	"""Moves an ISO timestamp forward."""
	moment = datetime.datetime.fromisoformat(stamp)
	return (moment + datetime.timedelta(seconds=seconds)).isoformat(
		timespec='milliseconds'
	)


def _clamp(stamp: str, limit: datetime.datetime) -> str:
	"""Caps a timestamp at the end of the window it was found in.

	Args:
		stamp: An ISO 8601 instant.
		limit: The window's exclusive end.

	Returns:
		The earlier of the two, as ISO 8601. Compared as datetimes rather
		than as strings, which happen to sort correctly only while both
		carry the same offset.
	"""
	moment = datetime.datetime.fromisoformat(stamp)
	return min(moment, limit).isoformat(timespec='milliseconds')


def _elapsed(start: str, end: str) -> float:
	"""Seconds between two ISO timestamps."""
	return (
		datetime.datetime.fromisoformat(end)
		- datetime.datetime.fromisoformat(start)
	).total_seconds()
