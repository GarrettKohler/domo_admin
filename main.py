#!/usr/bin/env python3
"""Domo Inventory Extraction Tool — CLI entry point.

Connects to the Domo API, extracts datasets (with schemas) and dataflows
(with lineage via DomoStats Governance datasets), and outputs a formatted
Excel workbook.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from domo_client import DomoAuthError, DomoClient
from excel_writer import write_workbook
from extractors import (
    extract_dataflow_lineage,
    extract_dataflows,
    extract_dataset_schemas,
    extract_datasets,
    rebuild_from_cache,
    save_cache,
)

load_dotenv()

logger = logging.getLogger("domo_extract")


def _progress_printer(label: str):
    """Return a callback that prints progress like '1/500... 50/500...'"""
    last_printed = [0]

    def callback(current: int, total: int):
        # Print at 1, then every 50, then at the end
        if current == 1 or current == total or current - last_printed[0] >= 50:
            print(f"  {label} {current}/{total}...")
            last_printed[0] = current

    return callback


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a full inventory from Domo into an Excel workbook."
    )
    parser.add_argument(
        "--output", "-o",
        default=".",
        help="Output directory for the Excel file (default: current directory)",
    )
    parser.add_argument(
        "--datasets-only",
        action="store_true",
        help="Extract only datasets and schemas (skip dataflows)",
    )
    parser.add_argument(
        "--dataflows-only",
        action="store_true",
        help="Extract only dataflows and lineage (skip datasets)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Authenticate and fetch the first page only (validate connectivity)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild workbook from cached API data (skips API calls, uses fresh definitions)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip saving API data to cache after extraction",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Handle --rebuild: skip API, load from cache, merge fresh definitions
    if args.rebuild:
        print("Rebuilding from cache...", end=" ", flush=True)
        result = rebuild_from_cache()
        if result is None:
            print("FAILED")
            print("Error: No cache found. Run a full extraction first to create the cache.")
            return 1
        datasets, schemas, dataflows, lineage, all_errors, cached_time = result
        extraction_time = datetime.now()
        print("✓")
        print(f"  Loaded from cache (originally extracted {cached_time})")
        print(f"  {len(datasets)} datasets, {len(schemas)} schema columns, {len(dataflows)} dataflows, {len(lineage)} lineage")

        # Jump straight to workbook writing (skip the API extraction below)
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"domo_inventory_{extraction_time.strftime('%Y%m%d')}.xlsx"
        output_path = output_dir / filename

        print("Writing Excel workbook...", end=" ", flush=True)
        write_workbook(
            output_path=str(output_path),
            datasets=datasets,
            schemas=schemas,
            dataflows=dataflows,
            lineage=lineage,
            errors=all_errors,
            extraction_time=extraction_time,
        )
        print("✓")
        print(f"Done! Output: {output_path}")
        return 0

    # Authenticate — prefers DOMO_ACCESS_TOKEN, falls back to DOMO_CLIENT_ID/SECRET.
    print("Authenticating with Domo API...", end=" ", flush=True)
    try:
        client = DomoClient.from_env()
        client.authenticate()
    except DomoAuthError as e:
        print("FAILED")
        print(f"Error: {e}")
        print("Create a .env file from .env.example or export credentials in your shell.")
        return 1
    except Exception as e:
        print("FAILED")
        print(f"Error: Could not connect to Domo API — {e}")
        return 1
    auth_mode = "developer token" if client.access_token else "OAuth2"
    print(f"✓ ({auth_mode}, {client.base_url})")

    if args.dry_run:
        print("Dry run: fetching first page of datasets...")
        datasets = client.list_datasets()
        print(f"  Found {len(datasets)} datasets on first page")
        print("Dry run complete — credentials and connectivity are valid.")
        return 0

    extraction_time = datetime.now()
    all_errors: list[dict[str, str]] = []

    # Extract datasets and schemas
    datasets = []
    schemas = []
    dataset_id_to_name: dict[str, str] = {}

    if not args.dataflows_only:
        print("Fetching datasets...", flush=True)
        datasets, ds_errors = extract_datasets(client)
        all_errors.extend(ds_errors)
        print(f"  Found {len(datasets)} datasets")

        # Build lookup for lineage name resolution
        dataset_id_to_name = {ds["dataset_id"]: ds["dataset_name"] for ds in datasets}

        print("Fetching dataset schemas...", flush=True)
        schemas, schema_errors = extract_dataset_schemas(
            client, datasets, progress_callback=_progress_printer("Schemas")
        )
        all_errors.extend(schema_errors)
        print(f"  Extracted {len(schemas)} columns across {len(datasets)} datasets")

    # Extract dataflows and lineage from DomoStats Governance datasets
    dataflows = []
    lineage = []
    if not args.datasets_only:
        print("Fetching dataflows from DomoStats...", flush=True)
        dataflows, df_errors = extract_dataflows(client, dataset_id_to_name)
        all_errors.extend(df_errors)
        print(f"  Found {len(dataflows)} dataflows")

        print("Fetching dataflow lineage from DomoStats...", flush=True)
        lineage, lin_errors = extract_dataflow_lineage(client, dataflows, dataset_id_to_name)
        all_errors.extend(lin_errors)
        print(f"  Mapped {len(lineage)} lineage relationships")

    # Save cache for future --rebuild runs
    if not args.no_cache:
        print("Saving cache...", end=" ", flush=True)
        cache_path = save_cache(
            datasets=datasets,
            schemas=schemas,
            dataflows=dataflows,
            lineage=lineage,
            errors=all_errors,
            extraction_time=extraction_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"✓ ({cache_path})")

    # Write workbook
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"domo_inventory_{extraction_time.strftime('%Y%m%d')}.xlsx"
    output_path = output_dir / filename

    print("Writing Excel workbook...", end=" ", flush=True)
    write_workbook(
        output_path=str(output_path),
        datasets=datasets,
        schemas=schemas,
        dataflows=dataflows,
        lineage=lineage,
        errors=all_errors,
        extraction_time=extraction_time,
    )
    print("✓")

    if all_errors:
        print(f"Warning: {len(all_errors)} item(s) were skipped due to errors (see Extraction Log tab)")

    print(f"Done! Output: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
