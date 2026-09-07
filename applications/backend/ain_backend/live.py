"""Payloads built from what the cameras actually saw.

`payloads` generates every card deterministically; this builds the same
shapes from `analytics-api` when an element declares a `Source` and the
service has something to say. The two are interchangeable by construction:
same models, same field names, same contract. `payloads.build_element`
tries this first and falls back, so a pipeline that is still building its
TensorRT engine leaves a readable dashboard rather than an empty one.

The analytics service returns numbers and units. Every string a person
reads - the formatted duration, the unit, the severity, the sentiment - is
decided here, which is what keeps Arabic in one place.
"""

import dataclasses
import datetime
import urllib.parse

from ain_backend import analytics
from ain_backend import catalogue
from ain_backend import formatting
from ain_backend import i18n
from ain_backend import models

_Kind = catalogue.SourceKind
_TREND_POINTS = 12

# What a card shows for a number the system cannot produce. Not 0: a zero
# asserts "we watched and there was nothing", which for the PPE checks is a
# claim no person detector can make - and one that would very likely render
# green on a hygiene dashboard.
_NO_VALUE = '—'

# Bucket sizes per range, in seconds. They match the x axis the generated
# series draws, so a card does not change shape when it switches to real
# data: hours across today, days across a week or a month.
_INTERVALS = {'today': 3600, '7d': 86400, '30d': 86400}
# Realtime cards want a finer trend than the chart granularity - but only
# where the axis can tell the buckets apart. A week is labelled by weekday,
# so hourly buckets there would stack twenty-four points on one x value.
_LIVE_INTERVALS = {'today': 300, '7d': 86400, '30d': 86400}

# Dwell histogram edges, in seconds: 0-10, 10-20, 20-30, 30-45, 45-60, 60+
# minutes, matching the buckets the generated histogram draws.
_DWELL_EDGES = (0, 600, 1200, 1800, 2700, 3600)

# Daily buckets are aligned to the branch's midnight, not to UTC's. Riyadh is
# three hours ahead, so a UTC-aligned day puts the first three hours of every
# local day on the previous bar - and today's data on yesterday's.
_TZ = str(catalogue.BRANCH_TIMEZONE)


@dataclasses.dataclass(frozen=True)
class Built:
	"""A payload from real data, and when that data was current."""

	data: models.Payload
	updated_at: str


def _moment(stamp: str) -> datetime.datetime:
	"""Reads one ISO 8601 timestamp into branch-local time."""
	return datetime.datetime.fromisoformat(stamp).astimezone(
		catalogue.BRANCH_TIMEZONE
	)


def _label(
	stamp: str, range_key: str, locale: i18n.Locale, interval: int = 3600
) -> str:
	"""Names one bucket on the x axis.

	Args:
		stamp: The bucket's ISO 8601 start.
		range_key: One of 'today', '7d' or '30d'.
		locale: The requested language.
		interval: The bucket size in seconds. Buckets finer than an hour
			need the minutes, or several of them print the same label and
			the chart reads as if the value jumped within one point.

	Returns:
		The label, in branch-local time. A real series starts when the
		pipeline did rather than at 08:00, so the axis is built from the
		buckets that exist instead of from a fixed list.
	"""
	moment = _moment(stamp)
	if range_key == '30d':
		days = (catalogue.today() - moment.date()).days
		return f'{i18n.DAY_AGO_PREFIX.get(locale)}{days}'
	if range_key == '7d':
		return i18n.WEEKDAYS[moment.weekday()].get(locale)
	if interval < 3600:
		return f'{moment.hour:02d}:{moment.minute:02d}'
	return f'{moment.hour:02d}:00'


def _updated_at(body: dict) -> str:
	"""Stamps a payload with the end of the window the data covers.

	Args:
		body: Any analytics response.

	Returns:
		The window's end, which is the newest detection the pipeline had
		stored. A stalled pipeline therefore shows a card going stale
		rather than a freshly-stamped card of old numbers.
	"""
	end = body.get('end')
	if not end:
		return catalogue.now().isoformat(timespec='seconds')
	return _moment(end).isoformat(timespec='seconds')


def _series_def(label: str, index: int = 0) -> models.SeriesDef:
	"""One line in a chart."""
	return models.SeriesDef(id='value', label=label, color_index=index)


def _kpi(
	context,
	points: list[models.Point],
	value: float,
	severity: models.Severity | None = None,
) -> models.KpiPayload:
	"""Assembles a KPI card from a real series.

	Args:
		context: The request the card is being built for.
		points: The trend, oldest first.
		value: The headline number, in the element's own units.
		severity: The judgement, or None to leave it OK.

	Returns:
		The payload, formatted and judged.
	"""
	trimmed = points[-_TREND_POINTS:]
	first = float(trimmed[0].get('value', 0)) if trimmed else value
	return models.KpiPayload(
		value=context.format(value),
		unit=context.unit(),
		severity=severity or models.Severity.OK,
		delta=formatting.delta_between(first, value, context.is_alert),
		trend=(
			models.TrendPayload(
				series=[_series_def(context.text(context.spec.title))],
				points=trimmed,
			)
			if trimmed
			else None
		),
	)


def _occupancy(context, source: catalogue.Source, params: dict) -> Built | None:
	"""Builds a headcount card - one number, or a total and its parts.

	Args:
		context: The request the card is being built for.
		source: The element's declared source.
		params: The window parameters.

	Returns:
		The payload, or None if the service had nothing.
	"""
	interval = _LIVE_INTERVALS[context.range_key]
	if source.split:
		return _occupancy_split(context, source, params, interval)

	body = analytics.get(
		'/occupancy', {**params, **source.query(), 'interval': interval, 'tz': _TZ}
	)
	if body is None:
		return None
	points: list[models.Point] = [
		{'x': _label(bucket['ts'], context.range_key, context.locale, interval),
		 'value': round(bucket['mean'])}
		for bucket in body['buckets']
	]
	return Built(
		data=_kpi(context, points, body['latest']),
		updated_at=_updated_at(body),
	)


def _occupancy_split(
	context, source: catalogue.Source, params: dict, interval: int
) -> Built | None:
	"""Builds a total-and-its-parts card from one call per zone.

	Args:
		context: The request the card is being built for.
		source: The element's declared source, carrying the split.
		params: The window parameters.
		interval: Bucket size in seconds.

	Returns:
		The payload, or None if any zone was unavailable.

	The total is the sum of the zones, which is only right because the
	polygons are drawn disjoint: there is no cross-camera
	re-identification to deduplicate somebody standing in two of them.
	"""
	bodies = {}
	labels = {'total': i18n.TOTAL}
	for stat_id, zone, label in source.split:
		body = analytics.get(
			'/occupancy',
			{**params, 'zone': zone, 'interval': interval, 'tz': _TZ},
		)
		if body is None:
			return None
		bodies[stat_id] = body
		labels[stat_id] = label
	series_ids = ('total', *bodies)
	length = min(len(body['buckets']) for body in bodies.values())
	points: list[models.Point] = []
	for index in range(length):
		parts = {
			stat_id: round(body['buckets'][index]['mean'])
			for stat_id, body in bodies.items()
		}
		first = next(iter(bodies.values()))['buckets'][index]
		points.append(
			{
				'x': _label(
					first['ts'], context.range_key, context.locale, interval
				),
				'total': sum(parts.values()),
				**parts,
			}
		)

	latest = {
		stat_id: round(body['latest']) for stat_id, body in bodies.items()
	}
	total = sum(latest.values())
	opening = float(points[0]['total']) if points else total
	stats = [
		models.Stat(
			id='total',
			label=context.text(i18n.TOTAL),
			value=context.format(total),
			unit=context.unit(),
			delta=formatting.delta_between(opening, total, context.is_alert),
		)
	]
	stats.extend(
		models.Stat(
			id=stat_id,
			label=context.text(labels.get(stat_id, i18n.TOTAL)),
			value=context.format(value),
		)
		for stat_id, value in latest.items()
	)
	return Built(
		data=models.StatGroupPayload(
			stats=stats,
			trend=models.TrendPayload(
				series=[
					models.SeriesDef(
						id=series_id,
						label=context.text(labels.get(series_id, i18n.TOTAL)),
						color_index=index,
					)
					for index, series_id in enumerate(series_ids)
				],
				points=points,
			),
		),
		updated_at=_updated_at(next(iter(bodies.values()))),
	)


def _footfall(context, source: catalogue.Source, params: dict) -> Built | None:
	"""Builds the crossings-per-bucket line.

	Args:
		context: The request the card is being built for.
		source: The element's declared source.
		params: The window parameters.

	Returns:
		The payload, or None if the service had nothing.
	"""
	interval = _INTERVALS[context.range_key]
	body = analytics.get(
		'/footfall', {**params, **source.query(), 'interval': interval, 'tz': _TZ}
	)
	if body is None:
		return None
	points: list[models.Point] = [
		{'x': _label(bucket['ts'], context.range_key, context.locale, interval),
		 'value': bucket['in']}
		for bucket in body['buckets']
	]
	return Built(
		data=models.SeriesPayload(
			series=[_series_def(context.text(context.spec.title))],
			points=points,
			x_label=context.text(
				i18n.HOUR if context.range_key == 'today' else i18n.DAY
			),
			y_label=context.text(i18n.COUNT),
			unit=context.unit(),
		),
		updated_at=_updated_at(body),
	)


def _dwell(context, source: catalogue.Source, params: dict) -> Built | None:
	"""Builds a duration card, as a headline number or a histogram.

	Args:
		context: The request the card is being built for.
		source: The element's declared source.
		params: The window parameters.

	Returns:
		The payload, or None if the service had nothing.

	Analytics measures in seconds; every duration in the catalogue is in
	minutes, because that is the unit `formatting.format_duration`
	reads. The conversion happens here, once.
	"""
	interval = _LIVE_INTERVALS[context.range_key]
	body = analytics.get(
		'/dwell',
		{
			**params,
			**source.query(),
			'buckets': ','.join(str(edge) for edge in _DWELL_EDGES),
			'interval': interval,
			'tz': _TZ,
		},
	)
	if body is None:
		return None

	if context.spec.type is models.ElementType.HISTOGRAM:
		points: list[models.Point] = [
			{'x': _bucket_label(bucket), 'value': bucket['visits']}
			for bucket in body['histogram']
		]
		return Built(
			data=models.SeriesPayload(
				series=[
					models.SeriesDef(
						id='value',
						label=context.text(i18n.VISITS),
						color_index=0,
					)
				],
				points=points,
				x_label=context.text(i18n.MINUTES),
				y_label=context.text(i18n.VISITS),
			),
			updated_at=_updated_at(body),
		)

	minutes = body['mean_seconds'] / 60
	# The sparkline under a duration is that duration over time, not the
	# histogram: a KPI card and a histogram card answer different questions
	# and must not draw the same picture.
	points = [
		{
			'x': _label(
				bucket['ts'], context.range_key, context.locale, interval
			),
			'value': round(bucket['mean_seconds'] / 60, 2),
		}
		for bucket in body['buckets']
	]
	return Built(
		data=_kpi(context, points, minutes),
		updated_at=_updated_at(body),
	)


def _bucket_label(bucket: dict) -> str:
	"""Names one histogram bucket in whole minutes."""
	low = bucket['from'] // 60
	if bucket['to'] is None:
		return f'{low}+'
	return f'{low}-{bucket["to"] // 60}'


def fetch_events(spec: catalogue.ElementSpec, params: dict) -> dict | None:
	"""Reads the occurrences behind one alert element.

	Args:
		spec: The element, which must carry an EVENTS source.
		params: The window parameters.

	Returns:
		The analytics response, or None if it was unavailable.
	"""
	source = spec.source
	if source is None or source.kind is not _Kind.EVENTS:
		return None
	return analytics.get(f'/events{source.route}', {**params, **source.query()})


def _events(context, source: catalogue.Source, params: dict) -> Built | None:
	"""Builds an alert count card from the occurrences themselves.

	Args:
		context: The request the card is being built for.
		source: The element's declared source.
		params: The window parameters.

	Returns:
		The payload, or None if the service had nothing.
	"""
	body = analytics.get(
		f'/events{source.route}', {**params, **source.query(), 'tz': _TZ}
	)
	if body is None:
		return None

	interval = _INTERVALS[context.range_key]
	counts: dict[str, int] = {}
	for event in body['events']:
		bucket = _floor(event['start'], interval)
		counts[bucket] = counts.get(bucket, 0) + 1
	points: list[models.Point] = [
		{'x': _label(stamp, context.range_key, context.locale, interval),
		 'value': count}
		for stamp, count in sorted(counts.items())
	]
	total = body['count']
	return Built(
		data=_kpi(
			context,
			points,
			total,
			severity=formatting.count_severity(total),
		),
		updated_at=_updated_at(body),
	)


def _floor(stamp: str, interval: int) -> str:
	"""Rounds a timestamp down to a bucket boundary."""
	moment = datetime.datetime.fromisoformat(stamp)
	epoch = int(moment.timestamp())
	return datetime.datetime.fromtimestamp(
		epoch - epoch % interval, datetime.timezone.utc
	).isoformat()


def instances(context) -> models.InstanceLog | None:
	"""Builds the occurrence log behind an alert card from real events.

	Args:
		context: The request the log is being built for.

	Returns:
		The log, newest first, or None to fall back to the generated
		one. Every entry carries a clip URL pointing at the exact window
		that raised it, so the video a reader opens is the video the
		number came from.
	"""
	spec = context.spec
	if spec.source is None or not analytics.configured():
		return None
	if spec.source.kind is _Kind.PPE:
		# The card reads "-" because nothing measures this. A drilldown of
		# generated violations under it would be the same false claim the
		# dash exists to avoid, told at greater length.
		return models.InstanceLog(
			element_id=spec.id,
			title=context.text(spec.title),
			total=0,
			instances=[],
		)
	params = analytics.window(
		context.range_key, catalogue.today(), catalogue.BRANCH_TIMEZONE
	)
	body = fetch_events(spec, params)
	if body is None:
		return None

	# Sorted on the instant, then labelled - not sorted on the label. Over
	# a week's window "09:15" appears seven times and sorting the strings
	# interleaves the days.
	entries = []
	for event in sorted(body['events'], key=lambda e: e['start'], reverse=True):
		camera = (event.get('cameras') or ['03'])[0]
		moment = _moment(event['start'])
		entries.append(
			models.Instance(
				id=event['id'],
				timestamp=(
					moment.strftime('%H:%M')
					if context.range_key == 'today'
					else moment.strftime('%m-%d %H:%M')
				),
				camera=f'{i18n.CAMERA.get(context.locale)} {camera}',
				detail=context.text(spec.description),
				severity=_event_severity(event),
				clip_url=_clip_url(event, camera),
			)
		)
	return models.InstanceLog(
		element_id=spec.id,
		title=context.text(spec.title),
		total=body['count'],
		instances=entries,
	)


def _event_severity(event: dict) -> models.Severity:
	"""Judges one occurrence by how far past its threshold it went.

	Args:
		event: One event from the analytics service.

	Returns:
		The severity that colours the row. Half again over the threshold
		is where "worth a look" becomes "go and look".
	"""
	threshold = float(event.get('threshold') or 0)
	peak = float(event.get('peak_value') or 0)
	if not threshold:
		return models.Severity.WARN
	ratio = peak / threshold
	if event.get('comparator') == 'below':
		ratio = 1 / ratio if ratio else 2.0
	return models.Severity.CRITICAL if ratio >= 1.5 else models.Severity.WARN


def _clip_url(event: dict, camera: str) -> str:
	"""Points at the video for exactly the window that raised an event."""
	query = urllib.parse.urlencode(
		{'camera': camera, 'start': event['start'], 'end': event['end']}
	)
	return f'/api/clips/{event["id"]}.mp4?{query}'


def feed_status() -> dict[str, bool] | None:
	"""Which of the branch's cameras are actually being watched.

	Returns:
		True per camera id that is publishing, or None when there is no
		analytics service to ask - in which case the generated roll fills
		in, as it does everywhere else.

	Two different "no" collapse into one here, deliberately. A camera the
	pipeline is not configured for has nothing watching it; a configured
	camera whose stream server cannot be reached cannot be seen either.
	The service reports those separately, because they are different
	facts and an operator wants both. The dashboard shows one thing,
	because a viewer asking "can I see this camera" gets the same answer
	to both - and the direction of the collapse matters: unwatched
	reported as online would be the lie, offline is merely the truth
	stated flatly.
	"""
	if not analytics.configured():
		return None
	body = analytics.get('/cameras', {})
	if body is None:
		return None
	watched = {entry['id']: entry.get('live') for entry in body['cameras']}
	return {camera.id: bool(watched.get(camera.id)) for camera in catalogue.CAMERAS}


def breaches(
	spec: catalogue.ElementSpec,
	comparator: str,
	threshold: float,
	range_key: str,
) -> int | None:
	"""Counts how many times one alert rule fired over a window.

	Args:
		spec: The monitor the rule watches.
		comparator: 'above' or 'below'.
		threshold: The rule's threshold, in the element's own units.
		range_key: One of 'today', '7d' or '30d'.

	Returns:
		The number of occurrences, or None when the rule cannot be
		evaluated - an unwatchable monitor, or no analytics service.

	Evaluated on read, not on a timer. A rule is a query; running it when
	somebody opens the alerts page costs nothing, needs no scheduler and
	keeps every read route a pure function of its query string. Pushing
	notifications is a different service: it needs a timer, a delivery
	channel, and dedupe so one sustained breach does not send forty
	messages.
	"""
	source = spec.source
	if source is None or not analytics.configured():
		return None
	target = _alert_target(source)
	metric = _ALERT_METRICS.get(source.kind)
	if target is None or metric is None:
		return None
	params = analytics.window(
		range_key, catalogue.today(), catalogue.BRANCH_TIMEZONE
	)
	# Durations are minutes everywhere in the catalogue, because that is
	# what formatting.format_duration reads; the analytics service measures
	# them in seconds. Keyed on the METRIC, not on value_format: dwell time
	# per table is a duration that happens to print as a plain count, and
	# scaling on the format would send its threshold sixty times too small.
	scaled = threshold * 60 if metric == 'dwell' else threshold
	body = analytics.get(
		'/events',
		{
			**params,
			'metric': metric,
			'zone': target,
			'comparator': comparator,
			'threshold': scaled,
			'type': 'rule',
			# The threshold came from the monitor's own 30-day average, so
			# it is in the units that monitor is read in. Footfall is a
			# rate - people per hour - and evaluating it against a
			# thirty-second bucket would compare an hour's number to half
			# a minute's.
			'interval': _INTERVALS[range_key] if metric == 'footfall' else None,
			'tz': str(catalogue.BRANCH_TIMEZONE),
		},
	)
	return body['count'] if body else None


def _alert_target(source: catalogue.Source) -> str | None:
	"""Names the zone or line a rule on this source is evaluated over.

	Args:
		source: The element's declared source.

	Returns:
		The target name, or None if the source has none. A split stat
		group is evaluated over its first part: a rule reading "indoor
		and outdoor together, above 40" is a different rule and would
		need its own zone in cameras.yml.
	"""
	params = dict(source.params)
	if 'zone' in params:
		return params['zone']
	if 'line' in params:
		return params['line']
	if source.split:
		return source.split[0][1]
	return None


_ALERT_METRICS = {
	_Kind.OCCUPANCY: 'occupancy',
	_Kind.FOOTFALL: 'footfall',
	_Kind.DWELL: 'dwell',
}


def _ppe(context, source: catalogue.Source, params: dict) -> Built | None:
	"""Reports that a PPE check cannot be answered yet.

	Args:
		context: The request the card is being built for.
		source: The element's declared source.
		params: Unused; PPE has no window.

	Returns:
		A card showing that number once a PPE model reports one, a dash
		until then, or None if the service was unreachable - in which
		case the generated data fills in, which is the same fallback
		every other element gets.
	"""
	del params
	body = analytics.get(f'/ppe{source.route}', {})
	if body is None:
		return None
	stamp = catalogue.now().isoformat(timespec='seconds')
	if body.get('status') == 'ok' and body.get('value') is not None:
		# The model landed. Its number is the answer, and the shape is the
		# one this card has been drawing all along.
		value = float(body['value'])
		return Built(
			data=models.KpiPayload(
				value=context.format(value),
				unit=context.unit(),
				severity=formatting.count_severity(value),
			),
			updated_at=stamp,
		)
	return Built(
		data=models.KpiPayload(
			value=_NO_VALUE,
			unit=context.unit(),
			severity=models.Severity.INFO,
		),
		updated_at=stamp,
	)


_BUILDERS = {
	_Kind.OCCUPANCY: _occupancy,
	_Kind.FOOTFALL: _footfall,
	_Kind.DWELL: _dwell,
	_Kind.EVENTS: _events,
	_Kind.PPE: _ppe,
}


def build(context) -> Built | None:
	"""Builds one card from real data, if there is any.

	Args:
		context: The request the card is being built for.

	Returns:
		The payload and its timestamp, or None - which is the caller's
		signal to fall back to the generated data.
	"""
	source = context.spec.source
	if source is None or not analytics.configured():
		return None
	params = analytics.window(
		context.range_key, catalogue.today(), catalogue.BRANCH_TIMEZONE
	)
	try:
		return _BUILDERS[source.kind](context, source, params)
	except (KeyError, TypeError, ValueError, ZeroDivisionError):
		# A response shaped differently from what this expects is a bug,
		# but not one worth blanking the dashboard over: the generated
		# data takes over exactly as it does when the service is down.
		return None
