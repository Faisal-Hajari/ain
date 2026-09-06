"""The HTTP surface the dashboard talks to.

Read routes are pure functions of the query string, so any replica can
answer any request. The alert-rule routes are the exception and say so
in `ain_backend.alerts`.
"""

import os
import urllib.parse
from typing import Annotated

import fastapi
from fastapi import responses
from fastapi.middleware import cors

from ain_backend import alerts
from ain_backend import analytics
from ain_backend import catalogue
from ain_backend import i18n
from ain_backend import models
from ain_backend import payloads

# The filters the frontend stacks onto every data request. UI state
# (`expanded`, `settings`, ...) also rides in the URL but is not sent,
# and anything unrecognised here is ignored rather than seeded on.
_FILTER_KEYS = ('branch', 'venue', 'range')

class Filters:
	"""The active filters, plus the seed they derive from.

	The seed excludes `lang` on purpose: switching language must relabel
	a card without moving its numbers.
	"""

	def __init__(self, request: fastapi.Request) -> None:
		self.locale = i18n.parse_locale(request.query_params.get('lang'))
		self.values = {
			key: request.query_params.get(key, '')
			for key in _FILTER_KEYS
			if request.query_params.get(key)
		}
		self.seed_key = urllib.parse.urlencode(sorted(self.values.items()))

	@property
	def range(self) -> str:
		"""The raw `range` filter, defaulting to today."""
		return self.values.get('range', 'today')

	@property
	def branch(self) -> str:
		"""The active branch."""
		return self.values.get('branch', 'olaya')

	@property
	def venue(self) -> str:
		"""The active venue type."""
		return self.values.get('venue', 'cafe')


Scope = Annotated[Filters, fastapi.Depends(Filters)]

app = fastapi.FastAPI(
	title='AIN dashboard API',
	version='0.2.0',
	summary='Layout, KPI payloads and alert rules for the AIN dashboard.',
)

app.add_middleware(
	cors.CORSMiddleware,
	allow_origins=os.environ.get('AIN_CORS_ORIGINS', '*').split(','),
	allow_methods=['GET', 'POST', 'DELETE'],
	allow_headers=['*'],
)


@app.get('/health')
def health() -> dict[str, str]:
	"""Reports that the service is up, and what is behind it."""
	return {
		'status': 'ok',
		'source': 'analytics' if analytics.configured() else 'dummy',
	}


@app.get('/api/dashboard/config', response_model_exclude_none=True)
def read_config(scope: Scope) -> models.DashboardConfig:
	"""Returns the whole navigation and layout for one language."""
	return catalogue.build_config(scope.locale)


@app.get('/api/elements/{element_id}', response_model_exclude_none=True)
def read_element(element_id: str, scope: Scope) -> models.ElementResponse:
	"""Returns one card's payload.

	Args:
		element_id: The catalogue id from the path.
		scope: The active filters.

	Returns:
		The payload, already shaped for the element's type.

	Raises:
		fastapi.HTTPException: The catalogue has no such element.
	"""
	try:
		return payloads.build_element(
			element_id, scope.seed_key, scope.locale, scope.range
		)
	except payloads.UnknownElementError as error:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown element: {element_id}'
		) from error


@app.get(
	'/api/elements/{element_id}/instances', response_model_exclude_none=True
)
def read_instances(element_id: str, scope: Scope) -> models.InstanceLog:
	"""Returns the occurrences behind one card.

	Args:
		element_id: The catalogue id from the path.
		scope: The active filters.

	Returns:
		The log. An element with nothing to show returns an empty list.

	Raises:
		fastapi.HTTPException: The catalogue has no such element.
	"""
	try:
		return payloads.build_instance_log(
			element_id, scope.seed_key, scope.locale, scope.range
		)
	except payloads.UnknownElementError as error:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown element: {element_id}'
		) from error


@app.get('/api/zones', response_model_exclude_none=True)
def read_zones() -> models.ZonesResponse:
	"""Returns the zone and line shapes drawn over the camera tiles.

	Returns:
		The geometry, normalised 0..1 against each camera's frame, or an
		empty document when no analytics service is wired up. This is
		configuration rather than a measurement, which is why it is not
		part of any element payload: an editor drags these, and nothing
		about that touches the GPU.

	Raises:
		fastapi.HTTPException: Never; an absent service is empty, not an
			error.
	"""
	body = analytics.get('/zones', {}) or {'zones': [], 'lines': []}
	return models.ZonesResponse.model_validate(body)


@app.get('/api/overlay', response_model_exclude_none=True)
def read_overlay(
	camera: str, start: str | None = None, end: str | None = None
) -> models.OverlayResponse:
	"""Returns the boxes to draw over one camera, for one short window.

	Args:
		camera: The camera id, as the catalogue names it.
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive. At most a minute after `start`.

	Returns:
		One entry per frame, in normalised coordinates. The browser
		fetches a window of these every few seconds and, on each frame,
		draws the one nearest `hls.playingDate` - the wall-clock instant
		of the frame actually on screen, which HLS carries as
		EXT-X-PROGRAM-DATE-TIME.

	Raises:
		fastapi.HTTPException: No analytics service is wired up, or it
			refused the window.
	"""
	body = analytics.get(
		'/overlay', {'camera': camera, 'start': start, 'end': end}
	)
	if body is None:
		raise fastapi.HTTPException(
			status_code=503, detail='no detections available'
		)
	return models.OverlayResponse.model_validate(body)


@app.get('/api/clips/{event_id}.mp4')
def read_clip(
	event_id: str, camera: str, start: str, end: str | None = None
) -> responses.Response:
	"""Streams the video behind one alert, boxes burnt in.

	Args:
		event_id: The occurrence, which names the file.
		camera: Which camera to cut from.
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive.

	Returns:
		An mp4. Unlike the live view these boxes are drawn into the
		frames: a file saved from here and opened in a player has to
		carry its own annotation.

	Raises:
		fastapi.HTTPException: There is no recording for that window -
			MediaMTX keeps a short one - or no analytics service.
	"""
	upstream = analytics.stream(
		f'/clips/{event_id}.mp4',
		{'camera': camera, 'start': start, 'end': end},
	)
	if upstream is None:
		raise fastapi.HTTPException(
			status_code=404, detail='no clip for that window'
		)
	def chunks():
		"""Yields the upstream body in blocks.

		Iterating an HTTP response directly yields LINES, which for a
		binary mp4 means a chunk per stray 0x0a - hundreds of thousands
		of them for a megabyte of video.
		"""
		try:
			while block := upstream.read(64 * 1024):
				yield block
		finally:
			upstream.close()

	return responses.StreamingResponse(
		chunks(), media_type='video/mp4',
		headers={
			'Content-Disposition': f'inline; filename="{event_id}.mp4"'
		},
	)


@app.get('/api/alerts/monitors', response_model_exclude_none=True)
def read_monitors(scope: Scope) -> models.AlertMonitorList:
	"""Returns every monitor an alert rule can be built on."""
	return alerts.list_monitors(scope.seed_key, scope.locale)


@app.get('/api/alerts/rules', response_model_exclude_none=True)
def read_rules(scope: Scope) -> models.AlertRuleList:
	"""Returns every stored rule, localised and evaluated at read time."""
	return alerts.list_rules(
		scope.locale,
		payloads.resolve_range(scope.range, catalogue.today()),
	)


@app.post(
	'/api/alerts/rules', status_code=201, response_model_exclude_none=True
)
def create_rule(
	draft: models.AlertRuleDraft, scope: Scope
) -> models.AlertRule:
	"""Stores one rule and returns the canonical record.

	Args:
		draft: The posted rule.
		scope: The active filters.

	Returns:
		The created rule, as the next read would return it.

	Raises:
		fastapi.HTTPException: The draft names an unknown monitor.
	"""
	try:
		return alerts.create_rule(
			draft, scope.locale, scope.branch, scope.venue
		)
	except alerts.UnknownMonitorError as error:
		raise fastapi.HTTPException(
			status_code=400,
			detail=f'unknown monitor: {draft.monitor_id}',
		) from error


@app.delete('/api/alerts/rules/{rule_id}', status_code=204)
def delete_rule(rule_id: str) -> responses.Response:
	"""Deletes one rule.

	Args:
		rule_id: The rule to remove.

	Returns:
		An empty 204, whether or not the rule was there. Delete is
		idempotent: the frontend re-reads the list either way.
	"""
	alerts.delete_rule(rule_id)
	return responses.Response(status_code=204)
