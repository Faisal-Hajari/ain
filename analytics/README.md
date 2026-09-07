# ain-analytics

Everything between the Savant pipeline and `ain_backend`:

* `ain_analytics.sink` - reads the module's ZeroMQ output and relays it onto
  Kafka. This should have been the stock `adapters.python.sinks.kafka_redis`
  container; in savant-adapters-py 0.6.x that adapter imports a module the
  image does not ship, and the runner behind it calls a method the image's own
  `Message` class does not have. The wire format here is unchanged.
* `ain_analytics.ingest` - Kafka consumer. Deserialises savant-rs messages,
  normalises the boxes to 0..1, maps the untracked sentinel to 0, and batches
  detections into ClickHouse.
* `ain_analytics.api` - FastAPI over those rows. Zones, lines, thresholds and
  dwell are all SQL at query time, so the geometry is editable without touching
  the GPU and last month can be recomputed against a moved line.

Two images from one Dockerfile: the API is an ordinary slim Python image, and
the ingest and sink processes run on the Savant adapters image, because
`savant-rs` is not published on PyPI and its message format is versioned.

Nothing here ever returns a formatted string, a severity or a sentence.
`ain_backend` owns all of that, because it is the service that ships Arabic.

## Editing the geometry

`cameras.yml` is the only place any of it lives - zone polygons, counting
lines, and which camera each belongs to.

```bash
uv run analytics/compose_gen.py     # regenerates docker-compose.analytics.yml
docker compose restart analytics-api
```

Never the module. That is the whole point: a Savant manifest resolves its
interpolation once, at init, so geometry in `module.yml` would cost a GPU
restart per zone edit - and would make it impossible to move the entrance line
and recompute last month's footfall against it.

To draw one rather than guess at coordinates, open the editor:

    http://localhost:8100/editor

It takes a still from the camera, draws the shapes this file already declares
over it, and lets you click new ones. **Save to cameras.yml** writes them
straight back and the API picks them up without a restart; *Copy YAML* is
still there for pasting into a review.

Saving rewrites `zones` and `lines` for the camera on screen and nothing else.
Comments survive - they are this file's documentation, including the note above
each polygon saying where it stops and why, so the round trip preserves them
rather than eroding the file one save at a time. `cameras` is deliberately not
writable: adding a camera also means `compose_gen.py` and a new source adapter,
which is a command, not a click. And the file is still checked in, so `git
diff` is the review and `git checkout` is the undo.

**A zone** is *+ Zone*, a click per corner, then Enter (or double-click) to
close it. Name it, and give it a capacity if you want to alert on "90% full".
On a selected zone the hollow dots between corners are new points - click one
to add a corner there and drag it where you want it; right-click a corner to
remove it.

**A counting line is a pair**, and the editor draws it as one: *+ Entrance* asks
for the two ends of the **outer** line, then starts the **inner** one for you
a little further in. Crossing outer then inner is somebody coming in - that
ordering is the whole reason there are two, because one line and a jittering
bounding box produce phantom crossings all day. The list shows them as
`entrance / outer` and `entrance / inner`, and the dropdown beside the name
swaps a shape between the two if you drew them the wrong way round. Pressing
*+ Entrance* again starts a separate line rather than a third half.

Drag any point to move it; *Delete* removes the selected shape. A `*` beside a
shape means it differs from what is on disk.

Two tabs open on the same camera would otherwise end with the second one
silently deleting what the first drew, because a save replaces a whole camera.
The page sends the version it read, and a save against a stale one is refused
rather than applied - *Refresh frame* re-reads both the picture and the
geometry.

To see a zone over moving video instead, open the dashboard's Cameras tab and
turn on the **Zones** toggle - the same polygons, drawn on the live tiles.

## Tests

```bash
uv run --all-extras pytest -q
docker compose run --rm --no-deps --entrypoint pytest track-ingest -q /app/tests
```

The second command runs the deserialiser's tests inside the ingest image,
because `savant-rs` only exists there.
