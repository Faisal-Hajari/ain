# AIN

A video analytics dashboard, and the computer vision behind it.

```bash
uv run analytics/compose_gen.py     # once, and after any cameras.yml edit
docker compose up --build
```

Dashboard on http://localhost:3000, API on http://localhost:8000, analytics API
on http://localhost:8100, and the ten recordings in `videos/cctv` served as
cameras by one MediaMTX server:

- **HLS**, `http://localhost:8888/cam3/` through `/cam15/` - what the tiles on
  the Cameras tab play. The dashboard proxies the same paths on its own origin,
  so `http://localhost:3000/cam3/` is the same stream.
- **RTSP**, `rtsp://localhost:8554/cam3` through `/cam15` (use
  `-rtsp_transport tcp`).

The recordings are H.265, which no browser plays; MediaMTX re-encodes each one
to H.264. All ten transcodes run continuously, because the pipeline is a
permanent reader on every path.

## What computes the numbers

```
videos/cctv/*.mp4  (H.265)
        │
        ▼
   MediaMTX ──────────── HLS (H.264) ──────────► browser <video>
        │  RTSP                                        ▲
        ▼                                              │ boxes drawn on <canvas>
 savant-source-NN  (one per camera)                    │
        │  ZeroMQ                                      │
        ▼                                              │
  savant-module  (GPU: detect + track, no encoding)    │
        │  ZeroMQ                                      │
        ▼                                              │
 savant-kafka-sink ──► kafka ──► track-ingest ──► clickhouse
                                                       │
                                                  analytics-api
                                                       │
                                                  backend ──► frontend
```

**The pipeline is dumb on purpose.** It finds people, tracks them, and emits
boxes. Zones, lines, thresholds, dwell and counting all happen in SQL over the
stored rows, which is what makes the geometry editable without touching the GPU
and what makes it possible to move the entrance line and recompute last month.

`analytics/cameras.yml` is the only place any of that geometry lives. It drives
the compose generator, the query layer and the browser overlay, and editing it
is a restart of `analytics-api` - never of the module.

## Requirements

The pipeline needs an Nvidia GPU (Turing or newer) and the
[NVIDIA container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
Without one, `savant-module` crash-loops and every KPI falls back to the
generated data the dashboard has always served - it degrades rather than
failing, which is also what happens for the first ten minutes of a fresh
install while TensorRT builds its engine. To build that engine ahead of time:

```bash
docker compose run --rm --no-deps savant-module --build-engines /opt/savant/module.yml
```

Roughly 5 GB of disk for the images, plus whatever MediaMTX's 15-minute
recording window costs (~4 GB across ten cameras), plus ClickHouse.

## Tests

```bash
cd applications/backend && uv run pytest -q
cd analytics && uv run --all-extras pytest -q
cd applications/frontend && npm ci && npm run typecheck && npm test && npm run lint
docker compose run --rm --no-deps --entrypoint pytest track-ingest -q /app/tests
```

The last one runs in the ingest image because it needs `savant-rs`, which is
not published on PyPI - the Kafka payload is a savant-rs binary blob, so the
deserialiser can only be exercised where the deserialiser lives.
