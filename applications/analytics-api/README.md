# analytics-api

FastAPI over the detection rows, and the geometry editor that decides which
rows count. Zones, lines, thresholds and dwell are all SQL at query time, so
the geometry is editable without touching the GPU and last month can be
recomputed against a moved line.

The two services either side of it are `../savant-sink` (the module's ZeroMQ
output onto Kafka) and `../track-ingest` (Kafka into ClickHouse). All three
share `../../libs/ain_analytics`, which is the config loader and the
ClickHouse client and nothing else - a shared library that grows whatever its
first caller wanted is how three services stop being able to move
independently.

Nothing here ever returns a formatted string, a severity or a sentence.
`ain_backend` owns all of that, because it is the service that ships Arabic.

## Editing the geometry

`../../config/cameras.yml` is the only place any of it lives - zone
polygons, counting lines, and which camera each belongs to. It is in `config/`
rather than in any one service because four things read it: this API, the
ingest, the sink and the compose generator.

```bash
uv run scripts/compose_gen.py     # only when the camera LIST changes
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
uv run --all-extras pytest -q                      # here: the query layer
(cd ../../libs/ain_analytics && uv run --all-extras pytest -q)
docker compose run --rm --no-deps --entrypoint pytest track-ingest -q tests
```

The last one runs inside the ingest image, because `savant-rs` only exists
there and is not on PyPI.
