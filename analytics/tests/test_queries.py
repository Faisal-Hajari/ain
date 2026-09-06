"""The SQL builders, checked for the things that are wrong when invisible."""

import datetime
import pathlib

import pytest

from ain_analytics import config
from ain_analytics import queries

_REAL = pathlib.Path(__file__).resolve().parent.parent / 'cameras.yml'


def _window(seconds: float) -> queries.Window:
	"""A window of a given length, ending now."""
	end = datetime.datetime(2026, 9, 6, 12, tzinfo=datetime.timezone.utc)
	return queries.Window(start=end - datetime.timedelta(seconds=seconds), end=end)


def test_a_short_window_keeps_the_interval_it_asked_for():
	assert queries.bucket_seconds(_window(3600), 300) == 300


def test_a_month_long_window_cannot_be_asked_for_second_buckets():
	# 30 days of one-second buckets is 2.6M rows through the API.
	interval = queries.bucket_seconds(_window(30 * 86400), 1)
	assert 30 * 86400 / interval <= queries._MAX_BUCKETS


def test_the_overlay_cap_is_a_minute():
	assert queries.OVERLAY_MAX_SECONDS == 60


def test_the_series_is_zero_filled():
	# Without WITH FILL a bucket nobody was seen in is missing rather than
	# zero, and every average is taken over only the busy buckets.
	assert 'WITH FILL' in queries._fill(_window(3600), 300, 'UTC')


def test_a_daily_bucket_is_aligned_to_a_local_midnight():
	# toStartOfInterval aligns a second-based interval to the epoch no
	# matter what timezone it is handed, so a whole day has to be asked
	# for in DAY units - otherwise the first three hours of every Riyadh
	# day land on the bar before.
	daily = queries.bucket_expr('ts', 86400, 'Asia/Riyadh')
	assert "INTERVAL 1 DAY, 'Asia/Riyadh'" in daily


def test_a_sub_day_bucket_stays_in_seconds():
	assert 'INTERVAL 300 SECOND' in queries.bucket_expr('ts', 300, 'Asia/Riyadh')


@pytest.mark.parametrize(
	('prev', 'curr', 'expected'),
	[
		((0.1, 0.5), (0.9, 0.5), True),
		((0.1, 0.5), (0.4, 0.5), False),
		((0.6, 0.1), (0.6, 0.9), False),
	],
)
def test_the_crossing_predicate_matches_plain_geometry(prev, curr, expected):
	# The predicate is SQL, so it is checked here against the same maths
	# written plainly. The line runs vertically at x = 0.5.
	assert _evaluate_crossing((0.5, 0.0), (0.5, 1.0), prev, curr) is expected


def _evaluate_crossing(a, b, prev, curr) -> bool:
	"""Evaluates the generated predicate as Python.

	Args:
		a: One end of the line.
		b: The other end.
		prev: The track's previous foot position.
		curr: Its current one.

	Returns:
		What ClickHouse would answer. The predicate is arithmetic, `>`,
		`!=` and `AND`, so the only difference between the two languages
		is the spelling of `and` - which makes this the cheapest way to
		check a sign error that would otherwise show up as footfall
		silently reading zero.
	"""
	sql = queries._crosses(a, b)
	assert '=' not in sql.replace('!=', ''), 'predicate grew a SQL-only operator'
	scope = {'px': prev[0], 'py': prev[1], 'x': curr[0], 'y': curr[1]}
	return bool(eval(sql.replace('AND', 'and'), {'__builtins__': {}}, scope))  # noqa: S307


def test_a_step_across_a_gap_in_the_track_is_thrown_away():
	settings = config.load(_REAL)
	sql = queries._steps_sql(settings.line('entrance'))
	# A position from ten minutes ago and one from now are not a movement,
	# and the segment between them would cross anything.
	assert "dateDiff('millisecond', prev_ts, ts) <= 1000" in sql


def test_dwell_excludes_untracked_detections():
	settings = config.load(_REAL)
	sql = queries._steps_sql(settings.line('entrance'))
	assert 'track_id != 0' in sql


def test_a_clip_id_that_is_not_one_is_refused(tmp_path, monkeypatch):
	"""The id becomes a filename, so it is checked where it is used."""
	from ain_analytics import clips

	monkeypatch.setattr(clips, '_CACHE', tmp_path)
	for bad in ('..', 'a/b', 'x' * 65, '', 'a b'):
		with pytest.raises(clips.ClipError, match='not an event id'):
			clips.render(None, bad, '03', _window(10))


def test_a_real_event_id_is_accepted():
	from ain_analytics import clips

	assert clips._ID.match('congestion-8f21a0b3')
	assert clips._ID.match('long-wait-289e3682')
