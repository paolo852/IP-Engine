#!/usr/bin/env sh
# Container entrypoint for the FORGE demo UI.
#
# Optional one-time setup, then serve. Toggle with env vars:
#   FORGE_AUTO_MIGRATE=1  -> run `forge db upgrade` before serving
#   FORGE_AUTO_SEED=1     -> load the synthetic demo data (offline) before serving
# FORGE_DATABASE_URL must point at a reachable Postgres (e.g. a Supabase project).
set -e

if [ -z "${FORGE_DATABASE_URL}" ]; then
  echo "error: FORGE_DATABASE_URL is not set" >&2
  exit 1
fi

if [ "${FORGE_AUTO_MIGRATE}" = "1" ]; then
  echo "[entrypoint] running migrations..."
  forge db upgrade
fi

if [ "${FORGE_AUTO_SEED}" = "1" ]; then
  echo "[entrypoint] seeding synthetic demo data..."
  forge seed || echo "[entrypoint] seed skipped/failed (continuing)"
fi

echo "[entrypoint] starting FORGE demo UI on ${FORGE_HOST:-0.0.0.0}:${PORT:-8000}"
exec forge serve --host "${FORGE_HOST:-0.0.0.0}" --port "${PORT:-8000}"
