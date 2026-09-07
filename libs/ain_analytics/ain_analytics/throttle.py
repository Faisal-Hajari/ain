"""Warnings for conditions that repeat faster than anybody can read them.

Both ends of the Kafka hop have one. The consumer sees UNKNOWN_TOPIC_OR_PART
on every poll until the sink creates the topic; the producer's local queue
fills at whatever rate the module is emitting, which is around a hundred
messages a second. Logged unconditionally either one is a wall of identical
lines that buries everything else in the container log.

Logging it once and never again is the other failure: a burst that clears and
returns an hour later is a second incident, and a process that decided at
startup it had already mentioned this will not say so. That is why this is a
period rather than a latch - and why the line carries how many occurrences it
swallowed, since "dropping detections" and "dropping 40,000 detections a
minute" are different problems.
"""

import logging
import time

# A minute. Long enough that a steady fault is one line a minute instead of a
# wall; short enough that two bursts an hour apart read as two events.
PERIOD_SECONDS = 60.0

_last: dict[object, float] = {}
_suppressed: dict[object, int] = {}


def warn(
	log: logging.Logger,
	key: object,
	message: str,
	*args: object,
	period: float = PERIOD_SECONDS,
) -> bool:
	"""Warns at most once per key per period, counting what it swallowed.

	Args:
		log: The logger to warn on.
		key: What makes two occurrences the same condition - a Kafka error
			code, a reason string, anything hashable. Distinct keys are
			throttled independently, so a flood of one does not hide the
			first occurrence of another.
		message: A %-style format string.
		*args: Its arguments.
		period: Seconds between lines for one key.

	Returns:
		Whether it logged, for a caller that wants to count the lines.
	"""
	now = time.monotonic()
	previous = _last.get(key)
	if previous is not None and now - previous < period:
		_suppressed[key] = _suppressed.get(key, 0) + 1
		return False

	_last[key] = now
	swallowed = _suppressed.pop(key, 0)
	# Formatted here rather than handed to the logger lazily: the decision to
	# log has already been made, and the suffix has to join the message.
	text = message % args if args else message
	if swallowed:
		text += f' (+{swallowed} more in the last {int(period)}s)'
	log.warning(text)
	return True


def reset() -> None:
	"""Forgets every key. For tests, and for a process that restarts a loop."""
	_last.clear()
	_suppressed.clear()
