"""Checks the ingested-events path and its fallback.

No ClickHouse runs here, so `store` is stubbed: what matters is that a
row on the topic reaches the drilldown intact, that a producer cannot
break a card by inventing a field value, and that an empty store still
answers.
"""

import fastapi.testclient
import pytest

from ain_backend import main
from ain_backend import payloads
from ain_backend import store

FILTERS = {'branch': 'olaya', 'venue': 'cafe', 'range': 'today'}
ELEMENT = 'no-mask-count'


@pytest.fixture(name='client')
def client_fixture() -> fastapi.testclient.TestClient:
	"""Returns a client bound to the app."""
	return fastapi.testclient.TestClient(main.app)


def instances(client, lang: str = 'en') -> dict:
	"""Reads one alert card's drilldown."""
	response = client.get(
		f'/api/elements/{ELEMENT}/instances',
		params={**FILTERS, 'lang': lang},
	)
	assert response.status_code == 200
	return response.json()


def stub(monkeypatch, rows: list[dict]) -> None:
	"""Makes the event store answer with `rows`."""
	monkeypatch.setattr(
		store, 'recent_events', lambda *args, **kwargs: rows
	)


def row(**overrides) -> dict:
	"""Builds one row shaped the way `store.recent_events` returns it."""
	return {
		'timestamp': '19:30',
		'camera_id': '05',
		'severity': 'critical',
		'detail': '',
		'clip_url': '/api/clips/no-mask-count/0.mp4',
	} | overrides


def test_query_is_inert_without_a_configured_server():
	assert store.query('SELECT 1') == []


def test_ingested_events_win_over_generated_ones(client, monkeypatch):
	stub(monkeypatch, [row(), row(timestamp='08:05', severity='warn')])
	body = instances(client)
	assert body['total'] == 2
	first = body['instances'][0]
	assert first['timestamp'] == '19:30'
	assert first['camera'] == 'Camera 05'
	assert first['severity'] == 'critical'
	assert first['clipUrl'] == '/api/clips/no-mask-count/0.mp4'


def test_empty_detail_falls_back_to_the_localised_description(
	client, monkeypatch
):
	stub(monkeypatch, [row()])
	english = instances(client)['instances'][0]['detail']
	arabic = instances(client, 'ar')['instances'][0]['detail']
	assert english and arabic and english != arabic


def test_producer_cannot_break_a_card_with_a_bad_severity(
	client, monkeypatch
):
	stub(monkeypatch, [row(severity='catastrophic', clip_url='')])
	instance = instances(client)['instances'][0]
	assert 'severity' not in instance
	assert 'clipUrl' not in instance


def test_an_empty_store_still_answers(client, monkeypatch):
	stub(monkeypatch, [])
	body = instances(client)
	assert body['total'] == len(body['instances']) >= 1


def test_range_maps_to_a_lookback_for_every_resolved_key():
	keys = {
		payloads.resolve_range(value, payloads.catalogue.today())
		for value in ('today', '7d', '30d', 'nonsense', '2026-01-01')
	}
	assert keys <= payloads._RANGE_HOURS.keys()
