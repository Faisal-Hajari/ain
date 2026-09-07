"""Rate-limited warnings, which are only useful if they resume."""

import logging

import pytest

from ain_analytics import throttle


@pytest.fixture(autouse=True)
def _clean():
	throttle.reset()
	yield
	throttle.reset()


@pytest.fixture(name='clock')
def _clock(monkeypatch):
	"""A monotonic clock the test moves by hand."""
	now = [1000.0]
	monkeypatch.setattr(throttle.time, 'monotonic', lambda: now[0])
	return now


def test_the_first_one_is_logged(caplog):
	with caplog.at_level(logging.WARNING):
		assert throttle.warn(logging.getLogger('t'), 'k', 'queue full')
	assert 'queue full' in caplog.text


def test_a_repeat_inside_the_period_is_not(clock, caplog):
	log = logging.getLogger('t')
	with caplog.at_level(logging.WARNING):
		throttle.warn(log, 'k', 'queue full')
		clock[0] += 59.0
		assert not throttle.warn(log, 'k', 'queue full')
	assert caplog.text.count('queue full') == 1


def test_it_resumes_after_the_period_and_says_what_it_swallowed(clock, caplog):
	"""The point of a period rather than a latch.

	A fault that clears and comes back an hour later is a second incident,
	and `warn_once` would have gone quiet for the life of the process.
	"""
	log = logging.getLogger('t')
	with caplog.at_level(logging.WARNING):
		throttle.warn(log, 'k', 'queue full')
		for _ in range(40_000):
			throttle.warn(log, 'k', 'queue full')
		clock[0] += 61.0
		assert throttle.warn(log, 'k', 'queue full')
	assert caplog.text.count('queue full') == 2
	assert '+40000 more in the last 60s' in caplog.text


def test_the_count_resets_with_each_line(clock, caplog):
	log = logging.getLogger('t')
	with caplog.at_level(logging.WARNING):
		throttle.warn(log, 'k', 'queue full')
		throttle.warn(log, 'k', 'queue full')
		clock[0] += 61.0
		throttle.warn(log, 'k', 'queue full')
		clock[0] += 61.0
		throttle.warn(log, 'k', 'queue full')
	assert '+1 more' in caplog.text
	# The second resumption swallowed nothing, so it says nothing about it.
	assert caplog.text.count('more in the last') == 1


def test_one_flood_does_not_hide_another_condition(clock, caplog):
	"""Distinct keys are throttled apart, or the loud one wins."""
	log = logging.getLogger('t')
	with caplog.at_level(logging.WARNING):
		for _ in range(100):
			throttle.warn(log, 'queue-full', 'queue full')
		assert throttle.warn(log, 'unknown-topic', 'no such topic')
	assert 'no such topic' in caplog.text


def test_format_arguments_are_applied(caplog):
	with caplog.at_level(logging.WARNING):
		throttle.warn(logging.getLogger('t'), 'k', 'kafka: %s at %d', 'full', 7)
	assert 'kafka: full at 7' in caplog.text
