"""What each endpoint actually does, with no routing in it.

`api.py` is the HTTP surface: a decorator, a signature and one call. This is
the layer under it, and the split is not cosmetic - the work here is
testable by calling a function, while the same code inside a route body can
only be reached through a client and a URL.

These functions raise `fastapi.HTTPException` directly. That is deliberate:
translating a domain error into a status code is the job, and routing it
back through `api.py` would move a hundred lines of `except ... raise
HTTPException` into the file this split exists to keep thin. What is NOT
here is anything that decides how a number reads to a person - that is
`ain_backend`'s, in both languages.
"""

import datetime
import logging

import fastapi

from ain_analytics import config
from ain_analytics import db
from ain_api import clips
from ain_api import events as events_module
from ain_api import feeds
from ain_api import frames
from ain_api import models
from ain_api import objects
from ain_api import queries

_LOG = logging.getLogger(__name__)

# The default dwell histogram, in seconds: ten minutes, twenty, half an hour,
# forty-five, an hour. The caller can pass its own, because the caller is the
# one drawing the chart.
_DEFAULT_DWELL_EDGES = (0, 600, 1200, 1800, 2700, 3600)


def health(response: fastapi.Response) -> models.Health:
	"""Reports that the service is up and the database answers.

	Args:
		response: Used to answer 503 rather than 200 when the database
			is unreachable. A container that reports itself healthy
			while it cannot serve anything is a container nothing will
			ever restart.

	Returns:
		The status, the newest detection stored, and what the config
		declares.
	"""
	try:
		latest = queries.latest_ts(db.client())
	except Exception as error:  # noqa: BLE001 - reported, not raised
		response.status_code = 503
		return models.Health(status='degraded', detail=str(error))
	settings = config.get()
	return models.Health(
		status='ok',
		latest_detection=latest,
		zones=sorted(settings.zones),
		lines=sorted(settings.lines),
	)


def cameras() -> models.Cameras:
	"""Which cameras the pipeline is watching, and whether they publish.

	Returns:
		One entry per camera in cameras.yml. `live` is true when
		MediaMTX has its path ready - which under runOnDemand means a
		reader is attached, and the readers are the source adapters -
		and null when MediaMTX itself could not be reached.
	"""
	return models.Cameras(
		cameras=feeds.status(config.get(), feeds.ready_streams())
	)


def still(camera_id: str, stream: str) -> bytes:
	"""One JPEG from a camera, to draw zones against.

	Args:
		camera_id: The camera, for the error message.
		stream: Its MediaMTX path.

	Returns:
		The encoded frame.

	Raises:
		fastapi.HTTPException: The stream produced no frame in time.
	"""
	try:
		return frames.still(stream)
	except frames.FrameError as error:
		raise fastapi.HTTPException(
			status_code=503, detail=f'{camera_id}: {error}'
		) from error


def zones() -> models.Zones:
	"""Every zone and line, with the geometry to draw them.

	Returns:
		The shapes, normalised 0..1 against each camera's frame. This is
		what the browser overlay draws and what the editor drags - which
		is why none of it is in module.yml.
	"""
	settings = config.get()
	return models.Zones(
		version=config.version(),
		zones=[
			models.NamedGeometry(name=name, **zone.geometry())
			for name, zone in settings.zones.items()
		],
		lines=[
			models.NamedGeometry(name=name, **line.geometry())
			for name, line in settings.lines.items()
		],
	)


def save_zones(body: models.DrawnCamera) -> models.SavedGeometry:
	"""Writes one camera's zones and lines back to cameras.yml.

	Args:
		body: The camera and every shape on it. Not a diff - a shape
			deleted on the canvas is deleted here.

	Returns:
		The zone and line names that camera now contributes to.

	Raises:
		fastapi.HTTPException: 400 if the result would not load, 409 if
			the file changed since the page read it. Nothing is written
			in either case: the file is parsed before it is replaced.
	"""
	try:
		written = config.save(
			body.camera,
			[shape.model_dump() for shape in body.shapes],
			expect=body.version,
		)
	except config.StaleWriteError as error:
		raise fastapi.HTTPException(status_code=409, detail=str(error)) from error
	except config.ConfigError as error:
		raise fastapi.HTTPException(status_code=400, detail=str(error)) from error
	_LOG.info(
		'cameras.yml: camera %s now has zones %s and lines %s',
		body.camera, written['zones'], written['lines'],
	)
	return models.SavedGeometry(**written)


def occupancy(
	scope: queries.Window, area: config.Zone, interval: int, tz: str
) -> models.Occupancy:
	"""How many people stood in a zone, bucketed over time.

	Args:
		scope: The time range.
		area: The zone.
		interval: Bucket size in seconds.
		tz: An IANA timezone name, so a daily bucket starts at midnight
			there rather than at UTC's.

	Returns:
		The series plus its summary, in people.
	"""
	size = queries.bucket_seconds(scope, interval)
	buckets = queries.occupancy(db.client(), area, scope, size, tz)
	# Weighted by how long each bucket covers: the first and last of a
	# window are partial, and a plain average would weight a one-second
	# sliver like a five-minute interval.
	covered = sum(bucket['covered_seconds'] for bucket in buckets)
	person_seconds = sum(
		bucket['mean'] * bucket['covered_seconds'] for bucket in buckets
	)
	return models.Occupancy(
		zone=area.name,
		cameras=list(area.cameras),
		start=scope.start,
		end=scope.end,
		interval_seconds=size,
		buckets=buckets,
		latest=queries.current_occupancy(db.client(), area, scope),
		mean=round(person_seconds / covered, 2) if covered else 0.0,
		peak=max((bucket['peak'] for bucket in buckets), default=0),
	)


def dwell(
	scope: queries.Window,
	area: config.Zone,
	buckets: str,
	interval: int,
	tz: str,
) -> models.Dwell:
	"""How long each visit to a zone lasted.

	Args:
		scope: The time range.
		area: The zone.
		buckets: Histogram lower bounds in seconds, comma-separated.
		interval: Bucket size for the over-time series, in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		Per-part statistics and the histogram, in seconds.

	Raises:
		fastapi.HTTPException: A bucket edge is not a number.
	"""
	if buckets:
		try:
			edges = sorted({int(edge) for edge in buckets.split(',')})
		except ValueError as error:
			raise fastapi.HTTPException(
				status_code=400, detail=f'bad buckets: {buckets!r}'
			) from error
	else:
		edges = list(_DEFAULT_DWELL_EDGES)
	size = queries.bucket_seconds(scope, interval)
	result = queries.dwell(db.client(), area, scope, edges, size, tz)
	return models.Dwell(
		zone=area.name,
		cameras=list(area.cameras),
		start=scope.start,
		end=scope.end,
		**result,
	)


def footfall(
	scope: queries.Window, counter: config.Line, interval: int, tz: str
) -> models.Footfall:
	"""People crossing a counting line, in each direction.

	Args:
		scope: The time range.
		counter: The line.
		interval: Bucket size in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		The series plus its totals, in people.
	"""
	size = queries.bucket_seconds(scope, interval)
	buckets = queries.footfall(db.client(), counter, scope, size, tz)
	return models.Footfall(
		line=counter.name,
		cameras=[counter.camera],
		start=scope.start,
		end=scope.end,
		interval_seconds=size,
		buckets=buckets,
		**{
			'in': sum(bucket['in'] for bucket in buckets),
			'out': sum(bucket['out'] for bucket in buckets),
		},
	)


def events(
	scope: queries.Window,
	metric: models.Metric,
	target: str,
	comparator: models.Comparator,
	threshold: float,
	for_seconds: int,
	kind: str,
	interval: int | None,
	tz: str,
	basis: models.Basis,
	rising: str | None,
) -> models.Events:
	"""Evaluates one alert rule over one window.

	Args:
		scope: The time range.
		metric: What to measure.
		target: A zone name, or a line name when the metric is footfall.
		comparator: Which side of the threshold counts.
		threshold: People for a series metric, seconds for dwell.
		for_seconds: How long a series breach must hold. A visit metric
			ignores it: the visit's own length is the test.
		kind: What to label the results, so a named wrapper reads back
			as itself.
		interval: Bucket size for a series metric, in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.
		basis: What the threshold is a threshold OF.
		rising: A zone that must be growing across the run for it to
			count.

	Returns:
		The occurrences, each carrying the geometry it was raised on so
		the renderer needs no second lookup.

	Raises:
		fastapi.HTTPException: The metric, the target or the basis is
			unknown, or the basis needs a capacity the zone has not got.
	"""
	try:
		found = events_module.evaluate(
			db.client(),
			metric=metric,
			target=target,
			comparator=comparator,
			threshold=threshold,
			window=scope,
			for_seconds=for_seconds,
			kind=kind,
			interval=interval,
			tz=tz,
			basis=basis,
			rising=rising,
		)
	except events_module.UnknownMetricError as error:
		raise fastapi.HTTPException(
			status_code=400,
			detail=f'unknown metric: {metric}. Known: {list(events_module.METRICS)}',
		) from error
	except events_module.UnknownBasisError as error:
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'unknown threshold_of: {basis}. Known: '
				f'{list(events_module.BASES)}'
			),
		) from error
	except config.NoCapacityError as error:
		# Not a 404 and not a guess: the zone exists, and a percentage of
		# a capacity nobody declared has no value. Inventing one would put
		# a made-up number behind an alert.
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'zone {error.args[0]} declares no capacity, so a threshold '
				'cannot be a share of one'
			),
		) from error
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown zone or line: {target}'
		) from error
	return models.Events(
		start=scope.start,
		end=scope.end,
		count=len(found),
		events=[event.as_dict() for event in found],
	)


def overlay(scope: queries.Window, camera: str) -> models.Overlay:
	"""Every stored box for one camera over one short window.

	Args:
		scope: The time range.
		camera: The camera id, already known to exist.

	Returns:
		One entry per frame, each with its objects in normalised
		coordinates. The browser looks up the frame nearest
		`hls.playingDate` and draws it to a canvas sized to the video.

	Raises:
		fastapi.HTTPException: The window is longer than the cap. This
			is fetched per window of video, not per frame, and a caller
			who asks for a day OOMs the service.
	"""
	if scope.seconds > queries.OVERLAY_MAX_SECONDS:
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'window is {scope.seconds:.0f}s; the cap is '
				f'{queries.OVERLAY_MAX_SECONDS}s'
			),
		)
	return models.Overlay(
		camera=camera,
		start=scope.start,
		end=scope.end,
		frames=queries.overlay(db.client(), camera, scope),
	)


def ppe() -> models.Ppe:
	"""Reports that PPE compliance is not measurable yet.

	Returns:
		`unavailable`, never a count. A person detector cannot tell
		whether somebody is wearing gloves; that needs an attribute
		model over person crops, which is a second pipeline this stack
		does not run.
	"""
	return models.Ppe(reason='ppe_model_not_deployed')


def clip(
	event_id: str, camera: str, start: str, end: str | None
) -> models.Clip:
	"""Renders the video behind one event and says where to fetch it.

	Args:
		event_id: The event the clip belongs to, which names the object.
		camera: Which camera to cut from.
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive. Defaults to a fixed-length clip.

	Returns:
		A presigned link to the annotated mp4 and when it expires.
		Unlike the live view these boxes are burnt into the frames: a
		browser overlay is a rendering, and a file opened in VLC has to
		carry its own annotation.

	Raises:
		fastapi.HTTPException: The window is unusable, MediaMTX has no
			recording covering it, or the object store would not answer.
	"""
	from ain_api import deps

	scope = clips.clip_window(
		deps.moment(start, 'start')
		or datetime.datetime.now(datetime.timezone.utc),
		deps.moment(end, 'end'),
	)
	try:
		url, expires = clips.render(db.client(), event_id, camera, scope)
	except clips.ClipError as error:
		raise fastapi.HTTPException(status_code=404, detail=str(error)) from error
	except objects.StoreError as error:
		# 503, not 404: the clip is not missing, the store is down, and a
		# 404 would tell the dashboard to stop offering the button.
		raise fastapi.HTTPException(status_code=503, detail=str(error)) from error
	return models.Clip(url=url, expires_at=expires, seconds=scope.seconds)
