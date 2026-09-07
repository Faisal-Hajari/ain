"""The seam between savant-rs and ClickHouse.

Runs only where savant_rs is installed, which is the ingest image:

    docker compose run --rm --entrypoint pytest track-ingest -q tests

The wheel is not on PyPI, so the API image and a plain `uv run pytest`
skip these rather than fail.
"""

import pathlib
import pytest

pytest.importorskip('savant_rs')

from savant_rs.primitives import (  # noqa: E402
	IdCollisionResolutionPolicy,
	VideoFrame,
	VideoFrameContent,
	VideoObject,
)
from savant_rs.primitives.geometry import RBBox  # noqa: E402
from savant_rs.utils.serialization import save_message_to_bytes  # noqa: E402

from ain_ingest import ingest  # noqa: E402

# 2026-09-06T20:00:00Z, in nanoseconds. Absolute rather than
# stream-relative, which is what USE_ABSOLUTE_TIMESTAMPS buys.
_PTS_NS = 1_757_188_800_000_000_000
_WIDTH = 1280
_HEIGHT = 720


def _message(*objects: VideoObject) -> bytes:
	"""Serialises a frame the way the sink publishes it."""
	frame = VideoFrame(
		source_id='03',
		framerate='15/1',
		width=_WIDTH,
		height=_HEIGHT,
		content=VideoFrameContent.none(),
		codec='hevc',
		keyframe=True,
		time_base=(1, 1_000_000_000),
		pts=_PTS_NS,
	)
	for obj in objects:
		frame.add_object(obj, IdCollisionResolutionPolicy.Error)
	return save_message_to_bytes(frame.to_message())


def _person(
	object_id: int, box: RBBox, track_id: int | None = None
) -> VideoObject:
	"""One detection, as the module emits it."""
	return VideoObject(
		id=object_id,
		namespace='detector',
		label='person',
		detection_box=box,
		confidence=0.9,
		attributes=[],
		**({'track_id': track_id} if track_id is not None else {}),
	)


def test_coordinates_are_normalised_at_ingest():
	# Pixels would mean every consumer needs the frame dimensions, and one
	# of them will forget. Centre form, 0..1, matching cameras.yml and the
	# browser canvas.
	rows = ingest.frame_rows(
		_message(_person(1, RBBox(640.0, 360.0, 128.0, 288.0), track_id=7))
	)
	(_, _, _, _, _, _, xc, yc, width, height, _) = rows[0]
	assert (xc, yc) == (0.5, 0.5)
	assert width == pytest.approx(0.1)
	assert height == pytest.approx(0.4)


def test_the_timestamp_is_absolute_milliseconds():
	rows = ingest.frame_rows(
		_message(_person(1, RBBox(640.0, 360.0, 128.0, 288.0), track_id=7))
	)
	assert rows[0][0] == _PTS_NS // 1_000_000


def test_the_source_id_is_the_backend_camera_id():
	rows = ingest.frame_rows(
		_message(_person(1, RBBox(640.0, 360.0, 128.0, 288.0), track_id=7))
	)
	assert rows[0][1] == '03'


def test_an_untracked_object_becomes_track_zero():
	# Savant's sentinel is max-uint64. Stored raw it is a 2e19 outlier that
	# poisons every ordering and every average that touches track_id.
	rows = ingest.frame_rows(_message(_person(1, RBBox(1.0, 1.0, 8.0, 8.0))))
	assert rows[0][2] == 0
	assert rows[0][2] != ingest._UNTRACKED


def test_objects_in_one_frame_get_distinct_indices():
	# ORDER BY is also ReplacingMergeTree's dedup key, and Kafka is
	# at-least-once. Without a per-frame discriminator, several untracked
	# objects in one frame collapse into a single row on merge.
	rows = ingest.frame_rows(
		_message(
			_person(1, RBBox(100.0, 100.0, 40.0, 90.0)),
			_person(2, RBBox(700.0, 300.0, 40.0, 90.0)),
		)
	)
	assert sorted(row[3] for row in rows) == [0, 1]
	assert {row[2] for row in rows} == {0}


def test_a_message_carrying_no_frame_produces_no_rows():
	# End-of-stream and shutdown messages ride the same topic.
	from savant_rs.utils.serialization import Message

	assert ingest.frame_rows(save_message_to_bytes(Message.unknown('bye'))) == []


def test_inserts_are_durable_before_the_offset_moves():
	"""Otherwise the consumer commits an offset for rows still in memory.

	An insert that returns early plus an immediate commit is at-most-once,
	and the schema is built to tolerate the opposite.
	"""
	import inspect

	from ain_analytics import db

	assert "'async_insert': 0" in inspect.getsource(db.connect)
	# And the commit still follows the insert rather than running on a
	# timer. Read as text: importing ingest needs savant_rs, which only
	# exists in the ingest image.
	loop = (
		pathlib.Path(__file__).resolve().parent.parent / 'ain_ingest' / 'ingest.py'
	).read_text()
	assert loop.index('client.insert') < loop.index('consumer.commit')
	assert "'enable.auto.commit': False" in loop
