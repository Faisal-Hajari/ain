"""End-to-end checks over the dummy API."""

import fastapi.testclient
import pytest

from ain_backend import catalogue
from ain_backend import main
from ain_backend import models


@pytest.fixture(name='client')
def client_fixture() -> fastapi.testclient.TestClient:
	"""Returns a client bound to the app."""
	return fastapi.testclient.TestClient(main.app)


def test_health(client):
	response = client.get('/health')
	assert response.status_code == 200
	assert response.json()['status'] == 'ok'


def test_catalogue_covers_every_section(client):
	body = client.get('/api/catalogue').json()
	assert len(body['cameras']) == 10
	assert [s['id'] for s in body['sections']] == [
		'customer-intelligence',
		'service-queue',
		'kitchen-operations',
		'hygiene-compliance',
		'employee-monitoring',
		'staff-conduct',
	]


def test_elements_filter_by_camera(client):
	response = client.get('/api/elements', params={'camera': '11'})
	assert response.status_code == 200
	assert all('11' in e['cameras'] for e in response.json())


@pytest.mark.parametrize('element', catalogue.ELEMENTS, ids=lambda e: e.id)
def test_every_element_serves_data(client, element):
	response = client.get(f'/api/elements/{element.id}/data')
	assert response.status_code == 200
	body = response.json()
	assert body['element_id'] == element.id
	if element.value_kind is models.ValueKind.CLOCK_TIME:
		assert body['text'] is not None
	elif element.value_kind is models.ValueKind.DISTRIBUTION:
		assert body['buckets']
	else:
		assert body['scalar'] is not None
		assert body['series']


def test_data_is_stable_for_the_same_filters(client):
	first = client.get('/api/elements/footfall-entries/data').json()
	second = client.get('/api/elements/footfall-entries/data').json()
	assert first['series'] == second['series']


def test_data_moves_with_the_branch_filter(client):
	url = '/api/elements/footfall-entries/data'
	riyadh = client.get(url, params={'branch': 'riyadh-01'}).json()
	jeddah = client.get(url, params={'branch': 'jeddah-02'}).json()
	assert riyadh['series'] != jeddah['series']


def test_percent_elements_stay_in_gauge_range(client):
	body = client.get('/api/elements/table-occupancy-rate/data').json()
	assert 0 <= body['scalar']['value'] <= 100
	assert all(0 <= point['value'] <= 100 for point in body['series'])


def test_unknown_range_is_rejected(client):
	response = client.get(
		'/api/elements/queue-length/data', params={'range': 'decade'}
	)
	assert response.status_code == 400


def test_custom_range_needs_both_bounds(client):
	response = client.get(
		'/api/elements/queue-length/data', params={'range': 'custom'}
	)
	assert response.status_code == 400


def test_instances_carry_clips_from_the_element_cameras(client):
	response = client.get('/api/elements/phone-use-count/instances')
	assert response.status_code == 200
	log = response.json()
	assert log
	element = catalogue.ELEMENTS_BY_ID['phone-use-count']
	assert all(entry['camera_id'] in element.cameras for entry in log)
	assert all(entry['clip_url'].endswith('.mp4') for entry in log)
	timestamps = [entry['occurred_at'] for entry in log]
	assert timestamps == sorted(timestamps, reverse=True)


def test_elements_without_a_log_return_404(client):
	response = client.get('/api/elements/live-occupancy/instances')
	assert response.status_code == 404


def test_alert_feed_respects_the_limit(client):
	response = client.get('/api/alerts', params={'limit': 5})
	assert response.status_code == 200
	assert len(response.json()) == 5


def test_employees_report_a_timesheet(client):
	roster = client.get('/api/employees').json()
	assert len(roster) == len(catalogue.STAFF_ROSTER)
	assert all(0 < member['hours_worked'] < 24 for member in roster)


def test_unknown_element_returns_404(client):
	assert client.get('/api/elements/nope/data').status_code == 404
