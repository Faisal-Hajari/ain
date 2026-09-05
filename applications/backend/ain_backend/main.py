"""The read-only HTTP API the dashboard front end talks to.

Every route answers from the static catalogue plus the deterministic
dummy layer. There are no writes: the services that feed the database
live elsewhere.
"""

import datetime
import os
from typing import Annotated

import fastapi
import pydantic
from fastapi.middleware import cors

from ain_backend import catalogue
from ain_backend import dummy
from ain_backend import models
from ain_backend import timeframes

_DEFAULT_ALERT_FEED_LIMIT = 25


class Filters(pydantic.BaseModel):
	"""The global controls that slice every panel."""

	branch: str = 'riyadh-01'
	venue_type: str = 'cafe'
	range: str = '7d'
	start: datetime.datetime | None = None
	end: datetime.datetime | None = None
	language: str = 'en'


class RequestScope(pydantic.BaseModel):
	"""The filters as the data layer consumes them."""

	window: models.TimeWindow
	key: str


def resolve_scope(
	filters: Annotated[Filters, fastapi.Query()],
) -> RequestScope:
	"""Resolves the query filters into a window and a seed key.

	Args:
		filters: The global filters as sent by the front end.

	Returns:
		The resolved scope shared by every data route.

	Raises:
		fastapi.HTTPException: The date range is not one we serve.
	"""
	try:
		window = timeframes.resolve(
			filters.range,
			datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
			filters.start,
			filters.end,
		)
	except timeframes.UnknownRangeError as error:
		raise fastapi.HTTPException(
			status_code=400, detail=str(error)
		) from error
	return RequestScope(
		window=window,
		key=f'{filters.branch}|{filters.venue_type}',
	)


Scope = Annotated[RequestScope, fastapi.Depends(resolve_scope)]


def _element_or_404(element_id: str) -> models.Element:
	"""Looks up a catalogue element.

	Args:
		element_id: The element's catalogue id.

	Returns:
		The element.

	Raises:
		fastapi.HTTPException: No element carries that id.
	"""
	element = catalogue.ELEMENTS_BY_ID.get(element_id)
	if element is None:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown element: {element_id}'
		)
	return element


app = fastapi.FastAPI(
	title='AIN dashboard API',
	version='0.1.0',
	summary='Read-only KPI feed for the AIN video-analytics dashboard.',
)

app.add_middleware(
	cors.CORSMiddleware,
	allow_origins=os.environ.get('AIN_CORS_ORIGINS', '*').split(','),
	allow_methods=['GET'],
	allow_headers=['*'],
)


@app.get('/health')
def health() -> dict[str, str]:
	"""Reports that the service is up."""
	return {'status': 'ok', 'source': 'dummy'}


@app.get('/api/catalogue')
def read_catalogue() -> models.Catalogue:
	"""Returns cameras, filters and every section in one call."""
	return catalogue.CATALOGUE


@app.get('/api/cameras')
def read_cameras() -> list[models.Camera]:
	"""Returns the camera layout as installed at the branch."""
	return catalogue.CAMERAS


@app.get('/api/filters')
def read_filters() -> models.FilterCatalogue:
	"""Returns the options behind the global filter controls."""
	return catalogue.FILTERS


@app.get('/api/sections')
def read_sections() -> list[models.Section]:
	"""Returns the catalogue sections and the elements they group."""
	return catalogue.SECTIONS


@app.get('/api/sections/{section_id}')
def read_section(section_id: str) -> models.Section:
	"""Returns one section.

	Args:
		section_id: The section's catalogue id.

	Returns:
		The section and its elements.

	Raises:
		fastapi.HTTPException: No section carries that id.
	"""
	section = catalogue.SECTIONS_BY_ID.get(section_id)
	if section is None:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown section: {section_id}'
		)
	return section


@app.get('/api/elements')
def read_elements(
	section: str | None = None,
	camera: str | None = None,
) -> list[models.Element]:
	"""Returns catalogue elements, optionally narrowed.

	Args:
		section: Keep only elements in this section.
		camera: Keep only elements derived from this camera.

	Returns:
		The matching elements, in catalogue order.
	"""
	elements = catalogue.ELEMENTS
	if section is not None:
		elements = [e for e in elements if e.section_id == section]
	if camera is not None:
		elements = [e for e in elements if camera in e.cameras]
	return elements


@app.get('/api/elements/{element_id}')
def read_element(element_id: str) -> models.Element:
	"""Returns one element's catalogue entry."""
	return _element_or_404(element_id)


@app.get('/api/elements/{element_id}/data')
def read_element_data(element_id: str, scope: Scope) -> models.ElementData:
	"""Returns the payload the front end draws for one element."""
	return dummy.element_data(
		_element_or_404(element_id), scope.window, scope.key
	)


@app.get('/api/elements/{element_id}/instances')
def read_element_instances(
	element_id: str, scope: Scope
) -> list[models.Instance]:
	"""Returns the instance log behind a clickable alert card.

	Args:
		element_id: The element's catalogue id.
		scope: The resolved global filters.

	Returns:
		One entry per occurrence, newest first.

	Raises:
		fastapi.HTTPException: The element has no instance log.
	"""
	element = _element_or_404(element_id)
	if not element.has_instances:
		raise fastapi.HTTPException(
			status_code=404,
			detail=f'{element_id} has no instance log',
		)
	return dummy.instances(element, scope.window, scope.key)


@app.get('/api/alerts')
def read_alert_feed(
	scope: Scope,
	limit: int = _DEFAULT_ALERT_FEED_LIMIT,
) -> list[models.Instance]:
	"""Returns the newest occurrences across every alerting element.

	Args:
		scope: The resolved global filters.
		limit: How many entries to return.

	Returns:
		The most recent instances, newest first.
	"""
	feed = []
	for element in catalogue.ELEMENTS:
		if not element.has_instances:
			continue
		feed.extend(dummy.instances(element, scope.window, scope.key))
	feed.sort(key=lambda entry: entry.occurred_at, reverse=True)
	return feed[:limit]


@app.get('/api/employees')
def read_employees(scope: Scope) -> list[models.Employee]:
	"""Returns the derived timesheet for the rostered staff."""
	return dummy.employees(scope.window, scope.key)
