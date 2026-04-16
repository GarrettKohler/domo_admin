#!/usr/bin/env python3
"""
cleanup_definitions_v4.py — Add missing prefixes and consolidate existing ones.

1. Add [Domo] prefix to DomoStats/system columns
2. Add [Vistar] prefix to match_* and Vistar-sourced columns
3. Add [GBase] prefix to GBase-sourced columns
4. Consolidate SF dot-notation prefixes → object-level
5. Shorten long compound SF prefixes → [SF]
"""

import csv, re
from collections import Counter

CSV = "column_definitions.csv"
PREFIX_RE = re.compile(r'^(\[[^\]]+\]\s*)')


def add_prefix(defn: str, prefix: str) -> str:
    """Prepend [prefix] to a definition that has no prefix."""
    if PREFIX_RE.match(defn):
        return defn  # Already has one
    return f"[{prefix}] {defn}"


def replace_prefix(defn: str, new_prefix: str) -> str:
    """Replace existing prefix with new one."""
    m = PREFIX_RE.match(defn)
    if m:
        return f"[{new_prefix}] {defn[m.end():]}"
    return defn


def main():
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    stats = Counter()

    for i, row in enumerate(rows):
        defn = row['definition']
        if not defn or not defn.strip():
            continue

        col = row['column_name']
        defn_lower = defn.lower()
        m = PREFIX_RE.match(defn)
        existing_prefix = m.group(1).strip('[] ') if m else None

        # ── 1. Add [Domo] to Domo system columns ──
        if not existing_prefix:
            is_domo = False
            # Domo form/editable dataset columns
            if col.startswith('__') and any(k in defn_lower for k in [
                'domo form', 'domo editable', 'domo webform', 'domo appdb'
            ]):
                is_domo = True
            # DomoStats / Domo system metadata columns
            elif any(k in defn_lower for k in [
                'domo card', 'domo page', 'domo dataset', 'domo instance',
                'domo buzz', 'cards powered', 'card powered',
                'number of cards on page', 'number of child pages',
                'parent page', 'card title', 'card locked', 'card count',
                'column count', 'page hierarchy', 'domo-managed'
            ]):
                is_domo = True

            if is_domo:
                rows[i]['definition'] = add_prefix(defn, 'Domo')
                stats['added_Domo'] += 1
                continue

        # ── 2. Add [Vistar] to Vistar-sourced columns ──
        if not existing_prefix:
            is_vistar = False
            # match_ columns from PX-to-Vistar comparison
            if col.startswith('match_') and 'vistar' in defn_lower:
                is_vistar = True
            # Vistar venue/API fields
            elif any(k in defn_lower for k in [
                'vistar venue', 'vistar api', 'vistar system',
                'vistar inventory', 'px-to-vistar', 'vistar diagnostic'
            ]):
                is_vistar = True
            # OpenRTB fields that are Vistar-specific
            elif any(k in defn_lower for k in ['openrtb', 'open rtb']):
                is_vistar = True

            if is_vistar:
                rows[i]['definition'] = add_prefix(defn, 'Vistar')
                stats['added_Vistar'] += 1
                continue

        # ── 3. Add [GBase] to GBase-sourced columns ──
        if not existing_prefix:
            is_gbase = False
            # Columns with GBase in the definition
            if 'gbase' in defn_lower:
                # But not just mentioning GBase as one system among many
                # Check if GBase is the primary source
                if any(k in defn_lower for k in [
                    'in gbase', 'from gbase', 'gbase system', 'gbase site',
                    'gbase retailer', 'gbase identifier', 'stored in gbase',
                    'as stored in gbase', 'gbase/mongo', 'gbase (uppercase',
                    'recorded in the gbase', 'in the gbase'
                ]):
                    is_gbase = True

            if is_gbase:
                rows[i]['definition'] = add_prefix(defn, 'GBase')
                stats['added_GBase'] += 1
                continue

        # ── 4. Consolidate SF dot-notation prefixes ──
        if existing_prefix and existing_prefix.startswith('SF:') and '.' in existing_prefix:
            # Extract the object name (before the dot)
            # e.g., "SF: Opportunity.type" → "SF: Opportunity"
            obj_part = existing_prefix.split('.')[0].strip()
            rows[i]['definition'] = replace_prefix(defn, obj_part)
            stats['consolidated_SF_dot'] += 1
            continue

        # ── 5. Shorten long compound SF prefixes ──
        if existing_prefix and existing_prefix.startswith('SF:') and existing_prefix.count('/') >= 3:
            rows[i]['definition'] = replace_prefix(defn, 'SF')
            stats['shortened_SF_compound'] += 1
            continue

    # Write
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Report
    print("V4 PREFIX CLEANUP SUMMARY")
    print("=" * 50)
    for cat, count in stats.most_common():
        print(f"  {cat:30s}: {count:>5d}")
    print(f"  {'TOTAL':30s}: {sum(stats.values()):>5d}")

    # Verify
    print()
    with open(CSV, newline='', encoding='utf-8') as f:
        rows2 = list(csv.DictReader(f))

    defined = [r for r in rows2 if r['definition'].strip()]

    # Check for remaining issues
    remaining_domo = 0
    remaining_vistar = 0
    remaining_gbase = 0
    remaining_sf_dot = 0
    remaining_sf_long = 0

    for r in defined:
        d = r['definition']
        m = PREFIX_RE.match(d)
        pfx = m.group(1).strip('[] ') if m else None

        if not pfx:
            dl = d.lower()
            if any(k in dl for k in ['domo form', 'domo card', 'domo page', 'domo dataset', 'domo editable']):
                remaining_domo += 1
            if r['column_name'].startswith('match_') and 'vistar' in dl:
                remaining_vistar += 1
            if 'in gbase' in dl or 'from gbase' in dl or 'stored in gbase' in dl:
                remaining_gbase += 1
        else:
            if pfx.startswith('SF:') and '.' in pfx:
                remaining_sf_dot += 1
            if pfx.startswith('SF:') and pfx.count('/') >= 3:
                remaining_sf_long += 1

    print("REMAINING ISSUES:")
    print(f"  Domo without [Domo]:       {remaining_domo}")
    print(f"  Vistar without [Vistar]:   {remaining_vistar}")
    print(f"  GBase without [GBase]:     {remaining_gbase}")
    print(f"  SF dot-notation:           {remaining_sf_dot}")
    print(f"  SF long compound:          {remaining_sf_long}")

    # Show updated prefix distribution
    print()
    prefixes = Counter()
    no_pfx = 0
    for r in defined:
        m = PREFIX_RE.match(r['definition'])
        if m:
            prefixes[m.group(1).strip('[] ')] += 1
        else:
            no_pfx += 1

    print(f"PREFIX DISTRIBUTION (top 20):")
    print(f"  (no prefix): {no_pfx}")
    for p, c in prefixes.most_common(20):
        print(f"  [{p}]: {c}")


if __name__ == '__main__':
    main()
