"""Every KPI, as SQL over stored detections.

Nothing here is precomputed and nothing here is a materialized view. Zones,
lines and thresholds are configuration, and an aggregate that reads
configuration cannot be an insert trigger: baking a zone into an MV is what
makes it impossible to move the zone and recompute last month. (It would
also be wrong - an MV sees one insert block, so a `lagInFrame` partitioned
by track cannot span them.)

Every window is [start, end) - start inclusive, end exclusive. Adjacent
buckets otherwise double-count on the boundary, which stays invisible until
somebody sums the hourly footfall and beats the daily total.

One thing the stored rows cannot tell you: a zone reading zero people is
either an empty room or a camera that stopped. Feed health comes from the
adapter and MediaMTX, not from here.
"""

import dataclasses
import datetime
import math
from collections.abc import Sequence

from clickhouse_connect.driver import client as ch_client

from ain_analytics import config
from ain_analytics import db

# A time series is evaluated on buckets, and the number of them has to stay
# bounded whether the caller asked for an hour or a month.
_MAX_BUCKETS = 5000

# A tracker reuses its ids. Two people can share one track_id an hour apart,
# and a visit measured as max(ts) - min(ts) over that id would be an hour
# long - which is how a "long wait" of forty-six minutes appears in a shop
# nobody stayed in. A gap longer than this ends the visit.
_VISIT_GAP_MS = 5_000

# `/overlay` covers one video window, not one frame. Anything past this is a
# caller who meant to ask for a chart.
OVERLAY_MAX_SECONDS = 60
OVERLAY_MAX_ROWS = 50_000

# A month of a busy queue is tens of thousands of visits. This is a ceiling
# on one response, not on the measurement: `dwell` aggregates in SQL and is
# not capped, so the counts it reports stay true above this.
MAX_VISITS = 20_000


@dataclasses.dataclass(frozen=True)
class Window:
	"""A half-open time range."""

	start: datetime.datetime
	end: datetime.datetime

	@property
	def seconds(self) -> float:
		"""How long the window is."""
		return (self.end - self.start).total_seconds()

	def params(self) -> dict:
		"""The bind parameters every query in here shares."""
		return {'start': self.start, 'end': self.end}


def latest_ts(client: ch_client.Client) -> datetime.datetime | None:
	"""Returns the newest detection stored, or None if there are none.

	Args:
		client: A connected ClickHouse client.

	Returns:
		The timestamp, in UTC. This is what an omitted `end` means: the
		pipeline runs a second or two behind, and answering "now" returns
		a trailing bucket that is empty for no reason a reader can see.
	"""
	rows = client.query(f'SELECT max(ts) FROM {db.TABLE}').result_rows
	value = rows[0][0] if rows else None
	if value is None or value.year < 2000:
		return None
	return value.replace(tzinfo=datetime.timezone.utc)


def bucket_seconds(window: Window, requested: int) -> int:
	"""Clamps a requested bucket size to something answerable.

	Args:
		window: The range being asked for.
		requested: The caller's interval, in seconds.

	Returns:
		An interval that divides the window into at most `_MAX_BUCKETS`.
	"""
	floor = math.ceil(window.seconds / _MAX_BUCKETS) if window.seconds else 1
	return max(1, requested, floor)


def bucket_expr(column: str, interval: int, tz: str) -> str:
	"""Buckets a timestamp, aligning whole days to a local midnight.

	Args:
		column: The expression to bucket.
		interval: The bucket size, in seconds.
		tz: An IANA timezone name.

	Returns:
		A `toStartOfInterval` call. A second-based interval is aligned to
		the epoch no matter what timezone it is given, so a whole number
		of days is expressed in DAY units instead - otherwise a daily bar
		for a branch three hours ahead of UTC holds the last three hours
		of the day before, and today's data lands on yesterday.
	"""
	if interval % 86400 == 0:
		days = interval // 86400
		return (
			f"toStartOfInterval({column}, INTERVAL {days} DAY, '{tz}')"
		)
	return f'toStartOfInterval({column}, INTERVAL {interval} SECOND)'


def _fill(window: Window, interval: int, tz: str) -> str:
	"""Zero-fills the empty buckets of a grouped series.

	Args:
		window: The range being asked for.
		interval: The bucket size, in seconds.
		tz: An IANA timezone name, for whole-day alignment.

	Returns:
		A `WITH FILL` clause. Without it a bucket in which nobody was
		seen is missing rather than zero, and every average is computed
		over only the buckets that happened to have somebody in them.
	"""
	# The bounds are cast to DateTime because toStartOfInterval returns one:
	# a DateTime64 here is rejected outright as an incompatible fill type.
	start = bucket_expr('{start:DateTime64(3)}', interval, tz)
	return (
		' WITH FILL'
		f" FROM toDateTime({start}, 'UTC')"
		" TO toDateTime({end:DateTime64(3)}, 'UTC')"
		f' STEP INTERVAL {interval} SECOND'
	)


def occupancy(
	client: ch_client.Client,
	zone: config.Zone,
	window: Window,
	interval: int,
	tz: str = 'UTC',
) -> list[dict]:
	"""Counts how many people stood in a zone, over time.

	Args:
		client: A connected ClickHouse client.
		zone: The area to count inside.
		window: The range to count over.
		interval: Bucket size in seconds.
		tz: An IANA timezone name, so a daily bucket starts at the
			branch's midnight rather than at UTC's.

	Returns:
		One entry per bucket: the mean number of people present, the peak,
		and how many seconds the bucket covers. `mean` is person-seconds
		over the covered length rather than an average of the seconds
		that had somebody in them, so a bucket with an empty room reads 0
		instead of vanishing.
	"""
	# The first and last buckets of a window are usually partial - the window
	# ends at the newest detection, not on a bucket boundary - so each one is
	# divided by the seconds it actually covers. Dividing a half-finished
	# bucket by the full interval halves it, which on a realtime card reads
	# as the room emptying every five minutes.
	covered = (
		"greatest(1, dateDiff('second',"
		" greatest(toDateTime(bucket), toDateTime({start:DateTime64(3)}, 'UTC')),"
		f' least(toDateTime(bucket) + INTERVAL {interval} SECOND,'
		" toDateTime({end:DateTime64(3)}, 'UTC'))))"
	)
	sql = f"""
		SELECT {bucket_expr('sec', interval, tz)} AS bucket,
		       sum(present) / {covered} AS mean,
		       max(present) AS peak,
		       {covered} AS covered
		FROM (
			SELECT toStartOfInterval(ts, INTERVAL 1 SECOND) AS sec,
			       uniqExact((source_id, track_id)) AS present
			FROM {db.TABLE}
			WHERE {zone.cameras_sql}
			  AND label = 'person'
			  AND ts >= {{start:DateTime64(3)}}
			  AND ts < {{end:DateTime64(3)}}
			  AND {zone.contains_sql}
			GROUP BY sec
		)
		GROUP BY bucket
		ORDER BY bucket{_fill(window, interval, tz)}
	"""
	rows = client.query(sql, parameters=window.params()).result_rows
	return [
		{
			'ts': _iso(bucket),
			'mean': round(float(mean), 2),
			'peak': int(peak),
			# How many seconds this bucket actually spans. The first and
			# last of a window are usually partial, and a summary that
			# averaged them alongside full ones would weight a one-second
			# sliver like five minutes.
			'covered_seconds': int(covered),
		}
		for bucket, mean, peak, covered in rows
	]


def current_occupancy(
	client: ch_client.Client,
	zone: config.Zone,
	window: Window,
	seconds: int = 5,
) -> int:
	"""Counts who is in a zone right now.

	Args:
		client: A connected ClickHouse client.
		zone: The area to count inside.
		window: The range being reported on; its end is "now".
		seconds: How far back to look for the instantaneous count.

	Returns:
		Distinct people seen in the last few seconds of the window. A
		"live occupancy" card wants this, not the mean of the trailing
		bucket: that bucket is partial, and averaging it over a period
		that has not finished reads as the room emptying on a timer.
	"""
	sql = f"""
		SELECT max(present) FROM (
			SELECT toStartOfInterval(ts, INTERVAL 1 SECOND) AS sec,
			       uniqExact((source_id, track_id)) AS present
			FROM {db.TABLE}
			WHERE {zone.cameras_sql}
			  AND label = 'person'
			  AND ts >= {{end:DateTime64(3)}} - INTERVAL {seconds} SECOND
			  AND ts < {{end:DateTime64(3)}}
			  AND {zone.contains_sql}
			GROUP BY sec
		)
	"""
	rows = client.query(sql, parameters=window.params()).result_rows
	return int(rows[0][0]) if rows and rows[0][0] is not None else 0


def dwell(
	client: ch_client.Client,
	zone: config.Zone,
	window: Window,
	edges: Sequence[int],
	interval: int,
	tz: str = 'UTC',
) -> dict:
	"""Measures how long each visit to a zone lasted.

	Args:
		client: A connected ClickHouse client.
		zone: The area to measure inside.
		window: The range to measure over.
		edges: Histogram bucket lower bounds, in seconds, ascending. A 0
			edge is prepended when the caller does not supply one.
		interval: Bucket size for the over-time series, in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		Per-part statistics, a histogram and a time series, all in
		seconds. A visit is
		one track's time inside one part; a zone with named parts - the
		tables - reports each separately, which is what "dwell per table"
		means. Untracked detections carry track_id 0 and are excluded:
		without a track there is no visit to time.
	"""
	# roundDown answers with the FIRST element for anything below it, so a
	# five-second visit against edges [600, 1200] is reported as 10-20
	# minutes. There is no underflow bucket, so one is guaranteed here
	# rather than trusted to the caller.
	edges = tuple(edges)
	if not edges or edges[0] > 0:
		edges = (0, *edges)
	edge_list = '[' + ','.join(str(int(edge)) for edge in edges) + ']'
	visits_sql = _visits_sql(zone)
	stats = client.query(
		f"""
		SELECT part, count() AS visits, avg(seconds) AS mean,
		       quantileExact(0.5)(seconds) AS median, max(seconds) AS longest
		FROM ({visits_sql})
		GROUP BY part ORDER BY part
		""",
		parameters=window.params(),
	).result_rows
	# Bucketed by when each visit STARTED, not by when it ended: a card
	# asking "how long were people waiting at 3pm" means the people who
	# joined the queue at 3pm.
	over_time = client.query(
		f"""
		SELECT {bucket_expr('started', interval, tz)} AS bucket,
		       count() AS visits, avg(seconds) AS mean
		FROM ({visits_sql})
		GROUP BY bucket
		ORDER BY bucket{_fill(window, interval, tz)}
		""",
		parameters=window.params(),
	).result_rows
	buckets = client.query(
		f"""
		SELECT roundDown(seconds, {edge_list}) AS lower, count() AS visits
		FROM ({visits_sql})
		GROUP BY lower ORDER BY lower
		""",
		parameters=window.params(),
	).result_rows

	counted = {int(lower): int(visits) for lower, visits in buckets}
	parts = [
		{
			'name': part,
			'visits': int(visits),
			'mean_seconds': round(float(mean), 1),
			'median_seconds': round(float(median), 1),
			'longest_seconds': round(float(longest), 1),
		}
		for part, visits, mean, median, longest in stats
	]
	total = sum(part['visits'] for part in parts)
	weighted = sum(
		part['visits'] * part['mean_seconds'] for part in parts
	)
	return {
		'unit': 'seconds',
		'visits': total,
		'mean_seconds': round(weighted / total, 1) if total else 0.0,
		'parts': parts,
		'histogram': [
			{
				'from': int(edge),
				'to': int(edges[index + 1]) if index + 1 < len(edges) else None,
				'visits': counted.get(int(edge), 0),
			}
			for index, edge in enumerate(edges)
		],
		'interval_seconds': interval,
		'buckets': [
			{
				'ts': _iso(bucket),
				'visits': int(visits),
				'mean_seconds': round(float(mean), 1),
			}
			for bucket, visits, mean in over_time
		],
	}


def _visits_sql(zone: config.Zone) -> str:
	"""Builds the per-visit subquery both dwell and events read.

	Args:
		zone: The area a visit happens inside.

	Returns:
		One row per visit: a track's unbroken stay inside one part of the
		zone. A visit is NOT one track id - the tracker reuses those, so
		grouping by the id alone welds two strangers an hour apart into a
		single forty-six-minute wait. It also ends when somebody walks
		out of the zone, which is why the part filter comes first.
	"""
	return f"""
		SELECT part, source_id, track_id, visit,
		       min(ts) AS started, max(ts) AS ended,
		       dateDiff('millisecond', min(ts), max(ts)) / 1000 AS seconds
		FROM (
			SELECT ts, source_id, track_id, part,
			       sum(started_visit) OVER (
			           PARTITION BY source_id, track_id, part ORDER BY ts
			           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
			       ) AS visit
			FROM (
				SELECT ts, source_id, track_id, part,
				       -- The first row of each track has no predecessor and
				       -- lagInFrame hands back the epoch, so it reads as a
				       -- gap and opens the first visit. That is correct.
				       dateDiff(
				           'millisecond',
				           lagInFrame(ts) OVER (
				               PARTITION BY source_id, track_id, part
				               ORDER BY ts
				           ),
				           ts
				       ) > {_VISIT_GAP_MS} AS started_visit
				FROM (
					SELECT ts, source_id, track_id,
					       {zone.part_name_sql()} AS part
					FROM {db.TABLE}
					WHERE {zone.cameras_sql}
					  AND label = 'person'
					  AND track_id != 0
					  AND ts >= {{start:DateTime64(3)}}
					  AND ts < {{end:DateTime64(3)}}
				)
				WHERE part != ''
			)
		)
		GROUP BY part, source_id, track_id, visit
	"""


def _crosses(a: config.Point, b: config.Point) -> str:
	"""Builds a predicate true when a step crosses one line.

	Args:
		a: One end of the line.
		b: The other end.

	Returns:
		SQL testing whether the segment (px, py) -> (x, y) properly
		crosses the segment a -> b: the two endpoints of each segment
		must fall on opposite sides of the other.
	"""
	ax, ay = a
	bx, by = b
	side_prev = f'(({bx} - {ax}) * (py - {ay}) - ({by} - {ay}) * (px - {ax}))'
	side_curr = f'(({bx} - {ax}) * (y - {ay}) - ({by} - {ay}) * (x - {ax}))'
	side_a = f'((x - px) * ({ay} - py) - (y - py) * ({ax} - px))'
	side_b = f'((x - px) * ({by} - py) - (y - py) * ({bx} - px))'
	return (
		f'((({side_prev} > 0) != ({side_curr} > 0))'
		f' AND (({side_a} > 0) != ({side_b} > 0)))'
	)


def _steps_sql(line: config.Line) -> str:
	"""Builds the per-track step table a crossing query reads.

	Args:
		line: The counting line.

	Returns:
		A subquery of consecutive positions per track, each flagged with
		whether it crossed the outer or the inner line.
	"""
	return f"""
		SELECT track_id, ts, prev_ts,
		       {_crosses(*line.outer)} AS crossed_outer,
		       {_crosses(*line.inner)} AS crossed_inner
		FROM (
			SELECT track_id, ts,
			       xc AS x, yc + h / 2 AS y,
			       lagInFrame(xc) OVER w AS px,
			       lagInFrame(yc + h / 2) OVER w AS py,
			       lagInFrame(ts) OVER w AS prev_ts
			FROM {db.TABLE}
			WHERE source_id = '{line.camera}'
			  AND label = 'person'
			  AND track_id != 0
			  AND ts >= {{start:DateTime64(3)}}
			  AND ts < {{end:DateTime64(3)}}
			WINDOW w AS (PARTITION BY track_id ORDER BY ts)
		)
		-- The first row of each track has no predecessor; lagInFrame gives
		-- it the epoch, which this drops. The second test throws away steps
		-- across a gap in the track: a position from ten minutes ago and one
		-- from now are not a movement, and the segment between them would
		-- cross anything.
		WHERE prev_ts >= {{start:DateTime64(3)}}
		  AND dateDiff('millisecond', prev_ts, ts) <= 1000
	"""


def footfall(
	client: ch_client.Client,
	line: config.Line,
	window: Window,
	interval: int,
	tz: str = 'UTC',
) -> list[dict]:
	"""Counts people crossing a counting line, in each direction.

	Args:
		client: A connected ClickHouse client.
		line: The two parallel lines to count across.
		window: The range to count over.
		interval: Bucket size in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		One entry per bucket, with an `in` and an `out` count.

	A crossing needs BOTH lines crossed, and which came first is the
	direction. Requiring two is the whole point: a bounding box jittering
	on a single line produces phantom crossings all day, and a track that
	only ever crosses one of them counts as nothing.

	Each track counts at most ONCE, in the direction of its first crossing
	of each line. Somebody who walks in, turns around and walks back out
	is therefore one entry, not one entry and one exit - the aggregation
	keeps only `minIf(ts, crossed)` per line and cannot see the second
	pass. That is the right reading for a doorway and the wrong one for a
	corridor people pace up and down; a corridor would need the visit
	sessionisation `_visits_sql` does.
	"""
	sql = f"""
		SELECT {bucket_expr('greatest(t_outer, t_inner)', interval, tz)}
		           AS bucket,
		       countIf(t_inner > t_outer) AS entered,
		       countIf(t_outer > t_inner) AS exited
		FROM (
			SELECT track_id,
			       minIf(ts, crossed_outer) AS t_outer,
			       minIf(ts, crossed_inner) AS t_inner,
			       countIf(crossed_outer) AS n_outer,
			       countIf(crossed_inner) AS n_inner
			FROM ({_steps_sql(line)})
			GROUP BY track_id
			HAVING n_outer > 0 AND n_inner > 0
		)
		GROUP BY bucket
		ORDER BY bucket{_fill(window, interval, tz)}
	"""
	rows = client.query(sql, parameters=window.params()).result_rows
	return [
		{'ts': _iso(bucket), 'in': int(entered), 'out': int(exited)}
		for bucket, entered, exited in rows
	]


def visits(
	client: ch_client.Client,
	zone: config.Zone,
	window: Window,
	longer_than: float | None = None,
	shorter_than: float | None = None,
) -> list[dict]:
	"""Lists individual visits to a zone.

	Args:
		client: A connected ClickHouse client.
		zone: The area to measure inside.
		window: The range to measure over.
		longer_than: Keep only visits above this many seconds.
		shorter_than: Keep only visits below it.

	Returns:
		One entry per visit, newest first, with the seconds it lasted. A
		visit is one unbroken stay, not one track id. This is what a
		per-visit alert - "somebody waited longer than X" - is evaluated
		against; it is not a time series and bucketing it would lose the
		visit.

		The threshold is applied here, in SQL, rather than by the caller,
		because the result is capped at `MAX_VISITS`. Filtering afterwards
		would cap the visits first and then look for the interesting ones
		inside the cap, which over a long window quietly reports the most
		recent tail as the whole answer.
	"""
	tests = []
	if longer_than is not None:
		tests.append(f'seconds > {float(longer_than)}')
	if shorter_than is not None:
		tests.append(f'seconds < {float(shorter_than)}')
	where = f'WHERE {" AND ".join(tests)}' if tests else ''
	sql = f"""
		SELECT part, source_id, track_id, started, ended, seconds
		FROM ({_visits_sql(zone)})
		{where}
		ORDER BY started DESC
		LIMIT {MAX_VISITS}
	"""
	rows = client.query(sql, parameters=window.params()).result_rows
	return [
		{
			'part': part,
			'camera': source_id,
			'track_id': int(track_id),
			'start': _iso(started),
			'end': _iso(ended),
			'seconds': round(float(seconds), 1),
		}
		for part, source_id, track_id, started, ended, seconds in rows
	]


def overlay(
	client: ch_client.Client, camera: str, window: Window
) -> list[dict]:
	"""Returns every stored box for one camera over one short window.

	Args:
		client: A connected ClickHouse client.
		camera: The camera id, as the catalogue names it.
		window: The range, capped by the caller at
			`OVERLAY_MAX_SECONDS`.

	Returns:
		One entry per frame, in time order, each carrying its objects.
		Coordinates are the normalised ones that were stored, so the
		browser scales them by whatever size the <video> happens to be.
	"""
	sql = f"""
		SELECT ts, track_id, label, xc, yc, w, h
		FROM {db.TABLE}
		WHERE source_id = {{camera:String}}
		  AND ts >= {{start:DateTime64(3)}}
		  AND ts < {{end:DateTime64(3)}}
		ORDER BY ts, obj_idx
		LIMIT {OVERLAY_MAX_ROWS}
	"""
	rows = client.query(
		sql, parameters={'camera': camera, **window.params()}
	).result_rows
	frames: list[dict] = []
	for ts, track_id, label, xc, yc, w, h in rows:
		stamp = _iso(ts)
		if not frames or frames[-1]['ts'] != stamp:
			frames.append({'ts': stamp, 'objects': []})
		frames[-1]['objects'].append(
			{
				'track_id': int(track_id),
				'label': label,
				'xc': round(float(xc), 4),
				'yc': round(float(yc), 4),
				'w': round(float(w), 4),
				'h': round(float(h), 4),
			}
		)
	return frames


def _iso(moment: datetime.datetime) -> str:
	"""Renders a timestamp the way every response in here does."""
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=datetime.timezone.utc)
	return moment.astimezone(datetime.timezone.utc).isoformat(
		timespec='milliseconds'
	)
