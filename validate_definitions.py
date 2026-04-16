#!/usr/bin/env python3
"""
Validate consistency of column definitions in the Domo data dictionary.
Runs 5 checks and outputs a summary report + CSV of issues.
"""

import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path("/Users/aaron.olson/Documents/gstv-domo-extract")
DEFINITIONS_CSV = BASE_DIR / "column_definitions.csv"
SCHEMA_JSON = BASE_DIR / ".cache" / "latest.json"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_CSV = OUTPUT_DIR / "definition_issues_20260411.csv"

issues = []  # list of dicts: issue_type, column_name, column_type, current_definition, suggestion


def load_definitions():
    """Load column_definitions.csv into a list of dicts."""
    rows = []
    with open(DEFINITIONS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_schemas():
    """Load schema data from latest.json."""
    with open(SCHEMA_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("schemas", [])


def check_1_conflicting_definitions(definitions):
    """Find same column_name with multiple column_types having contradictory definitions."""
    print("\n" + "=" * 80)
    print("CHECK 1: Conflicting definitions for same-name columns across types")
    print("=" * 80)

    # Group by column_name
    by_name = defaultdict(list)
    for row in definitions:
        defn = row.get("definition", "").strip()
        if defn:
            by_name[row["column_name"]].append({
                "column_type": row["column_type"],
                "definition": defn,
            })

    count = 0
    for col_name, entries in sorted(by_name.items()):
        if len(entries) < 2:
            continue
        # Check if definitions differ across types
        unique_defs = set(e["definition"] for e in entries)
        if len(unique_defs) > 1:
            count += 1
            types_defs = "; ".join(
                f'{e["column_type"]}="{e["definition"][:80]}"' for e in entries
            )
            print(f"  [{col_name}] {len(entries)} types, {len(unique_defs)} distinct definitions")
            for e in entries:
                print(f"    {e['column_type']:12s} -> {e['definition'][:120]}")
            for e in entries:
                issues.append({
                    "issue_type": "conflicting_cross_type",
                    "column_name": col_name,
                    "column_type": e["column_type"],
                    "current_definition": e["definition"],
                    "suggestion": f"Reconcile with other type definitions for '{col_name}'",
                })

    print(f"\n  Total columns with conflicting cross-type definitions: {count}")


def check_2_generic_templated(definitions):
    """Find generic/templated definitions that slipped through."""
    print("\n" + "=" * 80)
    print("CHECK 2: Generic/templated definitions that slipped through")
    print("=" * 80)

    generic_patterns = [
        (r"Salesforce custom field for", "Contains 'Salesforce custom field for' template text"),
        (r"field for the record", "Contains 'field for the record' template text"),
        (r"Field label:", "Contains raw 'Field label:' metadata (not a real definition)"),
        (r"For OMS$", "Definition is just 'For OMS' — too vague"),
        (r"^Values\s*=", "Definition is just a list of values, not a description"),
    ]

    short_count = 0
    pattern_count = 0

    for row in definitions:
        defn = row.get("definition", "").strip()
        if not defn:
            continue

        # Strip any [SF: ...] or [Domo] or [Vistar] prefix for length check
        defn_no_prefix = re.sub(r"^\[[^\]]*\]\s*", "", defn)

        # Check for short definitions
        if len(defn_no_prefix) < 15:
            short_count += 1
            print(f"  SHORT ({len(defn_no_prefix):2d} chars): [{row['column_name']}:{row['column_type']}] \"{defn}\"")
            issues.append({
                "issue_type": "too_short",
                "column_name": row["column_name"],
                "column_type": row["column_type"],
                "current_definition": defn,
                "suggestion": f"Definition body is only {len(defn_no_prefix)} chars (after prefix) — expand with meaningful detail",
            })

        # Check for generic patterns
        for pattern, reason in generic_patterns:
            if re.search(pattern, defn, re.IGNORECASE):
                pattern_count += 1
                print(f"  TEMPLATE: [{row['column_name']}:{row['column_type']}] {reason}")
                print(f"            \"{defn[:120]}\"")
                issues.append({
                    "issue_type": "generic_template",
                    "column_name": row["column_name"],
                    "column_type": row["column_type"],
                    "current_definition": defn,
                    "suggestion": reason,
                })
                break  # only flag once per row

    print(f"\n  Too-short definitions: {short_count}")
    print(f"  Template/generic definitions: {pattern_count}")


def check_3_prefix_inconsistencies(definitions, schemas):
    """Find [SF: Object] prefixes that don't match actual dataset context."""
    print("\n" + "=" * 80)
    print("CHECK 3: Prefix inconsistencies ([SF: Object] vs actual datasets)")
    print("=" * 80)

    # Build mapping: column_name -> set of dataset_names from schema
    col_datasets = defaultdict(set)
    for s in schemas:
        col_datasets[s["column_name"]].add(s["dataset_name"])

    # Known SF object keywords and what dataset names they'd appear in
    sf_object_keywords = {
        "Opportunity": ["opportunity", "opp", "pipeline", "booking", "booked"],
        "Account": ["account", "advertiser", "agency", "retailer"],
        "Contact": ["contact"],
        "Campaign": ["campaign"],
        "Site__c": ["site", "station", "location", "gbase"],
        "Site/Location": ["site", "station", "location", "gbase"],
        "User": ["user"],
        "DMA__c": ["dma"],
        "Campaign Delivery Report": ["campaign", "delivery"],
    }

    count = 0
    for row in definitions:
        defn = row.get("definition", "").strip()
        if not defn:
            continue

        # Extract SF prefix
        m = re.match(r"^\[SF:\s*([^\]]+)\]", defn)
        if not m:
            continue

        sf_objects_raw = m.group(1).strip()
        # Some have multiple objects like "Account/Opportunity"
        sf_objects = [o.strip() for o in re.split(r"[/,]", sf_objects_raw)]

        col_name = row["column_name"]
        datasets = col_datasets.get(col_name, set())

        if not datasets:
            # Column not found in schema at all — can't validate
            continue

        # Check if at least one SF object keyword appears in any dataset name
        dataset_names_lower = " ".join(d.lower() for d in datasets)

        # This is a heuristic check: if the SF prefix says "Opportunity" but
        # the column only appears in "Site" datasets, that's suspicious
        # We flag only clear mismatches where NONE of the SF objects match ANY dataset
        all_objects_mismatch = True
        for sf_obj in sf_objects:
            keywords = sf_object_keywords.get(sf_obj, [sf_obj.lower()])
            for kw in keywords:
                if kw.lower() in dataset_names_lower:
                    all_objects_mismatch = False
                    break
            if not all_objects_mismatch:
                break

        # Don't flag generic objects that appear everywhere
        if all_objects_mismatch and sf_objects_raw not in ("User",):
            # Additional check: only flag if we have a meaningful number of datasets
            # and can be reasonably confident about the mismatch
            sample_datasets = sorted(datasets)[:3]
            count += 1
            print(f"  [{col_name}:{row['column_type']}] prefix=[SF: {sf_objects_raw}]")
            print(f"    Sample datasets: {' | '.join(sample_datasets)}")
            issues.append({
                "issue_type": "prefix_mismatch",
                "column_name": col_name,
                "column_type": row["column_type"],
                "current_definition": defn,
                "suggestion": f"[SF: {sf_objects_raw}] prefix may not match datasets: {', '.join(sample_datasets[:3])}",
            })

    print(f"\n  Potential prefix mismatches: {count}")


def check_4_duplicate_definitions(definitions):
    """Find multiple different columns sharing the exact same definition."""
    print("\n" + "=" * 80)
    print("CHECK 4: Duplicate definitions (exact same text for different columns)")
    print("=" * 80)

    # Group by definition text
    by_def = defaultdict(list)
    for row in definitions:
        defn = row.get("definition", "").strip()
        if defn:
            by_def[defn].append((row["column_name"], row["column_type"]))

    count = 0
    for defn, cols in sorted(by_def.items(), key=lambda x: -len(x[1])):
        # Only flag if different column_names share the definition
        unique_names = set(c[0] for c in cols)
        if len(unique_names) < 2:
            continue
        count += 1
        col_list = ", ".join(f"{c[0]}:{c[1]}" for c in cols[:6])
        if len(cols) > 6:
            col_list += f" (+{len(cols)-6} more)"
        print(f"  DUPLICATE ({len(unique_names)} columns): \"{defn[:100]}\"")
        print(f"    Columns: {col_list}")
        for c_name, c_type in cols:
            issues.append({
                "issue_type": "duplicate_definition",
                "column_name": c_name,
                "column_type": c_type,
                "current_definition": defn,
                "suggestion": f"Shares exact definition with {len(unique_names)-1} other column(s) — likely copy-paste error",
            })

    print(f"\n  Definition texts shared by multiple columns: {count}")


def check_5_formatting_issues(definitions):
    """Find formatting problems: trailing periods, double spaces, lowercase start, etc."""
    print("\n" + "=" * 80)
    print("CHECK 5: Formatting issues")
    print("=" * 80)

    fmt_counts = defaultdict(int)

    for row in definitions:
        defn = row.get("definition", "").strip()
        if not defn:
            continue

        found_issues = []

        # Strip prefix for some checks
        defn_body = re.sub(r"^\[[^\]]*\]\s*", "", defn)

        # Ends with period
        if defn.endswith("."):
            found_issues.append("ends_with_period")

        # Double spaces
        if "  " in defn:
            found_issues.append("double_space")

        # Starts with lowercase (check the body after any prefix)
        if defn_body and defn_body[0].islower():
            found_issues.append("starts_lowercase")

        # Leading/trailing whitespace in the definition field itself (already stripped, but check original)
        raw_defn = row.get("definition", "")
        if raw_defn != raw_defn.strip():
            found_issues.append("extra_whitespace")

        # Contains newlines or tabs
        if "\n" in raw_defn or "\t" in raw_defn:
            found_issues.append("contains_newline_or_tab")

        # Multiple consecutive commas or other obvious typos
        if ",," in defn:
            found_issues.append("double_comma")

        # Unclosed parentheses/brackets
        if defn.count("(") != defn.count(")"):
            found_issues.append("unbalanced_parentheses")
        if defn.count("[") != defn.count("]"):
            found_issues.append("unbalanced_brackets")

        # Em dash vs hyphen inconsistency (just flag em dashes for awareness)
        # Not flagging this as it may be intentional

        for issue in found_issues:
            fmt_counts[issue] += 1
            issues.append({
                "issue_type": f"formatting_{issue}",
                "column_name": row["column_name"],
                "column_type": row["column_type"],
                "current_definition": defn,
                "suggestion": f"Formatting issue: {issue.replace('_', ' ')}",
            })

    print("  Issue type counts:")
    for issue_type, cnt in sorted(fmt_counts.items(), key=lambda x: -x[1]):
        print(f"    {issue_type:30s}: {cnt}")
    total = sum(fmt_counts.values())
    print(f"\n  Total formatting issues: {total}")


def write_output_csv():
    """Write all issues to the output CSV."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["issue_type", "column_name", "column_type", "current_definition", "suggestion"],
        )
        writer.writeheader()
        writer.writerows(issues)
    print(f"\nOutput CSV written to: {OUTPUT_CSV}")
    print(f"Total issues: {len(issues)}")


def main():
    print("Loading definitions...")
    definitions = load_definitions()
    print(f"  Loaded {len(definitions)} definition rows")

    print("Loading schema data...")
    schemas = load_schemas()
    print(f"  Loaded {len(schemas)} schema entries")

    check_1_conflicting_definitions(definitions)
    check_2_generic_templated(definitions)
    check_3_prefix_inconsistencies(definitions, schemas)
    check_4_duplicate_definitions(definitions)
    check_5_formatting_issues(definitions)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    # Count by issue_type
    type_counts = defaultdict(int)
    for issue in issues:
        type_counts[issue["issue_type"]] += 1
    for it, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {it:35s}: {cnt}")
    print(f"  {'TOTAL':35s}: {len(issues)}")

    write_output_csv()


if __name__ == "__main__":
    main()
