# FORGE Mining Engine — demo web UI container.
#
# Builds the engine with the 'web' extra and serves the FastAPI demo UI. The
# database is external (point FORGE_DATABASE_URL at any Postgres, e.g. a Supabase
# project). The entrypoint can optionally migrate and seed on startup.
FROM python:3.11-slim

# psycopg2-binary ships its own libpq, so no system build deps are needed.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    FORGE_HOST=0.0.0.0

WORKDIR /app

# Install dependencies first (better layer caching), then the source.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install '.[web]'

# Runtime files alembic + the engine read relative to the working directory.
COPY alembic.ini ./
COPY config ./config
COPY data ./data
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
RUN chmod +x ./scripts/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./scripts/entrypoint.sh"]
