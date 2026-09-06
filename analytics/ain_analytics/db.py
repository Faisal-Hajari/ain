"""The ClickHouse connection, and the schema it insists on.

The schema is applied on every start of every process that touches the
database rather than shipped as an `initdb` script, because the image runs
those only when the data directory is empty - which means the one time you
most want a migration to run, after an edit, is the one time it does not.
Every statement here is `IF NOT EXISTS`.
"""

import logging
import os
import threading
import time

import clickhouse_connect
from clickhouse_connect.driver import client as ch_client

_LOG = logging.getLogger(__name__)

_local = threading.local()

TABLE = 'detections'

# Flat and denormalised on purpose. A separate `frames` table would be right
# in Postgres and wrong here: sorted with LowCardinality, the repeated
# source_id and ts compress to almost nothing, and the join would cost more
# than the bytes it saved.
#
# Ten cameras x 15 fps x ~5 people is ~750 rows/sec and ~65M rows/day, which
# is small for ClickHouse. That is what pays for storing every detection of
# every frame and leaving all the clever parts to query time.
_SCHEMA = (
	f"""
	CREATE TABLE IF NOT EXISTS {TABLE}
	(
		ts          DateTime64(3, 'UTC'),
		source_id   LowCardinality(String),
		track_id    UInt64,
		obj_idx     UInt16,
		label       LowCardinality(String),
		confidence  Float32,
		xc Float32, yc Float32, w Float32, h Float32,
		frame_num   UInt64
	)
	ENGINE = ReplacingMergeTree
	PARTITION BY toYYYYMMDD(ts)
	ORDER BY (source_id, ts, track_id, obj_idx)
	TTL toDateTime(ts) + INTERVAL 30 DAY
	SETTINGS deduplicate_merge_projection_mode = 'rebuild'
	""",
	# ClickHouse 25.x refuses a projection on a ReplacingMergeTree unless it
	# is told what a deduplicating merge should do to it. 'rebuild' recomputes
	# the projection from the merged part, which is the only option that
	# leaves it usable; 'drop' would quietly delete it and turn every dwell
	# query back into a full scan. Repeated here as an ALTER so a table
	# created before this setting existed is fixed rather than skipped.
	f"""
	ALTER TABLE {TABLE}
		MODIFY SETTING deduplicate_merge_projection_mode = 'rebuild'
	""",
	# obj_idx is in the sort key for correctness, not information. ORDER BY
	# is also ReplacingMergeTree's dedup key, and Kafka is at-least-once: a
	# consumer restart replays, and without a per-frame discriminator several
	# untracked objects in one frame collapse into a single row.
	#
	# A second sort order for per-track access - dwell and line crossings walk
	# one track through time, which the primary (source_id, ts, ...) order
	# makes a full scan.
	f"""
	ALTER TABLE {TABLE} ADD PROJECTION IF NOT EXISTS by_track
		(SELECT * ORDER BY (source_id, track_id, ts))
	""",
	# Safe as a materialized view because min, max and sum are associative and
	# merge correctly across insert blocks. Nothing zone- or line-shaped may
	# follow it here: that geometry is configuration, and baking configuration
	# into an MV destroys the ability to move a zone and recompute history.
	# (It would also be wrong: an MV sees one insert block, so a lagInFrame
	# partitioned by track cannot span them.)
	"""
	CREATE TABLE IF NOT EXISTS track_summary
	(
		source_id  LowCardinality(String),
		track_id   UInt64,
		label      LowCardinality(String),
		first_seen SimpleAggregateFunction(min, DateTime64(3, 'UTC')),
		last_seen  SimpleAggregateFunction(max, DateTime64(3, 'UTC')),
		frames     SimpleAggregateFunction(sum, UInt64)
	)
	ENGINE = AggregatingMergeTree
	ORDER BY (source_id, track_id)
	""",
	f"""
	CREATE MATERIALIZED VIEW IF NOT EXISTS track_summary_mv TO track_summary AS
	SELECT source_id, track_id, label,
	       min(ts) AS first_seen, max(ts) AS last_seen, count() AS frames
	FROM {TABLE} GROUP BY source_id, track_id, label
	""",
)

COLUMNS = (
	'ts', 'source_id', 'track_id', 'obj_idx', 'label', 'confidence',
	'xc', 'yc', 'w', 'h', 'frame_num',
)


def connect(retries: int = 30, delay: float = 2.0) -> ch_client.Client:
	"""Opens a client, waiting for the server to accept connections.

	Args:
		retries: How many attempts before giving up.
		delay: Seconds between attempts.

	Returns:
		A connected client.

	Raises:
		RuntimeError: The server never answered.
	"""
	settings = {
		# One insert per second per worker still produces a part per insert.
		# Asynchronous inserts let the server coalesce them, which is what
		# keeps the merger ahead of 750 rows/sec.
		'async_insert': 1,
		'wait_for_async_insert': 0,
	}
	last: Exception | None = None
	for attempt in range(retries):
		try:
			client = clickhouse_connect.get_client(
				host=os.environ.get('CLICKHOUSE_HOST', 'clickhouse'),
				port=int(os.environ.get('CLICKHOUSE_PORT', '8123')),
				username=os.environ.get('CLICKHOUSE_USER', 'ain'),
				password=os.environ.get('CLICKHOUSE_PASSWORD', 'ain'),
				database=os.environ.get('CLICKHOUSE_DATABASE', 'default'),
				settings=settings,
			)
			client.command('SELECT 1')
			return client
		except Exception as error:  # noqa: BLE001 - any failure is "not yet up"
			last = error
			_LOG.info(
				'clickhouse not ready (%s/%s): %s', attempt + 1, retries, error
			)
			time.sleep(delay)
	raise RuntimeError(f'clickhouse never answered: {last}')


def apply_schema(client: ch_client.Client) -> None:
	"""Creates the tables, projection and view if they are missing.

	Args:
		client: A connected client.

	MATERIALIZE is only issued when the projection was not already there.
	It is a mutation over every existing part, and running it on each
	process start would queue one per restart against a table holding a
	month of detections.
	"""
	existed = bool(
		client.query(
			'SELECT 1 FROM system.projections '
			'WHERE table = %(table)s AND name = %(name)s '
			'AND database = currentDatabase()',
			parameters={'table': TABLE, 'name': 'by_track'},
		).result_rows
	)
	for statement in _SCHEMA:
		client.command(statement)
	if not existed:
		client.command(
			f'ALTER TABLE {TABLE} MATERIALIZE PROJECTION IF EXISTS by_track'
		)


_migrated = False


def client() -> ch_client.Client:
	"""Returns this thread's client, connected and migrated.

	Returns:
		A client bound to the calling thread.

	One client per thread, not one per process: a clickhouse-connect
	client carries a session, and two queries on one session fail with
	"Attempt to execute concurrent queries within the same session".
	FastAPI runs synchronous routes in a thread pool, so a shared client
	turns any two simultaneous requests into an error - and only under
	load, which is the worst time to find out.
	"""
	global _migrated
	existing = getattr(_local, 'client', None)
	if existing is None:
		existing = connect()
		if not _migrated:
			apply_schema(existing)
			_migrated = True
		_local.client = existing
	return existing
