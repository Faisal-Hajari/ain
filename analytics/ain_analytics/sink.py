"""ZeroMQ out of the module, Kafka in.

This should have been a stock container. `savant-adapters-py` ships
`adapters.python.sinks.kafka_redis`, and in 0.6.x it is broken twice over:
it imports `savant.client.runner.sink`, which the image does not contain,
and the runner it is meant to use calls `Message.validate_seq_id()`, which
the Rust `Message` in the same image does not define. Both are upstream
packaging faults rather than anything about this deployment, and patching
past the first only reaches the second.

So this is the vendor's sink, minus the parts that do not apply: no Redis,
because the module encodes no frames and there is nothing to put in it, and
no frame-content handling for the same reason. The wire format is
deliberately unchanged - `save_message_to_bytes(message)` keyed by
source_id - so the topic still carries standard Savant messages and a stock
consumer could read it.

Run it with `python -m ain_analytics.sink`.
"""

import logging
import os
import signal
import sys

import confluent_kafka
from confluent_kafka import admin
from savant_rs import zmq
from savant_rs.utils.serialization import save_message_to_bytes

from ain_analytics import config

_LOG = logging.getLogger('ain_analytics.sink')

_ENDPOINT = os.environ.get(
	'ZMQ_ENDPOINT', 'sub+connect:ipc:///tmp/zmq-sockets/output-video.ipc'
)
# Long enough that an idle pipeline is not a busy loop, short enough that
# SIGTERM is answered promptly.
_RECEIVE_TIMEOUT_MS = 1000
_PARTITIONS = int(os.environ.get('KAFKA_CREATE_TOPIC_NUM_PARTITIONS', '4'))

_running = True


def _stop(*_args: object) -> None:
	"""Asks the relay loop to finish and exit."""
	global _running
	_running = False


def ensure_topic(brokers: str, topic: str) -> None:
	"""Creates the detection topic if the broker does not have it.

	Args:
		brokers: The bootstrap servers.
		topic: The topic to publish to.

	A broker with auto-creation off would otherwise accept nothing, and
	the consumer would sit on UNKNOWN_TOPIC_OR_PART forever.
	"""
	client = admin.AdminClient({'bootstrap.servers': brokers})
	if topic in client.list_topics(timeout=10).topics:
		return
	request = admin.NewTopic(
		topic, num_partitions=_PARTITIONS, replication_factor=1
	)
	for name, future in client.create_topics([request]).items():
		try:
			future.result()
			_LOG.info('created topic %s with %s partitions', name, _PARTITIONS)
		except Exception as error:  # noqa: BLE001 - a race is not a failure
			_LOG.info('topic %s not created: %s', name, error)


def main() -> int:
	"""Relays module output onto Kafka until told to stop.

	Returns:
		A process exit code.
	"""
	logging.basicConfig(
		level=os.environ.get('LOGLEVEL', 'INFO').upper(),
		format='%(asctime)s %(levelname)s %(name)s %(message)s',
	)
	signal.signal(signal.SIGTERM, _stop)
	signal.signal(signal.SIGINT, _stop)

	settings = config.get()
	ensure_topic(settings.kafka_brokers, settings.kafka_topic)
	producer = confluent_kafka.Producer(
		{
			'bootstrap.servers': settings.kafka_brokers,
			# The module publishes over PUB/SUB and never blocks, so the
			# only thing this queue protects is memory: if Kafka is down,
			# drop rather than grow.
			'queue.buffering.max.messages': 100_000,
			'linger.ms': 50,
		}
	)

	builder = zmq.ReaderConfigBuilder(_ENDPOINT)
	builder.with_receive_timeout(_RECEIVE_TIMEOUT_MS)
	reader = zmq.BlockingReader(builder.build())
	reader.start()
	_LOG.info(
		'relaying %s -> %s/%s',
		_ENDPOINT,
		settings.kafka_brokers,
		settings.kafka_topic,
	)

	relayed = 0
	try:
		while _running:
			result = reader.receive()
			if not isinstance(result, zmq.ReaderResultMessage):
				# Timeouts, blacklisted sources and prefix mismatches are
				# all "nothing to do", not errors.
				continue
			try:
				producer.produce(
					settings.kafka_topic,
					key=bytes(result.topic),
					value=save_message_to_bytes(result.message),
				)
			except BufferError:
				# The local queue is full, which means Kafka is not
				# keeping up. Dropping metadata is the right answer here:
				# the alternative is back-pressure onto a GPU pipeline
				# that cannot pause a live camera anyway.
				producer.poll(0)
				continue
			relayed += 1
			producer.poll(0)
	finally:
		reader.shutdown()
		producer.flush(10)
		_LOG.info('stopped after %s messages', relayed)
	return 0


if __name__ == '__main__':
	sys.exit(main())
