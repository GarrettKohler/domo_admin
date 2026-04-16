#!/usr/bin/env python3
"""Extract governance data from DomoStats datasets: Cards, Pages, Card-Datasource
mappings, and Dataset Tags.

This script:
1. Connects to the Domo API (same credentials as main.py)
2. Exports 5 DomoStats governance datasets
3. Joins card-datasource mappings to our flagged cleanup datasets
4. Produces a dashboard impact report: which cards/pages break if datasets are removed
5. Extracts dataset tags to check for certification status

Outputs:
  - output/dashboard_impact_report.csv
  - output/dataset_tags.csv
  - output/certification_status.csv
  - output/pages_inventory.csv
  - output/cards_inventory.csv
"""

import csv
import io
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent))

from domo_client import DomoAuthError, DomoClient  # noqa: E402

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"
OUT_DIR = Path(__file__).resolve().parent / "output"

# DomoStats dataset IDs for governance data
DOMOSTATS_IDS = {
    "cards":             "2fd31460-4c86-4599-b97a-baff64e3bfb6",  # Governance - Cards
    "pages":             "397473ed-978a-4960-aaee-b4b522bd2f1b",  # Governance - Pages
    "card_datasource":   "216280fc-1c40-4723-a982-a9bf0ba733f9",  # DomoStats - Card Datasource
    "card_pages":        "3434ba8e-9d94-4844-9503-54e7dedb98e6",  # DomoStats - Card Pages
    "dataset_tags":      "d003321e-a362-42dd-a914-d458d9253b74",  # Domostats - Dataset Tags
    "pages_simple":      "68f9e954-f62e-4fe8-bcd2-e8ad13fe4f19",  # Domostats - Pages (with view count)
    "dataset_access":    "c0093bba-c3d2-43dc-8d9e-2d6204ed39e5",  # Domostats - Dataset Access
}


def _parse_csv(csv_text: str) -> list[dict[str, str]]:
    """Parse CSV text into list of dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def export_domostats(client: DomoClient, name: str, dataset_id: str) -> list[dict] | None:
    """Export a DomoStats dataset and return parsed rows."""
    print(f"  Exporting {name}...", end=" ", flush=True)
    csv_text = client.export_dataset_csv(dataset_id)
    if csv_text is None:
        print("FAILED")
        return None
    rows = _parse_csv(csv_text)
    print(f"{len(rows):,} rows")
    return rows


def build_dashboard_impact(
    cards: list[dict],
    card_datasources: list[dict],
    card_pages: list[dict],
    pages: list[dict],
    flagged_dataset_ids: set[str],
    ds_id_to_name: dict[str, str],
) -> list[dict]:
    """Build a dashboard impact report: which cards/pages are affected by
    removing flagged datasets.
    """
    # Build lookups
    # card_id → list of dataset_ids
    card_to_datasets: dict[str, list[str]] = defaultdict(list)
    for row in card_datasources:
        card_id = str(row.get("cardId", ""))
        ds_id = row.get("dataSourceId", "")
        if card_id and ds_id:
            card_to_datasets[card_id].append(ds_id)

    # card_id → card info
    card_info: dict[str, dict] = {}
    for row in cards:
        cid = row.get("Card ID", "")
        if cid:
            card_info[cid] = {
                "card_title": row.get("Title", ""),
                "card_type": row.get("Card Type", ""),
                "card_owner": row.get("Owner Name", ""),
                "card_page": row.get("Page", ""),
                "card_page_id": row.get("Page ID", ""),
                "card_locked": row.get("Locked", ""),
            }

    # card_id → page_ids (from card_pages mapping)
    card_to_page_ids: dict[str, list[str]] = defaultdict(list)
    for row in card_pages:
        cid = str(row.get("cardId", ""))
        pid = str(row.get("pageId", ""))
        if cid and pid:
            card_to_page_ids[cid].append(pid)

    # page_id → page info
    page_info: dict[str, dict] = {}
    for row in pages:
        pid = row.get("Page ID", "")
        if pid:
            page_info[pid] = {
                "page_title": row.get("Title", ""),
                "page_owner": row.get("Owner Name", ""),
                "card_count": row.get("Number of Cards on Page", ""),
                "parent_page": row.get("Parent Page Title", ""),
            }

    # Now find cards powered by flagged datasets
    results = []
    for card_id, ds_ids in card_to_datasets.items():
        flagged_ds = [ds_id for ds_id in ds_ids if ds_id in flagged_dataset_ids]
        if not flagged_ds:
            continue

        info = card_info.get(card_id, {})
        page_ids = card_to_page_ids.get(card_id, [])
        # Also get page from card info
        if info.get("card_page_id") and info["card_page_id"] not in page_ids:
            page_ids.append(info["card_page_id"])

        page_names = []
        for pid in page_ids:
            pinfo = page_info.get(pid)
            if pinfo:
                page_names.append(pinfo["page_title"])
            else:
                page_names.append(f"Page {pid}")

        for ds_id in flagged_ds:
            results.append({
                "flagged_dataset_id": ds_id,
                "flagged_dataset_name": ds_id_to_name.get(ds_id, ""),
                "card_id": card_id,
                "card_title": info.get("card_title", ""),
                "card_type": info.get("card_type", ""),
                "card_owner": info.get("card_owner", ""),
                "pages": "; ".join(page_names) if page_names else info.get("card_page", ""),
                "total_datasets_on_card": len(ds_ids),
                "all_datasets_flagged": "Yes" if all(d in flagged_dataset_ids for d in ds_ids) else "No",
            })

    results.sort(key=lambda r: (r["flagged_dataset_name"], r["card_title"]))
    return results


def analyze_tags(
    tags: list[dict],
    ds_id_to_name: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    """Analyze dataset tags and check for certification.

    Returns (all_tags, certification_status).
    """
    # Parse tags
    tag_records = []
    cert_datasets = set()
    tag_counter = Counter()

    for row in tags:
        ds_id = row.get("Dataset ID", "")
        tag = row.get("Tag", "").strip()
        if not tag:
            continue

        tag_records.append({
            "dataset_id": ds_id,
            "dataset_name": ds_id_to_name.get(ds_id, ""),
            "tag": tag,
        })
        tag_counter[tag.lower()] += 1

        if "certif" in tag.lower():
            cert_datasets.add(ds_id)

    # Build certification status
    cert_status = []
    for ds_id in cert_datasets:
        cert_status.append({
            "dataset_id": ds_id,
            "dataset_name": ds_id_to_name.get(ds_id, ""),
            "certified": "Yes",
        })

    return tag_records, cert_status, tag_counter


def main():
    # Load cache for dataset info
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache not found at {CACHE_PATH}")
        sys.exit(1)

    with open(CACHE_PATH) as f:
        cache = json.load(f)

    datasets = cache["datasets"]
    ds_id_to_name = {ds["dataset_id"]: ds["dataset_name"] for ds in datasets}
    print(f"Loaded {len(datasets)} datasets from cache")

    # Determine flagged dataset IDs (from the rollout spreadsheets)
    # Re-derive: flagged = stale/dormant/abandoned + test/temp + no-freshness
    from datetime import datetime, timezone
    from analytics import _classify_domain

    now = datetime(2026, 4, 11, tzinfo=timezone.utc)
    flagged_ids = set()

    for ds in datasets:
        ds_id = ds["dataset_id"]
        data_current = ds.get("data_current_at", "")
        domain, _ = _classify_domain(ds["dataset_name"])

        days_stale = None
        if data_current:
            try:
                dt = datetime.fromisoformat(str(data_current).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_stale = (now - dt).days
            except (ValueError, TypeError):
                pass

        if days_stale is None:
            flagged_ids.add(ds_id)
        elif days_stale > 90:
            flagged_ids.add(ds_id)
        elif domain == "Test / Temp / Archive":
            flagged_ids.add(ds_id)

    print(f"Flagged dataset IDs: {len(flagged_ids)}")

    # Authenticate with Domo
    client_id = os.environ.get("DOMO_CLIENT_ID", "").strip()
    client_secret = os.environ.get("DOMO_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print("ERROR: DOMO_CLIENT_ID and DOMO_CLIENT_SECRET must be set.")
        print("Set them in .env or export in shell.")
        sys.exit(1)

    print("\nAuthenticating with Domo API...", end=" ", flush=True)
    client = DomoClient(client_id, client_secret)
    try:
        client.authenticate()
    except DomoAuthError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    print("OK")

    # Export governance datasets
    print("\nExporting DomoStats governance datasets:")
    cards = export_domostats(client, "Governance - Cards", DOMOSTATS_IDS["cards"])
    pages = export_domostats(client, "Governance - Pages", DOMOSTATS_IDS["pages"])
    card_ds = export_domostats(client, "Card Datasource mappings", DOMOSTATS_IDS["card_datasource"])
    card_pg = export_domostats(client, "Card Pages mappings", DOMOSTATS_IDS["card_pages"])
    tags = export_domostats(client, "Dataset Tags", DOMOSTATS_IDS["dataset_tags"])
    pages_simple = export_domostats(client, "Pages with view counts", DOMOSTATS_IDS["pages_simple"])

    # Ensure output dir
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Dashboard Impact Report ──
    if cards and card_ds and pages:
        print("\nBuilding dashboard impact report...")
        impact = build_dashboard_impact(
            cards, card_ds, card_pg or [], pages, flagged_ids, ds_id_to_name
        )

        impact_path = OUT_DIR / "dashboard_impact_report.csv"
        if impact:
            with open(impact_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(impact[0].keys()))
                writer.writeheader()
                writer.writerows(impact)

        # Summary
        affected_cards = len(set(r["card_id"] for r in impact))
        affected_datasets = len(set(r["flagged_dataset_id"] for r in impact))
        affected_pages = set()
        for r in impact:
            for p in r["pages"].split("; "):
                if p.strip():
                    affected_pages.add(p.strip())
        all_flagged = sum(1 for r in impact if r["all_datasets_flagged"] == "Yes")

        print(f"\n  {'='*60}")
        print(f"  DASHBOARD IMPACT REPORT")
        print(f"  {'='*60}")
        print(f"    Flagged datasets with cards:  {affected_datasets}")
        print(f"    Cards affected:               {affected_cards}")
        print(f"    Pages affected:               {len(affected_pages)}")
        print(f"    Cards where ALL data flagged:  {all_flagged} (will definitely break)")
        print(f"    Output: {impact_path}")
    else:
        print("  Skipping dashboard impact (missing card/page data)")

    # ── Dataset Tags & Certification ──
    if tags:
        print("\nAnalyzing dataset tags...")
        tag_records, cert_status, tag_counter = analyze_tags(tags, ds_id_to_name)

        # Write tags
        tags_path = OUT_DIR / "dataset_tags.csv"
        if tag_records:
            with open(tags_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["dataset_id", "dataset_name", "tag"])
                writer.writeheader()
                writer.writerows(tag_records)

        # Write certification status
        cert_path = OUT_DIR / "certification_status.csv"
        if cert_status:
            with open(cert_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["dataset_id", "dataset_name", "certified"])
                writer.writeheader()
                writer.writerows(cert_status)

        print(f"\n  {'='*60}")
        print(f"  DATASET TAGS & CERTIFICATION")
        print(f"  {'='*60}")
        print(f"    Total tag entries:            {len(tag_records)}")
        print(f"    Unique tags:                  {len(tag_counter)}")
        print(f"    Certified datasets:           {len(cert_status)}")
        print(f"\n    Top 15 tags:")
        for tag, count in tag_counter.most_common(15):
            print(f"      {tag:<40s} {count:>4}")
        print(f"\n    Output: {tags_path}")
        if cert_status:
            print(f"    Output: {cert_path}")
        else:
            print(f"    No datasets with certification tags found.")
    else:
        print("  Skipping tags (export failed)")

    # ── Pages Inventory ──
    if pages:
        pages_path = OUT_DIR / "pages_inventory.csv"
        page_records = []
        for row in pages:
            page_records.append({
                "page_id": row.get("Page ID", ""),
                "title": row.get("Title", ""),
                "owner": row.get("Owner Name", ""),
                "card_count": row.get("Number of Cards on Page", ""),
                "parent_page": row.get("Parent Page Title", ""),
                "child_pages": row.get("Number of Child Pages", ""),
            })
        page_records.sort(key=lambda r: r["title"].lower() if r["title"] else "")

        with open(pages_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(page_records[0].keys()))
            writer.writeheader()
            writer.writerows(page_records)

        # Add view counts if available
        if pages_simple:
            view_lookup = {}
            for row in pages_simple:
                pid = row.get("Page ID", "")
                views = row.get("Number of views", "0")
                if pid:
                    view_lookup[str(pid)] = views

            with_views = sum(1 for p in page_records if view_lookup.get(p["page_id"]))
            total_views = sum(int(v) for v in view_lookup.values() if v.isdigit())

        print(f"\n  {'='*60}")
        print(f"  PAGES INVENTORY")
        print(f"  {'='*60}")
        print(f"    Total pages:                  {len(page_records)}")
        if pages_simple:
            print(f"    Pages with view data:         {with_views}")
            print(f"    Total page views:             {total_views:,}")
        print(f"    Output: {pages_path}")

    # ── Cards Inventory ──
    if cards:
        cards_path = OUT_DIR / "cards_inventory.csv"
        card_records = []
        for row in cards:
            card_records.append({
                "card_id": row.get("Card ID", ""),
                "title": row.get("Title", ""),
                "card_type": row.get("Card Type", ""),
                "owner": row.get("Owner Name", ""),
                "page": row.get("Page", ""),
                "locked": row.get("Locked", ""),
            })
        card_records.sort(key=lambda r: r["title"].lower() if r["title"] else "")

        with open(cards_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(card_records[0].keys()))
            writer.writeheader()
            writer.writerows(card_records)

        # Card type breakdown
        type_counter = Counter(r["card_type"] for r in card_records)
        print(f"\n  {'='*60}")
        print(f"  CARDS INVENTORY")
        print(f"  {'='*60}")
        print(f"    Total cards:                  {len(card_records):,}")
        print(f"    Card types:")
        for ct, count in type_counter.most_common(10):
            print(f"      {ct:<30s} {count:>6,}")
        print(f"    Output: {cards_path}")

    print(f"\n{'='*60}")
    print("DONE — All governance data extracted.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
