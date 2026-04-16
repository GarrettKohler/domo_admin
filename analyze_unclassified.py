#!/usr/bin/env python3
"""Analyze the 'Other / Unclassified' datasets from the Domo inventory cache.

Loads the cache, applies _classify_domain(), and clusters the unclassified
datasets by naming patterns to suggest new classification rules.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path so we can import analytics
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics import _classify_domain

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"


def load_unclassified():
    """Load cache and return datasets classified as Other / Unclassified."""
    with open(CACHE_PATH) as f:
        data = json.load(f)
    datasets = data.get("datasets", [])
    unclassified = []
    for ds in datasets:
        name = ds.get("dataset_name", "")
        domain, dept = _classify_domain(name)
        if domain == "Other / Unclassified":
            unclassified.append(ds)
    return unclassified, len(datasets)


# ---------------------------------------------------------------------------
# Proposed new clusters: (label, regex_pattern, suggested_workspace)
# Order matters -- first match wins, just like DOMAIN_RULES
# ---------------------------------------------------------------------------
PROPOSED_CLUSTERS = [
    # Internal tools / platforms
    ("Odyssey (Internal Tool)", r"(?i)\bodyssey", "Engineering"),
    ("Krypton (Internal Tool)", r"(?i)\bkrypton", "Engineering"),

    # Analysis / ad-hoc projects
    ("Analysis Projects", r"(?i)\banalysis\b|^Analysis\s*-", "Data & Analytics"),

    # PROD / View prefixes (data engineering outputs)
    ("PROD - Prefix (ETL Outputs)", r"(?i)^PROD\s*-", "Data Engineering"),
    ("View - Prefix (Reporting Views)", r"(?i)^View\s*-", "Data Engineering"),

    # Market plans / DMA
    ("Market Plans", r"(?i)market.?plan|mkt.?plan", "Sales"),

    # NVI / Impressions variants not caught
    ("Impressions (uncaught)", r"(?i)impression|imps\b|avg.*imp", "Data & Analytics"),

    # Revenue / Finance variants not caught
    ("Revenue / Finance (uncaught)", r"(?i)\bbudget|\bforecast|\bfinance|\bmargin|\bprofit|\bcost\b|\bspend|\bgross|\bnet\b.*rev", "Finance"),

    # Retailer / brand names that might be managed services
    ("Retailer / Brand Names", r"(?i)\bbp\b|\bshell\b|\bchevron|\bexxon|\bcumberland|\b7.?eleven|\blov|murphy|sunoco|phillips|valero|arco|citgo", "Ad Operations"),

    # Scheduling / calendar
    ("Scheduling", r"(?i)\bschedul|\bcalendar|\btimeline", "Ad Operations"),

    # Reports / dashboards
    ("Reports / Dashboards", r"(?i)\breport\b|\bdashboard|\bsummary\b|\bscorecard|\bkpi\b|\bmetric", "Data & Analytics"),

    # Inventory / avails (ad inventory)
    ("Ad Inventory / Avails", r"(?i)\bavail|\binventory\b|\bfill.?rate|\bdemand|\bsupply", "Programmatic"),

    # Dataflow / ETL related
    ("ETL / Dataflow Artifacts", r"(?i)\bdataflow|\betl|\bpipeline|\bstaging|\braw\b.*data", "Data Engineering"),

    # User / people / HR
    ("People / HR", r"(?i)\bheadcount|\bemployee|\bhiring|\bhr\b|\bpeople\b|\bstaff", "People Ops"),

    # Rates / pricing
    ("Rates / Pricing", r"(?i)\brate\b|\bpricing|\bcpm(?!.*floor)|\bratecard|rate.?card", "Finance"),

    # Network / connectivity / health
    ("Network Health", r"(?i)\bnetwork.*health|\buptime|\bconnectiv|\bheartbeat|\blatency", "Network Operations"),

    # Content / creative
    ("Content / Creative", r"(?i)\bcreative|\bcontent\b|\bvideo\b|\basset|\bmedia\b", "Ad Operations"),

    # Audience / targeting
    ("Audience / Targeting", r"(?i)\baudience|\btarget|\bsegment|\bdemograph", "Data & Analytics"),

    # Compliance / legal
    ("Compliance / Legal", r"(?i)\bcompliance|\blegal|\baudit|\bprivacy|\bgdpr", "Legal"),

    # Weather
    ("Weather Data", r"(?i)\bweather|\btemp(?:erature)?.*(?:high|low|avg)", "Data & Analytics"),

    # GeoJSON / maps
    ("Geographic / Maps", r"(?i)\bgeo|\bmap\b|\blatitude|\blongitude|\bpolygon|\bgeojson", "Data Engineering"),
]


def cluster_datasets(unclassified):
    """Apply proposed clusters to unclassified datasets.
    Returns: dict of cluster_label -> list of dataset names, and leftovers list.
    """
    clusters = defaultdict(list)
    leftovers = []

    for ds in unclassified:
        name = ds.get("dataset_name", "")
        matched = False
        for label, pattern, workspace in PROPOSED_CLUSTERS:
            if re.search(pattern, name):
                clusters[label].append(name)
                matched = True
                break
        if not matched:
            leftovers.append(name)

    return clusters, leftovers


def main():
    unclassified, total = load_unclassified()
    names = sorted([ds.get("dataset_name", "") for ds in unclassified], key=str.lower)

    print("=" * 80)
    print(f"UNCLASSIFIED DATASET ANALYSIS")
    print(f"Total datasets in cache: {total}")
    print(f"Classified as 'Other / Unclassified': {len(unclassified)}")
    print("=" * 80)

    # --- Full alphabetical list ---
    print(f"\n{'='*80}")
    print("FULL ALPHABETICAL LIST OF UNCLASSIFIED DATASETS")
    print(f"{'='*80}")
    for i, name in enumerate(names, 1):
        print(f"  {i:3d}. {name}")

    # --- Clustering ---
    clusters, leftovers = cluster_datasets(unclassified)

    print(f"\n{'='*80}")
    print("PROPOSED CLUSTERS")
    print(f"{'='*80}")

    total_clustered = 0
    for label, pattern, workspace in PROPOSED_CLUSTERS:
        if label in clusters:
            count = len(clusters[label])
            total_clustered += count
            print(f"\n--- {label} ({count} datasets) --> Workspace: {workspace} ---")
            print(f"    Regex: {pattern}")
            for name in sorted(clusters[label], key=str.lower):
                print(f"      - {name}")

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"  Total unclassified:              {len(unclassified)}")
    print(f"  Matched by proposed patterns:    {total_clustered}")
    print(f"  Still unclassified after:         {len(leftovers)}")
    print(f"  Classification improvement:       {len(unclassified) - len(leftovers)} fewer unclassified")
    print(f"  Reduction:                        {((len(unclassified) - len(leftovers)) / len(unclassified) * 100) if unclassified else 0:.1f}%")

    if leftovers:
        print(f"\n{'='*80}")
        print(f"STILL UNCLASSIFIED ({len(leftovers)} datasets)")
        print(f"{'='*80}")
        for i, name in enumerate(sorted(leftovers, key=str.lower), 1):
            print(f"  {i:3d}. {name}")

    # --- Suggested DOMAIN_RULES additions ---
    print(f"\n{'='*80}")
    print("SUGGESTED DOMAIN_RULES ADDITIONS (copy-paste ready)")
    print(f"{'='*80}")
    for label, pattern, workspace in PROPOSED_CLUSTERS:
        if label in clusters and len(clusters[label]) > 0:
            # Map workspace to a domain name
            print(f'    (r"{pattern}", "{label}", "{workspace}"),')


if __name__ == "__main__":
    main()
