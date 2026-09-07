"""Checks the responses against the frontend's contract.

The frontend has no fallbacks, so these assert the shapes it indexes
into rather than merely that a route answers.
"""

import dataclasses

import fastapi.testclient
import pytest

from ain_backend import alerts
from ain_backend import catalogue
from ain_backend import i18n
from ain_backend import live
from ain_backend import main
from ain_backend import models
from ain_backend import payloads
from ain_backend import store

FILTERS = {'branch': 'olaya', 'venue': 'cafe', 'range': 'today'}


@pytest.fixture(name='client')
def client_fixture() -> fastapi.testclient.TestClient:
	"""Returns a client bound to the app, with an empty rule store."""
	store.clear()
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
	"""Asserts the shape shared by line and histogram."""
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
	stats = {stat['id']: stat for stat in data['stats']}
	for stat in data['stats']:
		assert isinstance(stat['value'], str)
	trend = data.get('trend')
	if trend is None:
		return
	# A card may chart a subset of its numbers - Feed health draws only
	# the line worth watching - but every line still has to name one of
	# them, and to end on the number that stat is printing.
	series_ids = [series['id'] for series in trend['series']]
	assert series_ids and set(series_ids) <= set(stats)
	last = trend['points'][-1]
	for series_id in series_ids:
		assert str(round(float(last[series_id]))) in stats[series_id]['value']


def assert_camera_grid_payload(data: dict):
	"""A tile carries both the status and the word for it."""
	assert data['feeds']
	for feed in data['feeds']:
		assert feed['status'] in {'online', 'offline'}
		assert feed['statusLabel'] and feed['label'] and feed['zone']
		if feed['status'] == 'offline':
			assert 'streamUrl' not in feed


_ASSERTIONS = {
	'kpi': assert_kpi_payload,
	'stat-group': assert_stat_group_payload,
	'line': assert_series_payload,
	'histogram': assert_series_payload,
	'camera-grid': assert_camera_grid_payload,
}


def test_every_served_element_type_is_in_the_contract(client):
	"""Nothing is served that the frontend cannot render."""
	served = {element['type'] for element in element_defs(client)}
	assert served <= {member.value for member in models.ElementType}
	assert served <= set(_ASSERTIONS)


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
	"""No route serves clips, so the URLs the payloads link to 404."""
	assert client.get('/api/clips/congestion-count/0.mp4').status_code == 404


def test_an_online_feed_carries_the_stream_the_browser_plays(client):
	"""Streams are served next to the API, not by it."""
	feeds = fetch(client, 'camera-feeds')['data']['feeds']
	online = [feed for feed in feeds if feed['status'] == 'online']
	assert online
	for feed in online:
		assert feed['streamUrl'].startswith('/cam')
		assert feed['streamUrl'].endswith('.m3u8')


def test_every_camera_has_a_recording_behind_it(client):
	"""A camera id with no stream path is a tile that can never play."""
	paths = {camera.stream_url for camera in catalogue.CAMERAS}
	assert len(paths) == len(catalogue.CAMERAS)


def test_feed_health_agrees_with_the_grid(client):
	"""The health card and the tiles share one roll of who is up."""
	health = fetch(client, 'camera-status')['data']
	stats = {stat['id']: stat['value'] for stat in health['stats']}
	feeds = fetch(client, 'camera-feeds')['data']['feeds']
	offline = [feed for feed in feeds if feed['status'] == 'offline']
	assert stats['total'] == str(len(feeds))
	assert stats['offline'] == str(len(offline))


def test_feed_health_carries_the_downtime_over_the_window(client):
	"""The card is one card: the numbers now, and downtime behind them."""
	health = fetch(client, 'camera-status')['data']
	trend = health['trend']
	assert [series['id'] for series in trend['series']] == ['offline']
	total = int(health['stats'][0]['value'])
	assert trend['points']
	for point in trend['points']:
		assert 0 <= point['offline'] <= total


def test_a_rule_survives_a_new_connection(client):
	"""The store is a database, not a dict in the process."""
	created = client.post(
		'/api/alerts/rules',
		params=FILTERS,
		json={
			'monitorId': 'queue-length',
			'comparator': 'above',
			'threshold': 12,
		},
	)
	assert created.status_code == 201
	# A different thread opens its own connection, which is where a
	# per-connection in-memory database would lose the row.
	rows = store.rows()
	assert [row['id'] for row in rows] == [created.json()['id']]
	assert rows[0]['monitor_id'] == 'queue-length'
	assert rows[0]['comparator'] == 'above'


def test_deleting_a_rule_empties_the_store(client):
	created = client.post(
		'/api/alerts/rules',
		params=FILTERS,
		json={
			'monitorId': 'queue-length',
			'comparator': 'above',
			'threshold': 12,
		},
	)
	client.delete(f'/api/alerts/rules/{created.json()["id"]}')
	assert store.rows() == []


def test_a_rule_with_nothing_behind_it_reports_no_status():
	"""Unknown is not zero.

	A rule the pipeline cannot evaluate must not read as "did not fire":
	one says nothing happened, the other says nobody looked, and a chip
	saying the first about the second is worse than no chip.
	"""
	label, severity = alerts._status(None, i18n.Locale.EN)
	assert label is None
	assert severity is None


def test_a_rule_that_did_not_fire_says_so():
	label, severity = alerts._status(0, i18n.Locale.EN)
	assert label == 'Not fired'
	assert severity is models.Severity.OK


def test_a_rule_that_fired_a_lot_is_critical():
	label, severity = alerts._status(7, i18n.Locale.EN)
	assert '7' in label
	assert severity is models.Severity.CRITICAL


def test_a_duration_rule_is_converted_to_the_seconds_analytics_speaks(
	monkeypatch,
):
	"""Every duration in the catalogue is minutes; analytics is seconds."""
	sent: dict = {}

	def fake_get(path, params):
		sent.update({'path': path, **params})
		return {'count': 2}

	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(live.analytics, 'get', fake_get)
	spec = catalogue.ELEMENTS_BY_ID['queue-wait-time']
	assert live.breaches(spec, 'above', 5, 'today') == 2
	assert sent['path'] == '/events'
	assert sent['threshold'] == 300
	assert sent['zone'] == 'queue'
	assert sent['metric'] == 'dwell'


def test_a_split_stat_group_is_evaluated_over_its_first_zone(monkeypatch):
	sent: dict = {}

	def fake_get(path, params):
		sent.update(params)
		return {'count': 0}

	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(live.analytics, 'get', fake_get)
	spec = catalogue.ELEMENTS_BY_ID['live-occupancy']
	assert live.breaches(spec, 'above', 40, 'today') == 0
	assert sent['zone'] == 'indoor'
	assert sent['threshold'] == 40


def test_the_overlay_speaks_the_wire_contract_not_the_services(monkeypatch):
	"""snake_case in, camelCase out.

	The analytics service returns `track_id`; every other field on this
	wire is camelCase and the frontend reads `trackId`. Passing the body
	through verbatim is a box labelled "person undefined" on every tile.
	"""
	body = {
		'camera': '03',
		'start': '2026-09-06T21:00:00+00:00',
		'end': '2026-09-06T21:00:05+00:00',
		'frames': [
			{
				'ts': '2026-09-06T21:00:00.100+00:00',
				'objects': [
					{
						'track_id': 918, 'label': 'person',
						'xc': 0.41, 'yc': 0.62, 'w': 0.08, 'h': 0.31,
					}
				],
			}
		],
	}
	monkeypatch.setattr(main.analytics, 'get', lambda path, params: body)
	client = fastapi.testclient.TestClient(main.app)
	payload = client.get('/api/overlay', params={'camera': '03'}).json()
	obj = payload['frames'][0]['objects'][0]
	assert obj['trackId'] == 918
	assert 'track_id' not in obj


def test_zones_come_back_shaped_for_the_renderer(monkeypatch):
	body = {
		'zones': [
			{
				'name': 'queue',
				'kind': 'polygon',
				'parts': [
					{'camera': '12', 'name': None, 'points': [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]}
				],
			}
		],
		'lines': [],
	}
	monkeypatch.setattr(main.analytics, 'get', lambda path, params: body)
	client = fastapi.testclient.TestClient(main.app)
	payload = client.get('/api/zones').json()
	assert payload['zones'][0]['kind'] == 'polygon'
	assert payload['zones'][0]['parts'][0]['camera'] == '12'
	# Absent rather than null, matching what the TypeScript's `?:` means.
	assert 'name' not in payload['zones'][0]['parts'][0]


def test_no_analytics_service_means_no_zones_rather_than_an_error(monkeypatch):
	monkeypatch.setattr(main.analytics, 'get', lambda path, params: None)
	client = fastapi.testclient.TestClient(main.app)
	response = client.get('/api/zones')
	assert response.status_code == 200
	assert response.json() == {'zones': [], 'lines': []}


def test_a_new_split_card_needs_only_its_own_elementspec(monkeypatch):
	"""The whole point of the server-driven design.

	A second split stat group - back-of-house against front - must be one
	ElementSpec, so the labels ride on the spec rather than living in a
	table somewhere downstream that would have to be edited too.
	"""
	spec = dataclasses.replace(
		catalogue.ELEMENTS_BY_ID['live-occupancy'],
		id='kitchen-split',
		source=catalogue.Source(
			kind=catalogue.SourceKind.OCCUPANCY,
			split=(
				('kitchen', 'kitchen', i18n.Text('Kitchen', 'المطبخ')),
				('queue', 'queue', i18n.Text('Queue', 'الطابور')),
			),
		),
	)
	asked = []

	def fake_get(path, params):
		asked.append(params.get('zone'))
		return {
			'end': '2026-09-06T21:00:00+00:00',
			'latest': 2,
			'buckets': [
				{'ts': '2026-09-06T20:00:00+00:00', 'mean': 2.0, 'peak': 3}
			],
		}

	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(live.analytics, 'get', fake_get)
	monkeypatch.setitem(catalogue.ELEMENTS_BY_ID, 'kitchen-split', spec)

	built = payloads.build_element(
		'kitchen-split', '', i18n.Locale.EN, 'today'
	)
	labels = [stat.label for stat in built.data.stats]
	assert labels == ['Total', 'Kitchen', 'Queue']
	assert asked == ['kitchen', 'queue']
	assert [stat.value for stat in built.data.stats] == ['4', '2', '2']


def test_a_multi_day_instance_log_labels_the_day(monkeypatch):
	"""Over a week "09:15" happens seven times.

	The rows are ordered on the instant either way; this is about a
	reader being able to tell Tuesday's from Thursday's.
	"""
	body = {
		'count': 2,
		'events': [
			{
				'id': 'cong-1', 'start': '2026-09-05T09:15:00+00:00',
				'end': '2026-09-05T09:20:00+00:00', 'cameras': ['03'],
				'peak_value': 12, 'threshold': 8, 'comparator': 'above',
			},
			{
				'id': 'cong-2', 'start': '2026-09-06T09:15:00+00:00',
				'end': '2026-09-06T09:20:00+00:00', 'cameras': ['03'],
				'peak_value': 20, 'threshold': 8, 'comparator': 'above',
			},
		],
	}
	# Camera 03 has video from the 6th, so the older event has none.
	cameras = {
		'cameras': [
			{
				'id': '03', 'stream': 'cam3', 'live': True,
				'recorded_from': '2026-09-06T00:00:00+00:00',
			}
		]
	}
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: cameras if path == '/cameras' else body,
	)

	log = payloads.build_instance_log(
		'congestion-count', '', i18n.Locale.EN, '7d'
	)
	assert [entry.id for entry in log.instances] == ['cong-2', 'cong-1']
	assert all('-' in entry.timestamp for entry in log.instances)
	# Recording is a rolling window: the event inside it gets a link, the
	# one that predates it gets none rather than a button that 404s.
	by_id = {entry.id: entry for entry in log.instances}
	assert by_id['cong-2'].clip_url is not None
	assert by_id['cong-1'].clip_url is None

	today = payloads.build_instance_log(
		'congestion-count', '', i18n.Locale.EN, 'today'
	)
	assert all(len(entry.timestamp) == 5 for entry in today.instances)


def test_a_ppe_card_shows_its_number_once_a_model_reports_one(monkeypatch):
	"""The dash is for "not measured", not for "measured as zero"."""
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {'value': 3, 'status': 'ok'},
	)
	built = payloads.build_element(
		'no-mask-count', '', i18n.Locale.EN, 'today'
	)
	assert built.data.value == '3'
	assert built.data.severity is models.Severity.CRITICAL


def test_a_ppe_card_with_no_model_shows_a_dash_not_a_zero(monkeypatch):
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {
			'value': None,
			'status': 'unavailable',
			'reason': 'ppe_model_not_deployed',
		},
	)
	built = payloads.build_element(
		'no-mask-count', '', i18n.Locale.EN, 'today'
	)
	# Not "0": that would assert the kitchen was watched and found
	# compliant, and severity is derived from the value.
	assert built.data.value == live._NO_VALUE
	assert built.data.severity is models.Severity.INFO


def test_an_unwatched_camera_reports_no_signal(monkeypatch):
	"""The branch has ten cameras; the pipeline watches five.

	The other five are still on the wall and still in the catalogue -
	they exist - but nothing is looking at them, so the honest tile is a
	dark one. Reporting them online would be the lie.
	"""
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {
			'cameras': [
				{'id': '03', 'stream': 'cam3', 'live': True},
				{'id': '04', 'stream': 'cam4', 'live': True},
				{'id': '05', 'stream': 'cam5', 'live': False},
			]
		},
	)
	status = payloads.camera_status('')
	assert status['03'] is True
	assert status['04'] is True
	# Configured but its stream server does not have it.
	assert status['05'] is False
	# Not configured at all: nothing is watching it.
	assert status['09'] is False
	assert status['15'] is False
	# Every camera the catalogue declares is accounted for, so the grid
	# and the Feed health stats cannot disagree.
	assert set(status) == {camera.id for camera in catalogue.CAMERAS}


def test_a_camera_nobody_watches_carries_no_stream_url(client, monkeypatch):
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {
			'cameras': [{'id': '03', 'stream': 'cam3', 'live': True}]
		},
	)
	feeds = client.get('/api/elements/camera-feeds', params=FILTERS).json()
	by_id = {feed['id']: feed for feed in feeds['data']['feeds']}
	assert by_id['03']['status'] == 'online'
	assert by_id['03']['streamUrl'] == '/cam3/index.m3u8'
	# Absent, not a URL that would render as a broken player.
	assert by_id['15']['status'] == 'offline'
	assert 'streamUrl' not in by_id['15']


def test_feed_health_counts_what_the_grid_shows(client, monkeypatch):
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {
			'cameras': [
				{'id': camera_id, 'stream': f'cam{int(camera_id)}', 'live': True}
				for camera_id in ('03', '04', '05', '06', '12')
			]
		},
	)
	stats = client.get('/api/elements/camera-status', params=FILTERS).json()
	by_id = {stat['id']: stat['value'] for stat in stats['data']['stats']}
	assert by_id == {'total': '10', 'online': '5', 'offline': '5'}


def test_no_pipeline_falls_back_to_the_generated_roll(monkeypatch):
	monkeypatch.setattr(live.analytics, 'configured', lambda: False)
	status = payloads.camera_status('branch=olaya')
	assert set(status) == {camera.id for camera in catalogue.CAMERAS}
	# Deterministic, so a card does not flicker between polls.
	assert status == payloads.camera_status('branch=olaya')


def test_real_feed_health_draws_no_invented_history(client, monkeypatch):
	"""Nothing stores a history of which cameras were up.

	The three numbers come from the servers that own the streams and are
	true now. A random walk beside them would be the same false claim the
	PPE dash exists to refuse, drawn as a chart instead of written as a
	number.
	"""
	monkeypatch.setattr(live.analytics, 'configured', lambda: True)
	monkeypatch.setattr(
		live.analytics,
		'get',
		lambda path, params: {
			'cameras': [{'id': '03', 'stream': 'cam3', 'live': True}]
		},
	)
	payload = client.get(
		'/api/elements/camera-status', params=FILTERS
	).json()['data']
	assert [stat['id'] for stat in payload['stats']] == [
		'total', 'online', 'offline',
	]
	assert 'trend' not in payload


def test_invented_feed_health_still_draws_its_line(client, monkeypatch):
	# Without a pipeline the whole card is a placeholder, and the line is
	# the only thing on it that moves.
	monkeypatch.setattr(live.analytics, 'configured', lambda: False)
	payload = client.get(
		'/api/elements/camera-status', params=FILTERS
	).json()['data']
	assert payload['trend']['series'][0]['id'] == 'offline'
	# The last point is the number the stats print, not another roll.
	offline = next(
		stat['value'] for stat in payload['stats'] if stat['id'] == 'offline'
	)
	assert payload['trend']['points'][-1]['offline'] == int(offline)
