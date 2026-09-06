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

To see a zone on the video while tuning it, open the Cameras tab and turn on
the **Zones** toggle: the same polygons this file declares are drawn over the
live tiles.

## Tests

```bash
uv run --all-extras pytest -q
docker compose run --rm --no-deps --entrypoint pytest track-ingest -q /app/tests
```

The second command runs the deserialiser's tests inside the ingest image,
because `savant-rs` only exists there.
