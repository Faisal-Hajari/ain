"""Deterministic dummy payloads, one per element type.

Same element id and same filters always produce the same payload, so a
card never flickers between polls. The seed deliberately excludes the
language: switching locale must re-label a card without moving a single
number.

This module is the fallback, not the only answer. `live` builds the same
shapes from what the cameras saw and `build_element` tries that first;
this takes over whenever an element declares no source, the analytics
service is unset or unreachable, or it has nothing stored for the window.
That is what keeps a card readable while the pipeline is still building
its TensorRT engine.
"""

import dataclasses
import datetime
import hashlib
import random
from collections.abc import Callable, Sequence

from ain_backend import catalogue
from ain_backend import formatting
from ain_backend import i18n
from ain_backend import live
from ain_backend import models

_DURATION = formatting.ValueFormat.DURATION

_HOURS = tuple(f'{hour:02d}' for hour in range(8, 22))
_DWELL_BUCKETS = ('0-10', '10-20', '20-30', '30-45', '45-60', '60+')
_MONTH_DAYS = 30
_OFFLINE_CHANCE = 0.12
_TREND_POINTS = 12

# How long a card's data is considered current, which is what makes
# `updatedAt` the data's timestamp rather than the request's.
_FRESHNESS_SECONDS: dict[models.UpdateCadence, int] = {
	models.UpdateCadence.REALTIME: 15,
	models.UpdateCadence.EVENT: 60,
	models.UpdateCadence.VISIT: 120,
	models.UpdateCadence.HOURLY: 3600,
	models.UpdateCadence.DAILY: 86400,
	models.UpdateCadence.STATIC: 86400,
}


class UnknownElementError(KeyError):
	"""No element in the catalogue carries the requested id."""


@dataclasses.dataclass
class _Context:
	"""Everything a builder needs to shape one payload."""

	spec: catalogue.ElementSpec
	locale: i18n.Locale
	rand: random.Random
	seed_key: str
	range_key: str
	x_labels: list[str]

	@property
	def is_alert(self) -> bool:
		"""Whether the element counts occurrences."""
		return self.spec.kind is models.ElementKind.ALERT

	def text(self, text: i18n.Text) -> str:
		"""Resolves one localised string."""
		return text.get(self.locale)

	def format(self, value: float) -> str:
		"""Formats a value the way this element is read."""
		return formatting.format_value(
			value, self.spec.value_format, self.locale
		)

	def unit(self) -> str | None:
		"""Returns the element's localised unit, if it prints one."""
		return self.text(self.spec.unit) if self.spec.unit else None


def _rng(*parts: str) -> random.Random:
	"""Returns a generator seeded stably across processes and runs."""
	digest = hashlib.blake2b('|'.join(parts).encode(), digest_size=8)
	return random.Random(int.from_bytes(digest.digest(), 'big'))


def resolve_range(range_value: str, today: datetime.date) -> str:
	"""Buckets the range filter into the three shapes a chart draws.

	Args:
		range_value: A preset key, or an ISO date meaning "from that day
			to today".
		today: The branch's current date.

	Returns:
		One of 'today', '7d' or '30d'.
	"""
	if range_value in ('7d', '30d'):
		return range_value
	try:
		start = datetime.date.fromisoformat(range_value)
	except ValueError:
		return 'today'
	days = (today - start).days
	if days >= 8:
		return '30d'
	if days >= 1:
		return '7d'
	return 'today'


def _x_labels(range_key: str, locale: i18n.Locale) -> list[str]:
	"""Builds the x axis for a range, already formatted for display."""
	if range_key == '30d':
		prefix = i18n.DAY_AGO_PREFIX.get(locale)
		return [f'{prefix}{29 - index}' for index in range(_MONTH_DAYS)]
	if range_key == '7d':
		return [day.get(locale) for day in i18n.WEEKDAYS]
	return [f'{hour}:00' for hour in _HOURS]


def _updated_at(cadence: models.UpdateCadence) -> str:
	"""Stamps the payload with when its data was computed."""
	freshness = _FRESHNESS_SECONDS[cadence]
	moment = catalogue.now()
	if freshness >= 86400:
		floored = moment.replace(hour=0, minute=0, second=0, microsecond=0)
	else:
		seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
		floored = moment.replace(
			hour=0, minute=0, second=0, microsecond=0
		) + datetime.timedelta(seconds=seconds - seconds % freshness)
	return floored.isoformat(timespec='seconds')


def _walk(
	rand: random.Random,
	labels: Sequence[str],
	series_id: str,
	low: float,
	high: float,
	precision: int = 0,
) -> list[models.Point]:
	"""Random-walks a series between two bounds.

	Args:
		rand: The seeded generator.
		labels: Pre-formatted x values, in draw order.
		series_id: The key each point carries its value under.
		low: Lower bound.
		high: Upper bound.
		precision: Decimal places to keep. Durations need them, since a
			minute rounded to the minute can never read "4m 49s".

	Returns:
		One point per label.
	"""
	step = (high - low) / 4
	value = rand.uniform(low, high)
	points: list[models.Point] = []
	for label in labels:
		value = min(high, max(low, value + rand.uniform(-step, step)))
		points.append({'x': label, series_id: round(value, precision)})
	return points


def _numeric(point: models.Point, key: str) -> float:
	"""Reads one numeric field out of a point."""
	value = point.get(key, 0)
	return float(value) if isinstance(value, (int, float)) else 0.0


def _build_kpi(context: _Context) -> models.KpiPayload:
	"""One headline number, its trend, and whether it is good news."""
	spec = context.spec
	points = _walk(
		context.rand,
		context.x_labels[-_TREND_POINTS:],
		'value',
		spec.value_min,
		spec.value_max,
		precision=2 if spec.value_format is _DURATION else 0,
	)
	last = _numeric(points[-1], 'value')
	first = _numeric(points[0], 'value')
	severity = (
		formatting.rolled_severity(context.rand)
		if context.is_alert
		else models.Severity.OK
	)
	return models.KpiPayload(
		value=context.format(last),
		unit=context.unit(),
		severity=severity,
		delta=formatting.delta_between(first, last, context.is_alert),
		trend=models.TrendPayload(
			series=[
				models.SeriesDef(
					id='value',
					label=context.text(spec.title),
					color_index=0,
				)
			],
			points=points,
		),
	)


@dataclasses.dataclass(frozen=True)
class CameraStatus:
	"""Which cameras are up, and whether anything actually looked."""

	up: dict[str, bool]
	measured: bool


def camera_status(seed_key: str) -> CameraStatus:
	"""Reports which cameras are up.

	Args:
		seed_key: The filters, language excluded, as a stable key.

	Returns:
		True per camera id that is publishing, and whether that came
		from the pipeline. Real when there is one to ask - a camera is
		up when it is configured AND its stream server has it - and a
		stable roll otherwise.

		Feed health, the downtime chart and the grid all read this one
		answer, so the three can never disagree about how many cameras
		are down - and `measured` travels with it, so no caller has to
		re-derive the fallback and risk disagreeing about that too.
	"""
	real = live.feed_status()
	if real is not None:
		return CameraStatus(up=real, measured=True)
	return CameraStatus(up=rolled_camera_status(seed_key), measured=False)


def rolled_camera_status(seed_key: str) -> dict[str, bool]:
	"""Invents which cameras are up, stably.

	Args:
		seed_key: The filters, language excluded, as a stable key.

	Returns:
		True per camera id that is up. The same key always rolls the
		same answer, so a card does not flicker between polls.
	"""
	rand = _rng('cameras', seed_key)
	return {
		camera.id: rand.random() > _OFFLINE_CHANCE
		for camera in catalogue.CAMERAS
	}


def _build_camera_status(context: _Context) -> models.StatGroupPayload:
	"""How many feeds are reporting frames, now and over the window.

	Args:
		context: The request the card is being built for.

	Returns:
		The three numbers, and - only when they are invented - the one
		line worth watching behind them: how many were down. A total
		that never moves and an online count that is only the total
		minus this line would say nothing twice.

		Real feed health carries NO trend. Nothing stores a history of
		it: the servers that own the streams are asked what is true now,
		and drawing a random walk beside three numbers that are real
		would be the same false claim the rest of this design refuses to
		make, dressed as a chart.
	"""
	answer = camera_status(context.seed_key)
	status = answer.up
	online = sum(status.values())
	total = len(status)
	offline = total - online

	stats = [
		models.Stat(
			id='total', label=context.text(i18n.TOTAL), value=str(total)
		),
		models.Stat(
			id='online',
			label=context.text(i18n.ONLINE),
			value=str(online),
			severity=models.Severity.OK,
		),
		models.Stat(
			id='offline',
			label=context.text(i18n.OFFLINE),
			value=str(offline),
			severity=(
				models.Severity.OK
				if offline == 0
				else models.Severity.CRITICAL
			),
		),
	]
	if answer.measured:
		return models.StatGroupPayload(stats=stats)

	walk = _walk(
		context.rand,
		context.x_labels[-_TREND_POINTS:],
		'offline',
		0,
		max(3, offline),
	)
	points: list[models.Point] = [
		{
			'x': str(point['x']),
			'offline': min(total, int(_numeric(point, 'offline'))),
		}
		for point in walk
	]
	# The last point is now, so it carries the number the stats print
	# rather than another roll of the dice.
	points[-1] = {'x': points[-1]['x'], 'offline': offline}
	return models.StatGroupPayload(
		stats=stats,
		trend=models.TrendPayload(
			series=[
				models.SeriesDef(
					id='offline',
					label=context.text(i18n.OFFLINE),
					# The red slot: this line is the bad news.
					color_index=4,
				)
			],
			points=points,
		),
	)


def _split_stats(context: _Context) -> models.StatGroupPayload:
	"""A total and its two parts, with a trend the three agree with."""
	totals = _walk(
		context.rand,
		context.x_labels[-_TREND_POINTS:],
		'total',
		context.spec.value_min,
		context.spec.value_max,
	)
	points: list[models.Point] = []
	for point in totals:
		total = _numeric(point, 'total')
		# The first part is a share of the total and the second is the
		# remainder, so the lines add up the way the numbers do.
		first = round(total * context.rand.uniform(0.55, 0.75))
		points.append(
			{
				'x': str(point['x']),
				'total': total,
				'indoor': first,
				'outdoor': total - first,
			}
		)
	latest = points[-1]
	labels = (i18n.TOTAL, i18n.INDOOR, i18n.OUTDOOR)
	delta = formatting.delta_between(
		_numeric(points[0], 'total'),
		_numeric(latest, 'total'),
		context.is_alert,
	)
	stats = [
		models.Stat(
			id='total',
			label=context.text(labels[0]),
			value=context.format(_numeric(latest, 'total')),
			unit=context.unit(),
			delta=delta,
		),
		models.Stat(
			id='indoor',
			label=context.text(labels[1]),
			value=context.format(_numeric(latest, 'indoor')),
		),
		models.Stat(
			id='outdoor',
			label=context.text(labels[2]),
			value=context.format(_numeric(latest, 'outdoor')),
		),
	]
	series = [
		models.SeriesDef(
			id=series_id, label=context.text(label), color_index=index
		)
		for index, (series_id, label) in enumerate(
			zip(('total', 'indoor', 'outdoor'), labels)
		)
	]
	return models.StatGroupPayload(
		stats=stats,
		trend=models.TrendPayload(series=series, points=points),
	)


def _build_stat_group(context: _Context) -> models.StatGroupPayload:
	"""Picks the stat group this element is."""
	if context.spec.id == 'camera-status':
		return _build_camera_status(context)
	return _split_stats(context)


def _build_series(context: _Context) -> models.SeriesPayload:
	"""A line over the window's x axis."""
	spec = context.spec
	points = _walk(
		context.rand,
		context.x_labels,
		'value',
		spec.value_min,
		spec.value_max,
	)
	return models.SeriesPayload(
		series=[
			models.SeriesDef(
				id='value', label=context.text(spec.title), color_index=0
			)
		],
		points=points,
		x_label=context.text(
			i18n.HOUR if context.range_key == 'today' else i18n.DAY
		),
		y_label=context.text(i18n.COUNT),
		unit=context.unit(),
	)


def _build_histogram(context: _Context) -> models.SeriesPayload:
	"""Visits per dwell-time bucket."""
	spec = context.spec
	return models.SeriesPayload(
		series=[
			models.SeriesDef(
				id='value', label=context.text(i18n.VISITS), color_index=0
			)
		],
		points=_walk(
			context.rand,
			_DWELL_BUCKETS,
			'value',
			spec.value_min,
			spec.value_max,
		),
		x_label=context.text(i18n.MINUTES),
		y_label=context.text(i18n.VISITS),
	)


def _camera_label(camera_id: str, locale: i18n.Locale) -> str:
	"""Names a camera the way every payload names it."""
	return f'{i18n.CAMERA.get(locale)} {camera_id}'


def _build_camera_grid(context: _Context) -> models.CameraGridPayload:
	"""Every camera tile, with its status and stream."""
	status = camera_status(context.seed_key).up
	feeds = []
	for camera in catalogue.CAMERAS:
		online = status[camera.id]
		feeds.append(
			models.CameraFeed(
				id=camera.id,
				label=_camera_label(camera.id, context.locale),
				zone=context.text(camera.zone),
				status='online' if online else 'offline',
				status_label=context.text(
					i18n.ONLINE if online else i18n.OFFLINE
				),
				stream_url=camera.stream_url if online else None,
			)
		)
	return models.CameraGridPayload(feeds=feeds)


_BUILDERS: dict[models.ElementType, Callable[[_Context], models.Payload]] = {
	models.ElementType.KPI: _build_kpi,
	models.ElementType.STAT_GROUP: _build_stat_group,
	models.ElementType.LINE: _build_series,
	models.ElementType.HISTOGRAM: _build_histogram,
	models.ElementType.CAMERA_GRID: _build_camera_grid,
}


def _context(
	spec: catalogue.ElementSpec,
	seed_key: str,
	locale: i18n.Locale,
	range_value: str,
	prefix: str = '',
) -> _Context:
	"""Assembles what a builder needs for one request."""
	range_key = resolve_range(range_value, catalogue.today())
	return _Context(
		spec=spec,
		locale=locale,
		rand=_rng(prefix, spec.id, seed_key),
		seed_key=seed_key,
		range_key=range_key,
		x_labels=_x_labels(range_key, locale),
	)


def _spec_or_raise(element_id: str) -> catalogue.ElementSpec:
	"""Looks up an element.

	Args:
		element_id: The catalogue id from the request path.

	Returns:
		The element spec.

	Raises:
		UnknownElementError: The catalogue has no such element.
	"""
	spec = catalogue.ELEMENTS_BY_ID.get(element_id)
	if spec is None:
		raise UnknownElementError(element_id)
	return spec


def build_element(
	element_id: str, seed_key: str, locale: i18n.Locale, range_value: str
) -> models.ElementResponse:
	"""Builds the payload behind one card.

	Args:
		element_id: The catalogue id from the request path.
		seed_key: The filters, language excluded, as a stable key.
		locale: The requested language.
		range_value: The raw `range` filter.

	Returns:
		The response, with a `type` matching the config's. Built from
		what the cameras saw when the element declares a source and the
		analytics service has something to say, and from the generated
		data otherwise - which is what keeps a card readable while the
		pipeline is still warming up.

	Raises:
		UnknownElementError: The catalogue has no such element.
	"""
	spec = _spec_or_raise(element_id)
	context = _context(spec, seed_key, locale, range_value)
	built = live.build(context)
	if built is not None:
		return models.ElementResponse(
			element_id=spec.id,
			updated_at=built.updated_at,
			type=spec.type,
			source=models.DataSource.CAMERAS,
			data=built.data,
		)
	return models.ElementResponse(
		element_id=spec.id,
		updated_at=_updated_at(spec.updates),
		type=spec.type,
		source=models.DataSource.GENERATED,
		data=_BUILDERS[spec.type](context),
	)


def build_instance_log(
	element_id: str, seed_key: str, locale: i18n.Locale, range_value: str
) -> models.InstanceLog:
	"""Builds the occurrences behind an alert card.

	Args:
		element_id: The catalogue id from the request path.
		seed_key: The filters, language excluded, as a stable key.
		locale: The requested language.
		range_value: The raw `range` filter.

	Returns:
		The log, newest first. An element with nothing to show returns
		an empty list rather than an error.

	Raises:
		UnknownElementError: The catalogue has no such element.
	"""
	spec = _spec_or_raise(element_id)
	context = _context(spec, seed_key, locale, range_value, 'instances')
	real = live.instances(context)
	if real is not None:
		return real
	rand = context.rand
	total = rand.randint(3, 12)
	cameras = spec.cameras or ('03',)
	instances = [
		models.Instance(
			id=f'{spec.id}-{index}',
			timestamp=(
				f'{rand.randint(8, 21):02d}:{rand.randint(0, 59):02d}'
			),
			camera=_camera_label(
				cameras[index % len(cameras)], locale
			),
			detail=context.text(spec.description),
			severity=formatting.rolled_severity(rand),
			clip_url=f'/api/clips/{spec.id}/{index}.mp4',
		)
		for index in range(total)
	]
	instances.sort(key=lambda entry: entry.timestamp, reverse=True)
	return models.InstanceLog(
		element_id=spec.id,
		title=context.text(spec.title),
		total=total,
		source=models.DataSource.GENERATED,
		instances=instances,
	)


def monthly_trend(
	spec: catalogue.ElementSpec, seed_key: str, locale: i18n.Locale
) -> tuple[models.TrendPayload, float]:
	"""Builds a monitor's last 30 days and its average.

	Args:
		spec: The monitor being described.
		seed_key: The filters, language excluded, as a stable key.
		locale: The requested language.

	Returns:
		The trend the alert builder draws, and the raw 30-day average
		the threshold field is prefilled with.
	"""
	labels = _x_labels('30d', locale)
	points = _walk(
		_rng('monthly', spec.id, seed_key),
		labels,
		'value',
		spec.value_min,
		spec.value_max,
	)
	average = sum(_numeric(point, 'value') for point in points) / len(points)
	trend = models.TrendPayload(
		series=[
			models.SeriesDef(
				id='value', label=spec.title.get(locale), color_index=0
			)
		],
		points=points,
	)
	return trend, round(average)
