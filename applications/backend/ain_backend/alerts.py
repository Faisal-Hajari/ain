"""Alert monitors, the rules built on them, and how those rules have done.

Everything else in this service is stateless and derived. Rules are the
exception: the frontend keeps no copy, so a created rule has to come back
from the next read. They live in `ain_backend.store`, which is SQLite -
not ClickHouse, which holds the detections but handles small mutable
row-level state badly.

Rules are evaluated **on read**. Opening the alerts page runs each one as
a query against the analytics service for the window in view. That costs
nothing, needs no scheduler, and keeps every read route a pure function
of its query string. Pushing a notification is a different service: it
needs a timer, a delivery channel, and dedupe so that one sustained
breach does not send forty messages.
"""

import dataclasses
import datetime
import uuid
from concurrent import futures

from ain_backend import catalogue
from ain_backend import formatting
from ain_backend import i18n
from ain_backend import live
from ain_backend import models
from ain_backend import payloads
from ain_backend import store

_COMPARATORS = {
	models.Comparator.ABOVE: i18n.ABOVE,
	models.Comparator.BELOW: i18n.BELOW,
}


class UnknownMonitorError(KeyError):
	"""No monitor in the catalogue carries the requested id."""


@dataclasses.dataclass(frozen=True)
class StoredRule:
	"""A rule as held by the store: language-neutral, and dated.

	Nothing localised is kept, so a rule created in Arabic reads back in
	English without a migration.
	"""

	id: str
	monitor_id: str
	comparator: models.Comparator
	threshold: float
	created_on: datetime.date
	branch: str
	venue: str


def _stored(row) -> StoredRule:
	"""Reads one database row back into a rule."""
	return StoredRule(
		id=row['id'],
		monitor_id=row['monitor_id'],
		comparator=models.Comparator(row['comparator']),
		threshold=row['threshold'],
		created_on=datetime.date.fromisoformat(row['created_on']),
		branch=row['branch'],
		venue=row['venue'],
	)


def _monitor_spec(monitor_id: str) -> catalogue.ElementSpec:
	"""Looks up a monitor.

	Args:
		monitor_id: The element id a rule watches.

	Returns:
		The element spec.

	Raises:
		UnknownMonitorError: The id is not a monitor an alert can watch.
	"""
	for spec in catalogue.monitor_elements():
		if spec.id == monitor_id:
			return spec
	raise UnknownMonitorError(monitor_id)


def list_monitors(
	seed_key: str, locale: i18n.Locale
) -> models.AlertMonitorList:
	"""Builds everything the alert builder can watch.

	Args:
		seed_key: The filters, language excluded, as a stable key.
		locale: The requested language.

	Returns:
		One monitor per numeric element, each with the 30-day average
		the threshold field is prefilled from.
	"""
	monitors = []
	for spec in catalogue.monitor_elements():
		trend, average = payloads.monthly_trend(spec, seed_key, locale)
		monitors.append(
			models.AlertMonitor(
				id=spec.id,
				label=spec.title.get(locale),
				unit=spec.unit.get(locale) if spec.unit else None,
				monthly_average=formatting.format_value(
					average, spec.value_format, locale
				),
				monthly_average_value=average,
				trend=trend,
			)
		)
	return models.AlertMonitorList(monitors=monitors)


def _created_label(
	created_on: datetime.date, locale: i18n.Locale
) -> str:
	"""Says when a rule was made, in words."""
	if created_on == catalogue.today():
		return i18n.CREATED_TODAY.get(locale)
	return f'{i18n.CREATED_ON.get(locale)} {created_on.isoformat()}'


def _status(
	count: int | None, locale: i18n.Locale
) -> tuple[str | None, models.Severity | None]:
	"""Turns a breach count into the sentence and colour a row prints.

	Args:
		count: How many times the rule fired, or None if it could not be
			evaluated.
		locale: The requested language.

	Returns:
		The label and the severity, or (None, None) when the count is
		unknown. Unknown is not zero: "we did not check" and "it did not
		happen" must not read the same.
	"""
	if count is None:
		return None, None
	if count == 0:
		return i18n.NOT_FIRED.get(locale), models.Severity.OK
	if count == 1:
		return i18n.FIRED_ONCE.get(locale), models.Severity.WARN
	return (
		i18n.FIRED_TIMES.get(locale).format(count=count),
		formatting.count_severity(count),
	)


def localise(
	rule: StoredRule,
	locale: i18n.Locale,
	range_key: str = 'today',
) -> models.AlertRule:
	"""Renders a stored rule in one language, and evaluates it.

	Args:
		rule: The language-neutral record.
		locale: The language to read it in.
		range_key: The window to evaluate the rule over.

	Returns:
		The rule as the frontend prints it, sentences included, with how
		many times it fired over that window when there is a pipeline
		behind its monitor to ask.
	"""
	spec = catalogue.ELEMENTS_BY_ID.get(rule.monitor_id)
	label = spec.title.get(locale) if spec else rule.monitor_id
	unit = spec.unit.get(locale) if spec and spec.unit else None
	threshold = (
		formatting.format_value(
			rule.threshold, spec.value_format, locale
		)
		if spec
		else str(rule.threshold)
	)
	comparator = _COMPARATORS[rule.comparator].get(locale)
	summary = f'{comparator} {threshold}'
	if unit:
		summary = f'{summary} {unit}'
	breaches = (
		live.breaches(spec, rule.comparator.value, rule.threshold, range_key)
		if spec
		else None
	)
	status_label, severity = _status(breaches, locale)
	return models.AlertRule(
		id=rule.id,
		monitor_id=rule.monitor_id,
		monitor_label=label,
		comparator=rule.comparator,
		threshold=rule.threshold,
		unit=unit,
		summary=summary,
		created_label=_created_label(rule.created_on, locale),
		breaches=breaches,
		status_label=status_label,
		severity=severity,
	)


def list_rules(
	locale: i18n.Locale, range_key: str = 'today'
) -> models.AlertRuleList:
	"""Returns every stored rule, localised and evaluated at read time.

	Args:
		locale: The requested language.
		range_key: The window to evaluate each rule over.

	Returns:
		The rules, newest first. Scoping rules to a branch or a venue is
		still open, so the active filters do not narrow this list.
	"""
	rules = [_stored(row) for row in store.rows()]
	if not rules:
		return models.AlertRuleList(rules=[])
	# Evaluated side by side, not one after another. Each rule is its own
	# query against the analytics service, and ten of them in series is ten
	# times the latency against a client that gives up long before that -
	# which reads as every rule being unevaluable rather than slow.
	with futures.ThreadPoolExecutor(max_workers=min(8, len(rules))) as pool:
		localised = list(
			pool.map(lambda rule: localise(rule, locale, range_key), rules)
		)
	return models.AlertRuleList(rules=localised)


def create_rule(
	draft: models.AlertRuleDraft,
	locale: i18n.Locale,
	branch: str,
	venue: str,
) -> models.AlertRule:
	"""Validates and stores one rule.

	Args:
		draft: What the builder posted.
		locale: The language to return the created record in.
		branch: The branch filter active when it was created.
		venue: The venue filter active when it was created.

	Returns:
		The canonical record, localised.

	Raises:
		UnknownMonitorError: The draft names something unwatchable.
	"""
	_monitor_spec(draft.monitor_id)
	stored = StoredRule(
		id=str(uuid.uuid4()),
		monitor_id=draft.monitor_id,
		comparator=draft.comparator,
		threshold=draft.threshold,
		created_on=catalogue.today(),
		branch=branch,
		venue=venue,
	)
	store.insert(
		stored.id,
		stored.monitor_id,
		stored.comparator.value,
		stored.threshold,
		stored.created_on,
		stored.branch,
		stored.venue,
	)
	return localise(stored, locale)


def delete_rule(rule_id: str) -> bool:
	"""Deletes one rule, reporting whether it existed."""
	return store.delete(rule_id)
