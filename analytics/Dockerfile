# Two entrypoints, two bases, one package.
#
# The API is an ordinary FastAPI service and gets an ordinary slim image.
# The ingest consumer cannot: it deserialises savant-rs messages, that wheel
# is not published on PyPI, and its format is versioned - so it is built on
# the same Savant adapters image that produced the messages, which is the
# only way the two ends are guaranteed to agree.

# ---------------------------------------------------------------- api ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS api-builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra api

COPY ain_analytics ./ain_analytics


FROM python:3.12-slim-bookworm AS api

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AIN_CAMERAS_YML=/app/cameras.yml

# ffmpeg encodes the clips: OpenCV writes MPEG-4 Part 2, which no browser
# plays, and the tiles already play H.264. libgl1/libglib are what
# opencv-python-headless still links against.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10002 ain

# The clips volume mounts here. Docker seeds an empty named volume from the
# image, ownership included, so creating it as `ain` now is what lets a
# non-root service write to it later.
RUN mkdir -p /clips && chown ain:ain /clips

COPY --from=api-builder --chown=ain:ain /app/.venv /app/.venv
COPY --from=api-builder --chown=ain:ain /app/ain_analytics /app/ain_analytics
COPY --chown=ain:ain cameras.yml /app/cameras.yml

USER ain

EXPOSE 8100

CMD ["uvicorn", "ain_analytics.api:app", "--host", "0.0.0.0", "--port", "8100"]


# ------------------------------------------------------------- ingest ----
FROM ghcr.io/insight-platform/savant-adapters-py:latest AS ingest

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    AIN_CAMERAS_YML=/app/cameras.yml

# savant-rs and confluent-kafka are already in this image, at the versions
# the sink adapter publishes with. Only the two shared dependencies are
# added, and neither pulls OpenCV - installing another OpenCV over a Savant
# image breaks the CUDA-built one it ships.
# pytest rides along because this is the one module that cannot be tested
# anywhere else: savant-rs is not on PyPI, so the deserialiser can only be
# exercised where the deserialiser lives.
#
#   docker compose run --rm --no-deps --entrypoint pytest track-ingest -q
RUN pip install --no-cache-dir \
    'clickhouse-connect>=0.8.0' 'pyyaml>=6.0' 'pytest>=8.0'

COPY ain_analytics /app/ain_analytics
COPY tests/test_ingest.py /app/tests/test_ingest.py
COPY cameras.yml /app/cameras.yml

ENTRYPOINT []
CMD ["python", "-m", "ain_analytics.ingest"]

