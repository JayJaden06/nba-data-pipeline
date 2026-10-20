# One image for both workloads:
#   ingest (default):  docker run IMAGE ingest --date 2026-03-15
#   checks:            docker run IMAGE check --date 2026-03-15
#   migrations:        docker run --entrypoint alembic IMAGE upgrade head
#   read API:          docker run -p 8000:8000 --entrypoint uvicorn IMAGE \
#                        nba_pipeline.api.app:app --host 0.0.0.0 --port 8000

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so code changes reuse the cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
ENTRYPOINT ["nba-pipeline"]
CMD ["ingest"]
