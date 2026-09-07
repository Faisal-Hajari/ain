"""The generator, checked for the two mistakes that are silent.

It lives here rather than beside `scripts/compose_gen.py` because that is a
single-file PEP 723 script with no test environment of its own, and what it
actually exercises is this library: the generator validates cameras.yml
through `ain_analytics.config`, so that the compose file and the running
service can never disagree about which configs are legal. `scripts/` is on
the path via `pythonpath` in pyproject.toml.
"""

import pathlib

import pytest
import yaml

import compose_gen


@pytest.fixture(name='rendered')
def _rendered() -> str:
	"""The compose file the real cameras.yml produces."""
	return compose_gen.render(compose_gen.load_config())


def test_every_camera_gets_one_adapter(rendered):
	services = yaml.safe_load(rendered)['services']
	assert len(services) == len(compose_gen.load_config()['cameras'])


def test_camera_ids_are_quoted_in_the_generated_file(rendered):
	# `SOURCE_ID: 09` left bare reaches the adapter as `9`: PyYAML does not
	# quote it, because YAML 1.1 does not read it as a number, and Compose's
	# parser does. Every row that camera produces then lands under a
	# source_id the catalogue has never heard of, and the camera silently
	# contributes to nothing.
	for line in rendered.splitlines():
		if 'SOURCE_ID' in line:
			assert "'" in line or '"' in line, line


def test_source_ids_are_the_backend_ids_not_the_stream_paths(rendered):
	# The catalogue's '06' and MediaMTX's 'cam6' are two namespaces, and
	# cameras.yml is the one place they meet. Checked for every camera, so
	# this holds whichever ones the pipeline is configured for.
	cameras = compose_gen.load_config()['cameras']
	services = yaml.safe_load(rendered)['services']
	for camera_id, camera in cameras.items():
		adapter = services[f'savant-source-{camera_id}']['environment']
		assert adapter['SOURCE_ID'] == camera_id
		assert adapter['RTSP_URI'].endswith(f'/{camera["stream"]}')


def test_absolute_timestamps_are_on(rendered):
	# Without this, pts is stream-relative and resets on reconnect: no
	# stored row can be joined to a recording or to a HLS segment, and
	# every one of them is worthless.
	services = yaml.safe_load(rendered)['services']
	for name, service in services.items():
		assert service['environment']['USE_ABSOLUTE_TIMESTAMPS'] == 'True', name


def test_adapters_read_mediamtx_not_the_recordings(rendered):
	# Reading the mp4 files directly would be cheaper and would make browser
	# overlays permanently impossible: Savant and MediaMTX would each loop
	# the same file independently and drift apart within minutes.
	services = yaml.safe_load(rendered)['services']
	for name, service in services.items():
		assert service['environment']['RTSP_URI'].startswith(
			'rtsp://cameras:8554/'
		), name


def test_the_input_socket_is_not_pub_sub(rendered):
	# The sources carry H.264. PUB/SUB drops without backpressure, and a
	# dropped keyframe corrupts every frame after it.
	services = yaml.safe_load(rendered)['services']
	for name, service in services.items():
		assert service['environment']['ZMQ_ENDPOINT'].startswith(
			'dealer+connect:'
		), name


def test_the_generator_validates_what_the_service_will(tmp_path):
	# The generator used to carry its own copy of the geometry checks. It
	# now runs the service's loader, so a config this accepts is one
	# analytics-api will start on.
	path = tmp_path / 'cameras.yml'
	path.write_text(
		"cameras:\n  '03': {stream: cam3}\n"
		'zones:\n  bowtie:\n    parts:\n'
		"      - camera: '03'\n"
		'        points: [[0,0],[1,1],[1,0],[0,1]]\n'
	)
	with pytest.raises(compose_gen.ConfigError, match='bow-tie'):
		compose_gen.load_config(path)


def test_the_real_config_passes_that_validation():
	compose_gen.load_config()
