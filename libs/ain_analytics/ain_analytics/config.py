"""cameras.yml, parsed once, plus the SQL its geometry turns into.

Nothing else in this package knows what a zone is. A caller asks for
`zone=indoor` and gets back a predicate; the mapping from a zone name to
cameras and polygons stops here, which is what keeps `ain_backend` from
having to know which cameras compose a zone.
"""

import collections
import dataclasses
import functools
import hashlib
import io
import pathlib
import tempfile
from collections.abc import Iterable, Mapping

import yaml

from ain_analytics import settings

Point = tuple[float, float]

def _default_path() -> pathlib.Path:
	"""Where cameras.yml is, per the settings."""
	return settings.get().cameras_yml


class ConfigError(Exception):
	"""cameras.yml describes something that cannot work."""


class UnknownZoneError(KeyError):
	"""No zone or line in the config carries the requested name."""


@dataclasses.dataclass(frozen=True)
class Part:
	"""One camera's share of a zone.

	A zone is the sum of its parts. With no cross-camera re-identification
	two parts that see the same floor double-count whoever stands there,
	so the polygons are drawn disjoint and this stays a plain sum.
	"""

	camera: str
	points: tuple[Point, ...]
	name: str = ''

	@property
	def polygon_sql(self) -> str:
		"""The vertex list as a ClickHouse polygon literal."""
		vertices = ','.join(f'({x},{y})' for x, y in self.points)
		return f'[{vertices}]'

	@property
	def contains_sql(self) -> str:
		"""A predicate true for a detection standing in this part.

		Returns:
			SQL testing the FOOT point of the box, never its centre: on
			a wall-mounted camera the centre drifts across a boundary
			when somebody leans, and the foot point does not.
		"""
		return (
			f"(source_id = '{self.camera}' AND "
			f'pointInPolygon((xc, yc + h / 2), {self.polygon_sql}))'
		)


class NoCapacityError(KeyError):
	"""A zone was asked for a proportion of a capacity it does not declare."""


@dataclasses.dataclass(frozen=True)
class Zone:
	"""A named area, spread over one or more cameras."""

	name: str
	parts: tuple[Part, ...]
	# How many people the space holds. A judgement about the room, not a
	# measurement - it is what "occupancy passed 90%" is 90% of. None for a
	# zone where the question is meaningless, like the tables.
	capacity: int | None = None

	@property
	def cameras(self) -> tuple[str, ...]:
		"""Every camera this zone is seen by, in config order."""
		seen = dict.fromkeys(part.camera for part in self.parts)
		return tuple(seen)

	@property
	def contains_sql(self) -> str:
		"""A predicate true for a detection standing anywhere in it."""
		return '(' + ' OR '.join(part.contains_sql for part in self.parts) + ')'

	@property
	def cameras_sql(self) -> str:
		"""A predicate narrowing a scan to this zone's cameras.

		Returns:
			SQL that is redundant with `contains_sql` and there for
			speed. `source_id` is the first column of the table's sort
			key, so this prunes whole parts; without it a zone on one
			camera still evaluates pointInPolygon against every row of
			every other one, which over thirty days is a full scan of the
			retention window.
		"""
		ids = ', '.join(f"'{camera}'" for camera in self.cameras)
		return f'source_id IN ({ids})'

	def part_name_sql(self) -> str:
		"""An expression naming which part a detection stands in.

		Returns:
			SQL evaluating to the part's name, or `''` for a detection
			outside every part. Unnamed parts answer with the zone name,
			so a zone that is not subdivided still groups.
		"""
		branches = []
		for index, part in enumerate(self.parts):
			label = part.name or f'{self.name}-{index + 1}'
			branches.append(f"{part.contains_sql}, '{label}'")
		return f'multiIf({", ".join(branches)}, \'\')'

	def proportion(self, fraction: float) -> float:
		"""Turns "90% full" into a number of people.

		Args:
			fraction: The share of capacity, 0.9 for ninety percent.

		Returns:
			The threshold in people.

		Raises:
			NoCapacityError: This zone declares no capacity, so there is
				nothing for a percentage to be a percentage of. Guessing
				one would put a made-up number behind an alert.
		"""
		if self.capacity is None:
			raise NoCapacityError(self.name)
		return self.capacity * fraction

	def geometry(self) -> dict:
		"""The shape to draw for an event raised on this zone."""
		return {
			'kind': 'polygon',
			'capacity': self.capacity,
			'parts': [
				{
					'camera': part.camera,
					'name': part.name or None,
					'points': [list(point) for point in part.points],
				}
				for part in self.parts
			],
		}


@dataclasses.dataclass(frozen=True)
class Line:
	"""A counting line, which is really two parallel lines.

	One line and a jittering bounding box produce phantom crossings all
	day. Requiring both to be crossed, in order, throws those away, and
	which one is crossed first is what gives the crossing a direction.
	"""

	name: str
	camera: str
	outer: tuple[Point, Point]
	inner: tuple[Point, Point]

	def geometry(self) -> dict:
		"""The shape to draw for an event raised on this line."""
		return {
			'kind': 'line',
			'parts': [
				{
					'camera': self.camera,
					'name': side,
					'points': [list(point) for point in pair],
				}
				for side, pair in (('outer', self.outer), ('inner', self.inner))
			],
		}


@dataclasses.dataclass(frozen=True)
class Config:
	"""Everything cameras.yml declares."""

	cameras: dict[str, dict]
	zones: dict[str, Zone]
	lines: dict[str, Line]
	kafka_brokers: str
	kafka_topic: str

	def zone(self, name: str) -> Zone:
		"""Looks up a zone.

		Args:
			name: The zone name from the query string.

		Returns:
			The zone.

		Raises:
			UnknownZoneError: No zone carries that name.
		"""
		if name not in self.zones:
			raise UnknownZoneError(name)
		return self.zones[name]

	def line(self, name: str) -> Line:
		"""Looks up a counting line.

		Args:
			name: The line name from the query string.

		Returns:
			The line.

		Raises:
			UnknownZoneError: No line carries that name.
		"""
		if name not in self.lines:
			raise UnknownZoneError(name)
		return self.lines[name]

	def stream(self, camera: str) -> str | None:
		"""Returns the MediaMTX path a camera is published on."""
		entry = self.cameras.get(camera)
		return entry.get('stream') if entry else None


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
	"""Reports whether segments a-b and c-d properly intersect."""

	def side(p: Point, q: Point, r: Point) -> float:
		return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

	d1, d2 = side(c, d, a), side(c, d, b)
	d3, d4 = side(a, b, c), side(a, b, d)
	return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _check_simple(where: str, points: tuple[Point, ...]) -> None:
	"""Rejects a polygon whose edges cross.

	Args:
		where: What is being checked, for the error message.
		points: The vertices, in order.

	Raises:
		ConfigError: Two non-adjacent edges cross.

	A hand-written vertex list very easily describes a bow-tie, and a
	self-intersecting polygon does not fail - `pointInPolygon` simply
	answers nonsense for half of it. Checked here, at load, so the
	service refuses to start on one rather than reporting occupancy
	nobody can explain.
	"""
	count = len(points)
	edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
	for i, (a, b) in enumerate(edges):
		for j, (c, d) in enumerate(edges):
			# Adjacent edges share a vertex and always "touch".
			if j <= i or (j - i) % count <= 1 or (i - j) % count <= 1:
				continue
			if _segments_cross(a, b, c, d):
				raise ConfigError(
					f'{where}: edges {i} and {j} cross - the vertices are '
					'out of order and this polygon is a bow-tie'
				)


def _points(raw: object, where: str) -> tuple[Point, ...]:
	"""Converts a config point list, rejecting anything unusable.

	Args:
		raw: The value read from YAML.
		where: What is being read, for the error message.

	Returns:
		The points as tuples.

	Raises:
		ConfigError: A point is malformed or outside 0..1.
	"""
	if not isinstance(raw, list) or len(raw) < 2:
		raise ConfigError(f'{where}: needs at least two points')
	points = []
	for point in raw:
		if not isinstance(point, list) or len(point) != 2:
			raise ConfigError(f'{where}: {point!r} is not an [x, y] pair')
		x, y = float(point[0]), float(point[1])
		if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
			raise ConfigError(
				f'{where}: {point!r} is outside 0..1 - coordinates are '
				'normalised against the frame, not pixels'
			)
		points.append((x, y))
	return tuple(points)


def load(path: pathlib.Path | None = None) -> Config:
	"""Reads cameras.yml.

	Args:
		path: Where to read it from. Defaults to `$AIN_CAMERAS_YML`.

	Returns:
		The parsed config.

	Raises:
		ConfigError: A zone or line names an unknown camera, or its
			points are unusable.
	"""
	path = path or _default_path()
	document = yaml.safe_load(path.read_text())
	cameras = document.get('cameras') or {}
	if not cameras:
		raise ConfigError(f'{path}: no cameras')

	zones = {}
	for name, raw_zone in (document.get('zones') or {}).items():
		# A zone is `{capacity?, parts: [...]}`. A bare list is the older
		# shape and still reads, because a zone without a capacity is a
		# perfectly good zone - it just cannot be alerted on proportionally.
		if isinstance(raw_zone, list):
			raw_parts, capacity = raw_zone, None
		else:
			raw_parts = raw_zone.get('parts') or []
			capacity = raw_zone.get('capacity')
		if capacity is not None and (
			not isinstance(capacity, int) or capacity <= 0
		):
			raise ConfigError(
				f'zone {name}: capacity {capacity!r} is not a positive '
				'number of people'
			)
		parts = []
		for index, raw in enumerate(raw_parts):
			where = f'zone {name}[{index}]'
			camera = raw.get('camera')
			if camera not in cameras:
				raise ConfigError(f'{where}: unknown camera {camera!r}')
			points = _points(raw.get('points'), where)
			if len(points) < 3:
				raise ConfigError(f'{where}: a polygon needs three points')
			_check_simple(where, points)
			parts.append(
				Part(camera=camera, points=points, name=raw.get('name', ''))
			)
		if not parts:
			raise ConfigError(f'zone {name}: no parts')
		zones[name] = Zone(
			name=name, parts=tuple(parts), capacity=capacity
		)

	lines = {}
	for name, raw in (document.get('lines') or {}).items():
		camera = raw.get('camera')
		if camera not in cameras:
			raise ConfigError(f'line {name}: unknown camera {camera!r}')
		sides = {}
		for side in ('outer', 'inner'):
			if side not in raw:
				raise ConfigError(
					f'line {name}: no {side} line. Footfall needs two '
					'parallel lines crossed in order; one line and a '
					'jittering box produce phantom crossings.'
				)
			points = _points(raw[side], f'line {name}.{side}')
			if len(points) != 2:
				raise ConfigError(f'line {name}.{side}: needs exactly two points')
			sides[side] = points
		lines[name] = Line(
			name=name,
			camera=camera,
			outer=sides['outer'],
			inner=sides['inner'],
		)

	kafka = document.get('kafka') or {}
	options = settings.get()
	return Config(
		cameras=cameras,
		zones=zones,
		lines=lines,
		# The environment wins over the file, and the file over the
		# fallback. This is a deployment detail, not geometry: the
		# broker moves without the zones changing.
		kafka_brokers=(
			options.kafka_brokers or kafka.get('brokers') or 'kafka:9092'
		),
		kafka_topic=(
			options.kafka_topic or kafka.get('topic') or 'ain.people.raw'
		),
	)


def version(path: pathlib.Path | None = None) -> str:
	"""A short digest of the config file as it is on disk right now.

	The editor reads this with the geometry and hands it back when it saves.
	Every save replaces one whole camera, so two tabs open on the same camera
	- or one tab and one hand edit - end with the second silently deleting
	whatever the first drew. Comparing this is what turns that into a 409.
	"""
	path = path or _default_path()
	return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


class StaleWriteError(Exception):
	"""cameras.yml changed after the caller read it."""


@functools.cache
def get() -> Config:
	"""Returns the process-wide config, read once."""
	return load()


# --------------------------------------------------------------- writing --
#
# The geometry editor draws shapes and this writes them back. It is the only
# thing in the package that changes cameras.yml, and it changes exactly two
# keys: `zones` and `lines`. `cameras` is left alone deliberately - adding a
# camera also means regenerating docker-compose.analytics.yml and starting a
# source adapter, which is `compose_gen.py`'s job and not something a click
# on a canvas should set in motion.

# Two decimals is ~13px on a 1280-wide frame, which is a tenth of a person.
# It is also what every polygon in the checked-in file already uses, so a
# saved zone and a hand-written one look the same in a diff.
_PRECISION = settings.get().geometry_decimal_places


def _round_trip():
	"""A YAML that preserves comments.

	Imported here rather than at module scope because this module is also
	imported by the ingest process, which runs on the Savant adapters image
	and carries only the shared dependencies. Only the API ever saves.
	"""
	from ruamel.yaml import YAML

	yaml_rt = YAML()
	yaml_rt.preserve_quotes = True
	yaml_rt.indent(mapping=2, sequence=4, offset=2)
	# cameras.yml keeps one polygon per line. At the default 80 columns a
	# six-point one folds into a continuation nobody can read or diff.
	yaml_rt.width = 4096
	return yaml_rt


def _flow(items: list) -> object:
	"""A sequence that dumps inline, the way the coordinates are written."""
	from ruamel.yaml.comments import CommentedSeq

	seq = CommentedSeq(items)
	seq.fa.set_flow_style()
	return seq


def _quoted(camera: str) -> object:
	"""A camera id that survives a round trip as a string.

	`03` unquoted is a number to any YAML parser, and camera ids are the
	join key to `catalogue.py`. This is the same hazard `compose_gen.py`
	guards against for SOURCE_ID, in the other direction.
	"""
	from ruamel.yaml.scalarstring import SingleQuotedScalarString

	return SingleQuotedScalarString(camera)


def _coordinates(points: Iterable[Iterable[float]]) -> object:
	return _flow(
		[
			_flow([round(float(x), _PRECISION), round(float(y), _PRECISION)])
			for x, y in points
		]
	)


def _write_zones(document, camera: str, drawn: Mapping[str, list]) -> None:
	"""Swaps this camera's polygons for the drawn ones, in place."""
	zones = document.get('zones')
	if zones is None:
		zones = document['zones'] = {}

	# Where this camera's parts were, and the comments that sat above them.
	# Both are restored after the redraw. Without the anchor a zone
	# reshuffles every time it is saved; without the comments, the note
	# explaining why a polygon stops at the door frame is deleted by nudging
	# the polygon - which is the note's whole subject.
	anchors: dict[str, int] = {}
	notes: dict[str, list] = {}
	for name in list(zones):
		parts = (zones[name] or {}).get('parts')
		if parts is None:
			continue
		mine = [
			index
			for index, part in enumerate(parts)
			if str((part or {}).get('camera')) == camera
		]
		notes[name] = [parts.ca.items.get(index) for index in mine]
		# Parts on other cameras are none of this camera's business - a zone
		# is the sum of its parts and they are drawn one camera at a time.
		# Deleted in place, and backwards so the indices hold: rebuilding the
		# list instead hands ruamel a plain list and every comment inside the
		# zone goes with it.
		for index in reversed(mine):
			anchors[name] = index
			del parts[index]
		if not parts and name not in drawn:
			# Every part it had was on this camera and none was drawn back:
			# the zone was deleted.
			del zones[name]

	for name, shapes in drawn.items():
		body = zones.get(name)
		if body is None:
			body = zones[name] = {}
		capacity = next(
			(shape.get('capacity') for shape in shapes if shape.get('capacity')), None
		)
		if capacity:
			body['capacity'] = int(capacity)
		parts = body.get('parts')
		if parts is None:
			parts = body['parts'] = []
		where = anchors.get(name, len(parts))
		for offset, shape in enumerate(shapes):
			part = {'camera': _quoted(camera)}
			if shape.get('part'):
				part['name'] = str(shape['part'])
			part['points'] = _coordinates(shape['points'])
			parts.insert(where + offset, part)
		# After every insert, because inserting shifts the comment indices.
		# Matched by position: a redraw that changes how many parts a camera
		# contributes keeps as many notes as still have somewhere to go.
		for offset, note in enumerate(notes.get(name, [])[: len(shapes)]):
			if note is not None:
				parts.ca.items[where + offset] = note

	if not zones:
		document.pop('zones', None)


def _write_lines(document, camera: str, drawn: Mapping[str, list]) -> None:
	"""Swaps this camera's counting lines for the drawn ones, in place."""
	lines = document.get('lines')
	if lines is None:
		lines = document['lines'] = {}

	notes = {}
	for name, body in list(lines.items()):
		if str((body or {}).get('camera')) == camera:
			notes[name] = lines.ca.items.get(name)
			del lines[name]

	for name, halves in drawn.items():
		clash = lines.get(name)
		if clash is not None:
			# Unlike a zone, a line belongs to exactly one camera, so the
			# name is global. Silently taking it would delete somebody
			# else's entrance from a camera this editor is not even showing.
			raise ConfigError(
				f'{name!r} is already a counting line on camera '
				f'{clash.get("camera")}. Give this one another name.'
			)
		body = {'camera': _quoted(camera)}
		for side in ('outer', 'inner'):
			matching = [half for half in halves if half.get('part') == side]
			if len(matching) != 1:
				raise ConfigError(
					f'{name}: {len(matching)} {side} lines drawn, need one. '
					'A counting line is two parallels crossed in order - one '
					'line and a jittering box is phantom crossings all day.'
				)
			body[side] = _coordinates(matching[0]['points'])
		lines[name] = body
		note = notes.get(name)
		if note is not None:
			lines.ca.items[name] = note

	if not lines:
		document.pop('lines', None)


def save(
	camera: str,
	shapes: Iterable[Mapping[str, object]],
	path: pathlib.Path | None = None,
	expect: str | None = None,
) -> dict[str, list[str]]:
	"""Rewrites one camera's geometry, leaving the rest of the file alone.

	Args:
		camera: The camera whose shapes these are. Everything it previously
			owned is replaced, so a shape that was deleted in the editor is
			deleted here.
		shapes: Drawn shapes, each `{kind, name, part, capacity, points}`
			with `kind` either `polygon` or `line` and points normalised.
		path: The file to rewrite. Defaults to the configured one.
		expect: The `version()` the caller read before editing. Omitted
			skips the check, which is what a script wanting last-write-wins
			should do deliberately rather than by accident.

	Returns:
		The zone and line names this camera now contributes to.

	Raises:
		ConfigError: The camera is unknown, a line is not a complete pair,
			a line name is taken by another camera, or the result would not
			parse. Nothing is written in any of those cases.
		StaleWriteError: The file changed since `expect` was read.
	"""
	path = path or _default_path()
	if expect is not None and version(path) != expect:
		raise StaleWriteError(
			'cameras.yml changed since this page loaded. Reload before '
			'saving, or this would delete whatever was changed.'
		)
	yaml_rt = _round_trip()
	with path.open(encoding='utf-8') as handle:
		document = yaml_rt.load(handle) or {}

	if camera not in (document.get('cameras') or {}):
		raise ConfigError(f'{camera!r} is not a camera in {path.name}')

	grouped: dict[str, dict[str, list]] = {
		'polygon': collections.defaultdict(list),
		'line': collections.defaultdict(list),
	}
	for shape in shapes:
		kind = str(shape.get('kind'))
		if kind not in grouped:
			raise ConfigError(f'{kind!r} is not a shape this file can hold')
		name = str(shape.get('name') or '').strip()
		if not name:
			raise ConfigError('every zone and line needs a name before it saves')
		grouped[kind][name].append(shape)

	_write_zones(document, camera, grouped['polygon'])
	_write_lines(document, camera, grouped['line'])

	rendered = io.StringIO()
	yaml_rt.dump(document, rendered)
	text = rendered.getvalue()

	# Parsed before it is written, never after. A self-intersecting polygon
	# is a 400 the editor can show against the shape that caused it; written
	# first, it is an API that refuses to start and a file somebody has to
	# repair by hand to find out why.
	with tempfile.NamedTemporaryFile(
		'w', suffix='.yml', encoding='utf-8', delete=False
	) as check:
		check.write(text)
		checked = pathlib.Path(check.name)
	try:
		parsed = load(checked)
	finally:
		checked.unlink(missing_ok=True)

	# Written in place rather than renamed into position. cameras.yml is
	# bind-mounted into this container as a single file, and renaming onto a
	# mount point is EBUSY even as root. The validation above is what makes
	# that acceptable; git is the undo.
	path.write_text(text, encoding='utf-8')
	get.cache_clear()
	return {
		'zones': sorted(
			name for name, zone in parsed.zones.items() if camera in zone.cameras
		),
		'lines': sorted(
			name for name, line in parsed.lines.items() if line.camera == camera
		),
	}
