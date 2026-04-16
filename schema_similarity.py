#!/usr/bin/env python3
"""Schema similarity analysis — detect duplicate datasets by comparing column fingerprints.

Uses Jaccard similarity on (column_name, column_type) tuples to find datasets
with highly overlapping schemas. Weights rare columns more heavily than
ubiquitous ones (like 'date' or 'id').

Layers on top of the name-based detection in detect_duplicates.py.
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics import _classify_domain  # noqa: E402

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"
OUT_DIR = Path(__file__).resolve().parent / "output"


def normalize_column_name(name: str) -> str:
    """Normalize a column name for comparison.

    Lowercases, strips whitespace, removes common prefixes/suffixes,
    and normalizes separators.
    """
    n = name.strip().lower()
    # Remove leading underscores (Domo system columns)
    n = re.sub(r"^_+", "", n)
    # Normalize separators to underscore
    n = re.sub(r"[\s\-\.]+", "_", n)
    # Remove trailing underscores
    n = re.sub(r"_+$", "", n)
    # Collapse multiple underscores
    n = re.sub(r"_+", "_", n)
    return n


def build_fingerprints(
    schemas: list[dict],
) -> dict[str, set[tuple[str, str]]]:
    """Build per-dataset schema fingerprints.

    Returns: {dataset_id: set of (normalized_column_name, column_type)}
    """
    fingerprints: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for s in schemas:
        ds_id = s["dataset_id"]
        col_name = normalize_column_name(s["column_name"])
        col_type = s["column_type"]
        if col_name and not col_name.startswith("batch"):  # skip _BATCH_ columns
            fingerprints[ds_id].add((col_name, col_type))
    return dict(fingerprints)


def compute_column_rarity(
    fingerprints: dict[str, set[tuple[str, str]]],
) -> dict[tuple[str, str], float]:
    """Compute IDF-like rarity score for each (column_name, column_type).

    Columns appearing in many datasets get lower weight.
    """
    import math
    total_datasets = len(fingerprints)
    col_doc_freq: Counter = Counter()

    for fp in fingerprints.values():
        for col in fp:
            col_doc_freq[col] += 1

    rarity = {}
    for col, freq in col_doc_freq.items():
        rarity[col] = math.log(total_datasets / freq) if freq > 0 else 0

    return rarity


def weighted_jaccard(
    set_a: set[tuple[str, str]],
    set_b: set[tuple[str, str]],
    rarity: dict[tuple[str, str], float],
) -> float:
    """Compute weighted Jaccard similarity using column rarity as weights."""
    intersection = set_a & set_b
    union = set_a | set_b

    if not union:
        return 0.0

    weighted_intersect = sum(rarity.get(c, 1.0) for c in intersection)
    weighted_union = sum(rarity.get(c, 1.0) for c in union)

    return weighted_intersect / weighted_union if weighted_union > 0 else 0.0


def plain_jaccard(
    set_a: set[tuple[str, str]],
    set_b: set[tuple[str, str]],
) -> float:
    """Plain Jaccard similarity."""
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def find_similar_pairs(
    fingerprints: dict[str, set[tuple[str, str]]],
    datasets: list[dict],
    rarity: dict[tuple[str, str], float],
    threshold: float = 0.65,
    min_columns: int = 4,
) -> list[dict]:
    """Find dataset pairs with schema similarity above threshold.

    Optimizations:
    - Only compare datasets within the same domain (or across domains if
      one is 'Other / Unclassified')
    - Skip datasets with fewer than min_columns columns
    - Use plain Jaccard as a fast pre-filter before weighted Jaccard
    """
    # Build domain lookup
    ds_lookup = {ds["dataset_id"]: ds for ds in datasets}
    ds_domains: dict[str, str] = {}
    for ds in datasets:
        domain, _ = _classify_domain(ds["dataset_name"])
        ds_domains[ds["dataset_id"]] = domain

    # Filter to datasets with enough columns
    eligible = {
        ds_id: fp
        for ds_id, fp in fingerprints.items()
        if len(fp) >= min_columns
    }

    # Group by domain for comparison efficiency
    domain_groups: dict[str, list[str]] = defaultdict(list)
    for ds_id in eligible:
        domain = ds_domains.get(ds_id, "Other / Unclassified")
        domain_groups[domain].append(ds_id)

    results = []
    pairs_checked = 0
    fast_filtered = 0

    # Compare within same domain
    for domain, ds_ids in domain_groups.items():
        if len(ds_ids) < 2:
            continue

        for id_a, id_b in combinations(ds_ids, 2):
            fp_a = eligible[id_a]
            fp_b = eligible[id_b]
            pairs_checked += 1

            # Fast pre-filter: plain Jaccard
            plain_sim = plain_jaccard(fp_a, fp_b)
            if plain_sim < threshold * 0.7:  # generous pre-filter
                fast_filtered += 1
                continue

            # Full weighted Jaccard
            w_sim = weighted_jaccard(fp_a, fp_b, rarity)
            if w_sim < threshold:
                continue

            intersection = fp_a & fp_b
            shared_cols = sorted(c[0] for c in intersection)

            ds_a = ds_lookup.get(id_a, {})
            ds_b = ds_lookup.get(id_b, {})

            # Determine which to keep (more recent data, more rows)
            a_current = ds_a.get("data_current_at", "")
            b_current = ds_b.get("data_current_at", "")
            a_rows = ds_a.get("row_count", 0) or 0
            b_rows = ds_b.get("row_count", 0) or 0

            if a_current > b_current:
                keep_candidate = "A"
            elif b_current > a_current:
                keep_candidate = "B"
            elif a_rows >= b_rows:
                keep_candidate = "A"
            else:
                keep_candidate = "B"

            results.append({
                "dataset_a_id": id_a,
                "dataset_a_name": ds_a.get("dataset_name", ""),
                "dataset_a_owner": ds_a.get("owner_name", ""),
                "dataset_a_rows": a_rows,
                "dataset_a_columns": len(fp_a),
                "dataset_a_last_update": a_current,
                "dataset_b_id": id_b,
                "dataset_b_name": ds_b.get("dataset_name", ""),
                "dataset_b_owner": ds_b.get("owner_name", ""),
                "dataset_b_rows": b_rows,
                "dataset_b_columns": len(fp_b),
                "dataset_b_last_update": b_current,
                "plain_jaccard": round(plain_sim, 3),
                "weighted_jaccard": round(w_sim, 3),
                "shared_column_count": len(intersection),
                "total_unique_columns": len(fp_a | fp_b),
                "overlap_pct": round(100 * len(intersection) / len(fp_a | fp_b), 1),
                "shared_columns": "; ".join(shared_cols[:20]),
                "domain": domain,
                "keep_candidate": keep_candidate,
                "recommendation": "",
            })

    # Also compare across "Other / Unclassified" with everything else
    other_ids = domain_groups.get("Other / Unclassified", [])
    if other_ids:
        classified_ids = [
            ds_id for domain, ids in domain_groups.items()
            if domain != "Other / Unclassified"
            for ds_id in ids
        ]
        for id_a in other_ids:
            fp_a = eligible[id_a]
            for id_b in classified_ids:
                fp_b = eligible[id_b]
                pairs_checked += 1

                plain_sim = plain_jaccard(fp_a, fp_b)
                if plain_sim < threshold * 0.7:
                    fast_filtered += 1
                    continue

                w_sim = weighted_jaccard(fp_a, fp_b, rarity)
                if w_sim < threshold:
                    continue

                intersection = fp_a & fp_b
                shared_cols = sorted(c[0] for c in intersection)

                ds_a = ds_lookup.get(id_a, {})
                ds_b = ds_lookup.get(id_b, {})
                a_current = ds_a.get("data_current_at", "")
                b_current = ds_b.get("data_current_at", "")
                a_rows = ds_a.get("row_count", 0) or 0
                b_rows = ds_b.get("row_count", 0) or 0

                keep_candidate = "A" if (a_current > b_current or (a_current == b_current and a_rows >= b_rows)) else "B"

                results.append({
                    "dataset_a_id": id_a,
                    "dataset_a_name": ds_a.get("dataset_name", ""),
                    "dataset_a_owner": ds_a.get("owner_name", ""),
                    "dataset_a_rows": a_rows,
                    "dataset_a_columns": len(fp_a),
                    "dataset_a_last_update": a_current,
                    "dataset_b_id": id_b,
                    "dataset_b_name": ds_b.get("dataset_name", ""),
                    "dataset_b_owner": ds_b.get("owner_name", ""),
                    "dataset_b_rows": b_rows,
                    "dataset_b_columns": len(fp_b),
                    "dataset_b_last_update": b_current,
                    "plain_jaccard": round(plain_sim, 3),
                    "weighted_jaccard": round(w_sim, 3),
                    "shared_column_count": len(intersection),
                    "total_unique_columns": len(fp_a | fp_b),
                    "overlap_pct": round(100 * len(intersection) / len(fp_a | fp_b), 1),
                    "shared_columns": "; ".join(shared_cols[:20]),
                    "domain": ds_domains.get(id_b, "Cross-domain"),
                    "keep_candidate": keep_candidate,
                    "recommendation": "",
                })

    # Sort by weighted similarity descending
    results.sort(key=lambda r: -r["weighted_jaccard"])

    # Add recommendations
    for r in results:
        sim = r["weighted_jaccard"]
        overlap = r["overlap_pct"]
        if sim >= 0.90 and overlap >= 90:
            r["recommendation"] = "Likely Duplicate — consolidate"
        elif sim >= 0.80 and overlap >= 75:
            r["recommendation"] = "Probable Duplicate — review"
        elif sim >= 0.65:
            r["recommendation"] = "Similar Schema — investigate"

    return results


def main() -> None:
    """Main entry point."""
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache not found at {CACHE_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CACHE_PATH) as f:
        cache = json.load(f)

    datasets = cache["datasets"]
    schemas = cache["schemas"]
    print(f"Loaded {len(datasets)} datasets, {len(schemas)} schema columns")

    # Build fingerprints
    print("Building schema fingerprints...")
    fingerprints = build_fingerprints(schemas)
    print(f"  {len(fingerprints)} datasets with column data")

    # Filter out very small datasets
    min_cols = 4
    eligible = {k: v for k, v in fingerprints.items() if len(v) >= min_cols}
    print(f"  {len(eligible)} datasets with >= {min_cols} columns (eligible for comparison)")

    # Compute rarity scores
    print("Computing column rarity scores...")
    rarity = compute_column_rarity(fingerprints)

    # Most common columns (for reference)
    col_freq = Counter()
    for fp in fingerprints.values():
        for col in fp:
            col_freq[col] += 1

    print(f"  Most common columns:")
    for (col_name, col_type), freq in col_freq.most_common(10):
        print(f"    {col_name} ({col_type}): appears in {freq} datasets")

    # Find similar pairs
    print("\nFinding similar dataset pairs (threshold=0.65)...")
    results = find_similar_pairs(fingerprints, datasets, rarity, threshold=0.65, min_columns=min_cols)

    # Summary
    likely = [r for r in results if "Likely" in r["recommendation"]]
    probable = [r for r in results if "Probable" in r["recommendation"]]
    similar = [r for r in results if "Similar" in r["recommendation"]]

    print(f"\n{'='*70}")
    print("SCHEMA SIMILARITY ANALYSIS RESULTS")
    print(f"{'='*70}")
    print(f"  Total similar pairs found:    {len(results)}")
    print(f"    Likely Duplicates (>=90%):  {len(likely)}")
    print(f"    Probable Duplicates (>=80%): {len(probable)}")
    print(f"    Similar Schema (>=65%):     {len(similar)}")

    # Domain breakdown
    domain_counter = Counter(r["domain"] for r in results)
    print(f"\n  By domain:")
    for dom, count in domain_counter.most_common():
        print(f"    {dom:<35s} {count:>4}")

    # Show top pairs
    print(f"\n  TOP 20 MOST SIMILAR PAIRS:")
    print(f"  {'Dataset A':<40s} | {'Dataset B':<40s} | {'Overlap':>7s} | {'Rec'}")
    print(f"  {'-'*40}-+-{'-'*40}-+-{'-'*7}-+-{'-'*30}")
    for r in results[:20]:
        a = r["dataset_a_name"][:38]
        b = r["dataset_b_name"][:38]
        olap = f"{r['overlap_pct']}%"
        rec = r["recommendation"]
        print(f"  {a:<40s} | {b:<40s} | {olap:>7s} | {rec}")

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "schema_similarity_analysis.csv"
    fieldnames = [
        "dataset_a_name", "dataset_b_name", "overlap_pct", "weighted_jaccard",
        "shared_column_count", "total_unique_columns", "domain", "recommendation",
        "keep_candidate",
        "dataset_a_owner", "dataset_a_rows", "dataset_a_columns", "dataset_a_last_update",
        "dataset_b_owner", "dataset_b_rows", "dataset_b_columns", "dataset_b_last_update",
        "shared_columns",
        "dataset_a_id", "dataset_b_id",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\n  Output: {csv_path}")
    print(f"  Total pairs checked: many within-domain comparisons")
    print(f"  (Cross-domain comparisons limited to 'Other / Unclassified' datasets)")


if __name__ == "__main__":
    main()
