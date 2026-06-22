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

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG SOURCE_URL=https://example.invalid/toolwatch

ENV PATH="/app/.venv/bin:$PATH" \
    HOME="/tmp" \
    TMPDIR="/tmp" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.title="ToolWatch" \
      org.opencontainers.image.description="Experimental observability and runtime-safety proxy for AI-agent tool calls" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --system toolwatch \
    && useradd --system --gid toolwatch --home-dir /app toolwatch

WORKDIR /app
COPY --from=builder --chown=toolwatch:toolwatch /app/.venv /app/.venv
COPY --chown=toolwatch:toolwatch src ./src
COPY --chown=toolwatch:toolwatch alembic ./alembic
COPY --chown=toolwatch:toolwatch alembic.ini ./

USER toolwatch
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["uvicorn", "toolwatch.main:app", "--host", "0.0.0.0", "--port", "8000"]
