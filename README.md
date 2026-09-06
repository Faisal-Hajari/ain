# AIN

A video analytics dashboard.

```bash
docker compose up --build
```

Dashboard on http://localhost:3000, API on http://localhost:8000, and the ten
recordings in `videos/cctv` served as cameras by one MediaMTX server:

- **HLS**, `http://localhost:8888/cam3/` through `/cam15/` - what the tiles on
  the Cameras tab play. The dashboard proxies the same paths on its own origin,
  so `http://localhost:3000/cam3/` is the same stream.
- **RTSP**, `rtsp://localhost:8554/cam3` through `/cam15` (use
  `-rtsp_transport tcp`).

The recordings are H.265, which no browser plays; MediaMTX re-encodes each one
to H.264 on demand, when the first viewer opens it.

## Events

Detections are meant to ride one Kafka topic, `ain.events`, with ClickHouse
consuming it itself - a `Kafka` engine table feeding a materialized view - so
there is no consumer service to run and an analytics worker only has to
publish JSON.

**The schema is not written yet.** The broker and the server are in the
compose file and the API reads through `applications/backend/ain_backend/
store.py`, but nothing creates `ain.events`, so every read fails closed and
each card serves its generated payload instead. `/health` says `dummy` until
that changes and `clickhouse` after.

The row the API expects to read back:

```json
{"ts": "2026-09-06 13:42:11.000", "element_id": "no-mask-count",
 "camera_id": "05", "branch": "olaya", "venue": "cafe",
 "severity": "warn", "detail": "", "clip_url": "/api/clips/x.mp4"}
```

`element_id` is a catalogue id and `severity` is one of `ok`, `info`, `warn`
or `critical`; an unknown one is read as no judgement rather than failing the
card. An empty `detail` is filled in with the element's own description, so a
row still reads in Arabic.

An alert card's drilldown falls back per element rather than globally, so the
schema can land one card at a time.
