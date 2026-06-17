#!/usr/bin/env bash
# Boot a throwaway local PostgreSQL cluster for development and print a matching
# FORGE_DATABASE_URL. Intended for dev only — synthetic data, no secrets.
#
#   eval "$(scripts/pg_dev.sh)"   # exports FORGE_DATABASE_URL into your shell
#
# PostgreSQL refuses to run as root; when root we run it under the 'postgres' user.
set -euo pipefail

PORT="${FORGE_PG_PORT:-5433}"
DBNAME="${FORGE_PG_DB:-forge}"
DATADIR="${FORGE_PG_DATADIR:-/tmp/forge_pgdata}"
BINDIR="$(dirname "$(ls -d /usr/lib/postgresql/*/bin/initdb 2>/dev/null | sort -r | head -1)")"

if [ -z "${BINDIR}" ]; then
  echo "no PostgreSQL binaries found under /usr/lib/postgresql/*/bin" >&2
  exit 1
fi

RUNAS=""
if [ "$(id -u)" = "0" ]; then
  RUNAS="runuser -u postgres --"
  install -d -o postgres -g postgres "$(dirname "${DATADIR}")" "${DATADIR}" 2>/dev/null || true
  chown postgres:postgres "${DATADIR}"
fi

if [ ! -s "${DATADIR}/PG_VERSION" ]; then
  ${RUNAS} "${BINDIR}/initdb" -D "${DATADIR}" -U postgres --auth=trust >/dev/null
fi

if ! ${RUNAS} "${BINDIR}/pg_isready" -h "${DATADIR}" -p "${PORT}" >/dev/null 2>&1; then
  ${RUNAS} "${BINDIR}/pg_ctl" -D "${DATADIR}" \
    -o "-p ${PORT} -k ${DATADIR} -c listen_addresses=''" -w start >/dev/null
fi

${RUNAS} "${BINDIR}/createdb" -h "${DATADIR}" -p "${PORT}" -U postgres "${DBNAME}" 2>/dev/null || true

echo "export FORGE_DATABASE_URL=\"postgresql+psycopg2://postgres@/${DBNAME}?host=${DATADIR}&port=${PORT}\""
