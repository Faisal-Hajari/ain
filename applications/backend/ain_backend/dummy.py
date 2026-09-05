"""Deterministic stand-in data for every catalogue element.

Values are generated from a hash of the element, the active filters and
the window, so a given request always answers the same numbers while
different filters visibly move them. This module is the only place that
invents data: swapping it for the real read models leaves the response
shapes in `ain_backend.models` untouched.
"""

import datetime
import hashlib
import math
import random

from ain_backend import catalogue
from ain_backend import models

_MAX_SERIES_POINTS = 240
_CLIP_SECONDS = (12.0, 45.0)

# Labels for elements whose payload is a distribution. Elements keyed to
# None are broken down by employee instead of by fixed labels.
_DISTRIBUTION_LABELS: dict[str, list[str] | None] = {
	'dwell-time-per-table': [
		'0-15 min', '15-30 min', '30-45 min', '45-60 min', '60+ min'
	],
	'group-party-size': ['1', '2', '3+'],
	'demographics-gender': ['Male', 'Female', 'Unknown'],
	'throughput-per-employee': None,
	'no-gloves-count-per-employee': None,
	'no-hair-cover-count-per-employee': None,
	'no-mask-count-per-employee': None,
}


def _rng(*parts: str) -> random.Random:
	"""Returns a generator seeded stably across processes and runs."""
	digest = hashlib.blake2b('|'.join(parts).encode(), digest_size=8)
	return random.Random(int.from_bytes(digest.digest(), 'big'))


def _window_seed(window: models.TimeWindow, scope: str) -> str:
	"""Builds the seed fragment shared by everything in one request."""
	return f'{scope}|{window.range_id}|{window.start.date().isoformat()}'


def _bucket_starts(window: models.TimeWindow) -> list[datetime.datetime]:
	"""Lists the bucket boundaries a graph is drawn over."""
	span = (window.end - window.start).total_seconds()
	count = max(1, math.ceil(span / window.bucket_seconds))
	count = min(count, _MAX_SERIES_POINTS)
	step = datetime.timedelta(seconds=window.bucket_seconds)
	return [window.start + step * i for i in range(count)]


def _daylight_weight(at: datetime.datetime) -> float:
	"""Scales hourly buckets so a trading day has a plausible shape."""
	# Two humps: a morning peak near 09:00 and a lunch peak near 13:00.
	morning = math.exp(-(((at.hour - 9) / 3.0) ** 2))
	lunch = math.exp(-(((at.hour - 13) / 3.5) ** 2))
	return 0.25 + morning + lunch


def _series(
	element: models.Element, window: models.TimeWindow, rng: random.Random
) -> list[models.SeriesPoint]:
	"""Generates a trend line varying around the element's baseline."""
	hourly = window.bucket_seconds < 86400
	points = []
	for at in _bucket_starts(window):
		weight = _daylight_weight(at) if hourly else 1.0
		noise = rng.uniform(0.7, 1.3)
		value = element.baseline * weight * noise
		if not hourly:
			# Daily buckets aggregate a whole trading day.
			value *= 9.0
		points.append(
			models.SeriesPoint(at=at, value=round(value, 2))
		)
	return points


def _scalar(
	value: float, unit: str, rng: random.Random
) -> models.ScalarValue:
	"""Wraps a headline value with a trend against the last window."""
	return models.ScalarValue(
		value=round(value, 2),
		unit=unit,
		delta_pct=round(rng.uniform(-18.0, 18.0), 1),
	)


def _build_count(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Totals the window; the card shows the sum, the graph the trend."""
	series = _series(element, window, rng)
	total = sum(point.value for point in series)
	return models.ElementData(
		element_id=element.id,
		value_kind=element.value_kind,
		unit=element.unit,
		generated_at=window.end,
		window=window,
		scalar=_scalar(round(total), element.unit, rng),
		series=series,
	)


def _build_level(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Reports the latest reading of a quantity that rises and falls."""
	series = _series(element, window, rng)
	return models.ElementData(
		element_id=element.id,
		value_kind=element.value_kind,
		unit=element.unit,
		generated_at=window.end,
		window=window,
		scalar=_scalar(series[-1].value, element.unit, rng),
		series=series,
	)


def _build_percent(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Same as a level, clamped to the 0-100 a gauge can draw."""
	data = _build_level(element, window, rng)
	data.series = [
		models.SeriesPoint(at=p.at, value=min(100.0, round(p.value, 2)))
		for p in data.series or []
	]
	data.scalar = _scalar(
		min(100.0, data.scalar.value if data.scalar else 0.0),
		element.unit,
		rng,
	)
	return data


def _build_duration(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Averages the window, since a duration does not accumulate."""
	series = _series(element, window, rng)
	mean = sum(point.value for point in series) / len(series)
	return models.ElementData(
		element_id=element.id,
		value_kind=element.value_kind,
		unit=element.unit,
		generated_at=window.end,
		window=window,
		scalar=_scalar(mean, element.unit, rng),
		series=series,
	)


def _build_clock_time(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Renders a first-seen or last-seen stamp as wall-clock text."""
	minutes = round(element.baseline * 60 + rng.uniform(-25, 25))
	return models.ElementData(
		element_id=element.id,
		value_kind=element.value_kind,
		unit=element.unit,
		generated_at=window.end,
		window=window,
		text=f'{minutes // 60:02d}:{minutes % 60:02d}',
	)


def _distribution_labels(element_id: str) -> list[str]:
	"""Resolves the bars or slices an element is broken down into."""
	labels = _DISTRIBUTION_LABELS.get(element_id, None)
	if labels is not None:
		return labels
	return [member['name'] for member in catalogue.STAFF_ROSTER]


def _build_distribution(
	element: models.Element,
	window: models.TimeWindow,
	rng: random.Random,
) -> models.ElementData:
	"""Splits the baseline across the element's labels."""
	buckets = [
		models.Bucket(
			label=label,
			value=round(element.baseline * rng.uniform(0.2, 1.4)),
		)
		for label in _distribution_labels(element.id)
	]
	total = sum(bucket.value for bucket in buckets)
	return models.ElementData(
		element_id=element.id,
		value_kind=element.value_kind,
		unit=element.unit,
		generated_at=window.end,
		window=window,
		scalar=_scalar(total, element.unit, rng),
		buckets=buckets,
	)


_BUILDERS = {
	models.ValueKind.COUNT: _build_count,
	models.ValueKind.PEOPLE: _build_level,
	models.ValueKind.PERCENT: _build_percent,
	models.ValueKind.DURATION: _build_duration,
	models.ValueKind.CLOCK_TIME: _build_clock_time,
	models.ValueKind.DISTRIBUTION: _build_distribution,
}


def element_data(
	element: models.Element, window: models.TimeWindow, scope: str
) -> models.ElementData:
	"""Builds the payload behind one dashboard element.

	Args:
		element: The catalogue entry being rendered.
		window: The resolved date range.
		scope: The remaining filters, as a stable key.

	Returns:
		The element's dummy payload for those filters.
	"""
	rng = _rng(element.id, _window_seed(window, scope))
	return _BUILDERS[element.value_kind](element, window, rng)


def _instance_count(
	element: models.Element, rng: random.Random
) -> int:
	"""Decides how many occurrences an element logged in the window."""
	# Only counting elements carry an event rate in their baseline; for
	# the rest the baseline is a level or a duration, so it says nothing
	# about how often the alert fired.
	if element.value_kind is models.ValueKind.COUNT:
		return max(1, round(element.baseline * rng.uniform(0.6, 1.4)))
	return rng.randint(2, 9)


def _instance_duration(
	element: models.Element, rng: random.Random
) -> float:
	"""Returns how long one occurrence lasted, in seconds."""
	if element.value_kind is models.ValueKind.DURATION:
		return round(element.baseline * rng.uniform(0.5, 1.8), 1)
	return round(rng.uniform(*_CLIP_SECONDS), 1)


def instances(
	element: models.Element, window: models.TimeWindow, scope: str
) -> list[models.Instance]:
	"""Builds the instance log a clickable alert card opens.

	Args:
		element: The catalogue entry being drilled into.
		window: The resolved date range.
		scope: The remaining filters, as a stable key.

	Returns:
		One entry per occurrence, newest first, each with a clip link.
	"""
	rng = _rng('instances', element.id, _window_seed(window, scope))
	span = (window.end - window.start).total_seconds()
	count = _instance_count(element, rng)
	log = []
	for index in range(count):
		occurred_at = window.start + datetime.timedelta(
			seconds=rng.uniform(0, span)
		)
		instance_id = f'{element.id}-{index:03d}'
		log.append(
			models.Instance(
				id=instance_id,
				element_id=element.id,
				occurred_at=occurred_at,
				camera_id=rng.choice(element.cameras),
				duration_seconds=_instance_duration(element, rng),
				clip_url=f'/api/clips/{instance_id}.mp4',
				thumbnail_url=f'/api/clips/{instance_id}.jpg',
			)
		)
	log.sort(key=lambda entry: entry.occurred_at, reverse=True)
	return log


def employees(
	window: models.TimeWindow, scope: str
) -> list[models.Employee]:
	"""Builds the derived timesheet for the rostered staff.

	Args:
		window: The resolved date range.
		scope: The remaining filters, as a stable key.

	Returns:
		One record per rostered staff member.
	"""
	roster = []
	for member in catalogue.STAFF_ROSTER:
		rng = _rng('employee', member['id'], _window_seed(window, scope))
		start_hour, start_minute = member['shift_start'].split(':')
		start_minutes = int(start_hour) * 60 + int(start_minute)
		clock_in_minutes = start_minutes + round(rng.uniform(-12, 20))
		worked_minutes = round(rng.uniform(7.2, 9.1) * 60)
		clock_out_minutes = clock_in_minutes + worked_minutes
		roster.append(
			models.Employee(
				id=member['id'],
				name=member['name'],
				role=member['role'],
				shift_start=member['shift_start'],
				shift_end=member['shift_end'],
				clock_in=_clock(clock_in_minutes),
				clock_out=_clock(clock_out_minutes),
				hours_worked=round(worked_minutes / 60, 2),
				late_arrival=clock_in_minutes > start_minutes + 5,
				ppe_adherence_pct=round(rng.uniform(78, 100), 1),
				no_gloves_count=rng.randint(0, 4),
				no_hair_cover_count=rng.randint(0, 3),
				no_mask_count=rng.randint(0, 5),
			)
		)
	return roster


def _clock(minutes: int) -> str:
	"""Formats minutes past midnight as HH:MM."""
	return f'{(minutes // 60) % 24:02d}:{minutes % 60:02d}'
