"""Checks the responses against the frontend's contract.

The frontend has no fallbacks, so these assert the shapes it indexes
into rather than merely that a route answers.
"""

import fastapi.testclient
import pytest

from ain_backend import alerts
from ain_backend import catalogue
from ain_backend import main
from ain_backend import models
from ain_backend import payloads

FILTERS = {'branch': 'olaya', 'venue': 'cafe', 'range': 'today'}


@pytest.fixture(name='client')
def client_fixture() -> fastapi.testclient.TestClient:
	"""Returns a client bound to the app, with an empty rule store."""
	alerts.store().clear()
	return fastapi.testclient.TestClient(main.app)


def config(client, lang: str = 'en') -> dict:
	"""Reads the dashboard config in one language."""
	response = client.get('/api/dashboard/config', params={'lang': lang})
	assert response.status_code == 200
	return response.json()


def element_defs(client, lang: str = 'en') -> list[dict]:
	"""Returns every element the config lays out, deduplicated by id."""
	seen: dict[str, dict] = {}
	for section in config(client, lang)['sections']:
		for element in section['elements']:
			seen.setdefault(element['id'], element)
	return list(seen.values())


def fetch(client, element_id: str, **overrides) -> dict:
	"""Fetches one element payload under the standard filters."""
	response = client.get(
		f'/api/elements/{element_id}', params={**FILTERS, **overrides}
	)
	assert response.status_code == 200, element_id
	return response.json()


def test_health(client):
	assert client.get('/health').json()['status'] == 'ok'


def test_config_carries_todays_date_and_filters(client):
	body = config(client)
	assert body['today'] == catalogue.today().isoformat()
	assert body['branchLabel']
	filters = {item['id']: item for item in body['filters']}
	assert filters['range']['control'] == 'date-range'
	assert filters['branch']['defaultValue'] == 'olaya'
	assert all(item['options'] for item in body['filters'])


def test_exactly_one_section_uses_the_alert_view(client):
	views = [
		section.get('view') for section in config(client)['sections']
	]
	assert views.count('alerts') == 1


def test_repeated_elements_are_identical_across_sections(client):
	by_id: dict[str, dict] = {}
	for section in config(client)['sections']:
		for element in section['elements']:
			# Overview reuses cards; both tabs must send the same def so
			# they share one cache entry.
			assert by_id.setdefault(element['id'], element) == element
	assert len(by_id) > 1


def test_every_element_declares_a_renderable_type(client):
	renderable = {member.value for member in models.ElementType}
	for element in element_defs(client):
		assert element['type'] in renderable
		assert element['title']
		assert element['updates'] in {
			member.value for member in models.UpdateCadence
		}


def test_alert_kind_elements_are_not_offered_as_monitors(client):
	alert_ids = {
		element['id']
		for element in element_defs(client)
		if element['kind'] == 'alert'
	}
	monitors = client.get('/api/alerts/monitors', params=FILTERS).json()
	assert not alert_ids & {item['id'] for item in monitors['monitors']}


def assert_series_payload(data: dict):
	"""Asserts the shape shared by line, bar, stacked-bar, histogram."""
	assert data['series'] and data['points']
	assert data['xLabel'] and data['yLabel']
	series_ids = [series['id'] for series in data['series']]
	for point in data['points']:
		assert isinstance(point['x'], str)
		for series_id in series_ids:
			assert isinstance(point[series_id], (int, float))


def assert_kpi_payload(data: dict):
	"""A KPI prints a string and judges its own direction."""
	assert isinstance(data['value'], str)
	assert data['delta']['direction'] in {'up', 'down', 'flat'}
	assert data['delta']['sentiment'] in {'ok', 'info', 'warn', 'critical'}
	assert data['delta']['label']


def assert_stat_group_payload(data: dict):
	"""Stat values are strings, and any trend agrees with them."""
	assert data['stats']
	for stat in data['stats']:
		assert isinstance(stat['value'], str)
	trend = data.get('trend')
	if trend is None:
		return
	stat_ids = [stat['id'] for stat in data['stats']]
	assert [series['id'] for series in trend['series']] == stat_ids
	last = trend['points'][-1]
	for stat in data['stats']:
		assert str(round(float(last[stat['id']]))) in stat['value']


def assert_heatmap_payload(data: dict):
	"""The matrix has to match its own axes."""
	assert len(data['cells']) == len(data['yLabels'])
	assert all(
		len(row) == len(data['xLabels']) for row in data['cells']
	)


def assert_table_payload(data: dict):
	"""Every column key is present in every row."""
	keys = [column['key'] for column in data['columns']]
	assert data['columns']
	for row in data['rows']:
		assert set(keys) <= set(row)


def assert_camera_grid_payload(data: dict):
	"""A tile carries both the status and the word for it."""
	assert data['feeds']
	for feed in data['feeds']:
		assert feed['status'] in {'online', 'offline'}
		assert feed['statusLabel'] and feed['label'] and feed['zone']
		if feed['status'] == 'offline':
			assert 'streamUrl' not in feed


def assert_gauge_payload(data: dict):
	"""The needle sits inside the band, and prints its own label."""
	assert data['min'] <= data['value'] <= data['max']
	assert data['valueLabel']


def assert_donut_payload(data: dict):
	"""Slices are numeric; the centre is the pre-formatted total."""
	assert data['slices']
	assert all(
		isinstance(item['value'], (int, float)) for item in data['slices']
	)
	assert isinstance(data['centerValue'], str)


def assert_alert_payload(data: dict):
	"""A live state says what it is and how bad it is."""
	assert data['severity'] in {'ok', 'info', 'warn', 'critical'}
	assert data['headline']


_ASSERTIONS = {
	'kpi': assert_kpi_payload,
	'stat-group': assert_stat_group_payload,
	'line': assert_series_payload,
	'bar': assert_series_payload,
	'stacked-bar': assert_series_payload,
	'histogram': assert_series_payload,
	'heatmap': assert_heatmap_payload,
	'table': assert_table_payload,
	'camera-grid': assert_camera_grid_payload,
	'gauge': assert_gauge_payload,
	'donut': assert_donut_payload,
	'alert': assert_alert_payload,
}


def test_every_served_element_type_is_in_the_contract(client):
	"""The catalogue is a subset of the contract, not a tour of it.

	The dashboard is scoped to a fixed set of cards, so most element types have
	no card today. What must hold is that nothing is served which the frontend
	cannot render, and that anything served is covered by an assertion here.
	"""
	served = {element['type'] for element in element_defs(client)}
	assert served <= {member.value for member in models.ElementType}
	assert served <= set(_ASSERTIONS)


def test_every_element_type_in_the_contract_has_a_builder():
	"""The reference implementation stays complete even where unused.

	Adding a card of an existing type should be a catalogue edit alone, so a
	type losing its last card must not quietly lose the ability to be served.
	Reaching into the private map is deliberate: there is no configured element
	to reach these builders through.
	"""
	assert set(payloads._BUILDERS) == set(models.ElementType)


@pytest.mark.parametrize('element', catalogue.ELEMENTS, ids=lambda e: e.id)
def test_payload_matches_its_declared_type(client, element):
	body = fetch(client, element.id)
	assert body['elementId'] == element.id
	assert body['type'] == element.type.value
	assert body['updatedAt']
	_ASSERTIONS[body['type']](body['data'])


def test_payloads_are_stable_for_the_same_filters(client):
	assert fetch(client, 'footfall') == fetch(client, 'footfall')


def test_filters_move_the_numbers(client):
	today = fetch(client, 'footfall')
	month = fetch(client, 'footfall', range='30d')
	assert today['data']['points'] != month['data']['points']
	assert len(month['data']['points']) == 30


def test_an_iso_date_reaches_back_from_that_day(client):
	body = fetch(client, 'footfall', range='2026-08-01')
	assert len(body['data']['points']) == 30


def test_language_relabels_without_moving_the_numbers(client):
	english = fetch(client, 'live-occupancy', lang='en')
	arabic = fetch(client, 'live-occupancy', lang='ar')
	assert english['data']['trend']['points'] == (
		arabic['data']['trend']['points']
	)
	assert [stat['value'] for stat in english['data']['stats']] == (
		[stat['value'] for stat in arabic['data']['stats']]
	)
	assert [stat['label'] for stat in english['data']['stats']] != (
		[stat['label'] for stat in arabic['data']['stats']]
	)


def test_durations_are_formatted_per_language(client):
	assert 'm ' in fetch(client, 'queue-wait-time')['data']['value']
	assert 'د' in fetch(client, 'queue-wait-time', lang='ar')['data']['value']


def test_unknown_element_is_a_404(client):
	assert client.get('/api/elements/nope', params=FILTERS).status_code == 404


def test_instance_log_is_preformatted(client):
	drilldowns = [
		element['id']
		for element in element_defs(client)
		if element.get('drilldown') == 'instances'
	]
	assert drilldowns
	body = client.get(
		f'/api/elements/{drilldowns[0]}/instances', params=FILTERS
	).json()
	assert body['title'] and body['total'] >= len(body['instances'])
	for instance in body['instances']:
		assert len(instance['timestamp']) == 5
		assert instance['camera'].startswith('Camera ')
		assert instance['clipUrl'].endswith('.mp4')


def test_monitors_carry_a_thirty_day_average(client):
	body = client.get('/api/alerts/monitors', params=FILTERS).json()
	assert body['monitors']
	for monitor in body['monitors']:
		assert isinstance(monitor['monthlyAverage'], str)
		assert isinstance(monitor['monthlyAverageValue'], (int, float))
		assert len(monitor['trend']['points']) == 30


def test_duration_monitors_average_as_a_duration(client):
	body = client.get('/api/alerts/monitors', params=FILTERS).json()
	wait = next(
		item for item in body['monitors'] if item['id'] == 'queue-wait-time'
	)
	assert 'm ' in wait['monthlyAverage']
	assert isinstance(wait['monthlyAverageValue'], (int, float))


def create_rule(client, lang='en', **overrides):
	"""Posts a rule and returns the response."""
	draft = {
		'monitorId': 'live-occupancy',
		'comparator': 'above',
		'threshold': 46,
		**overrides,
	}
	return client.post(
		'/api/alerts/rules', params={**FILTERS, 'lang': lang}, json=draft
	)


def test_a_created_rule_comes_back_from_the_next_read(client):
	created = create_rule(client)
	assert created.status_code == 201
	rules = client.get('/api/alerts/rules', params=FILTERS).json()['rules']
	assert [rule['id'] for rule in rules] == [created.json()['id']]
	assert rules[0]['summary'] == 'Above 46 people'
	assert rules[0]['createdLabel'] == 'Created today'


def test_rules_are_stored_language_neutrally(client):
	create_rule(client, lang='ar')
	english = client.get(
		'/api/alerts/rules', params={**FILTERS, 'lang': 'en'}
	).json()['rules'][0]
	arabic = client.get(
		'/api/alerts/rules', params={**FILTERS, 'lang': 'ar'}
	).json()['rules'][0]
	assert english['monitorLabel'] == 'Live occupancy'
	assert arabic['monitorLabel'] == 'الإشغال الحالي'
	assert english['id'] == arabic['id']


def test_an_unknown_monitor_is_rejected(client):
	assert create_rule(client, monitorId='nope').status_code == 400
	assert create_rule(client, monitorId='congestion-count').status_code == 400


def test_a_negative_threshold_is_rejected(client):
	assert create_rule(client, threshold=-1).status_code == 422


def test_deleting_a_rule_empties_the_list(client):
	rule_id = create_rule(client).json()['id']
	assert client.delete(f'/api/alerts/rules/{rule_id}').status_code == 204
	assert client.get('/api/alerts/rules', params=FILTERS).json() == {
		'rules': []
	}


def test_deleting_an_absent_rule_is_still_204(client):
	assert client.delete('/api/alerts/rules/nope').status_code == 204


def test_media_urls_answer_a_404_rather_than_hanging(client):
	assert client.get('/api/clips/congestion-count/0.mp4').status_code == 404
	assert client.get('/api/cameras/03/stream.m3u8').status_code == 404
