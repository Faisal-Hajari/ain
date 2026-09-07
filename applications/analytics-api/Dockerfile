# Built from the REPO ROOT, and laid out inside the image exactly as the repo
# is laid out. Both are forced by the same thing: the service depends on
# libs/ain_analytics by relative path, so the library has to be in the build
# context AND has to sit the same number of directories above the service as
# it does in the repo. Flattening this to /app makes `../../libs` climb above
# the filesystem root and uv refuses to resolve it.
#
#   docker compose build analytics-api

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /src/applications/analytics-api

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# The library first: it changes far less often than the service, and a path
# dependency has to exist before `uv sync` can resolve it.
COPY libs/ain_analytics /src/libs/ain_analytics
COPY applications/analytics-api/pyproject.toml applications/analytics-api/uv.lock ./
RUN uv sync --locked --no-dev

COPY applications/analytics-api/ain_api ./ain_api


FROM python:3.12-slim-bookworm AS runtime

WORKDIR /src/applications/analytics-api

ENV PATH="/src/applications/analytics-api/.venv/bin:$PATH" \
    PYTHONPATH=/src/applications/analytics-api \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AIN_CAMERAS_YML=/src/config/cameras.yml

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

# The venv stays at the path it was built at: uv writes absolute shebangs
# into its console scripts, and an editable install records where its source
# lives. Moving it to /app would break both.
COPY --from=builder --chown=ain:ain /src/libs/ain_analytics /src/libs/ain_analytics
COPY --from=builder --chown=ain:ain \
     /src/applications/analytics-api/.venv /src/applications/analytics-api/.venv
COPY --from=builder --chown=ain:ain \
     /src/applications/analytics-api/ain_api /src/applications/analytics-api/ain_api
# cameras.yml is NOT copied in. It is bind-mounted from config/, because the
# editor writes to it and a baked copy would be a second answer to "what is
# the geometry" that goes stale the first time anybody saves.

USER ain

EXPOSE 8100

CMD ["uvicorn", "ain_api.api:app", "--host", "0.0.0.0", "--port", "8100"]
