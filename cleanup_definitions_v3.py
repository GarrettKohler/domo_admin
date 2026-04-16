#!/usr/bin/env python3
"""
cleanup_definitions_v3.py — Differentiate duplicate definitions where column
names provide meaningful context differences.

Strategy: For columns with specific context in their name (e.g., "Contract Renewal
Start Date" vs generic "Start Date"), incorporate that context into the definition.
"""

import csv, re
from collections import defaultdict, Counter

CSV = "column_definitions.csv"
PREFIX_RE = re.compile(r'^(\[[^\]]+\]\s*)')

# ── Context extraction for date fields ──────────────────────────────────────
# Column names that have specific qualifiers before/after "Start Date", "End Date", etc.

def extract_date_context(col_name: str) -> str | None:
    """Extract qualifying context from a date column name."""
    col = col_name.strip()

    # Patterns: "X Start Date" or "Start Date - X"
    # Remove the generic date part and return the qualifier
    for date_word in ['Start Date', 'End Date', 'Created Date', 'Modified Date',
                      'Last Modified Date', 'Updated Date', 'Run Date', 'Schedule Date',
                      'POP Date', 'Install Date', 'Installation Date']:
        dw_lower = date_word.lower()
        col_lower = col.lower().replace('_', ' ').replace('-', ' ')

        if dw_lower in col_lower:
            # Remove the date word and see what's left
            remainder = col_lower.replace(dw_lower, '').strip()
            remainder = re.sub(r'\s+', ' ', remainder).strip(' -_./\\')
            if remainder and len(remainder) > 2:
                return remainder.title()
    return None


def differentiate_date_defs(rows: list) -> int:
    """Add context to date definitions where column names provide specificity."""
    changes = 0

    # Generic date definitions to differentiate
    GENERIC_DEFS = {
        'Start date for the campaign, flight, or scheduled period',
        'End date for the campaign, flight, or scheduled period',
        'Date/time when the record was originally created',
        'Date/time when the record was last updated',
        'Date/time when the record was last modified',
        'Date of the scheduled ad play or content delivery',
        'Calendar day for the data record',
        'Date of the Proof of Play event',
        'Date of hardware installation at the site',
        'Date of the last process execution',
        'Date of the ad play event',
    }

    for i, row in enumerate(rows):
        defn = row['definition']
        if not defn.strip():
            continue

        m = PREFIX_RE.match(defn)
        prefix = m.group(1) if m else ''
        body = defn[len(prefix):]

        if body not in GENERIC_DEFS:
            continue

        col = row['column_name']
        ctx = extract_date_context(col)

        if ctx:
            # Build context-specific version
            # E.g., "Start date for the campaign..." + context "Contract Renewal"
            # → "Start date for the contract renewal period"
            ctx_lower = ctx.lower()

            if 'start date' in body.lower():
                new_body = f"Start date for the {ctx_lower} period"
            elif 'end date' in body.lower():
                new_body = f"End date for the {ctx_lower} period"
            elif 'created' in body.lower():
                new_body = f"Date/time when the {ctx_lower} record was originally created"
            elif 'last updated' in body.lower() or 'last modified' in body.lower():
                new_body = f"Date/time when the {ctx_lower} record was last updated"
            elif 'scheduled' in body.lower():
                new_body = f"Date of the {ctx_lower} scheduled event"
            elif 'installation' in body.lower() or 'install' in body.lower():
                new_body = f"Date of {ctx_lower} hardware installation at the site"
            elif 'last process' in body.lower() or 'last run' in body.lower():
                new_body = f"Date of the last {ctx_lower} process execution"
            elif 'play event' in body.lower():
                new_body = f"Date of the {ctx_lower} ad play event"
            elif 'Proof of Play' in body:
                new_body = f"Date of the {ctx_lower} Proof of Play event"
            else:
                new_body = f"{body} ({ctx_lower})"

            rows[i]['definition'] = f"{prefix}{new_body}"
            changes += 1

    return changes


def differentiate_same_concept_variants(rows: list) -> int:
    """For same-definition groups where columns are just naming variants
    (Start Date / START_DATE / start_date), keep them the same — they're fine."""
    return 0  # Intentionally no-op; these are legitimate


def main():
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    stats = Counter()

    # Differentiate date fields
    n = differentiate_date_defs(rows)
    stats['date_differentiated'] = n

    # Write
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Report
    print(f"V3 CLEANUP SUMMARY")
    print(f"{'='*50}")
    for cat, count in stats.most_common():
        print(f"  {cat:30s}: {count:>5d}")

    # Remaining dup check
    with open(CSV, newline='', encoding='utf-8') as f:
        rows2 = list(csv.DictReader(f))

    defined = [r for r in rows2 if r['definition'].strip()]
    defn_map = defaultdict(list)
    for r in defined:
        defn_map[r['definition']].append(r['column_name'])

    diff_groups = [(d, sorted(set(cols))) for d, cols in defn_map.items()
                   if len(set(cols)) > 1]
    diff_groups.sort(key=lambda x: -len(x[1]))

    total_dup_cols = sum(len(cols) for _, cols in diff_groups)
    print(f"\n  Remaining diff-name duplicate groups: {len(diff_groups)} ({total_dup_cols} columns)")


if __name__ == '__main__':
    main()
