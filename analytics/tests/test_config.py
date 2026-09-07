"""cameras.yml is the only place geometry lives, so it is worth checking."""

import pathlib

import pytest

from ain_analytics import config

_REAL = pathlib.Path(__file__).resolve().parent.parent / 'cameras.yml'


@pytest.fixture(name='settings')
def _settings() -> config.Config:
	"""The config the running stack actually uses."""
	return config.load(_REAL)


def _write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
	"""Writes a throwaway cameras.yml."""
	path = tmp_path / 'cameras.yml'
	path.write_text(body)
	return path


def test_real_config_declares_the_zones_the_kpis_ask_for(settings):
	assert {'indoor', 'outdoor', 'queue', 'kitchen', 'tables'} <= set(
		settings.zones
	)
	assert 'entrance' in settings.lines


def test_camera_ids_keep_their_leading_zero(settings):
	# '06' parsed as the number 6 stops matching catalogue.py, and every row
	# in ClickHouse joins on this string. Asserted over the whole roster
	# rather than one named camera, so it still holds when the list of
	# cameras the pipeline watches changes.
	padded = [
		camera_id for camera_id in settings.cameras if camera_id.startswith('0')
	]
	assert padded, 'no zero-padded camera to check'
	for camera_id in padded:
		assert isinstance(camera_id, str)
		assert int(camera_id) not in settings.cameras


def test_zone_membership_tests_the_foot_point_not_the_centre(settings):
	sql = settings.zone('queue').contains_sql
	assert 'yc + h / 2' in sql
	assert 'pointInPolygon' in sql


def test_zone_predicate_names_every_one_of_its_cameras(settings):
	indoor = settings.zone('indoor')
	assert set(indoor.cameras) == {'03', '04'}
	for camera in indoor.cameras:
		assert f"source_id = '{camera}'" in indoor.contains_sql


def test_named_parts_survive_into_the_grouping_expression(settings):
	expression = settings.zone('tables').part_name_sql()
	assert "'table-1'" in expression
	assert "'table-3'" in expression


def test_unnamed_parts_still_group(settings):
	# A zone that is not subdivided has to answer with something, or every
	# visit to it lands in the "outside" bucket.
	expression = settings.zone('queue').part_name_sql()
	assert "'queue-1'" in expression


def test_a_line_carries_both_of_its_parallels(settings):
	geometry = settings.lines['entrance'].geometry()
	assert geometry['kind'] == 'line'
	assert {part['name'] for part in geometry['parts']} == {'outer', 'inner'}


def test_unknown_zone_is_an_error_not_an_empty_result(settings):
	with pytest.raises(config.UnknownZoneError):
		settings.zone('car-park')


def test_a_zone_on_an_undeclared_camera_is_rejected(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n'
		"    - camera: '99'\n      points: [[0,0],[1,0],[1,1]]\n",
	)
	with pytest.raises(config.ConfigError, match='unknown camera'):
		config.load(path)


def test_pixel_coordinates_are_rejected(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n'
		"    - camera: '03'\n      points: [[0,0],[1280,0],[1280,720]]\n",
	)
	with pytest.raises(config.ConfigError, match='outside 0..1'):
		config.load(path)


def test_a_line_with_only_one_parallel_is_rejected(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'lines:\n  entrance:\n'
		"    camera: '03'\n    outer: [[0,0],[1,1]]\n",
	)
	with pytest.raises(config.ConfigError, match='phantom crossings'):
		config.load(path)


def test_a_zone_declares_its_capacity_beside_its_parts(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n    capacity: 14\n    parts:\n'
		"      - camera: '03'\n        points: [[0,0],[1,0],[1,1]]\n",
	)
	zone = config.load(path).zone('indoor')
	assert zone.capacity == 14
	assert zone.proportion(0.9) == pytest.approx(12.6)


def test_a_zone_without_a_capacity_refuses_a_proportion(tmp_path):
	# An invented denominator would put a made-up number behind an alert,
	# and nothing downstream could tell.
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  tables:\n    parts:\n'
		"      - camera: '03'\n        points: [[0,0],[1,0],[1,1]]\n",
	)
	zone = config.load(path).zone('tables')
	assert zone.capacity is None
	with pytest.raises(config.NoCapacityError):
		zone.proportion(0.9)


def test_a_capacity_that_is_not_a_headcount_is_rejected(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n    capacity: 0\n    parts:\n'
		"      - camera: '03'\n        points: [[0,0],[1,0],[1,1]]\n",
	)
	with pytest.raises(config.ConfigError, match='positive number of people'):
		config.load(path)


def test_a_zone_written_as_a_bare_list_still_loads(tmp_path):
	# The older shape, before capacity existed. A zone without one is a
	# perfectly good zone; it just cannot be alerted on proportionally.
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n'
		"    - camera: '03'\n      points: [[0,0],[1,0],[1,1]]\n",
	)
	zone = config.load(path).zone('indoor')
	assert zone.capacity is None
	assert len(zone.parts) == 1


def test_a_zone_with_no_parts_is_an_error(tmp_path):
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  indoor:\n    capacity: 8\n    parts: []\n',
	)
	with pytest.raises(config.ConfigError, match='no parts'):
		config.load(path)


def test_what_the_editor_writes_is_what_the_loader_reads(tmp_path):
	"""Pins the editor's output format to this loader.

	The page emits YAML for a human to paste into cameras.yml. If the two
	drift, the failure is a config file that looks right and does not
	load - so the exact shape it writes is asserted here.
	"""
	path = _write(
		tmp_path,
		"cameras:\n  '03': {stream: cam3}\n"
		'\n'
		'zones:\n'
		'  waiting:\n'
		'    capacity: 6\n'
		'    parts:\n'
		"      - camera: '03'\n"
		'        points: [[0.20, 0.70], [0.46, 0.66], [0.52, 0.90], [0.24, 0.94]]\n'
		'  tables:\n'
		'    parts:\n'
		"      - camera: '03'\n"
		'        name: table-1\n'
		'        points: [[0.33, 0.55], [0.60, 0.55], [0.62, 0.90]]\n'
		'\n'
		'lines:\n'
		'  entrance:\n'
		"    camera: '03'\n"
		'    outer: [[0.73, 0.40], [1.00, 0.83]]\n'
		'    inner: [[0.66, 0.46], [0.93, 0.89]]\n',
	)
	settings = config.load(path)
	assert settings.zone('waiting').capacity == 6
	assert settings.zone('tables').parts[0].name == 'table-1'
	assert settings.line('entrance').outer == ((0.73, 0.40), (1.00, 0.83))
	# And the geometry it produces is usable, not merely parseable.
	assert 'pointInPolygon' in settings.zone('waiting').contains_sql
