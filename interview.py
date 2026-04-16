"""Interactive interview process for filling in missing column definitions.

Presents undefined columns in prioritized batches grouped by domain context,
shows example datasets and existing columns for context, and collects
definitions from the user.

Usage:
    python3 interview.py                    # Start from the top
    python3 interview.py --domain "RPA"     # Focus on a specific domain
    python3 interview.py --dataset "Sites - Base Data Set"  # Focus on one dataset
    python3 interview.py --resume           # Resume from where you left off
    python3 interview.py --export           # Export undefined columns to CSV for offline review
"""

import argparse
import csv
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from analytics import _classify_domain
from extractors import DEFINITIONS_FILE

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / ".cache"
PROGRESS_FILE = CACHE_DIR / "interview_progress.json"
EXPORT_DIR = Path(__file__).parent / "output"


def _load_cache() -> dict[str, Any]:
    cache_path = CACHE_DIR / "latest.json"
    if not cache_path.exists():
        print("Error: No cache found. Run a full extraction first.")
        sys.exit(1)
    with open(cache_path) as f:
        return json.load(f)


def _load_definitions() -> dict[tuple[str, str], dict[str, str]]:
    """Load all definitions keyed by (column_name, column_type)."""
    defs = {}
    if DEFINITIONS_FILE.exists():
        with open(DEFINITIONS_FILE, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["column_name"], row["column_type"])
                defs[key] = row
    return defs


def _save_definition(column_name: str, column_type: str, definition: str, status: str = "manual") -> None:
    """Update a single definition in the CSV file."""
    defs_path = DEFINITIONS_FILE
    rows = []
    fieldnames = None
    updated = False

    with open(defs_path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["column_name"] == column_name and row["column_type"] == column_type:
                row["definition"] = definition
                row["status"] = status
                updated = True
            rows.append(row)

    if not updated:
        rows.append({
            "column_name": column_name,
            "column_type": column_type,
            "definition": definition,
            "status": status,
        })

    with open(defs_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _save_progress(progress: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "skipped": [], "session_start": datetime.now().isoformat()}


def _build_interview_batches(
    schemas: list[dict],
    definitions: dict,
    domain_filter: str | None = None,
    dataset_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Build prioritized batches of undefined columns with full context.

    Returns a list of interview items, each containing:
    - column_name, column_type
    - datasets it appears in (with domain classification)
    - sibling columns (other columns in the same datasets, for context)
    - appearance count
    """
    # Group schemas by column
    col_info = defaultdict(lambda: {"datasets": set(), "all_dataset_names": set()})
    dataset_columns = defaultdict(list)  # dataset_name -> list of column names

    for schema in schemas:
        key = (schema["column_name"], schema["column_type"])
        ds_name = schema["dataset_name"]
        col_info[key]["datasets"].add(ds_name)
        col_info[key]["all_dataset_names"].add(ds_name)
        dataset_columns[ds_name].append(schema["column_name"])

    # Filter to undefined only
    items = []
    for key, info in col_info.items():
        defn = definitions.get(key, {}).get("definition", "").strip()
        if defn:
            continue  # Already defined

        col_name, col_type = key
        ds_names = sorted(info["datasets"])

        # Apply filters
        if dataset_filter:
            matching = [d for d in ds_names if dataset_filter.lower() in d.lower()]
            if not matching:
                continue
            ds_names = matching

        if domain_filter:
            matching = []
            for d in ds_names:
                domain, dept = _classify_domain(d)
                if domain_filter.lower() in domain.lower():
                    matching.append(d)
            if not matching:
                continue
            ds_names = matching

        # Get domain for primary dataset
        primary_ds = ds_names[0] if ds_names else ""
        domain, department = _classify_domain(primary_ds)

        # Get sibling columns (defined ones in the same dataset, for context)
        siblings = []
        if ds_names:
            for sib_col in dataset_columns.get(ds_names[0], []):
                sib_key = (sib_col, "")  # Try to find any type
                for sib_type in ["STRING", "LONG", "DOUBLE", "DATETIME", "DATE"]:
                    sib_full_key = (sib_col, sib_type)
                    sib_def = definitions.get(sib_full_key, {}).get("definition", "")
                    if sib_def:
                        siblings.append(f"  {sib_col} ({sib_type}): {sib_def[:80]}")
                        break

        items.append({
            "column_name": col_name,
            "column_type": col_type,
            "dataset_count": len(info["datasets"]),
            "datasets": ds_names[:8],
            "domain": domain,
            "department": department,
            "siblings": siblings[:10],
        })

    # Sort: multi-dataset first, then by domain grouping, then alphabetical
    items.sort(key=lambda r: (-r["dataset_count"], r["domain"].lower(), r["column_name"].lower()))

    return items


def _print_context(item: dict, index: int, total: int) -> None:
    """Print the context for one column to help the user define it."""
    print()
    print(f"{'='*70}")
    print(f"  Column {index}/{total}: {item['column_name']}")
    print(f"  Type: {item['column_type']}    |    Domain: {item['domain']}    |    Datasets: {item['dataset_count']}")
    print(f"{'='*70}")
    print()
    print(f"  Found in:")
    for ds in item["datasets"]:
        domain, _ = _classify_domain(ds)
        print(f"    - {ds}  [{domain}]")
    print()

    if item["siblings"]:
        print(f"  Other defined columns in same dataset (for context):")
        for sib in item["siblings"][:8]:
            print(f"    {sib}")
        print()


def _run_interview(items: list[dict], progress: dict) -> None:
    """Run the interactive interview loop."""
    completed = set(tuple(x) for x in progress.get("completed", []))
    skipped = set(tuple(x) for x in progress.get("skipped", []))

    # Filter out already completed/skipped
    remaining = [
        item for item in items
        if (item["column_name"], item["column_type"]) not in completed
        and (item["column_name"], item["column_type"]) not in skipped
    ]

    total = len(remaining)
    if total == 0:
        print("\nAll columns in this batch have been addressed!")
        return

    print(f"\n{total} columns to review. Commands:")
    print(f"  [type definition] — Save the definition")
    print(f"  s                 — Skip this column (come back later)")
    print(f"  n/a               — Mark as not applicable / no definition needed")
    print(f"  q                 — Quit and save progress")
    print(f"  context           — Show more sibling columns for context")
    print()

    defined_count = 0
    skipped_count = 0

    for idx, item in enumerate(remaining, 1):
        _print_context(item, idx, total)

        while True:
            try:
                response = input("  Definition: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nSaving progress...")
                _save_progress(progress)
                print(f"Session: {defined_count} defined, {skipped_count} skipped")
                return

            if not response:
                print("  (empty — type a definition, 's' to skip, or 'q' to quit)")
                continue

            if response.lower() == "q":
                _save_progress(progress)
                print(f"\nSession saved: {defined_count} defined, {skipped_count} skipped")
                return

            if response.lower() == "s":
                key = (item["column_name"], item["column_type"])
                skipped.add(key)
                progress.setdefault("skipped", []).append(list(key))
                skipped_count += 1
                print("  → Skipped")
                break

            if response.lower() == "n/a":
                _save_definition(item["column_name"], item["column_type"], "[N/A]", "manual-na")
                key = (item["column_name"], item["column_type"])
                completed.add(key)
                progress.setdefault("completed", []).append(list(key))
                defined_count += 1
                print("  → Marked N/A")
                break

            if response.lower() == "context":
                print(f"\n  All datasets containing '{item['column_name']}':")
                for ds in item["datasets"]:
                    print(f"    - {ds}")
                if item["siblings"]:
                    print(f"\n  Defined sibling columns:")
                    for sib in item["siblings"]:
                        print(f"    {sib}")
                print()
                continue

            # It's a definition — validate and save
            definition = response
            # Auto-capitalize first letter
            if definition[0].islower():
                definition = definition[0].upper() + definition[1:]
            # Remove trailing period
            definition = definition.rstrip(".")

            _save_definition(item["column_name"], item["column_type"], definition, "manual")
            key = (item["column_name"], item["column_type"])
            completed.add(key)
            progress.setdefault("completed", []).append(list(key))
            defined_count += 1
            print(f"  → Saved")
            break

    _save_progress(progress)
    print(f"\nBatch complete! {defined_count} defined, {skipped_count} skipped")


def _export_for_review(items: list[dict], output_path: Path) -> None:
    """Export undefined columns to CSV for offline review."""
    fieldnames = [
        "column_name", "column_type", "dataset_count", "domain",
        "department", "example_datasets", "definition",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow({
                "column_name": item["column_name"],
                "column_type": item["column_type"],
                "dataset_count": item["dataset_count"],
                "domain": item["domain"],
                "department": item["department"],
                "example_datasets": " | ".join(item["datasets"][:5]),
                "definition": "",  # Blank for user to fill in
            })

    print(f"Exported {len(items)} undefined columns to {output_path}")
    print(f"Fill in the 'definition' column and import with:")
    print(f"  python3 interview.py --import {output_path}")


def _import_definitions(import_path: Path) -> None:
    """Import definitions from a filled-in CSV."""
    imported = 0
    with open(import_path, newline="") as f:
        for row in csv.DictReader(f):
            defn = row.get("definition", "").strip()
            if not defn:
                continue
            # Auto-capitalize, remove trailing period
            if defn[0].islower():
                defn = defn[0].upper() + defn[1:]
            defn = defn.rstrip(".")

            _save_definition(row["column_name"], row["column_type"], defn, "manual")
            imported += 1

    print(f"Imported {imported} definitions from {import_path}")
    print("Run 'python3 main.py --rebuild' to regenerate the workbook")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactive interview process for filling in column definitions."
    )
    parser.add_argument("--domain", help="Focus on a specific domain (e.g., 'RPA', 'Transactions')")
    parser.add_argument("--dataset", help="Focus on columns from a specific dataset name (partial match)")
    parser.add_argument("--resume", action="store_true", help="Resume from saved progress")
    parser.add_argument("--export", action="store_true", help="Export undefined columns to CSV for offline review")
    parser.add_argument("--import-csv", dest="import_csv", help="Import definitions from a filled-in CSV")
    parser.add_argument("--reset", action="store_true", help="Reset interview progress")
    parser.add_argument("--stats", action="store_true", help="Show definition coverage statistics")
    args = parser.parse_args()

    # Handle import
    if args.import_csv:
        _import_definitions(Path(args.import_csv))
        return 0

    # Handle reset
    if args.reset:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
            print("Interview progress reset")
        else:
            print("No progress to reset")
        return 0

    # Load data
    cache = _load_cache()
    definitions = _load_definitions()

    # Handle stats
    if args.stats:
        total = len(definitions)
        defined = sum(1 for d in definitions.values() if d.get("definition", "").strip())
        undefined = total - defined

        # By domain
        col_domains = defaultdict(lambda: {"defined": 0, "undefined": 0})
        for schema in cache["schemas"]:
            key = (schema["column_name"], schema["column_type"])
            defn = definitions.get(key, {}).get("definition", "").strip()
            domain, _ = _classify_domain(schema["dataset_name"])
            if defn:
                col_domains[domain]["defined"] += 1
            else:
                col_domains[domain]["undefined"] += 1

        print(f"\nDefinition Coverage")
        print(f"{'='*60}")
        print(f"  Total unique columns:  {total}")
        print(f"  Defined:               {defined} ({defined/total*100:.1f}%)")
        print(f"  Undefined:             {undefined} ({undefined/total*100:.1f}%)")
        print()
        print(f"  {'Domain':<35} {'Defined':>8} {'Undefined':>10} {'Coverage':>9}")
        print(f"  {'-'*65}")
        for domain in sorted(col_domains, key=lambda d: -col_domains[d]["undefined"]):
            d = col_domains[domain]
            total_d = d["defined"] + d["undefined"]
            pct = d["defined"] / total_d * 100 if total_d > 0 else 0
            print(f"  {domain:<35} {d['defined']:>8} {d['undefined']:>10} {pct:>8.1f}%")
        return 0

    # Build interview items
    items = _build_interview_batches(
        cache["schemas"], definitions,
        domain_filter=args.domain,
        dataset_filter=args.dataset,
    )

    if not items:
        print("No undefined columns found matching your filters!")
        return 0

    # Handle export
    if args.export:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        domain_suffix = f"_{args.domain.lower().replace(' ', '_')}" if args.domain else ""
        dataset_suffix = f"_{args.dataset.lower().replace(' ', '_')[:30]}" if args.dataset else ""
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"undefined_columns{domain_suffix}{dataset_suffix}_{timestamp}.csv"
        _export_for_review(items, EXPORT_DIR / filename)
        return 0

    # Load progress
    if args.resume:
        progress = _load_progress()
        print(f"Resuming interview ({len(progress.get('completed', []))} already completed)")
    else:
        progress = {"completed": [], "skipped": [], "session_start": datetime.now().isoformat()}

    # Print summary
    filter_desc = ""
    if args.domain:
        filter_desc = f" in domain '{args.domain}'"
    elif args.dataset:
        filter_desc = f" in dataset '{args.dataset}'"

    print(f"\nColumn Definition Interview")
    print(f"{'='*40}")
    print(f"  {len(items)} undefined columns{filter_desc}")
    print(f"  Progress: {len(progress.get('completed', []))} completed, {len(progress.get('skipped', []))} skipped")
    print()

    _run_interview(items, progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
