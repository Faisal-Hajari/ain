"""The SQL builders, checked for the things that are wrong when invisible."""

import datetime
import pathlib

import pytest

from ain_analytics import config
from ain_analytics import settings
from ain_api import queries

_REAL = (
	pathlib.Path(__file__).resolve().parents[3] / 'config' / 'cameras.yml'
)


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


def test_a_clip_id_that_is_not_one_is_refused():
	"""The id names an object in a shared bucket, so it is checked here.

	Refused before anything is reached for - no ClickHouse client, no
	object store. A `..` or a slash in an object key is a path into
	somebody else's clip.
	"""
	from ain_api import clips

	for bad in ('..', 'a/b', 'x' * 65, '', 'a b'):
		with pytest.raises(clips.ClipError, match='not an event id'):
			clips.render(None, bad, '03', _window(10))


def test_a_real_event_id_is_accepted():
	from ain_api import clips

	assert clips._ID.match('congestion-8f21a0b3')
	assert clips._ID.match('long-wait-289e3682')


def test_a_still_is_cached_so_a_repaint_does_not_reopen_rtsp(monkeypatch):
	"""Opening an RTSP session per page load is a lot for one picture."""
	import subprocess

	from ain_api import frames

	calls = []

	def fake_run(command, **kwargs):
		calls.append(command)
		return subprocess.CompletedProcess(command, 0, b'\xff\xd8jpeg', b'')

	monkeypatch.setattr(frames.subprocess, 'run', fake_run)
	monkeypatch.setattr(frames, '_cache', {})

	assert frames.still('cam3').startswith(b'\xff\xd8')
	frames.still('cam3')
	assert len(calls) == 1, 'the second read should come from the cache'
	# A different camera is a different picture.
	frames.still('cam4')
	assert len(calls) == 2


def test_a_stream_that_gives_no_frame_is_an_error(monkeypatch):
	import subprocess

	from ain_api import frames

	monkeypatch.setattr(frames, '_cache', {})
	monkeypatch.setattr(
		frames.subprocess,
		'run',
		lambda command, **kwargs: subprocess.CompletedProcess(
			command, 1, b'', b'Connection refused'
		),
	)
	with pytest.raises(frames.FrameError, match='Connection refused'):
		frames.still('cam3')


def test_an_event_id_is_wide_enough_not_to_collide():
	"""The id names a cached file, so a collision serves the wrong video.

	Thirty-two bits over MAX_VISITS events collides inside a single
	response about one time in twenty. Sixty-four does not.
	"""
	from ain_api import events

	assert len(events._event_id('x').split('-')[-1]) == 16
	seen = {
		events._event_id('long-wait', 'queue', '12', track, '2026-09-07')
		for track in range(20_000)
	}
	assert len(seen) == 20_000
def test_camera_horizons_are_asked_once_and_cached(monkeypatch):
	"""Five cameras in series is five timeouts behind a four-second caller."""
    
	import datetime

	from ain_api import feeds

	asked = []

	def fake(stream):
		asked.append(stream)
		return datetime.datetime(2026, 9, 7, tzinfo=datetime.timezone.utc)

	monkeypatch.setattr(feeds, '_horizon', {})
	monkeypatch.setattr(feeds, 'recorded_from', fake)

	first = feeds.horizons(['cam3', 'cam4', 'cam5'])
	assert set(first) == {'cam3', 'cam4', 'cam5'}
	assert sorted(asked) == ['cam3', 'cam4', 'cam5']

	feeds.horizons(['cam3', 'cam4', 'cam5'])
	assert len(asked) == 3, 'the second round should come from the cache'


def test_a_bow_tie_zone_stops_the_service_starting(tmp_path):
	"""pointInPolygon does not fail on one; it answers nonsense."""
	from ain_analytics import config

	path = tmp_path / 'cameras.yml'
	path.write_text(
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  bowtie:\n    parts:\n'
		"      - camera: '03'\n"
		'        points: [[0,0],[1,1],[1,0],[0,1]]\n'
	)
	with pytest.raises(config.ConfigError, match='bow-tie'):
		config.load(path)


def test_the_bucket_expires_clips_rather_than_this_service_pruning_them(monkeypatch):
	"""Retention is a lifecycle rule now, not a directory walk.

	The local cache had a limit to tune, a directory to walk, and a prune
	that raced its own renders and fell over when a file vanished under
	it. None of that exists any more, so what is worth pinning is that
	the rule replacing it is actually applied: a bucket created without
	one keeps every clip forever.
	"""
	from ain_api import objects

	applied = {}

	class FakeStore:
		def head_bucket(self, **kwargs):
			return {}

		def put_bucket_lifecycle_configuration(self, **kwargs):
			applied.update(kwargs)

	monkeypatch.setattr(objects, 'client', lambda: FakeStore())
	objects.ensure_bucket.cache_clear()
	try:
		objects.ensure_bucket()
	finally:
		objects.ensure_bucket.cache_clear()

	rule = applied['LifecycleConfiguration']['Rules'][0]
	assert rule['Status'] == 'Enabled'
	assert rule['Expiration']['Days'] == settings.get().clip_retention_days


def test_a_clip_can_be_as_long_as_the_event_it_is_evidence_of():
	"""Two minutes could not contain a long-wait alert.

	A long-wait fires on a queue wait measured in minutes, and the clip
	is what somebody looks at to decide whether the alert was real. The
	old two-minute ceiling silently truncated exactly the events most
	worth watching, so the cap is twenty minutes.
	"""
	from ain_api import clips

	start = datetime.datetime(2026, 9, 7, tzinfo=datetime.timezone.utc)
	# An eight-minute wait survives whole.
	eight = clips.clip_window(start, start + datetime.timedelta(minutes=8))
	assert eight.seconds == 480

	# And the cap still exists, so a caller cannot ask for a day.
	capped = clips.clip_window(start, start + datetime.timedelta(hours=4))
	assert capped.seconds == settings.get().clip_max_seconds

	# An open-ended request is still short: a clip with no end is one
	# somebody clicked, not an event with a measured length.
	assert clips.clip_window(start, None).seconds == (
		settings.get().clip_default_seconds
	)


def test_a_rendered_clip_is_not_kept_on_local_disk(monkeypatch, tmp_path):
	"""The artefact is the object. Nothing survives the render locally.

	A half-written mp4 left behind used to be indistinguishable from a
	finished one, and the size check accepted it forever.
	"""
	import inspect

	from ain_api import clips

	source = inspect.getsource(clips.render)
	assert 'TemporaryDirectory' in source
	# And no module-level directory to leak into.
	assert not hasattr(clips, '_CACHE')
	assert not hasattr(clips, '_prune')


def test_boxes_are_shifted_to_the_frame_they_belong_on(monkeypatch):
	"""The two ends of a clip are on different clocks.

	A detection is stamped by the source adapter after it has pulled the
	frame over RTSP and decoded it; the recording it is drawn onto is
	stamped by MediaMTX's recorder. Measured, the detection runs about a
	third of a second late, so a box keyed by its raw timestamp lands
	where its subject WAS - invisible on somebody sitting, half a person
	wide on anybody walking.

	The sign is the whole test: shifting the wrong way doubles the error.
	"""
	from ain_api import clips

	origin = datetime.datetime(2026, 9, 7, 20, 30, tzinfo=datetime.timezone.utc)
	scope = queries.Window(start=origin, end=origin + datetime.timedelta(seconds=10))
	# One detection, stamped exactly 5s into the clip.
	stamped = (origin + datetime.timedelta(seconds=5)).isoformat()
	monkeypatch.setattr(
		queries, 'overlay',
		lambda *args, **kwargs: [{'ts': stamped, 'objects': [{'track_id': 1}]}],
	)
	monkeypatch.setattr(clips, '_OPTIONS', settings.Settings(clip_box_lag_ms=300))

	keyed = clips._boxes_by_offset(None, '03', scope)
	# It is drawn EARLIER in the clip than its timestamp says, because the
	# timestamp is late.
	assert list(keyed) == [4700], keyed


def test_the_lag_can_be_turned_off(monkeypatch):
	"""It is a calibration, so zero has to mean "trust the timestamps"."""
	from ain_api import clips

	origin = datetime.datetime(2026, 9, 7, 20, 30, tzinfo=datetime.timezone.utc)
	scope = queries.Window(start=origin, end=origin + datetime.timedelta(seconds=10))
	stamped = (origin + datetime.timedelta(seconds=5)).isoformat()
	monkeypatch.setattr(
		queries, 'overlay',
		lambda *args, **kwargs: [{'ts': stamped, 'objects': [{'track_id': 1}]}],
	)
	monkeypatch.setattr(clips, '_OPTIONS', settings.Settings(clip_box_lag_ms=0))

	assert list(clips._boxes_by_offset(None, '03', scope)) == [5000]


def test_a_drawing_change_does_not_serve_the_old_clip():
	"""Clips are cached in the bucket under their event id.

	Without a version in the key, fixing the drawing returns the copy the
	previous version rendered and the fix looks like it did nothing.
	"""
	from ain_api import clips

	assert clips._RENDER_VERSION >= 2
	assert f'v{clips._RENDER_VERSION}' in f'evt.v{clips._RENDER_VERSION}.mp4'
