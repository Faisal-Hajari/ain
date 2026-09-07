"""The HTTP surface `ain_backend` reads.

Two rules hold everywhere in here, and both are load-bearing:

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

import datetime
import os
import pathlib
from typing import Annotated, Literal

import fastapi
from fastapi.middleware import cors

from ain_analytics import clips
from ain_analytics import config
from ain_analytics import db
from ain_analytics import events as events_module
from ain_analytics import feeds
from ain_analytics import frames
from ain_analytics import queries

# The PPE models are not deployed. These endpoints answer `unavailable`
# rather than 0, because 0 asserts "we watched the kitchen and nobody
# violated the mask policy" - a claim this system cannot make. `ain_backend`
# derives sentiment from the value, so a zero would very likely render green,
# and a hygiene dashboard confidently showing three green zeros is worse than
# one showing three dashes. When the model lands, `status` flips to `ok` and
# nothing else about the shape changes.
_PPE_KINDS = ('no-gloves', 'no-hair-cover', 'no-mask')

app = fastapi.FastAPI(
	title='AIN analytics API',
	version='0.1.0',
	summary='Occupancy, dwell, footfall and threshold events over ClickHouse.',
)

app.add_middleware(
	cors.CORSMiddleware,
	allow_origins=os.environ.get('AIN_CORS_ORIGINS', '*').split(','),
	allow_methods=['GET'],
	allow_headers=['*'],
)

Comparator = Literal['above', 'below']

# The geometry editor. Served from here rather than from the dashboard
# because this is the service that owns cameras.yml - the shapes it draws
# and the shapes it reads are the same file.
_EDITOR = pathlib.Path(
	os.environ.get('AIN_EDITOR_HTML', '/app/editor.html')
)


def _parse(moment: str | None, field: str) -> datetime.datetime | None:
	"""Reads one ISO 8601 timestamp from the query string.

	Args:
		moment: The raw value, or None.
		field: Which parameter it came from, for the error message.

	Returns:
		An aware UTC datetime, or None.

	Raises:
		fastapi.HTTPException: The value is not ISO 8601.
	"""
	if not moment:
		return None
	try:
		parsed = datetime.datetime.fromisoformat(moment)
	except ValueError as error:
		raise fastapi.HTTPException(
			status_code=400, detail=f'{field} is not ISO 8601: {moment!r}'
		) from error
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=datetime.timezone.utc)
	return parsed.astimezone(datetime.timezone.utc)


def window(start: str | None = None, end: str | None = None) -> queries.Window:
	"""Resolves the time range every read route takes.

	Args:
		start: ISO 8601, inclusive. Defaults to an hour before the end.
		end: ISO 8601, exclusive. Defaults to the newest stored
			detection, or to now when there is none.

	Returns:
		The half-open range.

	Raises:
		fastapi.HTTPException: A timestamp is unparseable, or the range
			runs backwards.

	Every plain parameter of a FastAPI dependency becomes a query
	parameter, so this deliberately takes only the two that are meant to
	be one. A `default_seconds` here would appear in the schema of every
	route that depends on it, and a caller could widen any of them to the
	full retention window.
	"""
	return _window(start, end)


def _window(
	start: str | None,
	end: str | None,
	default_seconds: int = 3600,
) -> queries.Window:
	"""Resolves a range, with a caller-chosen default width.

	Args:
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive.
		default_seconds: How far back an omitted `start` reaches.

	Returns:
		The half-open range.

	Raises:
		fastapi.HTTPException: A timestamp is unparseable, or the range
			runs backwards.
	"""
	finish = _parse(end, 'end') or queries.latest_ts(db.client()) or (
		datetime.datetime.now(datetime.timezone.utc)
	)
	begin = _parse(start, 'start') or finish - datetime.timedelta(
		seconds=default_seconds
	)
	if begin >= finish:
		raise fastapi.HTTPException(
			status_code=400, detail='start must be before end'
		)
	return queries.Window(start=begin, end=finish)


Window = Annotated[queries.Window, fastapi.Depends(window)]


def _zone(name: str) -> config.Zone:
	"""Looks up a zone.

	Args:
		name: The zone name from the query string.

	Returns:
		The zone.

	Raises:
		fastapi.HTTPException: cameras.yml declares no such zone.
	"""
	try:
		return config.get().zone(name)
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404,
			detail=(
				f'unknown zone: {name}. Known: '
				f'{sorted(config.get().zones)}'
			),
		) from error


def _line(name: str) -> config.Line:
	"""Looks up a counting line.

	Args:
		name: The line name from the query string.

	Returns:
		The line.

	Raises:
		fastapi.HTTPException: cameras.yml declares no such line.
	"""
	try:
		return config.get().line(name)
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404,
			detail=(
				f'unknown line: {name}. Known: {sorted(config.get().lines)}'
			),
		) from error


@app.get('/health')
def health(response: fastapi.Response) -> dict:
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
		return {'status': 'degraded', 'detail': str(error)}
	return {
		'status': 'ok',
		'latest_detection': latest.isoformat() if latest else None,
		'zones': sorted(config.get().zones),
		'lines': sorted(config.get().lines),
	}


@app.get('/editor', include_in_schema=False)
def read_editor() -> fastapi.Response:
	"""Serves the zone and line editor.

	Returns:
		A single self-contained page. It draws the shapes in cameras.yml
		over a still from the camera they belong to, and writes the YAML
		for whatever you draw.

	Raises:
		fastapi.HTTPException: The page is not in the image.
	"""
	if not _EDITOR.is_file():
		raise fastapi.HTTPException(status_code=404, detail='no editor bundled')
	return fastapi.responses.FileResponse(
		_EDITOR,
		media_type='text/html',
		# The file is bind-mounted, so it changes without the image
		# changing. Cached, an edit to it appears to do nothing at all.
		headers={'Cache-Control': 'no-store'},
	)


@app.get('/frame', include_in_schema=False)
def read_frame(camera: str) -> fastapi.Response:
	"""Returns one still from a camera, to draw zones against.

	Args:
		camera: The camera id, as the catalogue names it.

	Returns:
		A JPEG.

	Raises:
		fastapi.HTTPException: The camera is unknown, or its stream did
			not produce a frame.
	"""
	stream = config.get().stream(camera)
	if stream is None:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown camera: {camera}'
		)
	try:
		image = frames.still(stream)
	except frames.FrameError as error:
		raise fastapi.HTTPException(status_code=503, detail=str(error)) from error
	return fastapi.Response(
		content=image,
		media_type='image/jpeg',
		# Briefly, so a reload gets a fresh moment without re-opening RTSP
		# on every repaint.
		headers={'Cache-Control': 'max-age=5'},
	)


@app.get('/cameras')
def read_cameras() -> dict:
	"""Reports which cameras the pipeline is watching, and whether they
	are publishing.

	Returns:
		One entry per camera in cameras.yml, with `live` true when
		MediaMTX has its path ready - which under runOnDemand means a
		reader is attached, and the readers are the source adapters.
		`live` is null when MediaMTX itself could not be reached.

		A camera the branch has and this list does not is simply absent:
		nothing is watching it, and the caller reports it as having no
		signal.
	"""
	return {'cameras': feeds.status(config.get(), feeds.ready_streams())}


@app.get('/zones')
def read_zones() -> dict:
	"""Returns every zone and line, with the geometry to draw them.

	Returns:
		The shapes, normalised 0..1 against each camera's frame. This is
		what the browser overlay draws on top of the video, and what an
		editor would drag - which is why none of it is in module.yml.
	"""
	settings = config.get()
	return {
		'zones': [
			{'name': name, **zone.geometry()}
			for name, zone in settings.zones.items()
		],
		'lines': [
			{'name': name, **line.geometry()}
			for name, line in settings.lines.items()
		],
	}


@app.get('/occupancy')
def read_occupancy(
	scope: Window, zone: str = 'indoor', interval: int = 300, tz: str = 'UTC'
) -> dict:
	"""How many people stood in a zone, bucketed over time.

	Args:
		scope: The time range.
		zone: A zone name from cameras.yml.
		interval: Bucket size in seconds.
		tz: An IANA timezone name. A daily bucket starts at midnight
			there rather than at UTC's, or three hours of every local day
			land on the bar before.

	Returns:
		The series plus its summary, in people. `mean` is time-weighted,
		so an empty bucket reads 0 rather than disappearing.
	"""
	area = _zone(zone)
	size = queries.bucket_seconds(scope, interval)
	buckets = queries.occupancy(db.client(), area, scope, size, tz)
	# Weighted by how long each bucket covers: the first and last of a
	# window are partial, and a plain average would weight a one-second
	# sliver like a five-minute interval.
	covered = sum(bucket['covered_seconds'] for bucket in buckets)
	person_seconds = sum(
		bucket['mean'] * bucket['covered_seconds'] for bucket in buckets
	)
	return {
		'zone': zone,
		'unit': 'people',
		'cameras': list(area.cameras),
		'start': scope.start.isoformat(),
		'end': scope.end.isoformat(),
		'interval_seconds': size,
		'buckets': buckets,
		# Instantaneous, not the trailing bucket's average: "how many are
		# here now" and "how many were here on average over the last five
		# minutes" are different questions and the card asks the first.
		'latest': queries.current_occupancy(db.client(), area, scope),
		'mean': round(person_seconds / covered, 2) if covered else 0.0,
		'peak': max((bucket['peak'] for bucket in buckets), default=0),
	}


@app.get('/dwell')
def read_dwell(
	scope: Window,
	zone: str = 'tables',
	buckets: str = '',
	interval: int = 3600,
	tz: str = 'UTC',
) -> dict:
	"""How long each visit to a zone lasted.

	Args:
		scope: The time range.
		zone: A zone name from cameras.yml.
		buckets: Histogram lower bounds in seconds, comma-separated. The
			caller chooses them because the caller is the one drawing the
			chart.
		interval: Bucket size for the over-time series, in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		Per-part statistics and the histogram, in seconds.

	Raises:
		fastapi.HTTPException: A bucket edge is not a number.
	"""
	area = _zone(zone)
	if buckets:
		try:
			edges = sorted({int(edge) for edge in buckets.split(',')})
		except ValueError as error:
			raise fastapi.HTTPException(
				status_code=400, detail=f'bad buckets: {buckets!r}'
			) from error
	else:
		edges = [0, 600, 1200, 1800, 2700, 3600]
	size = queries.bucket_seconds(scope, interval)
	result = queries.dwell(db.client(), area, scope, edges, size, tz)
	return {
		'zone': zone,
		'cameras': list(area.cameras),
		'start': scope.start.isoformat(),
		'end': scope.end.isoformat(),
		**result,
	}


@app.get('/footfall')
def read_footfall(
	scope: Window, line: str = 'entrance', interval: int = 3600, tz: str = 'UTC'
) -> dict:
	"""People crossing a counting line, in each direction.

	Args:
		scope: The time range.
		line: A line name from cameras.yml.
		interval: Bucket size in seconds.
		tz: An IANA timezone name, for whole-day bucket alignment.

	Returns:
		The series plus its totals, in people.
	"""
	counter = _line(line)
	size = queries.bucket_seconds(scope, interval)
	buckets = queries.footfall(db.client(), counter, scope, size, tz)
	return {
		'line': line,
		'unit': 'people',
		'cameras': [counter.camera],
		'start': scope.start.isoformat(),
		'end': scope.end.isoformat(),
		'interval_seconds': size,
		'buckets': buckets,
		'in': sum(bucket['in'] for bucket in buckets),
		'out': sum(bucket['out'] for bucket in buckets),
	}


@app.get('/events')
def read_events(
	scope: Window,
	metric: str = 'occupancy',
	zone: str = 'indoor',
	comparator: Comparator = 'above',
	threshold: float = 0,
	for_seconds: int = 0,
	type: str = 'threshold',
	interval: int | None = None,
	tz: str = 'UTC',
	threshold_of: str = 'absolute',
	rising: str | None = None,
) -> dict:
	"""Evaluates one alert rule over one window.

	Args:
		scope: The time range.
		metric: 'occupancy', 'footfall' or 'dwell'.
		zone: A zone name, or a line name when the metric is footfall.
		comparator: 'above' or 'below'.
		threshold: People for a series metric, seconds for dwell.
		for_seconds: How long a series breach must hold to count. A
			visit metric ignores it: the visit's own length is the test.
		type: What to label the results, so a named wrapper reads back
			as itself.
		interval: Bucket size for a series metric, in seconds. A
			threshold is authored in the units its metric is read in, so
			a rate like footfall needs the interval it was authored for.
		tz: An IANA timezone name, for whole-day bucket alignment.
		threshold_of: What the threshold is a threshold OF.
			`absolute` is a number of people; `capacity` makes it a
			share of what the zone holds, so 0.9 is "passed 90%";
			`mean` makes it a share of the window's own average, so
			1.0 is "below average". A visit metric ignores it.
		rising: A zone that must be growing across the run for it to
			count. A room at capacity with a shrinking queue is a rush
			that is clearing, not congestion.

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
			target=zone,
			comparator=comparator,
			threshold=threshold,
			window=scope,
			for_seconds=for_seconds,
			kind=type,
			interval=interval,
			tz=tz,
			basis=threshold_of,
			rising=rising,
		)
	except events_module.UnknownMetricError as error:
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'unknown metric: {metric}. Known: '
				f'{list(events_module.METRICS)}'
			),
		) from error
	except events_module.UnknownBasisError as error:
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'unknown threshold_of: {threshold_of}. Known: '
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
				f'zone {error.args[0]} declares no capacity, so a '
				'threshold cannot be a share of one'
			),
		) from error
	except config.UnknownZoneError as error:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown zone or line: {zone}'
		) from error
	return {
		'start': scope.start.isoformat(),
		'end': scope.end.isoformat(),
		'count': len(found),
		'events': [event.as_dict() for event in found],
	}


@app.get('/events/congestion')
def read_congestion(
	scope: Window,
	n: float = 0.9,
	m: float = 2,
	zone: str = 'indoor',
	queue: str | None = 'queue',
	tz: str = 'UTC',
) -> dict:
	"""Times the zone was over `n` of capacity for `m` minutes, queue rising.

	Args:
		scope: The time range.
		n: The share of the zone's capacity, so 0.9 is "passed 90%".
		m: How long it has to hold, in minutes.
		zone: The area that filled up.
		queue: The area that must be growing at the same time. Pass an
			empty value to drop that condition and alert on a full room
			alone.
		tz: An IANA timezone name.

	Returns:
		The occurrences.

	A room at capacity with a shrinking queue is a rush that is
	clearing. Congestion is a full room that is still filling, which is
	why this is two conditions and not one.
	"""
	return read_events(
		scope, 'occupancy', zone, 'above', n, int(m * 60), 'congestion',
		tz=tz, threshold_of='capacity', rising=queue or None,
	)


@app.get('/events/empty')
def read_empty(
	scope: Window,
	n: float = 0.5,
	m: float = 10,
	zone: str = 'indoor',
	tz: str = 'UTC',
) -> dict:
	"""Times the zone stayed below `n` of its own average for `m` minutes.

	Args:
		scope: The time range.
		n: The share of the window's mean occupancy, so 0.5 is "half the
			usual".
		m: How long it has to hold, in minutes.
		zone: The area that emptied out.
		tz: An IANA timezone name.

	Returns:
		The occurrences.

	Against the window's own average rather than a fixed headcount,
	because "quiet" is a different number at 3pm and at midnight, and a
	branch that is busier than this one should not need a different
	config to get the same alert.
	"""
	return read_events(
		scope, 'occupancy', zone, 'below', n, int(m * 60), 'empty',
		tz=tz, threshold_of='mean',
	)


@app.get('/events/long-wait')
def read_long_wait(
	scope: Window, m: float = 5, zone: str = 'queue', tz: str = 'UTC'
) -> dict:
	"""Visits to `zone` that lasted longer than `m` minutes."""
	return read_events(
		scope, 'dwell', zone, 'above', m * 60, 0, 'long-wait', tz=tz
	)


@app.get('/overlay')
def read_overlay(camera: str, start: str | None = None, end: str | None = None) -> dict:
	"""Every stored box for one camera over one short window.

	Args:
		camera: The camera id, as the catalogue names it.
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive.

	Returns:
		One entry per frame, each with its objects in normalised
		coordinates. The browser looks up the frame nearest
		`hls.playingDate` and draws it to a canvas sized to the video.

	Raises:
		fastapi.HTTPException: The camera is unknown, or the window is
			longer than a minute - this is fetched per window of video,
			not per frame, and a caller who asks for a day OOMs the
			service.
	"""
	if camera not in config.get().cameras:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown camera: {camera}'
		)
	scope = _window(start, end, default_seconds=5)
	if scope.seconds > queries.OVERLAY_MAX_SECONDS:
		raise fastapi.HTTPException(
			status_code=400,
			detail=(
				f'window is {scope.seconds:.0f}s; the cap is '
				f'{queries.OVERLAY_MAX_SECONDS}s'
			),
		)
	return {
		'camera': camera,
		'start': scope.start.isoformat(),
		'end': scope.end.isoformat(),
		'frames': queries.overlay(db.client(), camera, scope),
	}


@app.get('/ppe/{kind}')
def read_ppe(kind: str) -> dict:
	"""Reports that PPE compliance is not measurable yet.

	Args:
		kind: One of `_PPE_KINDS`.

	Returns:
		`unavailable`, never a count. A person detector cannot tell
		whether somebody is wearing gloves; that needs an attribute model
		over person crops, which is a second pipeline this stack does not
		run.

	Raises:
		fastapi.HTTPException: The kind is not one of the three.
	"""
	if kind not in _PPE_KINDS:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown ppe check: {kind}'
		)
	return {
		'value': None,
		'status': 'unavailable',
		'reason': 'ppe_model_not_deployed',
	}


@app.get('/clips/{event_id}.mp4')
def read_clip(
	event_id: str,
	camera: str,
	start: str,
	end: str | None = None,
) -> fastapi.Response:
	"""Renders the video behind one event, with the boxes burnt in.

	Args:
		event_id: The event the clip belongs to, used as its filename.
		camera: Which camera to cut from.
		start: ISO 8601, inclusive.
		end: ISO 8601, exclusive. Defaults to 20 seconds after `start`.

	Returns:
		An mp4. Unlike the live view these boxes are drawn into the
		frames: a browser overlay is a rendering, and a file pulled out
		of here and opened in VLC has to carry its own annotation.

	Raises:
		fastapi.HTTPException: The camera is unknown, the window is
			unusable, or MediaMTX has no recording covering it.
	"""
	if camera not in config.get().cameras:
		raise fastapi.HTTPException(
			status_code=404, detail=f'unknown camera: {camera}'
		)
	scope = clips.clip_window(
		_parse(start, 'start') or datetime.datetime.now(datetime.timezone.utc),
		_parse(end, 'end'),
	)
	try:
		path = clips.render(db.client(), event_id, camera, scope)
	except clips.ClipError as error:
		raise fastapi.HTTPException(status_code=404, detail=str(error)) from error
	return fastapi.responses.FileResponse(
		path, media_type='video/mp4', filename=f'{event_id}.mp4'
	)
