"""Round-trip a synthetic asset through the L2 store — the slice-1 demo.

Usage (after `eval "$(scripts/pg_dev.sh)"` and `alembic upgrade head`):

    python scripts/roundtrip_demo.py

Prints the asset as loaded back from Postgres, with the source grounding each
factual field. Synthetic data only.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running the synthetic fixtures without installing the test package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from forge.db.base import create_db_engine, make_session_factory  # noqa: E402
from forge.repository import get_asset, provenance_map, save_asset  # noqa: E402
from synthetic.assets import synthetic_patent_bundle  # noqa: E402


def main() -> int:
    engine = create_db_engine()
    session = make_session_factory(engine)()

    saved = save_asset(session, synthetic_patent_bundle())
    print(f"saved asset {saved.id}")

    session.expunge_all()
    loaded = get_asset(session, saved.id)
    assert loaded is not None

    print(f"\nasset_type : {loaded.asset_type.value}")
    print(f"title      : {loaded.title}")
    print(f"fee_status : {loaded.fee_status}")
    print(f"key_dates  : {loaded.key_dates}")

    print("\nprovenance (field -> source.locator [licence]):")
    for field, sources in sorted(provenance_map(loaded).items()):
        for s in sources:
            print(f"  {field:<22} <- {s.locator} [{s.licence.value}]")

    print("\nround-trip OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
