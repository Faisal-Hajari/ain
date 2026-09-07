"""The settings file is the configuration contract, so it is pinned like one."""

import pydantic
import pytest

from ain_analytics import settings


def test_every_setting_has_a_default():
	"""The stack has to come up with an empty environment.

	A required setting means `docker compose up` on a fresh clone fails
	with a validation error instead of running, and every default here is
	the value that was hard-coded before this file existed.
	"""
	assert settings.Settings()  # no environment needed


def test_the_environment_names_are_the_ones_compose_sets(monkeypatch):
	"""Renaming a field must not silently orphan an env var.

	These are set in docker-compose.yml and in CI. A field renamed
	without its alias would read as unset - and unset means the default,
	which is a config change nobody wrote.
	"""
	for name, value, field in (
		('CLICKHOUSE_HOST', 'somewhere', 'clickhouse_host'),
		('KAFKA_BROKERS', 'broker:9092', 'kafka_brokers'),
		('AIN_CAMERAS_YML', '/tmp/x.yml', 'cameras_yml'),
		('AIN_S3_ENDPOINT', 'http://store:9000', 's3_endpoint'),
		('AIN_CLIP_MAX_SECONDS', '60', 'clip_max_seconds'),
		('LOGLEVEL', 'DEBUG', 'log_level'),
	):
		monkeypatch.setenv(name, value)
		assert str(getattr(settings.Settings(), field)) == value, name
		monkeypatch.delenv(name)


def test_a_test_can_override_without_touching_the_environment():
	"""Otherwise every test that needs a different value mutates os.environ."""
	assert settings.Settings(clip_max_seconds=7).clip_max_seconds == 7


def test_settings_are_frozen():
	"""Configuration read at startup and mutated at runtime is a bug source."""
	with pytest.raises(pydantic.ValidationError):
		settings.Settings().clip_max_seconds = 5


def test_durations_and_counts_say_what_they_are():
	"""`_EVENT_INTERVAL = 30` did not say seconds, buckets or objects.

	Anything that is a duration or a count carries its unit in its name,
	so a reader never has to go and find out.
	"""
	numeric = {
		name
		for name, field in settings.Settings.model_fields.items()
		if field.annotation in (int, float)
	}
	unitless = {
		name
		for name in numeric
		if not name.endswith(
			('_seconds', '_ms', '_days', '_rows', '_files', '_messages',
			 '_buckets', '_visits', '_places', '_partitions', '_port',
			 '_concurrency')
		)
	}
	assert not unitless, f'these numbers do not say what they are: {unitless}'
