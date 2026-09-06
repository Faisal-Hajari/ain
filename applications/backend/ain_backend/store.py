"""Where alert rules are kept.

Everything else this service answers is derived: same query string, same
response, from any replica. Rules are the exception - the frontend keeps no
copy, so a created rule has to come back from the next read - and until now
they lived in a process-local dict that did not survive a restart and that
two replicas would have disagreed about.

SQLite, not ClickHouse. ClickHouse holds detections, and it holds them
beautifully; it handles small mutable row-level state badly, because an
update or a delete there is an asynchronous mutation rather than a
transaction. A handful of rules created and deleted one at a time is
ordinary application state and wants an ordinary database.

`AIN_STORE_PATH` names the file. The default is an in-memory database in
SQLite's shared-cache mode rather than a plain `:memory:`, because a plain
one is per-connection and the connections here are per-thread: a rule
written by one request would be invisible to the next. That only shows up
once something runs in a thread pool, which FastAPI does. A deployment
points this at a file on a volume.
"""

import contextlib
import datetime
import os
import sqlite3
import threading
from collections.abc import Iterator

_MEMORY = 'file:ain-alerts?mode=memory&cache=shared'
_PATH = os.environ.get('AIN_STORE_PATH', _MEMORY)

_SCHEMA = """
	CREATE TABLE IF NOT EXISTS alert_rules (
		id          TEXT PRIMARY KEY,
		monitor_id  TEXT NOT NULL,
		comparator  TEXT NOT NULL,
		threshold   REAL NOT NULL,
		created_on  TEXT NOT NULL,
		branch      TEXT NOT NULL,
		venue       TEXT NOT NULL
	)
"""

_local = threading.local()

# A shared-cache in-memory database exists only while some connection to it
# is open. This is that connection; without it the rules vanish between
# requests rather than between restarts.
_keepalive: sqlite3.Connection | None = None


def _open() -> sqlite3.Connection:
	"""Opens one connection, with the schema in place."""
	connection = sqlite3.connect(
		_PATH, uri=_PATH.startswith('file:'), check_same_thread=False
	)
	connection.row_factory = sqlite3.Row
	connection.execute(_SCHEMA)
	connection.commit()
	return connection


def _connection() -> sqlite3.Connection:
	"""Returns this thread's connection, opened on first use.

	Returns:
		An open connection.

	One per thread, because a sqlite3 connection may not be shared across
	them - and FastAPI runs synchronous routes in a thread pool, so a
	shared one fails only under concurrency, which is the worst time to
	find out.
	"""
	global _keepalive
	existing = getattr(_local, 'connection', None)
	if existing is None:
		if _keepalive is None:
			_keepalive = _open()
		existing = _open()
		_local.connection = existing
	return existing


@contextlib.contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
	"""Runs a write and commits it."""
	connection = _connection()
	with connection:
		yield connection


def rows() -> list[sqlite3.Row]:
	"""Returns every stored rule, newest first."""
	return _connection().execute(
		'SELECT * FROM alert_rules ORDER BY created_on DESC, rowid DESC'
	).fetchall()


def insert(
	rule_id: str,
	monitor_id: str,
	comparator: str,
	threshold: float,
	created_on: datetime.date,
	branch: str,
	venue: str,
) -> None:
	"""Stores one rule."""
	with transaction() as connection:
		connection.execute(
			'INSERT INTO alert_rules VALUES (?, ?, ?, ?, ?, ?, ?)',
			(
				rule_id,
				monitor_id,
				comparator,
				threshold,
				created_on.isoformat(),
				branch,
				venue,
			),
		)


def delete(rule_id: str) -> bool:
	"""Deletes one rule, reporting whether it was there."""
	with transaction() as connection:
		cursor = connection.execute(
			'DELETE FROM alert_rules WHERE id = ?', (rule_id,)
		)
	return cursor.rowcount > 0


def clear() -> None:
	"""Empties the store. For tests."""
	with transaction() as connection:
		connection.execute('DELETE FROM alert_rules')
