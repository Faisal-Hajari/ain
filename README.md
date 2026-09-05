# AIN

A video analytics dashboard.

```bash
docker compose up --build
```

Dashboard on http://localhost:3000, API on http://localhost:8000, and the ten
recordings in `videos/cctv` served as cameras on `rtsp://localhost:8554/cam3`
through `/cam15` (use `-rtsp_transport tcp`). The cameras used to be one
container each on ports 8603-8615; they are now ten paths on one MediaMTX
server, so only the port changed.
