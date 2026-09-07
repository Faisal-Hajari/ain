# AIN

A video analytics dashboard, and the computer vision behind it.

```bash
uv run scripts/compose_gen.py     # once, and after any cameras.yml edit
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

The recordings are H.265, which no browser plays; MediaMTX re-encodes to H.264
on demand.

**The pipeline watches five of the ten: 03, 04, 05, 06 and 12.** Each one it
watches is a transcode that never stops, because the Savant adapter is a
permanent reader - ten of them saturated the host. Those five cover every KPI
the dashboard computes: `indoor` and the entrance line (03, 04), the `queue`
(12), the kitchen (05) and `outdoor` (06). The other five stay on the Cameras
tab and report **no signal**, which is what they are: nothing is looking at
them, so there is no feed to show and no transcode running for them.

Which five is one list, `cameras:` in `config/cameras.yml`. Add one back
with a line there and `uv run scripts/compose_gen.py`.

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

`config/cameras.yml` is the only place any of that geometry lives. It drives
the compose generator, the query layer and the browser overlay, and editing it
never restarts the module.

**To draw the zones rather than guess at coordinates**, open
<http://localhost:8101>: a still from each camera with the shapes it already
has drawn over it, click to add new ones, and a Save button that writes
`config/cameras.yml` back - comments and all.

Every environment variable the services read is declared in one file each -
`libs/ain_analytics/ain_analytics/settings.py` and
`applications/backend/ain_backend/settings.py` - with its default and the
reason for it. There is no `os.environ` anywhere else.

## Layout

```
config/       cameras.yml - the geometry, read by four things and owned by none
scripts/      compose_gen.py - writes the per-camera half of the compose stack
libs/         ain_analytics - what more than one service needs: the config
              loader and the ClickHouse client
applications/ one directory per running service
  backend/          the dashboard's API, and every string a human reads
  frontend/         React, the only thing that renders
  analytics-api/    the KPI query layer
  geometry-editor/  one page for drawing zones, and a proxy
  track-ingest/     Kafka -> ClickHouse
  savant-sink/      the module's ZeroMQ output -> Kafka
  savant-module/    module.yml, the only thing on the GPU
  cameras/          mediamtx.yml, the RTSP and HLS server
videos/cctv/  the recordings the cameras play
```

The three analytics services build from the repo root, because each depends on
`libs/ain_analytics` by relative path and a build context that cannot see the
library cannot install it.

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

Roughly 5 GB of disk for the images, plus MediaMTX's two-hour recording
window (~10 GB across the five watched cameras), plus ClickHouse. Budget
about three CPU cores for the transcodes and a couple of GB of VRAM.

That two hours is what alert clips are cut from, so it is also how far back
a "Watch clip" button works. An occurrence older than it says **no video
kept** rather than offering a link that 404s.

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
