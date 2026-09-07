"""The SQL, run against a real ClickHouse over rows with known answers.

Everything interesting in this service is a query, and a query is exactly
the thing that unit tests cannot check: the arithmetic lives in the server,
not in Python. So these build a table, put a handful of detections in it
whose right answers are obvious by hand, and assert them.

Skipped when there is no server, so `uv run pytest` still passes anywhere:

    docker compose up -d clickhouse
    CLICKHOUSE_HOST=localhost uv run --all-extras pytest -q
"""

import dataclasses
import datetime
import os
import uuid

import pytest

from ain_analytics import config
from ain_analytics import db
from ain_analytics import events
from ain_analytics import queries

_START = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
_WINDOW = queries.Window(
	start=_START, end=_START + datetime.timedelta(hours=1)
)

# The left half of the frame, floor level. A box's FOOT point decides
# membership, so a detection is in this zone when yc + h/2 lands inside it.
_ZONE = config.Zone(
	name='left',
	parts=(
		config.Part(
			camera='03',
			points=((0.0, 0.5), (0.5, 0.5), (0.5, 1.0), (0.0, 1.0)),
		),
	),
)

# Two vertical parallels at x = 0.4 and x = 0.6. Crossing the outer one
# first is coming in.
_LINE = config.Line(
	name='door',
	camera='03',
	outer=((0.4, 0.0), (0.4, 1.0)),
	inner=((0.6, 0.0), (0.6, 1.0)),
)


def _iso(moment: datetime.datetime) -> str:
	"""The same ISO form the queries emit, for comparing against."""
	return moment.isoformat(timespec='milliseconds')


def _seconds(offset: float) -> int:
	"""Milliseconds since the epoch, `offset` seconds into the window."""
	return round((_START.timestamp() + offset) * 1000)


@pytest.fixture(name='client')
def client_fixture(monkeypatch):
	"""A client pointed at a table of this test's own."""
	if not os.environ.get('CLICKHOUSE_HOST'):
		pytest.skip('no CLICKHOUSE_HOST; run the stack to exercise these')
	try:
		connection = db.connect(retries=1, delay=0)
	except RuntimeError as error:
		pytest.skip(f'clickhouse unreachable: {error}')

	table = f'test_detections_{uuid.uuid4().hex[:8]}'
	connection.command(
		f"""
		CREATE TABLE {table} (
			ts DateTime64(3, 'UTC'),
			source_id LowCardinality(String),
			track_id UInt64,
			obj_idx UInt16,
			label LowCardinality(String),
			confidence Float32,
			xc Float32, yc Float32, w Float32, h Float32,
			frame_num UInt64
		) ENGINE = MergeTree ORDER BY (source_id, ts, track_id, obj_idx)
		"""
	)
	monkeypatch.setattr(db, 'TABLE', table)
	try:
		yield connection
	finally:
		connection.command(f'DROP TABLE IF EXISTS {table}')


def _insert(client, rows: list[tuple]) -> None:
	"""Writes detections, filling in everything the tests do not care about.

	Args:
		client: The connected client.
		rows: (offset seconds, track_id, xc, yc) per detection. Boxes are
			0.1 x 0.2, so the foot point is yc + 0.1.
	"""
	client.insert(
		db.TABLE,
		[
			(
				_seconds(offset), '03', track_id, index % 8, 'person', 0.9,
				xc, yc, 0.1, 0.2, index,
			)
			for index, (offset, track_id, xc, yc) in enumerate(rows)
		],
		column_names=list(db.COLUMNS),
		# The service inserts asynchronously and does not wait, which is
		# what keeps the merger ahead of 750 rows/sec. A test that did the
		# same would read the table before its own rows arrived.
		settings={'async_insert': 0},
	)


def test_occupancy_counts_distinct_people_per_second(client):
	# Two people, both present for the first second; one of them seen twice
	# in that second, which must not make three.
	_insert(
		client,
		[
			(0.0, 1, 0.2, 0.7), (0.3, 1, 0.2, 0.7), (0.0, 2, 0.3, 0.7),
			(60.0, 1, 0.2, 0.7),
		],
	)
	buckets = queries.occupancy(client, _ZONE, _WINDOW, 60)
	assert buckets[0]['peak'] == 2
	assert buckets[1]['peak'] == 1


def test_an_empty_bucket_reads_zero_rather_than_vanishing(client):
	_insert(client, [(0.0, 1, 0.2, 0.7)])
	buckets = queries.occupancy(client, _ZONE, _WINDOW, 60)
	assert len(buckets) == 60
	assert buckets[1]['mean'] == 0.0
	assert buckets[1]['peak'] == 0


def test_a_partial_bucket_is_divided_by_what_it_covers(client):
	# A window ending 10 seconds into a 60-second bucket: one person there
	# the whole time is one person, not one sixth of one.
	window = queries.Window(
		start=_START, end=_START + datetime.timedelta(seconds=70)
	)
	_insert(client, [(float(second), 1, 0.2, 0.7) for second in range(60, 70)])
	buckets = queries.occupancy(client, _ZONE, window, 60)
	assert buckets[-1]['covered_seconds'] == 10
	assert buckets[-1]['mean'] == pytest.approx(1.0, abs=0.05)


def test_a_visit_shorter_than_the_first_edge_lands_in_a_zero_bucket(client):
	# roundDown answers with the first element for anything below it, so
	# edges that do not start at 0 would file a five-second visit under
	# "ten to twenty minutes".
	_insert(client, [(0.0, 7, 0.2, 0.7), (5.0, 7, 0.2, 0.7)])
	result = queries.dwell(client, _ZONE, _WINDOW, [600, 1200], 3600)
	assert result['histogram'][0]['from'] == 0
	assert result['histogram'][0]['visits'] == 1
	assert result['histogram'][1]['visits'] == 0


def test_a_visit_threshold_is_applied_before_the_row_cap(client):
	_insert(
		client,
		# One second of somebody, then somebody who stays thirty - sampled
		# throughout, because a gap of its own would split it in two.
		[(0.0, 1, 0.2, 0.7), (1.0, 1, 0.2, 0.7)]
		+ [(100.0 + step, 2, 0.2, 0.7) for step in range(0, 31, 2)],
	)
	long_ones = queries.visits(client, _ZONE, _WINDOW, longer_than=10)
	assert [round(visit['seconds']) for visit in long_ones] == [30]


def test_membership_uses_the_foot_point_not_the_centre(client):
	# yc = 0.45 puts the centre above the zone's top edge at 0.5 and the
	# foot point (0.45 + 0.1) inside it. Someone leaning is still standing
	# in the queue.
	_insert(client, [(0.0, 1, 0.2, 0.45)])
	assert queries.occupancy(client, _ZONE, _WINDOW, 60)[0]['peak'] == 1


def test_a_person_outside_the_zone_is_not_counted(client):
	# Foot point at 0.3, well above the zone.
	_insert(client, [(0.0, 1, 0.2, 0.2)])
	assert queries.occupancy(client, _ZONE, _WINDOW, 60)[0]['peak'] == 0


def test_a_reused_track_id_is_two_visits_not_one(client):
	# The tracker reuses ids. Ten seconds of somebody, then the same id
	# again half an hour later. Grouping by the id alone would call that
	# one thirty-minute visit.
	_insert(
		client,
		[(0.0, 7, 0.2, 0.7), (5.0, 7, 0.2, 0.7)]
		+ [(1800.0, 7, 0.3, 0.7), (1802.0, 7, 0.3, 0.7)],
	)
	visits = queries.visits(client, _ZONE, _WINDOW)
	assert len(visits) == 2
	assert sorted(round(visit['seconds']) for visit in visits) == [2, 5]


def test_a_brief_gap_does_not_split_a_visit(client):
	# Two seconds of occlusion is the same person, not a new one.
	_insert(
		client,
		[(0.0, 7, 0.2, 0.7), (2.0, 7, 0.2, 0.7), (4.0, 7, 0.2, 0.7)],
	)
	visits = queries.visits(client, _ZONE, _WINDOW)
	assert len(visits) == 1
	assert round(visits[0]['seconds']) == 4


def test_leaving_the_zone_and_returning_is_two_visits(client):
	_insert(
		client,
		[
			(0.0, 7, 0.2, 0.7),
			(1.0, 7, 0.2, 0.7),
			# Outside: foot point at 0.3.
			(2.0, 7, 0.2, 0.2),
			(30.0, 7, 0.2, 0.7),
			(31.0, 7, 0.2, 0.7),
		],
	)
	assert len(queries.visits(client, _ZONE, _WINDOW)) == 2


def test_an_untracked_detection_has_no_visit(client):
	# track_id 0 is the untracked sentinel, remapped at ingest. Without a
	# track there is nothing to time.
	_insert(client, [(0.0, 0, 0.2, 0.7), (5.0, 0, 0.2, 0.7)])
	assert queries.visits(client, _ZONE, _WINDOW) == []


def test_crossing_both_lines_left_to_right_counts_as_entering(client):
	_insert(
		client,
		[(0.0, 1, 0.30, 0.5), (0.2, 1, 0.50, 0.5), (0.4, 1, 0.70, 0.5)],
	)
	buckets = queries.footfall(client, _LINE, _WINDOW, 3600)
	assert buckets[0]['in'] == 1
	assert buckets[0]['out'] == 0


def test_crossing_the_other_way_counts_as_leaving(client):
	_insert(
		client,
		[(0.0, 1, 0.70, 0.5), (0.2, 1, 0.50, 0.5), (0.4, 1, 0.30, 0.5)],
	)
	buckets = queries.footfall(client, _LINE, _WINDOW, 3600)
	assert buckets[0]['out'] == 1
	assert buckets[0]['in'] == 0


def test_crossing_only_the_outer_line_counts_as_nothing(client):
	# Jitter around one line is the phantom crossing two lines exist to
	# throw away: it must not become footfall.
	_insert(
		client,
		[
			(0.0, 1, 0.30, 0.5), (0.2, 1, 0.50, 0.5),
			(0.4, 1, 0.30, 0.5), (0.6, 1, 0.50, 0.5),
		],
	)
	buckets = queries.footfall(client, _LINE, _WINDOW, 3600)
	assert buckets[0]['in'] == 0
	assert buckets[0]['out'] == 0


def test_a_teleport_across_a_gap_is_not_a_crossing(client):
	# Two positions ten minutes apart are not a movement, and the segment
	# between them would cross anything in the frame.
	_insert(client, [(0.0, 1, 0.30, 0.5), (600.0, 1, 0.70, 0.5)])
	buckets = queries.footfall(client, _LINE, _WINDOW, 3600)
	assert buckets[0]['in'] == 0


def test_the_window_end_is_exclusive(client):
	# A detection exactly on the end boundary belongs to the next window,
	# or adjacent buckets double-count and the hourly footfall beats the
	# daily total.
	_insert(client, [(3600.0, 1, 0.2, 0.7), (0.0, 2, 0.2, 0.7)])
	buckets = queries.occupancy(client, _ZONE, _WINDOW, 3600)
	assert buckets[0]['peak'] == 1


def test_a_sustained_breach_becomes_one_event(client, monkeypatch):
	monkeypatch.setattr(
		config, 'get',
		lambda: config.Config(
			cameras={'03': {'stream': 'cam3'}},
			zones={'left': _ZONE},
			lines={'door': _LINE},
			kafka_brokers='', kafka_topic='',
		),
	)
	# Two people for two solid minutes, then nobody.
	rows = []
	for second in range(0, 120):
		rows.append((float(second), 1, 0.2, 0.7))
		rows.append((float(second), 2, 0.3, 0.7))
	_insert(client, rows)
	found = events.evaluate(
		client, metric='occupancy', target='left', comparator='above',
		threshold=1, window=_WINDOW, for_seconds=60, kind='congestion',
	)
	assert len(found) == 1
	assert found[0].type == 'congestion'
	assert found[0].peak_value == pytest.approx(2, abs=0.01)
	assert found[0].geometry['kind'] == 'polygon'


def test_a_breach_shorter_than_the_duration_raises_nothing(
	client, monkeypatch
):
	monkeypatch.setattr(
		config, 'get',
		lambda: config.Config(
			cameras={'03': {'stream': 'cam3'}},
			zones={'left': _ZONE},
			lines={'door': _LINE},
			kafka_brokers='', kafka_topic='',
		),
	)
	rows = []
	for second in range(0, 20):
		rows.append((float(second), 1, 0.2, 0.7))
		rows.append((float(second), 2, 0.3, 0.7))
	_insert(client, rows)
	assert (
		events.evaluate(
			client, metric='occupancy', target='left', comparator='above',
			threshold=1, window=_WINDOW, for_seconds=600, kind='congestion',
		)
		== []
	)


# The right half of the frame, so a second zone can be filled independently
# of `_ZONE` and stand in for the queue.
_RIGHT = config.Zone(
	name='right',
	capacity=10,
	parts=(
		config.Part(
			camera='03',
			points=((0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)),
		),
	),
)


@pytest.fixture(name='two_zones')
def two_zones_fixture(monkeypatch):
	"""A config with a capacity on one zone and none on the other."""
	monkeypatch.setattr(
		config, 'get',
		lambda: config.Config(
			cameras={'03': {'stream': 'cam3'}},
			zones={
				'left': dataclasses.replace(_ZONE, capacity=10),
				'right': _RIGHT,
				'uncapped': _ZONE,
			},
			lines={'door': _LINE},
			kafka_brokers='', kafka_topic='',
		),
	)


def _crowd(zone_x: float, count: int, seconds: range) -> list[tuple]:
	"""`count` people standing in one half of the frame, second by second."""
	return [
		(float(second), 100 + person, zone_x + person * 0.01, 0.7)
		for second in seconds
		for person in range(count)
	]


def test_a_capacity_threshold_is_a_share_of_the_zones_own_capacity(
	client, two_zones
):
	# Capacity 10, so 0.6 is six people. Five in the room is not a breach
	# and seven is - which is what "passed 60%" has to mean, or the card's
	# copy and its number are two different claims.
	_insert(client, _crowd(0.1, 5, range(0, 60)) + _crowd(0.1, 7, range(60, 180)))
	found = events.evaluate(
		client, metric='occupancy', target='left', comparator='above',
		threshold=0.6, window=_WINDOW, for_seconds=60, basis='capacity',
	)
	assert len(found) == 1
	assert found[0].detail['threshold_value'] == 6.0
	assert found[0].peak_value == pytest.approx(7, abs=0.01)


def test_a_capacity_threshold_needs_a_capacity(client, two_zones):
	# Better a 400 than a guessed capacity: an invented denominator puts a
	# made-up number behind an alert and nothing downstream can tell.
	with pytest.raises(config.NoCapacityError):
		events.evaluate(
			client, metric='occupancy', target='uncapped',
			comparator='above', threshold=0.9, window=_WINDOW,
			basis='capacity',
		)


def test_a_mean_threshold_is_a_share_of_the_windows_own_average(
	client, two_zones
):
	# Four people for the first half of the window, none for the second.
	# The time-weighted mean over the whole window is 2, so "below 0.5 of
	# average" is below 1 - which the empty stretch is and the busy one is
	# not.
	_insert(client, _crowd(0.1, 4, range(0, 1800)))
	found = events.evaluate(
		client, metric='occupancy', target='left', comparator='below',
		threshold=0.5, window=_WINDOW, for_seconds=600, basis='mean',
		kind='empty',
	)
	assert len(found) == 1
	assert found[0].detail['threshold_value'] == pytest.approx(1.0, abs=0.05)
	# It starts when the room emptied, not when the window did.
	assert found[0].start > _iso(_START)


def test_congestion_needs_the_queue_to_be_growing(client, two_zones):
	# The room is over capacity throughout. The queue drains across it, so
	# this is a rush that is clearing - the one thing congestion is not.
	rows = _crowd(0.1, 8, range(0, 300))
	rows += _crowd(0.6, 4, range(0, 100))
	rows += _crowd(0.6, 1, range(100, 300))
	_insert(client, rows)

	without = events.evaluate(
		client, metric='occupancy', target='left', comparator='above',
		threshold=0.6, window=_WINDOW, for_seconds=60, basis='capacity',
	)
	assert len(without) == 1, 'the room was full'

	with_queue = events.evaluate(
		client, metric='occupancy', target='left', comparator='above',
		threshold=0.6, window=_WINDOW, for_seconds=60, basis='capacity',
		rising='right', kind='congestion',
	)
	assert with_queue == [], 'a draining queue is not congestion'


def test_congestion_fires_when_the_queue_is_growing(client, two_zones):
	rows = _crowd(0.1, 8, range(0, 300))
	rows += _crowd(0.6, 1, range(0, 100))
	rows += _crowd(0.6, 5, range(100, 300))
	_insert(client, rows)

	found = events.evaluate(
		client, metric='occupancy', target='left', comparator='above',
		threshold=0.6, window=_WINDOW, for_seconds=60, basis='capacity',
		rising='right', kind='congestion',
	)
	assert len(found) == 1
	assert found[0].type == 'congestion'
	assert found[0].detail['rising'] == 'right'
	# The shape carries what the percentage was a percentage of, so a
	# reader can check the arithmetic without a second lookup.
	assert found[0].geometry['capacity'] == 10


def test_an_unknown_basis_is_an_error(client, two_zones):
	with pytest.raises(events.UnknownBasisError):
		events.evaluate(
			client, metric='occupancy', target='left', comparator='above',
			threshold=1, window=_WINDOW, basis='vibes',
		)


def test_an_empty_stretch_counts_toward_the_average(client):
	"""The buckets nobody appears in are the point of the average.

	WITH FILL synthesises them, and a synthesised row carries the default
	for every column but the one being filled - so their coverage arrives
	as 0. Weighted by that, an empty hour weighs nothing, and "average
	occupancy" becomes "average occupancy while somebody was there".
	"""
	# Four people for the first half of the window, nobody for the second.
	_insert(
		client,
		[
			(float(second), 100 + person, 0.1 + person * 0.01, 0.7)
			for second in range(0, 1800)
			for person in range(4)
		],
	)
	buckets = queries.occupancy(client, _ZONE, _WINDOW, 60)
	assert len(buckets) == 60
	assert all(bucket['covered_seconds'] == 60 for bucket in buckets)
	# 4 people for half an hour over a full hour is a mean of 2, not 4.
	total = sum(b['mean'] * b['covered_seconds'] for b in buckets)
	assert total / sum(b['covered_seconds'] for b in buckets) == pytest.approx(
		2.0, abs=0.05
	)
