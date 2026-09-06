"""The threshold evaluator, which every alert in the product goes through."""

import pytest

from ain_analytics import events


def _series(*values: float) -> list[dict]:
	"""Builds a bucket series with one-minute buckets."""
	return [
		{'ts': f'2026-09-06T10:{index:02d}:00.000+00:00', 'mean': value}
		for index, value in enumerate(values)
	]


def test_a_run_is_bounded_by_the_buckets_that_breach():
	runs = list(events._runs(_series(1, 9, 9, 1), 'mean', 'above', 5))
	assert runs == [(1, 2, 9.0)]


def test_two_breaches_with_a_quiet_bucket_between_them_are_two_events():
	runs = list(events._runs(_series(9, 1, 9), 'mean', 'above', 5))
	assert [(first, last) for first, last, _ in runs] == [(0, 0), (2, 2)]


def test_a_breach_running_to_the_end_of_the_window_still_closes():
	runs = list(events._runs(_series(1, 9, 9), 'mean', 'above', 5))
	assert runs == [(1, 2, 9.0)]


def test_below_tracks_its_own_extreme():
	# The peak of a "below" run is its minimum: that is the worst it got.
	runs = list(events._runs(_series(9, 2, 1, 9), 'mean', 'below', 5))
	assert runs == [(1, 2, 1.0)]


def test_the_comparison_is_strict_at_the_threshold():
	assert not events._holds(5, 'above', 5)
	assert not events._holds(5, 'below', 5)
	assert events._holds(5.1, 'above', 5)


def test_event_ids_are_stable_across_repeats_of_the_same_query():
	first = events._event_id('congestion', 'occupancy', 'indoor', 12)
	again = events._event_id('congestion', 'occupancy', 'indoor', 12)
	other = events._event_id('congestion', 'occupancy', 'indoor', 13)
	assert first == again
	assert first != other


def test_an_unknown_metric_is_an_error(monkeypatch):
	with pytest.raises(events.UnknownMetricError):
		events.evaluate(
			client=None,
			metric='vibes',
			target='indoor',
			comparator='above',
			threshold=1,
			window=None,
		)
