FROM python:3.12-slim

# libx264 lives in the ffmpeg package on Debian; ffprobe comes with it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Without this Python buffers stdout when it is not a TTY and "docker logs"
# stays empty until the buffer fills.
ENV PYTHONUNBUFFERED=1
# Both the server and the healthcheck below read the port from here, so
# overriding it keeps the two in step.
ENV RTSP_PORT=8554

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
# Documentation only, and only for the default: the port actually bound follows
# $RTSP_PORT, so publish whatever that is set to.
EXPOSE 8554/tcp

# DESCRIBE rather than OPTIONS: OPTIONS never looks at the path, so it would
# pass even if the configured stream did not resolve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,socket,sys\nport=int(os.environ.get('RTSP_PORT','8554'))\npath=os.environ.get('RTSP_PATH','live').strip('/')\nc=socket.create_connection(('127.0.0.1',port),3)\nc.sendall(('DESCRIBE rtsp://127.0.0.1:%d/%s RTSP/1.0\\r\\nCSeq: 1\\r\\nAccept: application/sdp\\r\\n\\r\\n' % (port,path)).encode())\nsys.exit(0 if b'RTSP/1.0 200' in c.recv(2048) else 1)"]

ENTRYPOINT ["rtsp-video-streaming"]
CMD ["/videos"]
