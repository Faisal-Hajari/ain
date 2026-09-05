"""Alert monitors and the rules built on them.

Everything else in this service is stateless and derived. Rules are the
exception: the frontend keeps no copy, so a created rule has to come
back from the next read. That store is a process-local dict here, which
is enough for a placeholder backend and wrong for a real one - it does
not survive a restart and two replicas would disagree.

TODO: move `RULES` to a database table.
"""

import dataclasses
import datetime
import uuid

from ain_backend import catalogue
from ain_backend import formatting
from ain_backend import i18n
from ain_backend import models
from ain_backend import payloads

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


RULES: dict[str, StoredRule] = {}


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


def localise(rule: StoredRule, locale: i18n.Locale) -> models.AlertRule:
	"""Renders a stored rule in one language.

	Args:
		rule: The language-neutral record.
		locale: The language to read it in.

	Returns:
		The rule as the frontend prints it, sentences included.
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
	return models.AlertRule(
		id=rule.id,
		monitor_id=rule.monitor_id,
		monitor_label=label,
		comparator=rule.comparator,
		threshold=rule.threshold,
		unit=unit,
		summary=summary,
		created_label=_created_label(rule.created_on, locale),
	)


def list_rules(locale: i18n.Locale) -> models.AlertRuleList:
	"""Returns every stored rule, localised at read time.

	Args:
		locale: The requested language.

	Returns:
		The rules, newest first. Scoping rules to a branch or a venue is
		still open, so the active filters do not narrow this list.
	"""
	return models.AlertRuleList(
		rules=[
			localise(rule, locale)
			for rule in sorted(
				RULES.values(),
				key=lambda rule: rule.created_on,
				reverse=True,
			)
		]
	)


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
	RULES[stored.id] = stored
	return localise(stored, locale)


def delete_rule(rule_id: str) -> bool:
	"""Deletes one rule, reporting whether it existed."""
	return RULES.pop(rule_id, None) is not None
