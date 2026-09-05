FROM python:3.12-slim

# libx264 lives in the ffmpeg package on Debian; ffprobe comes with it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --system --create-home app \
 && mkdir -p /videos \
 && chown app /videos
USER app

# Mount the folder of videos here.
VOLUME ["/videos"]
EXPOSE 8554/tcp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import socket,sys\ns=socket.create_connection(('127.0.0.1',8554),3)\ns.sendall(b'OPTIONS rtsp://127.0.0.1:8554/live RTSP/1.0\\r\\nCSeq: 1\\r\\n\\r\\n')\nsys.exit(0 if b'200' in s.recv(1024) else 1)"]

ENTRYPOINT ["rtsp-video-streaming"]
CMD ["/videos"]
