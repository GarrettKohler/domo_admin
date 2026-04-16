#!/usr/bin/env python3
"""Populate `.cache/latest.json` with datasets + dataflows only (no schemas).

This is a fast-path alternative to ``python3 main.py`` for the common case
where the UI just needs the inventory lists. Schemas are the slow part of a
full extract (2,300+ individual detail calls × 0.6s rate limit ≈ 23 min).
Skipping them gets the cache populated in well under a minute.

Run the full ``python3 main.py`` when you actually need column-level data
for the Excel workbook or downstream analytics.
"""
from __future__ import annotations

import sys
from datetime import datetime

from dotenv import load_dotenv

from domo_client import DomoAuthError, DomoClient
from extractors import (
    extract_dataflow_lineage,
    extract_dataflows,
    extract_datasets,
    save_cache,
)

load_dotenv()


def main() -> int:
    print("Quick cache build (skips schema fetches)")
    try:
        client = DomoClient.from_env()
        client.authenticate()
    except DomoAuthError as exc:
        print(f"Auth error: {exc}")
        return 1

    auth_mode = "developer token" if client.access_token else "OAuth2"
    print(f"  auth: {auth_mode} @ {client.base_url}")

    extraction_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errors: list[dict[str, str]] = []

    print("Fetching datasets...", flush=True)
    datasets, ds_errors = extract_datasets(client)
    errors.extend(ds_errors)
    print(f"  {len(datasets):,} datasets")

    dataset_id_to_name = {ds["dataset_id"]: ds["dataset_name"] for ds in datasets}

    print("Fetching dataflows (via DomoStats)...", flush=True)
    dataflows, df_errors = extract_dataflows(client, dataset_id_to_name)
    errors.extend(df_errors)
    print(f"  {len(dataflows):,} dataflows")

    print("Fetching lineage...", flush=True)
    lineage, lin_errors = extract_dataflow_lineage(client, dataflows, dataset_id_to_name)
    errors.extend(lin_errors)
    print(f"  {len(lineage):,} lineage rows")

    cache_path = save_cache(
        datasets=datasets,
        schemas=[],  # Intentionally empty — run main.py for the full set
        dataflows=dataflows,
        lineage=lineage,
        errors=errors,
        extraction_time=extraction_time,
    )
    print(f"Cache: {cache_path}")
    print("Done. Reload the Streamlit UI to see the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
