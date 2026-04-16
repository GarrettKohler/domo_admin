#!/usr/bin/env python3
"""Transfer ownership of datasets from former employees to current owners.

Reads the cache to identify datasets/dataflows owned by former employees
and reassigns them to specified current team members.

Usage:
    python3 transfer_ownership.py --dry-run                     # Preview (default)
    python3 transfer_ownership.py --execute                      # Transfer all
    python3 transfer_ownership.py --execute --target-owner "Garrett Kohler"  # Specific owner
    python3 transfer_ownership.py --execute --mapping owners.csv # From mapping file
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

# Known former employees — these Domo user IDs own dataflows but don't
# resolve to any current dataset owner. Identified from cache analysis on
# 2026-04-12. The IDs are used because these accounts no longer have
# human-readable names in the Domo inventory.
#
# To find these: dataflow owner_ids that don't match any dataset owner_id.
# Total: 121 dataflows across 11 former-employee accounts.
FORMER_EMPLOYEE_IDS = {
    "1164580851",   # 38 dataflows
    "482474271",    # 18 dataflows
    "1162106314",   # 17 dataflows
    "1960308144",   # 15 dataflows
    "645664158",    # 12 dataflows
    "521647651",    #  8 dataflows
    "858744214",    #  6 dataflows
    "2040603854",   #  4 dataflows
    "698445125",    #  1 dataflow
    "1540926796",   #  1 dataflow
    "2089963288",   #  1 dataflow
}

# Name-based matching for any future additions (case-insensitive).
FORMER_EMPLOYEES = {
    # Add former employee names here if they still resolve in the system:
    # "Jane Smith",
}

# Default target owner for bulk reassignment (Domo user ID).
# Override with --target-owner or --mapping flag.
DEFAULT_TARGET_OWNER_NAME = "Garrett Kohler"


def load_orphaned_items() -> list[dict]:
    """Load datasets and dataflows owned by former employees from cache."""
    with open(CACHE_PATH, encoding="utf-8") as f:
        cache = json.load(f)

    orphaned = []

    # Check datasets
    for ds in cache.get("datasets", []):
        owner_name = ds.get("owner_name", "")
        owner_id = str(ds.get("owner_id", ""))

        if _is_former_employee(owner_name, owner_id):
            orphaned.append({
                "id": ds["dataset_id"],
                "name": ds.get("dataset_name", ""),
                "type": "dataset",
                "current_owner_name": owner_name or f"Unknown (ID: {owner_id})",
                "current_owner_id": owner_id,
            })

    # Check dataflows
    for df in cache.get("dataflows", []):
        owner_name = df.get("owner_name", "")
        owner_id = str(df.get("owner_id", ""))

        if _is_former_employee(owner_name, owner_id):
            orphaned.append({
                "id": df["dataflow_id"],
                "name": df.get("dataflow_name", ""),
                "type": "dataflow",
                "current_owner_name": owner_name or f"Unknown (ID: {owner_id})",
                "current_owner_id": owner_id,
            })

    return orphaned


def _is_former_employee(name: str, owner_id: str = "") -> bool:
    """Check if an owner matches the former employees list (by name or ID)."""
    if owner_id and str(owner_id) in FORMER_EMPLOYEE_IDS:
        return True
    if not name:
        return False
    name_lower = name.strip().lower()
    return any(fe.lower() == name_lower for fe in FORMER_EMPLOYEES)


def load_owner_mapping(mapping_path: str) -> dict[str, str]:
    """Load a CSV mapping of former_owner_name -> new_owner_id.

    CSV format: former_owner_name,new_owner_id,new_owner_name
    """
    mapping = {}
    with open(mapping_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            former = row.get("former_owner_name", "").strip()
            new_id = row.get("new_owner_id", "").strip()
            if former and new_id:
                mapping[former.lower()] = new_id
    return mapping


def resolve_target_owner(client: DomoClient, target_name: str) -> str | None:
    """Look up a Domo user ID by name. Returns user_id or None."""
    # The Domo API doesn't have a direct user search, so we'll check
    # the cache for known owner IDs, or the caller should provide the ID directly.
    with open(CACHE_PATH, encoding="utf-8") as f:
        cache = json.load(f)

    # Build owner lookup from datasets
    for ds in cache.get("datasets", []):
        if ds.get("owner_name", "").lower() == target_name.lower():
            return ds.get("owner_id")

    logger.warning("Could not find Domo user ID for '%s' in cache", target_name)
    return None


def apply_transfers(
    orphaned: list[dict],
    target_owner_id: str | None = None,
    owner_mapping: dict[str, str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Transfer dataset ownership via the Domo API."""
    # Only datasets can be transferred via API
    dataset_items = [item for item in orphaned if item["type"] == "dataset"]
    dataflow_items = [item for item in orphaned if item["type"] == "dataflow"]

    if dataflow_items:
        logger.warning(
            "Skipping %d dataflow transfers — dataflow ownership cannot be changed via API",
            len(dataflow_items),
        )

    stats = {
        "total": len(dataset_items),
        "success": 0,
        "failed": 0,
        "skipped_no_target": 0,
        "skipped_dataflows": len(dataflow_items),
        "dry_run": dry_run,
    }

    if not dataset_items:
        logger.info("No datasets to transfer.")
        return stats

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"transfers_{timestamp}.csv"

    if dry_run:
        logger.info("\n" + "=" * 70)
        logger.info("DRY RUN — No ownership changes will be made")
        logger.info("=" * 70)
        logger.info("Would transfer %d datasets:\n", len(dataset_items))

        with open(log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["dataset_id", "name", "current_owner", "new_owner_id", "status"])
            for item in dataset_items:
                new_id = _get_target_id(item, target_owner_id, owner_mapping)
                status = "dry_run" if new_id else "no_target"
                logger.info("  %s (owner: %s) → %s", item["name"][:50], item["current_owner_name"], new_id or "NO TARGET")
                writer.writerow([item["id"], item["name"], item["current_owner_name"], new_id or "", status])

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
    for i, item in enumerate(dataset_items, 1):
        new_id = _get_target_id(item, target_owner_id, owner_mapping)
        if not new_id:
            stats["skipped_no_target"] += 1
            results.append([item["id"], item["name"], item["current_owner_name"], "", "skipped_no_target"])
            logger.warning("[%d/%d] Skipping %s — no target owner mapped", i, len(dataset_items), item["name"][:50])
            continue

        logger.info("[%d/%d] Transferring %s → %s", i, len(dataset_items), item["name"][:50], new_id)
        result = client.change_dataset_owner(item["id"], new_id)
        if result:
            stats["success"] += 1
            results.append([item["id"], item["name"], item["current_owner_name"], new_id, "success"])
            logger.info("  ✓ Transferred")
        else:
            stats["failed"] += 1
            results.append([item["id"], item["name"], item["current_owner_name"], new_id, "failed"])
            logger.error("  ✗ Failed")

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dataset_id", "name", "current_owner", "new_owner_id", "status"])
        writer.writerows(results)

    logger.info("\nResults log saved to: %s", log_path)
    return stats


def _get_target_id(item: dict, default_id: str | None, mapping: dict[str, str] | None) -> str | None:
    """Determine the target owner ID for an item."""
    if mapping:
        owner_lower = item["current_owner_name"].lower()
        if owner_lower in mapping:
            return mapping[owner_lower]
    return default_id


def main():
    parser = argparse.ArgumentParser(description="Transfer dataset ownership from former employees")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview changes without applying (default: True)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually transfer ownership (overrides --dry-run)")
    parser.add_argument("--target-owner", type=str, default=DEFAULT_TARGET_OWNER_NAME,
                        help=f"Name of the new owner (default: {DEFAULT_TARGET_OWNER_NAME})")
    parser.add_argument("--target-owner-id", type=str, default=None,
                        help="Domo user ID of the new owner (bypasses name lookup)")
    parser.add_argument("--mapping", type=str, default=None,
                        help="CSV file mapping former_owner_name to new_owner_id")
    args = parser.parse_args()

    dry_run = not args.execute

    if not FORMER_EMPLOYEES:
        logger.warning(
            "FORMER_EMPLOYEES set is empty. Edit transfer_ownership.py to add "
            "former employee names, or provide a --mapping CSV."
        )
        logger.info(
            "Tip: Check the cache for owners with orphaned dataflows — "
            "111 dataflows were flagged as owned by former employees."
        )

    orphaned = load_orphaned_items()
    logger.info("Found %d orphaned items (%d datasets, %d dataflows)",
                len(orphaned),
                sum(1 for o in orphaned if o["type"] == "dataset"),
                sum(1 for o in orphaned if o["type"] == "dataflow"))

    # Resolve target owner
    owner_mapping = None
    target_owner_id = args.target_owner_id

    if args.mapping:
        owner_mapping = load_owner_mapping(args.mapping)
        logger.info("Loaded %d owner mappings from %s", len(owner_mapping), args.mapping)
    elif not target_owner_id and not dry_run:
        # Look up the target owner ID from cache
        from domo_client import DomoClient as _DC
        target_owner_id = resolve_target_owner(None, args.target_owner)
        if not target_owner_id:
            logger.error(
                "Could not resolve Domo user ID for '%s'. "
                "Use --target-owner-id to provide it directly.",
                args.target_owner,
            )
            sys.exit(1)

    stats = apply_transfers(orphaned, target_owner_id, owner_mapping, dry_run=dry_run)

    print(f"\n{'=' * 60}")
    print("OWNERSHIP TRANSFER SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Mode:               {'DRY RUN' if stats['dry_run'] else 'LIVE'}")
    print(f"  Datasets to transfer: {stats['total']}")
    if not dry_run:
        print(f"  Transferred:        {stats['success']}")
        print(f"  Failed:             {stats['failed']}")
        print(f"  No target mapped:   {stats['skipped_no_target']}")
    print(f"  Dataflows skipped:  {stats['skipped_dataflows']} (requires UI)")


if __name__ == "__main__":
    main()
