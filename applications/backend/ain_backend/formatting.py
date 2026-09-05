"""Formatting and judgement - the two things the frontend refuses to do.

Values leave here as display strings, and every "is this good news?"
call is made here rather than inferred downstream from a number.
"""

import enum
import random

from ain_backend import i18n
from ain_backend import models


class ValueFormat(enum.StrEnum):
	"""How an element's numbers are turned into display strings."""

	COUNT = 'count'
	PEOPLE = 'people'
	DURATION = 'duration'
	HOURS = 'hours'
	PERCENT = 'percent'


def format_duration(minutes: float, locale: i18n.Locale) -> str:
	"""Renders a duration in minutes as "4m 49s" / "4 د 49 ث"."""
	whole = int(minutes)
	seconds = round((minutes - whole) * 60)
	if seconds == 60:
		whole, seconds = whole + 1, 0
	if locale is i18n.Locale.AR:
		return f'{whole} د {seconds} ث'
	return f'{whole}m {seconds}s'


def format_hours(minutes: float, locale: i18n.Locale) -> str:
	"""Renders a long duration as "7h 8m" / "7 س 8 د"."""
	hours = int(minutes // 60)
	remainder = round(minutes - hours * 60)
	if remainder == 60:
		hours, remainder = hours + 1, 0
	if locale is i18n.Locale.AR:
		return f'{hours} س {remainder} د'
	return f'{hours}h {remainder}m'


def format_value(
	value: float, value_format: ValueFormat, locale: i18n.Locale
) -> str:
	"""Renders one number the way its element is read.

	Args:
		value: The raw number.
		value_format: The element's format, from the catalogue.
		locale: The requested language.

	Returns:
		A display string the frontend prints unchanged.
	"""
	if value_format is ValueFormat.DURATION:
		return format_duration(value, locale)
	if value_format is ValueFormat.HOURS:
		return format_hours(value, locale)
	if value_format is ValueFormat.PERCENT:
		return f'{round(value)}%'
	return str(round(value))


def format_percent_change(change: float) -> str:
	"""Renders a percentage change with an explicit sign."""
	rounded = round(change)
	return f'+{rounded}%' if rounded > 0 else f'{rounded}%'


def _direction(change: float) -> models.Direction:
	"""Picks the glyph for a change."""
	if change > 0:
		return models.Direction.UP
	if change < 0:
		return models.Direction.DOWN
	return models.Direction.FLAT


def _sentiment(change: float, is_alert: bool) -> models.Severity:
	"""Decides whether a change is good news.

	Args:
		change: The percentage change over the window.
		is_alert: Whether the element counts occurrences.

	Returns:
		The severity that colours the delta pill. A rising alert count is
		bad; a falling monitor is what a monitor is watched for.
	"""
	if is_alert:
		return (
			models.Severity.CRITICAL if change > 0 else models.Severity.OK
		)
	return models.Severity.WARN if change < 0 else models.Severity.OK


def delta_between(
	first: float, last: float, is_alert: bool
) -> models.Delta:
	"""Builds the delta pill for a series that ran first -> last.

	Args:
		first: The window's opening value.
		last: The window's closing value.
		is_alert: Whether the element counts occurrences.

	Returns:
		The formatted change, its glyph and its sentiment.
	"""
	change = 0.0 if first == 0 else ((last - first) / first) * 100
	return models.Delta(
		label=format_percent_change(change),
		direction=_direction(change),
		sentiment=_sentiment(change, is_alert),
	)


def rolled_severity(rand: random.Random) -> models.Severity:
	"""Draws a plausible severity for a dummy element."""
	roll = rand.random()
	if roll > 0.88:
		return models.Severity.CRITICAL
	if roll > 0.65:
		return models.Severity.WARN
	return models.Severity.OK


def gauge_severity(value: float) -> models.Severity:
	"""Judges a 0-100 gauge reading."""
	if value > 90:
		return models.Severity.CRITICAL
	if value > 75:
		return models.Severity.WARN
	return models.Severity.OK
