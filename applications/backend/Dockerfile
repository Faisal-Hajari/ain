# Build the virtualenv with uv, then hand it to a runtime image that has
# no build tooling in it.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Dependencies resolve in their own layer, so a code change does not
# reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY ain_backend ./ain_backend


FROM python:3.12-slim-bookworm AS runtime

# The venv is built against /app/.venv, so the path has to match.
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 ain

COPY --from=builder --chown=ain:ain /app/.venv /app/.venv
COPY --from=builder --chown=ain:ain /app/ain_backend /app/ain_backend

USER ain

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; \
        urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "ain_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
