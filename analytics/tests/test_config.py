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
	# '09' parsed as the number 9 stops matching catalogue.py, and every row
	# in ClickHouse joins on this string.
	assert '09' in settings.cameras
	assert 9 not in settings.cameras


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
