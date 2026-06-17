"""Ephemeral PostgreSQL cluster for self-contained tests.

If FORGE_TEST_DATABASE_URL (or FORGE_DATABASE_URL) is set, tests use it. Otherwise
this helper boots a throwaway local cluster from the system Postgres binaries, so
`pytest` works with zero setup. PostgreSQL refuses to run as root, so when invoked
as root we run the server under an unprivileged account (default: ``postgres``).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass


class PostgresUnavailable(RuntimeError):
    """Raised when no Postgres binaries are available to boot a cluster."""


def _find_bindir() -> str:
    for candidate in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if os.path.isfile(os.path.join(candidate, "initdb")):
            return candidate
    if shutil.which("initdb"):
        return os.path.dirname(shutil.which("initdb"))
    raise PostgresUnavailable("no PostgreSQL 'initdb' binary found")


def _unprivileged_user() -> str | None:
    """Account to own the cluster when we are root; None if we are not root."""
    if os.geteuid() != 0:
        return None
    import pwd

    for name in ("postgres", "ubuntu", "claude"):
        try:
            pwd.getpwnam(name)
            return name
        except KeyError:
            continue
    raise PostgresUnavailable("running as root but no unprivileged user available")


@dataclass
class EmbeddedPostgres:
    url: str
    _datadir: str
    _bindir: str
    _runas: str | None

    def stop(self) -> None:
        self._run([os.path.join(self._bindir, "pg_ctl"), "-D", self._datadir, "stop", "-m", "immediate"])
        shutil.rmtree(self._datadir, ignore_errors=True)

    def _run(
        self, args: list[str], check: bool = False, capture: bool = True
    ) -> subprocess.CompletedProcess:
        if self._runas:
            args = ["runuser", "-u", self._runas, "--"] + args
        if capture:
            return subprocess.run(args, check=check, capture_output=True, text=True)
        # No pipes: used for `pg_ctl start`, whose forked daemon would otherwise
        # inherit the stdout/stderr pipes and keep them open, hanging the caller.
        return subprocess.run(
            args, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def start_embedded(dbname: str = "forge_test", port: int = 5433) -> EmbeddedPostgres:
    bindir = _find_bindir()
    runas = _unprivileged_user()
    datadir = tempfile.mkdtemp(prefix="forge_pg_")
    sockdir = datadir  # unix socket lives inside the data dir

    if runas:
        shutil.chown(datadir, user=runas)

    pg = EmbeddedPostgres(url="", _datadir=datadir, _bindir=bindir, _runas=runas)

    init = pg._run(
        [os.path.join(bindir, "initdb"), "-D", datadir, "-U", "postgres", "--auth=trust"]
    )
    if init.returncode != 0:
        raise PostgresUnavailable(f"initdb failed: {init.stderr}")

    # Send the server's own output to a logfile (-l) so the daemon does not hold
    # the parent's stdout/stderr open. capture=False keeps subprocess from piping.
    logfile = os.path.join(datadir, "server.log")
    start = pg._run(
        [
            os.path.join(bindir, "pg_ctl"),
            "-D",
            datadir,
            "-l",
            logfile,
            "-o",
            f"-p {port} -k {sockdir} -c listen_addresses=''",
            "-w",
            "start",
        ],
        capture=False,
    )
    if start.returncode != 0:
        raise PostgresUnavailable("pg_ctl start failed; see server.log")

    # Wait for readiness, then create the database (fail loudly if it doesn't).
    ready = False
    for _ in range(50):
        if pg._run([os.path.join(bindir, "pg_isready"), "-h", sockdir, "-p", str(port)]).returncode == 0:
            ready = True
            break
        time.sleep(0.2)
    if not ready:
        raise PostgresUnavailable("Postgres did not become ready in time")

    created = pg._run(
        [os.path.join(bindir, "createdb"), "-h", sockdir, "-p", str(port), "-U", "postgres", dbname]
    )
    if created.returncode != 0:
        raise PostgresUnavailable(f"createdb failed: {created.stderr}")

    pg.url = f"postgresql+psycopg2://postgres@/{dbname}?host={sockdir}&port={port}"
    return pg
