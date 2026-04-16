#!/usr/bin/env python3
"""Upload the GSTV Business Glossary to Domo as a reference dataset.

Creates (or updates) a dataset named "Reference - GSTV Business Glossary"
in Domo and uploads the glossary CSV data.

Usage:
    python3 upload_glossary.py --dry-run       # Preview (default)
    python3 upload_glossary.py --execute        # Create and upload
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from domo_client import DomoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

GLOSSARY_CSV = Path(__file__).resolve().parent / "gstv_glossary.csv"
DATASET_NAME = "Reference - GSTV Business Glossary"
DATASET_DESCRIPTION = (
    "GSTV business glossary containing 197 standard terms, acronyms, and "
    "definitions used across the organization. Sourced from the GSTV Confluence "
    "glossary. Used by Domo AI for natural language query understanding and "
    "consistent data interpretation. Maintained by the Data team."
)

SCHEMA_COLUMNS = [
    {"name": "term", "type": "STRING"},
    {"name": "acronym", "type": "STRING"},
    {"name": "definition", "type": "STRING"},
    {"name": "domain", "type": "STRING"},
    {"name": "category", "type": "STRING"},
]


def load_glossary() -> tuple[list[dict], str]:
    """Load glossary CSV and return (rows, raw_csv_text)."""
    with open(GLOSSARY_CSV, newline="", encoding="utf-8") as f:
        raw_csv = f.read()

    with open(GLOSSARY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return rows, raw_csv


def find_existing_dataset(client: DomoClient) -> str | None:
    """Check if the glossary dataset already exists in Domo."""
    datasets = client.list_datasets()
    for ds in datasets:
        if ds.get("name") == DATASET_NAME:
            return ds.get("id")
    return None


def upload_glossary(dry_run: bool = True) -> dict:
    """Create or update the glossary dataset in Domo."""
    rows, raw_csv = load_glossary()
    logger.info("Loaded %d glossary terms from %s", len(rows), GLOSSARY_CSV.name)

    stats = {
        "terms": len(rows),
        "action": "none",
        "dry_run": dry_run,
        "dataset_id": None,
    }

    if dry_run:
        logger.info("\n" + "=" * 70)
        logger.info("DRY RUN — No changes will be made to Domo")
        logger.info("=" * 70)
        logger.info("Would create dataset: %s", DATASET_NAME)
        logger.info("Description: %s", DATASET_DESCRIPTION[:80] + "...")
        logger.info("Schema: %s", ", ".join(c["name"] for c in SCHEMA_COLUMNS))
        logger.info("Data: %d rows", len(rows))
        logger.info("\nSample terms:")
        for row in rows[:10]:
            logger.info("  %s (%s) — %s", row.get("term", ""), row.get("acronym", ""), row.get("definition", "")[:60])
        if len(rows) > 10:
            logger.info("  ... and %d more", len(rows) - 10)
        return stats

    # Live execution
    client = DomoClient(
        client_id=os.environ["DOMO_CLIENT_ID"],
        client_secret=os.environ["DOMO_CLIENT_SECRET"],
    )
    client.authenticate()
    logger.info("Authenticated with Domo API")

    # Check if dataset already exists
    existing_id = find_existing_dataset(client)

    if existing_id:
        logger.info("Found existing glossary dataset: %s", existing_id)
        logger.info("Updating data...")
        success = client.upload_dataset_data(existing_id, raw_csv)
        if success:
            stats["action"] = "updated"
            stats["dataset_id"] = existing_id
            logger.info("✓ Glossary data updated successfully")
        else:
            stats["action"] = "failed"
            logger.error("✗ Failed to update glossary data")
    else:
        logger.info("Creating new glossary dataset...")
        result = client.create_dataset(DATASET_NAME, DATASET_DESCRIPTION, SCHEMA_COLUMNS)
        if not result:
            stats["action"] = "failed"
            logger.error("✗ Failed to create glossary dataset")
            return stats

        dataset_id = result.get("id")
        stats["dataset_id"] = dataset_id
        logger.info("Created dataset: %s", dataset_id)

        logger.info("Uploading glossary data (%d terms)...", len(rows))
        success = client.upload_dataset_data(dataset_id, raw_csv)
        if success:
            stats["action"] = "created"
            logger.info("✓ Glossary uploaded successfully")
        else:
            stats["action"] = "created_no_data"
            logger.error("✗ Dataset created but data upload failed — retry with upload_dataset_data()")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Upload GSTV glossary to Domo")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview without making changes (default: True)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually create/upload (overrides --dry-run)")
    args = parser.parse_args()

    dry_run = not args.execute

    if not GLOSSARY_CSV.exists():
        logger.error("Glossary CSV not found: %s", GLOSSARY_CSV)
        logger.error("Run glossary extraction first.")
        sys.exit(1)

    stats = upload_glossary(dry_run=dry_run)

    print(f"\n{'=' * 60}")
    print("GLOSSARY UPLOAD SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Mode:       {'DRY RUN' if stats['dry_run'] else 'LIVE'}")
    print(f"  Terms:      {stats['terms']}")
    print(f"  Action:     {stats['action']}")
    if stats["dataset_id"]:
        print(f"  Dataset ID: {stats['dataset_id']}")
        print(f"  Domo URL:   https://gstv.domo.com/datasources/{stats['dataset_id']}/details/overview")


if __name__ == "__main__":
    main()
