"""Writing cameras.yml back, which is the only thing here that can lose work.

Every test starts from the real file rather than a fixture. The point of a
comment-preserving round trip is that it survives THIS document - the one
with 74 lines of comments explaining why each polygon sits where it does -
and a three-line fixture would pass while the real file was flattened.
"""

import pathlib
import shutil

import pytest

from ain_analytics import config

_REAL = (
	pathlib.Path(__file__).resolve().parents[3] / 'config' / 'cameras.yml'
)


@pytest.fixture(name='copy')
def _copy(tmp_path: pathlib.Path) -> pathlib.Path:
	"""A scratch copy of the checked-in config."""
	path = tmp_path / 'cameras.yml'
	shutil.copy(_REAL, path)
	return path


def _square(x: float = 0.1) -> list[list[float]]:
	return [[x, 0.1], [x + 0.2, 0.1], [x + 0.2, 0.3], [x, 0.3]]


def test_saving_keeps_every_comment(copy):
	"""The reason for ruamel, stated as an assertion."""
	before = copy.read_text().count('#')
	config.save(
		'03',
		[{'kind': 'polygon', 'name': 'lobby', 'part': '', 'capacity': 4,
		  'points': _square()}],
		copy,
	)
	assert copy.read_text().count('#') == before


def test_saving_leaves_the_other_cameras_alone(copy):
	"""A zone is the sum of its parts, drawn one camera at a time."""
	before = config.load(copy).zone('indoor')
	elsewhere = [part for part in before.parts if part.camera != '03']
	assert elsewhere, 'fixture assumption: indoor spans more than camera 03'

	config.save('03', [], copy)

	after = config.load(copy).zone('indoor')
	assert [part.camera for part in after.parts] == [
		part.camera for part in elsewhere
	]
	assert after.capacity == before.capacity


def test_a_camera_that_draws_nothing_drops_its_own_zones(copy):
	"""Deleting a shape and saving has to actually delete it."""
	settings = config.load(copy)
	only_here = [
		name
		for name, zone in settings.zones.items()
		if zone.cameras == ('12',)
	]
	assert only_here, 'fixture assumption: some zone lives only on camera 12'

	config.save('12', [], copy)

	assert set(config.load(copy).zones).isdisjoint(only_here)


def test_camera_ids_stay_quoted(copy):
	"""`03` unquoted is the number 3, and camera ids join to catalogue.py."""
	config.save(
		'04',
		[{'kind': 'polygon', 'name': 'lobby', 'part': '', 'capacity': None,
		  'points': _square()}],
		copy,
	)
	for line in copy.read_text().splitlines():
		if 'camera:' in line:
			assert "'" in line, line
	assert config.load(copy).zone('lobby').parts[0].camera == '04'


def test_a_line_saves_as_the_pair_it_is(copy):
	config.save(
		'05',
		[
			{'kind': 'line', 'name': 'side-door', 'part': 'outer',
			 'points': [[0.1, 0.2], [0.4, 0.5]]},
			{'kind': 'line', 'name': 'side-door', 'part': 'inner',
			 'points': [[0.1, 0.3], [0.4, 0.6]]},
		],
		copy,
	)
	line = config.load(copy).line('side-door')
	assert line.camera == '05'
	assert line.outer == ((0.1, 0.2), (0.4, 0.5))
	assert line.inner == ((0.1, 0.3), (0.4, 0.6))


def test_half_a_line_is_refused_and_nothing_is_written(copy):
	before = copy.read_text()
	with pytest.raises(config.ConfigError, match='0 inner lines'):
		config.save(
			'05',
			[{'kind': 'line', 'name': 'side-door', 'part': 'outer',
			  'points': [[0.1, 0.2], [0.4, 0.5]]}],
			copy,
		)
	assert copy.read_text() == before


def test_a_line_name_another_camera_owns_is_refused(copy):
	"""Lines are keyed by name globally, so this would delete an entrance
	from a camera the editor is not even showing."""
	owner = config.load(copy).line('entrance').camera
	assert owner != '05'
	with pytest.raises(config.ConfigError, match='already a counting line'):
		config.save(
			'05',
			[
				{'kind': 'line', 'name': 'entrance', 'part': side,
				 'points': [[0.1, 0.2], [0.4, 0.5]]}
				for side in ('outer', 'inner')
			],
			copy,
		)
	assert config.load(copy).line('entrance').camera == owner


def test_a_broken_polygon_is_refused_and_nothing_is_written(copy):
	"""A bow-tie. Validated before the write, so the file stays loadable."""
	before = copy.read_text()
	with pytest.raises(config.ConfigError):
		config.save(
			'03',
			[{'kind': 'polygon', 'name': 'bad', 'part': '', 'capacity': None,
			  'points': [[0.1, 0.1], [0.5, 0.5], [0.5, 0.1], [0.1, 0.5]]}],
			copy,
		)
	assert copy.read_text() == before


def test_an_unknown_camera_is_refused(copy):
	with pytest.raises(config.ConfigError, match='not a camera'):
		config.save('99', [], copy)


def test_an_unnamed_shape_is_refused(copy):
	with pytest.raises(config.ConfigError, match='needs a name'):
		config.save(
			'03',
			[{'kind': 'polygon', 'name': '  ', 'part': '', 'points': _square()}],
			copy,
		)


def test_a_round_trip_that_changes_nothing_changes_nothing(copy):
	"""Open the editor, save without drawing, and the diff should be empty.

	This is the test that catches a round trip which reformats - quoting,
	indentation, flow style, float precision. Any of those would turn every
	save into an unreviewable diff.
	"""
	before = copy.read_text()
	settings = config.load(copy)
	for camera in settings.cameras:
		shapes = [
			{'kind': 'polygon', 'name': name, 'part': part.name,
			 'capacity': zone.capacity, 'points': [list(p) for p in part.points]}
			for name, zone in settings.zones.items()
			for part in zone.parts
			if part.camera == camera
		] + [
			{'kind': 'line', 'name': name, 'part': side,
			 'points': [list(p) for p in pair]}
			for name, line in settings.lines.items()
			if line.camera == camera
			for side, pair in (('outer', line.outer), ('inner', line.inner))
		]
		config.save(camera, shapes, copy)
	assert copy.read_text() == before


def test_the_note_above_a_polygon_survives_redrawing_it(copy):
	"""These comments are the file's documentation, and they are per-polygon.

	Deleting a part takes the comment above it, so a nudge in the editor
	would quietly delete the sentence explaining where the polygon stops
	and why. Captured and put back.
	"""
	note = '# The seating corridor'
	assert note in copy.read_text(), 'fixture assumption: camera 04 has a note'
	settings = config.load(copy)
	part = next(p for p in settings.zone('indoor').parts if p.camera == '04')
	moved = [[round(x + 0.01, 2), y] for x, y in part.points]

	config.save(
		'04',
		[{'kind': 'polygon', 'name': 'indoor', 'part': '',
		  'capacity': settings.zone('indoor').capacity, 'points': moved}],
		copy,
	)

	body = copy.read_text()
	assert note in body
	# And still above camera 04's part, not orphaned somewhere else.
	after = body.split(note, 1)[1].split('\n', 1)[1]
	assert after.startswith("      - camera: '04'")


def test_saving_does_not_reshuffle_a_zone(copy):
	"""A redrawn part goes back where it was, so the diff is the shape."""
	before = [p.camera for p in config.load(copy).zone('indoor').parts]
	settings = config.load(copy)
	part = next(p for p in settings.zone('indoor').parts if p.camera == '04')
	config.save(
		'04',
		[{'kind': 'polygon', 'name': 'indoor', 'part': '',
		  'capacity': settings.zone('indoor').capacity,
		  'points': [list(q) for q in part.points]}],
		copy,
	)
	assert [p.camera for p in config.load(copy).zone('indoor').parts] == before


def test_a_save_against_a_stale_read_is_refused(copy):
	"""Two tabs on one camera, or one tab and a hand edit.

	Every save replaces a whole camera, so without this the second writer
	deletes whatever the first drew and says "Saved" while doing it. The
	audit of this feature reproduced exactly that within minutes.
	"""
	read_at = config.version(copy)
	config.save(
		'03',
		[{'kind': 'polygon', 'name': 'first', 'part': '', 'capacity': None,
		  'points': _square()}],
		copy,
	)
	with pytest.raises(config.StaleWriteError):
		config.save(
			'03',
			[{'kind': 'polygon', 'name': 'second', 'part': '', 'capacity': None,
			  'points': _square(0.4)}],
			copy,
			expect=read_at,
		)
	# And the first writer's work is still there.
	assert 'first' in config.load(copy).zones
	assert 'second' not in config.load(copy).zones


def test_a_save_against_a_fresh_read_goes_through(copy):
	config.save(
		'03',
		[{'kind': 'polygon', 'name': 'first', 'part': '', 'capacity': None,
		  'points': _square()}],
		copy,
		expect=config.version(copy),
	)
	assert 'first' in config.load(copy).zones
