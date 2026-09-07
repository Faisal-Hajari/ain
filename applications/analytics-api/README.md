# analytics-api

FastAPI over the detection rows. Zones, lines, thresholds and dwell are all
SQL at query time, so the geometry is editable without touching the GPU and
last month can be recomputed against a moved line.

Four modules, and the split is the point:

* `api.py` is **routing only** - a decorator, a signature and one call. A
  route body is the one place in a Python service that cannot be reached from
  a test without a URL, so nothing that can live elsewhere lives there.
* `service.py` is what each endpoint does.
* `deps.py` turns query strings into the things the query layer takes, and
  answers 400 or 404 rather than raising Python errors.
* `models.py` is the wire contract. A hand-built dict is a contract nobody
  can see: it does not appear in the OpenAPI schema, so `ain_backend` - a
  different service written against this one - has nothing to generate from,
  and a renamed key ships green and breaks the dashboard at runtime.

The services either side of it are `../savant-sink` (the module's ZeroMQ
output onto Kafka) and `../track-ingest` (Kafka into ClickHouse), and
`../geometry-editor` draws the shapes this one reads. The three Python
services share `../../libs/ain_analytics`, which is the config loader, the
ClickHouse client and the settings and nothing else - a shared library that
grows whatever its first caller wanted is how three services stop being able
to move independently.

## Clips

Rendered on demand and uploaded to the object store; the caller gets a
presigned link. The mp4 does not travel back through this service, and
retention is the bucket's lifecycle rule rather than a cache limit to tune
and a prune to race. The window can be up to twenty minutes, because a clip
has to be able to contain the thing it is evidence of - a long-wait alert
fires on a queue wait measured in minutes.

## When the boxes sit on where somebody was

A source adapter maps its RTSP stream onto wall-clock time once, when the
session opens, and every timestamp for the life of that session comes off
that one anchor. Anchor it while the encoder upstream is still starting and
the error is baked in until the adapter restarts - measured here at 3.5-3.7 s
on every camera after a cold start, which is where both the browser overlay
and the burnt-in clip boxes got their boxes from.

Two things stop it, both in `scripts/compose_gen.py`'s output: MediaMTX runs
the encoders with `runOnInit` so a stream exists before anything reads it,
and each adapter waits for its path to have been publishing for twenty
seconds before it connects. Cold-start error went from 3.5-3.7 s to
0.4-0.5 s.

To check, or after changing cameras or the transcode settings:

```bash
docker compose exec analytics-api python -m ain_api.calibrate
```

It needs no detector - movement between frames is ground truth for where a
person is - and prints what `AIN_OVERLAY_CLOCK_OFFSET_MS` should be. That
setting is the last resort for whatever latency is left; it shifts
timestamps only where they are served for DRAWING, and touches no stored row
and no aggregate.

## Settings

Every environment variable is declared in
`../../libs/ain_analytics/ain_analytics/settings.py`, with its default and
the reason for it. Nothing here calls `os.environ`.

Nothing here ever returns a formatted string, a severity or a sentence.
`ain_backend` owns all of that, because it is the service that ships Arabic.

## Editing the geometry

`../../config/cameras.yml` is the only place any of it lives - zone polygons,
counting lines, and which camera each belongs to. It is in `config/` rather
than in any one service because four things read it: this API, the ingest, the
sink and the compose generator.

Draw it rather than guessing at coordinates: `../geometry-editor`, on
<http://localhost:8101>. Adding or removing a CAMERA is still a command,
because it also means a new source adapter:

```bash
uv run scripts/compose_gen.py     # only when the camera LIST changes
```

Never the module. That is the whole point: a Savant manifest resolves its
interpolation once, at init, so geometry in `module.yml` would cost a GPU
restart per zone edit - and would make it impossible to move the entrance
line and recompute last month's footfall against it.

## Tests

```bash
uv run --all-extras pytest -q                      # here: the query layer
(cd ../../libs/ain_analytics && uv run --all-extras pytest -q)
docker compose run --rm --no-deps --entrypoint pytest track-ingest -q tests
```

The last one runs inside the ingest image, because `savant-rs` only exists
there and is not on PyPI.
