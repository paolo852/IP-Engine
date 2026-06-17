"""Run the EPO OPS connector for one or more publication numbers.

Independently runnable (rule: connectors modular and independently runnable):

    export FORGE_DATABASE_URL=...        # see scripts/pg_dev.sh
    export FORGE_EPO_OPS_KEY=...         # OPS OAuth2 consumer key
    export FORGE_EPO_OPS_SECRET=...      # OPS OAuth2 consumer secret
    python scripts/ingest_epo_ops.py EP1000000 EP1000001

Hits the live OPS API, so it needs credentials and network. The test suite uses
recorded fixtures instead and needs neither.
"""

from __future__ import annotations

import os
import sys

from forge.config import load_connectors_config
from forge.connectors.epo_ops import EpoOpsConnector, OpsClient, OpsSettings
from forge.db.base import create_db_engine, make_session_factory


def main(argv: list[str]) -> int:
    refs = argv[1:]
    if not refs:
        print("usage: ingest_epo_ops.py REF [REF ...]", file=sys.stderr)
        return 2

    config_path = os.environ.get("FORGE_CONNECTORS_CONFIG", "config/connectors.yaml")
    settings = OpsSettings.from_config(load_connectors_config(config_path))
    connector = EpoOpsConnector(OpsClient(settings))

    session = make_session_factory(create_db_engine())()
    report = connector.run(refs, session)

    print(f"EPO OPS ingest: {report.summary()}")
    for failure in report.failed:
        print(f"  FAILED {failure.ref} [{failure.stage}]: {failure.error}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
