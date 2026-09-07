"""The HTTP surface `ain_backend` reads.

Routing only. Every handler here is a decorator, a signature and one call
into `service`, which is where the work is - a route body is the one place
in a Python service that cannot be called from a test without a URL, so
nothing that can live anywhere else lives in it.

Two rules hold across the whole surface, and both are load-bearing:

* **Numbers and units, never strings a human reads.** No formatted
  durations, no severities, no sentences. The product ships English and
  Arabic with RTL, and Arabic duration and number formatting is exactly
  where a second formatting layer rots. `ain_backend` owns all of it.
* **Zones, not cameras.** A caller asks for `zone=indoor`. Which cameras
  compose it, and what polygon each contributes, stops in cameras.yml.

Conventions, fixed on day one because they are invisible when wrong:
`start` is inclusive and `end` exclusive; every timestamp is ISO 8601 with
an explicit UTC offset, matching both `DateTime64(3, 'UTC')` and the HLS
`EXT-X-PROGRAM-DATE-TIME` the browser lines boxes up against; and an
omitted `end` means "the newest data there is", not "now" - the pipeline
runs a second or two behind and answering "now" hands back a trailing
bucket that is empty for no reason a reader can see.
"""

import fastapi
from fastapi.middleware import cors

from ain_analytics import config
from ain_analytics import settings

from ain_api import deps
from ain_api import models
from ain_api import service

_OPTIONS = settings.get()

app = fastapi.FastAPI(
	title='AIN analytics API',
	version='0.1.0',
	summary='Occupancy, dwell, footfall and threshold events over ClickHouse.',
)

app.add_middleware(
	cors.CORSMiddleware,
	allow_origins=_OPTIONS.cors_origin_list,
	# The geometry editor is a separate service on a separate origin, and it
	# writes: it is the only reason anything but GET is allowed here.
	allow_methods=['GET', 'PUT'],
	allow_headers=['*'],
)


@app.get('/health')
def health(response: fastapi.Response) -> models.Health:
	"""Whether the service is up and the database answers."""
	return service.health(response)


@app.get('/cameras')
def read_cameras() -> models.Cameras:
	"""Which cameras the pipeline is watching, and whether they publish."""
	return service.cameras()


@app.get('/frame', include_in_schema=False)
def read_frame(camera: str) -> fastapi.Response:
	"""One still from a camera, to draw zones against."""
	image = service.still(camera, deps.camera(camera))
	return fastapi.Response(
		content=image,
		media_type='image/jpeg',
		# Briefly, so a reload gets a fresh moment without re-opening RTSP
		# on every repaint.
		headers={'Cache-Control': 'max-age=5'},
	)


@app.get('/zones')
def read_zones() -> models.Zones:
	"""Every zone and line, with the geometry to draw them."""
	return service.zones()


@app.put('/zones')
def write_zones(body: models.DrawnCamera) -> models.SavedGeometry:
	"""Writes one camera's zones and lines back to cameras.yml."""
	return service.save_zones(body)


@app.get('/occupancy')
def read_occupancy(
	scope: deps.Window,
	zone: str = 'indoor',
	interval: int = 300,
	tz: str = 'UTC',
) -> models.Occupancy:
	"""How many people stood in a zone, bucketed over time."""
	return service.occupancy(scope, deps.zone(zone), interval, tz)


@app.get('/dwell')
def read_dwell(
	scope: deps.Window,
	zone: str = 'tables',
	buckets: str = '',
	interval: int = 3600,
	tz: str = 'UTC',
) -> models.Dwell:
	"""How long each visit to a zone lasted."""
	return service.dwell(scope, deps.zone(zone), buckets, interval, tz)


@app.get('/footfall')
def read_footfall(
	scope: deps.Window,
	line: str = 'entrance',
	interval: int = 3600,
	tz: str = 'UTC',
) -> models.Footfall:
	"""People crossing a counting line, in each direction."""
	return service.footfall(scope, deps.line(line), interval, tz)


@app.get('/events')
def read_events(
	scope: deps.Window,
	metric: models.Metric = 'occupancy',
	zone: str = 'indoor',
	comparator: models.Comparator = 'above',
	threshold: float = 0,
	for_seconds: int = 0,
	type: str = 'threshold',
	interval: int | None = None,
	tz: str = 'UTC',
	threshold_of: models.Basis = 'absolute',
	rising: str | None = None,
) -> models.Events:
	"""Evaluates one alert rule over one window.

	`metric`, `comparator` and `threshold_of` are Literals rather than
	strings validated in the body: FastAPI turns the annotation into a 422
	that lists the alternatives, instead of a 400 raised from somewhere
	inside a query builder.
	"""
	return service.events(
		scope, metric, zone, comparator, threshold, for_seconds, type,
		interval, tz, threshold_of, rising,
	)


@app.get('/events/congestion')
def read_congestion(
	scope: deps.Window,
	n: float = 0.9,
	m: float = 2,
	zone: str = 'indoor',
	queue: str | None = 'queue',
	tz: str = 'UTC',
) -> models.Events:
	"""Times the zone was over `n` of capacity for `m` minutes, queue rising.

	A room at capacity with a shrinking queue is a rush that is clearing.
	Congestion is a full room that is still filling, which is why this is
	two conditions and not one.
	"""
	return service.events(
		scope, 'occupancy', zone, 'above', n, int(m * 60), 'congestion',
		None, tz, 'capacity', queue or None,
	)


@app.get('/events/empty')
def read_empty(
	scope: deps.Window,
	n: float = 0.5,
	m: float = 10,
	zone: str = 'indoor',
	tz: str = 'UTC',
) -> models.Events:
	"""Times the zone stayed below `n` of its own average for `m` minutes.

	Against the window's own average rather than a fixed headcount,
	because "quiet" is a different number at 3pm and at midnight.
	"""
	return service.events(
		scope, 'occupancy', zone, 'below', n, int(m * 60), 'empty',
		None, tz, 'mean', None,
	)


@app.get('/events/long-wait')
def read_long_wait(
	scope: deps.Window, m: float = 5, zone: str = 'queue', tz: str = 'UTC'
) -> models.Events:
	"""Visits to `zone` that lasted longer than `m` minutes."""
	return service.events(
		scope, 'dwell', zone, 'above', m * 60, 0, 'long-wait',
		None, tz, 'absolute', None,
	)


@app.get('/overlay')
def read_overlay(
	camera: str, start: str | None = None, end: str | None = None
) -> models.Overlay:
	"""Every stored box for one camera over one short window."""
	if camera not in config.get().cameras:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown camera: {camera}'
		)
	return service.overlay(deps.span(start, end, default_seconds=5), camera)


@app.get('/ppe/{kind}')
def read_ppe(kind: models.PpeKind) -> models.Ppe:
	"""Reports that PPE compliance is not measurable yet.

	The kind is a Literal, so an unknown one is a 422 from the router
	rather than a hand-written 404 - the list of three lives in one place
	and the schema shows it.
	"""
	return service.ppe()


@app.get('/clips/{event_id}')
def read_clip(
	event_id: str, camera: str, start: str, end: str | None = None
) -> models.Clip:
	"""Renders the clip for one event and returns where to fetch it.

	The mp4 itself does not come back through here. It is uploaded to the
	object store and the caller gets a presigned link, so the bytes travel
	from the store to the browser instead of through this service and the
	backend behind it.
	"""
	deps.camera(camera)
	return service.clip(event_id, camera, start, end)
