"""Show the dormancy rules classifying a few synthetic assets — the slice-3 demo.

    python scripts/dormancy_demo.py

Pure computation: no database or network needed. Synthetic data only (rule 4).
"""

from __future__ import annotations

from datetime import date

from forge.config import load_dormancy_config, load_organisation_config
from forge.db.models import Asset, AssetType
from forge.dormancy import assess_asset

AS_OF = date(2025, 1, 1)


def main() -> int:
    config = load_dormancy_config("config/dormancy.yaml")
    org = load_organisation_config("config/organisation.yaml")

    examples = [
        Asset(
            asset_type=AssetType.patent, source_layer="L1.synthetic",
            title="Dormant photonic interconnect",
            key_dates={"filing_date": "2020-01-01"}, fee_status="lapsing",
            encumbrances="none recorded",
        ),
        Asset(
            asset_type=AssetType.patent, source_layer="L1.synthetic",
            title="Recently filed (too young)",
            key_dates={"filing_date": "2023-06-01"}, fee_status="paid",
        ),
        Asset(
            asset_type=AssetType.project_result, source_layer="L1.synthetic",
            title="Shelved EU project result",
            key_dates={"end_date": "2022-01-01"}, owners=["Synthetic Research Org"],
        ),
    ]

    for asset in examples:
        result = assess_asset(asset, config, as_of=AS_OF, org=org)
        print(f"\n# {asset.title}")
        print(result.explanation())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
