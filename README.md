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
