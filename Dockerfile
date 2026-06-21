FROM ghcr.io/astral-sh/uv:0.11.23 AS uv

FROM python:3.13-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system toolwatch \
    && useradd --system --gid toolwatch --home-dir /app toolwatch

WORKDIR /app
COPY --from=builder --chown=toolwatch:toolwatch /app/.venv /app/.venv
COPY --chown=toolwatch:toolwatch src ./src
COPY --chown=toolwatch:toolwatch alembic ./alembic
COPY --chown=toolwatch:toolwatch alembic.ini ./

USER toolwatch
EXPOSE 8000

CMD ["uvicorn", "toolwatch.main:app", "--host", "0.0.0.0", "--port", "8000"]
