"""Every environment variable the analytics services read, in one place.

There is no second place. A tunable that lives as a bare number halfway down
a module is a tunable nobody knows exists until it is wrong in production,
and `os.environ.get` scattered across nine files is a configuration surface
you can only discover by grepping. Both were true here.

Two rules this file follows:

* **The name carries the unit.** `_EVENT_INTERVAL = 30` does not say whether
  it is seconds, buckets or objects, and the reader has to go and find out.
  Every duration here ends in `_seconds` or `_ms`, every count in `_rows`,
  `_files` or `_messages`.
* **The default is the value that was hard-coded before**, so importing this
  changed no behaviour. Where a default is a judgement rather than a
  measurement, the field says whose judgement and why.

Read it as `settings.get()`, which is cached. Tests that need a different
value construct `Settings(...)` directly rather than reaching for monkeypatch
on os.environ.
"""

import functools
import pathlib

import pydantic
import pydantic_settings


class Settings(pydantic_settings.BaseSettings):
	"""The whole configurable surface of the analytics services."""

	model_config = pydantic_settings.SettingsConfigDict(
		# The variable names predate this file and are set by
		# docker-compose.yml, so they are declared explicitly per field
		# rather than derived from a prefix. Case-insensitive matching is
		# pydantic-settings' default and is what makes `AIN_RTSP_URL` find
		# a field named for it.
		extra='ignore',
		frozen=True,
		# Both names work: the alias is what the environment sets, the
		# field name is what a test passes. Without this a test's keyword
		# argument is silently ignored and the environment wins - which is
		# exactly the bug that makes a settings object untestable.
		populate_by_name=True,
	)

	# ---------------------------------------------------------- storage --
	clickhouse_host: str = pydantic.Field('clickhouse', alias='CLICKHOUSE_HOST')
	clickhouse_port: int = pydantic.Field(8123, alias='CLICKHOUSE_PORT')
	clickhouse_user: str = pydantic.Field('ain', alias='CLICKHOUSE_USER')
	clickhouse_password: str = pydantic.Field('ain', alias='CLICKHOUSE_PASSWORD')
	clickhouse_database: str = pydantic.Field('default', alias='CLICKHOUSE_DATABASE')

	# ------------------------------------------------------------ kafka --
	# None rather than a default, because cameras.yml may name the broker
	# and the environment has to win over it without this file being able to
	# tell "unset" from "set to the same thing as the default".
	kafka_brokers: str | None = pydantic.Field(None, alias='KAFKA_BROKERS')
	kafka_topic: str | None = pydantic.Field(None, alias='KAFKA_TOPIC')
	kafka_group_id: str = pydantic.Field('ain-track-ingest', alias='KAFKA_GROUP_ID')
	kafka_topic_partitions: int = pydantic.Field(
		4, alias='KAFKA_CREATE_TOPIC_NUM_PARTITIONS'
	)
	# The only thing this queue protects is memory: the module publishes
	# over PUB/SUB and never blocks, so if Kafka is down the choice is drop
	# or grow.
	kafka_queue_max_messages: int = pydantic.Field(
		100_000, alias='KAFKA_QUEUE_MAX_MESSAGES'
	)

	# ----------------------------------------------------------- geometry -
	cameras_yml: pathlib.Path = pydantic.Field(
		pathlib.Path('/src/config/cameras.yml'), alias='AIN_CAMERAS_YML'
	)
	# Two decimals is ~13px on a 1280-wide frame, a tenth of a person, and
	# is what every polygon in the checked-in file already uses.
	geometry_decimal_places: int = pydantic.Field(2, alias='AIN_GEOMETRY_DECIMALS')

	# ------------------------------------------------------------ ingest --
	ingest_batch_rows: int = pydantic.Field(1000, alias='AIN_INGEST_BATCH_ROWS')
	ingest_batch_seconds: float = pydantic.Field(
		1.0, alias='AIN_INGEST_BATCH_SECONDS'
	)

	# -------------------------------------------------------------- sink --
	zmq_endpoint: str = pydantic.Field(
		'sub+connect:ipc:///tmp/zmq-sockets/output-video.ipc', alias='ZMQ_ENDPOINT'
	)
	# Long enough that an idle pipeline is not a busy loop, short enough
	# that SIGTERM is answered promptly.
	zmq_receive_timeout_ms: int = pydantic.Field(1000, alias='AIN_ZMQ_TIMEOUT_MS')

	# ---------------------------------------------------------- upstream --
	mediamtx_url: str = pydantic.Field('http://cameras:9997', alias='AIN_MEDIAMTX_URL')
	playback_url: str = pydantic.Field('http://cameras:9996', alias='AIN_PLAYBACK_URL')
	rtsp_url: str = pydantic.Field('rtsp://cameras:8554', alias='AIN_RTSP_URL')
	mediamtx_timeout_seconds: float = pydantic.Field(
		3, alias='AIN_MEDIAMTX_TIMEOUT'
	)
	# How long a camera's recording horizon is trusted. Asking MediaMTX per
	# camera per request is five round trips behind one caller.
	horizon_ttl_seconds: float = pydantic.Field(20, alias='AIN_HORIZON_TTL')

	# ------------------------------------------------------------ frames --
	# Long enough to open an RTSP session and decode to a keyframe; short
	# enough that a dead camera does not hold the request open.
	frame_timeout_seconds: float = pydantic.Field(15, alias='AIN_FRAME_TIMEOUT')
	frame_ttl_seconds: float = pydantic.Field(5, alias='AIN_FRAME_TTL')

	# ------------------------------------------------------------- clips --
	# Twenty minutes, because a clip has to be able to show the thing it is
	# evidence of: a long-wait alert fires on a queue wait measured in
	# minutes, and a two-minute cap cannot contain one.
	clip_max_seconds: int = pydantic.Field(1200, alias='AIN_CLIP_MAX_SECONDS')
	clip_default_seconds: int = pydantic.Field(20, alias='AIN_CLIP_DEFAULT_SECONDS')
	# Rendering decodes, redraws and re-encodes on the CPU, on the same host
	# that is running the transcodes and the GPU pipeline. Two at a time
	# keeps a burst of alert clicks from starving the thing the clips are of.
	clip_concurrency: int = pydantic.Field(2, alias='AIN_CLIP_CONCURRENCY')

	# ------------------------------------------------------- object store -
	s3_endpoint: str = pydantic.Field('http://minio:9000', alias='AIN_S3_ENDPOINT')
	# What the BROWSER can reach, which is not what this container can: a
	# presigned URL is signed for one host, so signing with the internal
	# name produces links only the internal network can open.
	s3_public_endpoint: str = pydantic.Field(
		'http://localhost:9000', alias='AIN_S3_PUBLIC_ENDPOINT'
	)
	s3_bucket: str = pydantic.Field('ain-clips', alias='AIN_S3_BUCKET')
	s3_access_key: str = pydantic.Field('ain', alias='AIN_S3_ACCESS_KEY')
	s3_secret_key: str = pydantic.Field('ainsecret', alias='AIN_S3_SECRET_KEY')
	s3_region: str = pydantic.Field('us-east-1', alias='AIN_S3_REGION')
	# The bucket expires objects on this, so nothing here has to prune. It
	# matches the recording retention: a clip that outlives the video it was
	# cut from is a clip nobody can re-render.
	clip_retention_days: int = pydantic.Field(1, alias='AIN_CLIP_RETENTION_DAYS')
	clip_link_ttl_seconds: int = pydantic.Field(3600, alias='AIN_CLIP_LINK_TTL')

	# ----------------------------------------------------------- queries --
	# A chart nobody can read, and a query that makes the browser chew a
	# megabyte of JSON to draw it.
	max_buckets: int = pydantic.Field(5000, alias='AIN_MAX_BUCKETS')
	# The tracker reuses ids, so one id is not one visit. A gap longer than
	# this splits it - without it a table shows a 46-minute sitting that
	# was four people.
	visit_gap_ms: int = pydantic.Field(5000, alias='AIN_VISIT_GAP_MS')
	max_visits: int = pydantic.Field(20_000, alias='AIN_MAX_VISITS')
	overlay_max_seconds: int = pydantic.Field(60, alias='AIN_OVERLAY_MAX_SECONDS')
	overlay_max_rows: int = pydantic.Field(50_000, alias='AIN_OVERLAY_MAX_ROWS')
	# Buckets finer than this make an event out of one person walking past.
	event_bucket_seconds: int = pydantic.Field(30, alias='AIN_EVENT_BUCKET_SECONDS')
	# Milliseconds to add to a detection's timestamp when it is served for
	# DRAWING - the overlay and the burnt-in clip boxes - to line it up with
	# the video. Zero because the cause was fixed rather than compensated
	# for: the adapters used to anchor their clocks to a stream that was
	# still starting, which put every box 3.5s ahead of its frame, and they
	# now wait for the stream to settle. What is left is real pipeline
	# latency, under half a second, and measurable at any time with
	# `python -m ain_api.calibrate`. It does not touch the stored rows or
	# any aggregate: a constant shift changes no five-minute bucket.
	overlay_clock_offset_ms: int = pydantic.Field(
		0, alias='AIN_OVERLAY_CLOCK_OFFSET_MS'
	)

	# ----------------------------------------------------------- service --
	cors_origins: str = pydantic.Field('*', alias='AIN_CORS_ORIGINS')
	log_level: str = pydantic.Field('INFO', alias='LOGLEVEL')
	# One line per condition per this, rather than five a second or one for
	# the life of the process.
	warn_period_seconds: float = pydantic.Field(60, alias='AIN_WARN_PERIOD')

	@property
	def cors_origin_list(self) -> list[str]:
		"""The CORS origins as the middleware wants them."""
		return [origin.strip() for origin in self.cors_origins.split(',')]


@functools.cache
def get() -> Settings:
	"""The process-wide settings, read once from the environment."""
	return Settings()
