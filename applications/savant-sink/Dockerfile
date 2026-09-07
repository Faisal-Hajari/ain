# Reads the Savant module's ZeroMQ output and relays it onto Kafka.
#
# Built on the Savant adapters image, and that is not a preference: this
# service speaks savant-rs, that wheel is not published on PyPI, and its
# message format is versioned. Building on the image that produced the bytes
# is the only way the two ends are guaranteed to agree. Pinned by digest for
# the same reason - :latest on both ends is how they silently stop agreeing.
#
# Built from the REPO ROOT and laid out the way the repo is, like the API,
# because it shares libs/ain_analytics with it.
FROM ghcr.io/insight-platform/savant-adapters-py@sha256:4b09a32cd5ded9459f3f834f4a6263263f4edb4ac7cb70ab7cfb059201e81f3c

WORKDIR /src/applications/savant-sink

ENV PYTHONPATH=/src/applications/savant-sink:/src/libs/ain_analytics \
    PYTHONUNBUFFERED=1 \
    AIN_CAMERAS_YML=/src/config/cameras.yml

# savant-rs and confluent-kafka are already here, at the versions the adapter
# publishes with. Only the shared library's two dependencies are added, and
# neither pulls OpenCV - installing another OpenCV over this image breaks the
# CUDA-built one it ships. `uv sync` is deliberately not used here: it would
# build a fresh environment and lose exactly the wheels this image exists for.
RUN pip install --no-cache-dir 'clickhouse-connect>=0.8.0' 'pyyaml>=6.0' 'pytest>=8.0'

COPY libs/ain_analytics/ain_analytics /src/libs/ain_analytics/ain_analytics
COPY applications/savant-sink/ain_sink ./ain_sink

ENTRYPOINT []
CMD ["python", "-m", "ain_sink"]
