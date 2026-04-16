#!/usr/bin/env python3
"""Push inferred descriptions to datasets that are missing them.

Reads the cache to identify datasets with no description, then applies
auto-generated descriptions from the analytics module.

Usage:
    python3 apply_descriptions.py --dry-run       # Preview (default)
    python3 apply_descriptions.py --execute        # Push to Domo
    python3 apply_descriptions.py --execute --only-empty   # Only datasets with no description
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from domo_client import DomoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOG_DIR = OUTPUT_DIR / "automation_logs"


def generate_description(ds: dict) -> str | None:
    """Generate a description for a dataset based on its metadata.

    Uses domain classification, column names, row count, and owner to
    build a concise, useful description.
    """
    from analytics import _classify_domain

    name = ds.get("dataset_name", "")
    domain, department = _classify_domain(name)

    # Build description from available metadata
    parts = []

    if domain and domain != "Unclassified":
        parts.append(f"{domain} domain dataset")
    else:
        parts.append("Dataset")

    if department:
        parts.append(f"({department})")

    # Add column summary if available
    columns = ds.get("columns", [])
    if columns:
        col_names = [c.get("name", "") for c in columns[:5]]
        if len(columns) > 5:
            col_summary = ", ".join(col_names) + f", and {len(columns) - 5} more columns"
        else:
            col_summary = ", ".join(col_names)
        parts.append(f"with columns: {col_summary}")

    # Add row count
    row_count = ds.get("row_count")
    if row_count:
        parts.append(f"({row_count:,} rows)")

    # Add owner context
    owner = ds.get("owner_name", "")
    if owner:
        parts.append(f"Owned by {owner}.")

    description = " ".join(parts)

    # Cap at a reasonable length
    if len(description) > 500:
        description = description[:497] + "..."

    return description


def load_datasets_needing_descriptions(only_empty: bool = True) -> list[dict]:
    """Load datasets from cache that need descriptions.

    If only_empty=True, only return datasets with no current description.
    If only_empty=False, return all datasets (will overwrite existing descriptions).
    """
    with open(CACHE_PATH, encoding="utf-8") as f:
        cache = json.load(f)

    candidates = []
    for ds in cache["datasets"]:
        current_desc = (ds.get("description") or "").strip()

        if only_empty and current_desc:
            continue

        new_desc = generate_description(ds)
        if new_desc and new_desc != current_desc:
            candidates.append({
                "id": ds["dataset_id"],
                "name": ds.get("dataset_name", ""),
                "current_description": current_desc,
                "new_description": new_desc,
            })

    return candidates


def apply_descriptions(candidates: list[dict], dry_run: bool = True) -> dict:
    """Push descriptions to Domo via the API."""
    stats = {"total": len(candidates), "success": 0, "failed": 0, "dry_run": dry_run}

    if not candidates:
        logger.info("No datasets need descriptions.")
        return stats

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"descriptions_{timestamp}.csv"

    if dry_run:
        logger.info("\n" + "=" * 70)
        logger.info("DRY RUN — No changes will be made")
        logger.info("=" * 70)
        logger.info("Would update descriptions for %d datasets\n", len(candidates))

        with open(log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["dataset_id", "name", "new_description", "status"])
            for c in candidates[:20]:  # Show first 20 in console
                logger.info("  %s: %s", c["name"][:40], c["new_description"][:80])
                writer.writerow([c["id"], c["name"], c["new_description"], "dry_run"])
            for c in candidates[20:]:
                writer.writerow([c["id"], c["name"], c["new_description"], "dry_run"])

        if len(candidates) > 20:
            logger.info("  ... and %d more (see log file)", len(candidates) - 20)

        logger.info("\nDry run log saved to: %s", log_path)
        return stats

    # Live execution
    client = DomoClient(
        client_id=os.environ["DOMO_CLIENT_ID"],
        client_secret=os.environ["DOMO_CLIENT_SECRET"],
    )
    client.authenticate()
    logger.info("Authenticated with Domo API")

    results = []
    for i, c in enumerate(candidates, 1):
        logger.info("[%d/%d] Updating description for %s", i, len(candidates), c["name"][:50])

        result = client.update_dataset(c["id"], description=c["new_description"])
        if result:
            stats["success"] += 1
            results.append([c["id"], c["name"], c["new_description"], "success"])
        else:
            stats["failed"] += 1
            results.append([c["id"], c["name"], c["new_description"], "failed"])
            logger.error("  Failed: %s", c["id"])

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset_id", "name", "new_description", "status"])
        writer.writerows(results)

    logger.info("\nResults log saved to: %s", log_path)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Push inferred descriptions to Domo datasets")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview changes without applying (default: True)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually push descriptions (overrides --dry-run)")
    parser.add_argument("--only-empty", action="store_true", default=True,
                        help="Only update datasets with no existing description (default: True)")
    parser.add_argument("--all", action="store_true",
                        help="Update all datasets, even those with existing descriptions")
    args = parser.parse_args()

    dry_run = not args.execute
    only_empty = not args.all

    candidates = load_datasets_needing_descriptions(only_empty=only_empty)
    logger.info("Found %d datasets needing descriptions", len(candidates))

    stats = apply_descriptions(candidates, dry_run=dry_run)

    print(f"\n{'=' * 60}")
    print("DESCRIPTION UPDATE SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Mode:       {'DRY RUN' if stats['dry_run'] else 'LIVE'}")
    print(f"  Candidates: {stats['total']}")
    if not dry_run:
        print(f"  Success:    {stats['success']}")
        print(f"  Failed:     {stats['failed']}")


if __name__ == "__main__":
    main()
