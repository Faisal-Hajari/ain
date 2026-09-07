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
from ain_api import queries

# Buckets finer than this make an event out of one person walking past.
_EVENT_INTERVAL = 30

SERIES_METRICS = ('occupancy', 'footfall')
VISIT_METRICS = ('dwell',)
METRICS = SERIES_METRICS + VISIT_METRICS

COMPARATORS = ('above', 'below')

# What a threshold is a threshold OF. `absolute` is a number of people;
# `capacity` is a share of what the zone holds, so "passed 90%" means
# something; `mean` is a share of the window's own average, so "below
# average" means something. All three go through the same run-finding, which
# is the point - a named event and a custom rule must not disagree about
# where a breach starts.
BASES = ('absolute', 'capacity', 'mean')


class UnknownBasisError(KeyError):
	"""No threshold basis carries the requested name."""


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


def _weighted_mean(buckets: list[dict], key: str) -> float:
	"""Averages a series by how long each bucket covers.

	Args:
		buckets: The series, in time order.
		key: Which field carries the measurement.

	Returns:
		The time-weighted mean. The first and last buckets of a window
		are usually partial, and a plain average would weigh a
		one-second sliver like a full interval.
	"""
	covered = sum(bucket.get('covered_seconds', 1) for bucket in buckets)
	if not covered:
		return 0.0
	total = sum(
		float(bucket[key]) * bucket.get('covered_seconds', 1)
		for bucket in buckets
	)
	return total / covered


def _resolve(
	threshold: float,
	basis: str,
	zone: 'config.Zone | None',
	buckets: list[dict],
	key: str,
) -> float:
	"""Turns a threshold and its basis into a number of people.

	Args:
		threshold: The number as the caller wrote it - people for
			`absolute`, a fraction for the other two.
		basis: One of `BASES`.
		zone: The area, for a capacity basis.
		buckets: The series, for a mean basis.
		key: Which field of a bucket carries the measurement.

	Returns:
		The threshold the comparator is applied against.

	Raises:
		UnknownBasisError: The basis is not one of `BASES`.
		config.NoCapacityError: A capacity basis on something without one.
	"""
	if basis == 'absolute':
		return threshold
	if basis == 'capacity':
		if zone is None:
			raise config.NoCapacityError('a counting line has no capacity')
		return zone.proportion(threshold)
	if basis == 'mean':
		return _weighted_mean(buckets, key) * threshold
	raise UnknownBasisError(basis)


def _is_rising(buckets: list[dict], key: str, first: int, last: int) -> bool:
	"""Reports whether a series grew across a run of buckets.

	Args:
		buckets: The series, in time order.
		key: Which field carries the measurement.
		first: Index of the run's first bucket.
		last: Index of its last, inclusive.

	Returns:
		Whether the second half of the run averaged higher than the
		first. Halves rather than endpoints: one bucket at each end is
		two samples of a noisy signal, and "growing" should not turn on
		which second somebody happened to step out of frame.

		A run too short to have two halves is not rising. Nothing can be
		called growing from one sample, and saying so is better than
		guessing.
	"""
	span = buckets[first : last + 1]
	if len(span) < 2:
		return False
	middle = len(span) // 2
	return _weighted_mean(span[middle:], key) > _weighted_mean(
		span[:middle], key
	)


def _event_id(kind: str, *parts: object) -> str:
	"""Builds an id that is stable across repeats of the same query.

	Args:
		kind: The event type, used as a readable prefix.
		*parts: Everything that identifies the occurrence.

	Returns:
		An id the frontend can cache on and a clip URL can be built
		from. Re-asking the same question must not produce new ids.

		Sixty-four bits, not thirty-two. A full response can carry
		`queries.MAX_VISITS` events, and at 20 000 ids a 32-bit digest
		collides within one response about one time in twenty - which
		would be survivable if the id were only a key, and is not,
		because the clip cache is a file named after it. A collision
		there serves one customer's video for another's alert.
	"""
	digest = hashlib.blake2b(
		'|'.join(str(part) for part in parts).encode(), digest_size=8
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
	basis: str,
	rising: str | None,
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
		basis: What the threshold is a threshold OF - one of `BASES`.
		rising: A zone that must be growing across the run for it to
			count. This is what turns a full room into congestion: a
			room at capacity with a shrinking queue is a rush that is
			clearing, and alerting on it is alerting on good news.

	Returns:
		One event per sustained run.

	Raises:
		config.UnknownZoneError: The target, or `rising`, names nothing.
		config.NoCapacityError: A capacity basis on a zone without one.
		UnknownBasisError: The basis is not one of `BASES`.
	"""
	settings = config.get()
	requested = interval or _EVENT_INTERVAL
	interval = max(requested, queries.bucket_seconds(window, requested))
	zone = None
	if metric == 'occupancy':
		zone = settings.zone(target)
		buckets = queries.occupancy(client, zone, window, interval, tz)
		key, cameras, geometry = 'mean', zone.cameras, zone.geometry()
	else:
		line = settings.line(target)
		buckets = queries.footfall(client, line, window, interval, tz)
		key = 'in'
		cameras, geometry = (line.camera,), line.geometry()

	# Resolved once, from the same buckets the runs are found in, so a
	# `mean` basis is the mean of exactly the window being reported on.
	limit = _resolve(threshold, basis, zone, buckets, key)
	# Same window, same interval, so the two series are index-aligned - both
	# are zero-filled across the whole range.
	trend = (
		queries.occupancy(
			client, settings.zone(rising), window, interval, tz
		)
		if rising
		else None
	)

	events = []
	for first, last, peak in _runs(buckets, key, comparator, limit):
		if trend is not None and not _is_rising(trend, 'mean', first, last):
			continue
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
				id=_event_id(
					kind, metric, target, comparator, threshold, basis, started
				),
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
					# What the caller asked for, and what it worked out
					# to. A card reading "passed 90%" needs the first;
					# somebody asking why it fired needs the second.
					'threshold': threshold,
					'threshold_of': basis,
					'threshold_value': round(limit, 2),
					'for_seconds': for_seconds,
					'rising': rising,
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
	basis: str = 'absolute',
	rising: str | None = None,
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
		basis: What the threshold is a threshold OF - one of `BASES`.
			Ignored by a visit metric, whose threshold is always seconds.
		rising: A zone that must be growing across a series run for it
			to count. Ignored by a visit metric.

	Returns:
		The occurrences, oldest first.

	Raises:
		UnknownMetricError: The metric is not one this evaluates.
		UnknownBasisError: The basis is not one of `BASES`.
		config.UnknownZoneError: The target names nothing.
		config.NoCapacityError: A capacity basis on a zone without one.
	"""
	if basis not in BASES:
		raise UnknownBasisError(basis)
	if metric in SERIES_METRICS:
		return _series_events(
			client, metric, target, comparator, threshold, for_seconds,
			window, kind, interval, tz, basis, rising,
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
