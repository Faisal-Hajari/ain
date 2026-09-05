FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first so a code change does not re-resolve them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY ain_backend ./ain_backend

EXPOSE 8000

CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "ain_backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
