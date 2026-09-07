"""Kafka -> ClickHouse.

The Kafka sink adapter publishes `save_message_to_bytes(message)`: a
savant-rs binary blob keyed by source_id, not JSON. ClickHouse's Kafka table
engine reads JSONEachRow, Avro, Protobuf and CapnProto, and none of those is
this, so something has to deserialise. This is that something, and it is the
easiest part of the design to overlook.

Run it with `python -m ain_ingest`.
"""

import logging
import os
import signal
import sys
import time
from collections.abc import Iterator

import confluent_kafka
from savant_rs.utils.serialization import load_message_from_bytes

from ain_analytics import config #to track kafak topic and brokers
from ain_analytics import db #connection to clickhouse and getting table information
from ain_analytics import settings #every tunable, in one file
from ain_analytics import throttle #keeps a broker fault to one line a minute
_LOG = logging.getLogger('ain_ingest')

# Savant's "this object is not tracked" sentinel. Stored raw it is a 2e19
# outlier that poisons every ordering and every average that touches
# track_id, so it becomes 0 here, once, at the edge.
_UNTRACKED = 2**64 - 1

# ~750 rows/sec across ten cameras. Row-by-row inserts would create one part
# per row and the merger would never catch up; a batch per second is one part
# per second, which it does.
_OPTIONS = settings.get()

_running = True


def _stop(*_args: object) -> None:
	"""Asks the consume loop to finish the batch it is on and exit."""
	global _running
	_running = False


def frame_rows(payload: bytes) -> list[tuple]:
	"""Turns one Kafka message into ClickHouse rows.

	Args:
		payload: The savant-rs serialised message.

	Returns:
		One row per detected object, or an empty list for a message that
		carries no video frame - end-of-stream and shutdown messages ride
		the same topic.
	"""
	message = load_message_from_bytes(payload)
	if not message.is_video_frame():
		return []
	frame = message.as_video_frame()
	width, height = frame.width, frame.height
	if not width or not height:
		return []

	# pts is in time_base units and, because the source adapters run with
	# USE_ABSOLUTE_TIMESTAMPS=True, it is absolute rather than stream-
	# relative. That is the whole reason these rows can be joined to a
	# recording or to a HLS segment's EXT-X-PROGRAM-DATE-TIME.
	numerator, denominator = frame.time_base
	seconds = frame.pts * numerator / denominator

	rows = []
	for index, obj in enumerate(frame.get_all_objects()):
		box = obj.detection_box
		track_id = obj.track_id
		if track_id is None or track_id == _UNTRACKED:
			track_id = 0
		rows.append(
			(
				# Milliseconds, matching DateTime64(3). Passed as a number so
				# the driver does not go via a string and a timezone.
				round(seconds * 1000),
				frame.source_id,
				track_id,
				index,
				obj.label,
				float(obj.confidence or 0.0),
				# Normalised at ingest, not at read: the canvas is whatever
				# size the tile is and the video may be re-encoded at another
				# resolution later. Storing pixels means every consumer needs
				# the frame dimensions, and one of them will forget.
				box.xc / width,
				box.yc / height,
				box.width / width,
				box.height / height,
				message.seq_id,
			)
		)
	return rows


def _consume(consumer: confluent_kafka.Consumer) -> Iterator[list[tuple]]:
	"""Yields batches of rows, by size or by age, whichever comes first.

	Args:
		consumer: A subscribed consumer.

	Yields:
		A non-empty list of rows.
	"""
	batch: list[tuple] = []
	deadline = time.monotonic() + _OPTIONS.ingest_batch_seconds
	while _running:
		message = consumer.poll(0.2)
		if message is not None and message.error() is None:
			try:
				batch.extend(frame_rows(message.value()))
			except Exception:  # noqa: BLE001 - one bad message is not fatal
				_LOG.exception('undecodable message, skipped')
		elif message is not None:
			# Keyed by error code, so a flood of one does not hide the
			# first sight of another. The common one is
			# UNKNOWN_TOPIC_OR_PART - "the sink has not created the
			# topic yet" - which arrives on every poll and would
			# otherwise be five lines a second.
			error = message.error()
			throttle.warn(_LOG, error.code(), 'kafka: %s', error)

		expired = time.monotonic() >= deadline
		if batch and (len(batch) >= _OPTIONS.ingest_batch_rows or expired):
			yield batch
			batch = []
		if expired:
			deadline = time.monotonic() + _OPTIONS.ingest_batch_seconds
	if batch:
		yield batch


def main() -> int:
	"""Consumes the detection topic until told to stop.

	Returns:
		A process exit code.
	"""
	logging.basicConfig(
		level=_OPTIONS.log_level.upper(),
		format='%(asctime)s %(levelname)s %(name)s %(message)s',
	)
	signal.signal(signal.SIGTERM, _stop)
	signal.signal(signal.SIGINT, _stop)

	settings = config.get()
	client = db.client()
	consumer = confluent_kafka.Consumer(
		{
			'bootstrap.servers': settings.kafka_brokers,
			'group.id': _OPTIONS.kafka_group_id,
			'auto.offset.reset': 'latest',
			# Offsets are committed after the insert, not on a timer. That
			# makes this at-least-once, which the schema is built to
			# tolerate: occupancy is a uniq over track ids, dwell is
			# max(ts) - min(ts), and a crossing needs two distinct
			# positions, so a replayed row changes none of them and
			# ReplacingMergeTree eventually drops it. Committing on a timer
			# would make it at-MOST-once instead, and a restart would lose
			# whatever was in flight.
			'enable.auto.commit': False,
		}
	)
	consumer.subscribe([settings.kafka_topic])
	_LOG.info(
		'consuming %s from %s', settings.kafka_topic, settings.kafka_brokers
	)

	total = 0
	try:
		for batch in _consume(consumer):
			client.insert(db.TABLE, batch, column_names=list(db.COLUMNS))
			consumer.commit(asynchronous=True)
			total += len(batch)
			_LOG.debug('inserted %s rows (%s total)', len(batch), total)
	finally:
		consumer.close()
		_LOG.info('stopped after %s rows', total)
	return 0


if __name__ == '__main__':
	sys.exit(main())
