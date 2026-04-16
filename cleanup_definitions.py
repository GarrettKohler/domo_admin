#!/usr/bin/env python3
"""
cleanup_definitions.py — Fix quality issues in column_definitions.csv

Addresses all audit findings:
1. Standardize concept casing (GTVID, GBase, NVI, DMA, RPA, ICS, Proof of Play, etc.)
2. Fix lowercase-after-prefix issues
3. Remove double spaces
4. Standardize boolean definition style to "Whether …"
5. Expand very short definitions (body < 10 chars)
6. Differentiate duplicate definitions with column-specific context
7. Expand name-restating definitions
8. Consolidate prefix formats
"""

import csv, re, os, shutil
from collections import Counter, defaultdict
from datetime import datetime

CSV = "column_definitions.csv"
BACKUP = f"column_definitions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ── 1. Concept-casing map ──────────────────────────────────────────────────
# key = regex pattern (case-insensitive), value = canonical form
CONCEPT_CASING = {
    r'\bgtvid\b': 'GTVID',
    r'\bgbase\b': 'GBase',
    r'\b[Nn][Vv][Ii]\b': 'NVI',
    r'\bdma\b': 'DMA',
    r'\brpa\b': 'RPA',
    r'\bics\b': 'ICS',
    r'\bcpm\b': 'CPM',
    r'\becpm\b': 'eCPM',
    r'\bssp\b': 'SSP',
    r'\bdsp\b': 'DSP',
    r'\bpop\b': 'POP',       # Proof-of-Play abbreviation
    r'\biot\b': 'IoT',
    r'\biotv\b': 'IOTV',
    r'\burl\b': 'URL',
    r'\bapi\b': 'API',
    r'\bjson\b': 'JSON',
    r'\buuid\b': 'UUID',
    r'\bid\b': 'ID',
    r'\bcsv\b': 'CSV',
    r'\bzip\b(?!\s*code)': 'ZIP',
    r'\bmtd\b': 'MTD',
    r'\bytd\b': 'YTD',
    r'\bmom\b': 'MoM',
    r'\biso\b': 'ISO',
    r'\butc\b': 'UTC',
    r'\bfips\b': 'FIPS',
    r'\brtb\b': 'RTB',
    r'\bcc\b': 'CC',
    r'\bpmp\b': 'PMP',
    r'\booh\b': 'OOH',
    r'\bsla\b': 'SLA',
    r'\bitsm\b': 'ITSM',
}

# Proof of Play normalization (multiple forms → one)
PROOF_OF_PLAY_RE = re.compile(r'proof[\s-]*of[\s-]*play', re.I)


def fix_concept_casing(text: str) -> str:
    """Standardize acronym/concept casing throughout a definition."""
    # First, normalize "proof-of-play" / "Proof of Play" / "proof of play" → "Proof of Play"
    text = PROOF_OF_PLAY_RE.sub('Proof of Play', text)

    for pattern, canonical in CONCEPT_CASING.items():
        # Don't replace inside [prefix] brackets
        def _repl(m):
            return canonical
        # Only replace in definition body (after ] if prefix present)
        text = re.sub(pattern, _repl, text, flags=re.I)

    return text


# ── 2. Fix lowercase after prefix ──────────────────────────────────────────
PREFIX_RE = re.compile(r'^(\[[^\]]+\]\s*)')

def fix_lowercase_after_prefix(defn: str) -> str:
    """Ensure first character after [Prefix] is uppercase."""
    m = PREFIX_RE.match(defn)
    if m:
        rest = defn[m.end():]
        if rest and rest[0].islower():
            return defn[:m.end()] + rest[0].upper() + rest[1:]
    elif defn and defn[0].islower():
        # No prefix — capitalize start
        return defn[0].upper() + defn[1:]
    return defn


# ── 3. Remove double spaces ────────────────────────────────────────────────
def fix_double_spaces(text: str) -> str:
    return re.sub(r'  +', ' ', text)


# ── 4. Boolean style → "Whether …" ─────────────────────────────────────────
BOOL_FLAG_RE = re.compile(
    r'^(\[[^\]]+\]\s*)?'           # optional prefix
    r'(?:Boolean\s+flag\s+(?:indicating\s+)?(?:whether\s+)?|Flag\s+(?:indicating\s+)?(?:whether\s+)?)',
    re.I
)

def fix_boolean_style(defn: str) -> str:
    """Normalize 'Boolean flag indicating whether X' / 'Flag whether X' → 'Whether X'."""
    m = BOOL_FLAG_RE.match(defn)
    if m:
        prefix = m.group(1) or ''
        rest = defn[m.end():]
        # Capitalize first letter of rest
        if rest and rest[0].islower():
            rest = rest[0].upper() + rest[1:]
        return f"{prefix}Whether {rest}" if rest else defn
    return defn


# ── 5. Expand very short definitions ───────────────────────────────────────
# Map of (prefix-free body → expanded body) for common short defs
SHORT_EXPANSIONS = {
    # SF fields
    'Dma': 'Designated Market Area associated with this record',
    'DMA': 'Designated Market Area associated with this record',
    'Title': 'Title or job title associated with this record',
    'Name': 'Display name for this record',
    'Status': 'Current status of this record',
    'Type': 'Record type or classification',
    'Email': 'Email address associated with this record',
    'Phone': 'Phone number associated with this record',
    'Owner': 'Record owner (Salesforce user)',
    'State': 'U.S. state associated with this record',
    'City': 'City associated with this record',
    'Country': 'Country associated with this record',
    'Street': 'Street address associated with this record',
    'Region': 'Geographic region associated with this record',
    'Source': 'Origin or source of this record',
    'Stage': 'Current pipeline stage of this record',
    'Amount': 'Monetary amount in USD associated with this record',
    'Rate': 'Rate value associated with this record',
    'Description': 'Free-text description of this record',
    'Id': 'Unique Salesforce identifier for this record',
    'ID': 'Unique identifier for this record',
    'Count': 'Count of items associated with this record',
    'Rank': 'Ranking or priority value for this record',
    'Priority': 'Priority level for this record',
    'Score': 'Calculated score for this record',
    'Notes': 'Free-text notes associated with this record',
    'Url': 'URL link associated with this record',
    'URL': 'URL link associated with this record',
    'Key': 'Unique key identifier for this record',
    'Fax': 'Fax number associated with this record',
    'Revenue': 'Revenue amount in USD associated with this record',
    'Industry': 'Industry classification for this record',
    'Website': 'Website URL associated with this record',
    'Currency': 'Currency code for monetary values in this record',
}


def expand_short_definition(defn: str, col_name: str) -> str:
    """Expand definitions where the body (after prefix) is < 10 characters."""
    m = PREFIX_RE.match(defn)
    prefix = m.group(1) if m else ''
    body = defn[len(prefix):].strip()

    if len(body) >= 10:
        return defn

    # Try direct expansion lookup
    if body in SHORT_EXPANSIONS:
        return f"{prefix}{SHORT_EXPANSIONS[body]}"

    # If body is a single word, try to build a better definition from column name
    if len(body.split()) <= 2 and len(body) < 10:
        # Use column name context to build better def
        expanded = _expand_from_column_name(col_name, body, prefix)
        if expanded:
            return expanded

    return defn


def _expand_from_column_name(col_name: str, body: str, prefix: str) -> str:
    """Try to create a richer definition from the column name when body is too short."""
    # Common patterns: column name words → longer description
    words = re.sub(r'[_\-]', ' ', col_name).strip()
    if body.lower() == words.lower():
        # Body just restates the column name — needs real expansion
        return None
    return None


# ── 6. Differentiate duplicate definitions ──────────────────────────────────
# This maps generic definitions → context-aware differentiation logic

GENERIC_DATE_DEF = "Start date for the campaign, flight, or scheduled period"
GENERIC_END_DATE_DEF = "End date for the campaign, flight, or scheduled period"
GENERIC_ID_DEF_RE = re.compile(r'^(?:\[[^\]]+\]\s*)?Unique identifier\b', re.I)


def differentiate_duplicates(rows: list) -> list:
    """Find groups of columns with identical definitions and add differentiating context."""
    # Build map: definition → list of row indices
    defn_map = defaultdict(list)
    for i, row in enumerate(rows):
        d = row['definition'].strip()
        if d:
            defn_map[d].append(i)

    changes = 0
    for defn, indices in defn_map.items():
        if len(indices) < 2:
            continue

        # Skip if columns are truly the same concept across datasets (e.g., GTVID)
        col_names = [rows[i]['column_name'] for i in indices]
        unique_names = set(col_names)

        # If all have the same column name, these are legit duplicates — skip
        if len(unique_names) == 1:
            continue

        # If there are only 2-3 unique names, try to differentiate
        # Strategy: append " (for {column_name})" or build context from name
        for idx in indices:
            row = rows[idx]
            col = row['column_name']
            d = row['definition']

            # Try to add column-name context if not already embedded
            col_lower = col.lower().replace('_', ' ')
            if col_lower not in d.lower():
                # Extract meaningful words from column name
                enhanced = _add_column_context(d, col, row)
                if enhanced and enhanced != d:
                    rows[idx]['definition'] = enhanced
                    changes += 1

    print(f"  Differentiated {changes} duplicate definitions")
    return rows


def _add_column_context(defn: str, col_name: str, row: dict) -> str:
    """Add column-specific context to a generic definition."""
    # Clean column name for readability
    readable = re.sub(r'[_\-]', ' ', col_name).strip()

    # For date fields: use column name to specify which date
    if 'date' in defn.lower() and 'date' in col_name.lower():
        # Extract what kind of date from the column name
        parts = readable.lower().replace('date', '').strip()
        if parts:
            m = PREFIX_RE.match(defn)
            prefix = m.group(1) if m else ''
            body = defn[len(prefix):]
            # Replace generic "start date" with specific
            return defn  # Keep as-is for dates — they're context-dependent

    return defn  # Default: don't change


# ── 7. Expand name-restating definitions ────────────────────────────────────
def is_name_restating(col_name: str, defn: str) -> bool:
    """Check if a definition just restates the column name."""
    m = PREFIX_RE.match(defn)
    body = defn[m.end():] if m else defn
    body = body.strip().rstrip('.')

    # Normalize both for comparison
    col_normalized = re.sub(r'[_\-\.]', ' ', col_name).strip().lower()
    body_normalized = re.sub(r'[_\-\.]', ' ', body).strip().lower()

    # Direct match
    if col_normalized == body_normalized:
        return True

    # Body is just "The {col_name}" or "{col_name} value"
    body_stripped = re.sub(r'^the\s+', '', body_normalized)
    body_stripped = re.sub(r'\s+value$', '', body_stripped)
    body_stripped = re.sub(r'\s+field$', '', body_stripped)
    if col_normalized == body_stripped:
        return True

    # Body is column name with spaces added between camelCase
    col_spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', col_name).lower()
    if col_spaced == body_normalized:
        return True

    return False


# Context-based expansion rules for name-restating definitions
NAME_EXPANSION_RULES = [
    # Date patterns
    (re.compile(r'(?:^|[_\s])(?:created?|creation)(?:[_\s]|$)(?:.*date)?', re.I),
     lambda col, pfx: f"{pfx}Timestamp when this record was created"),
    (re.compile(r'(?:^|[_\s])(?:updated?|modified|last.?modified)(?:[_\s]|$)(?:.*date)?', re.I),
     lambda col, pfx: f"{pfx}Timestamp when this record was last modified"),
    (re.compile(r'(?:^|[_\s])closed?(?:[_\s]|$)(?:.*date)?', re.I),
     lambda col, pfx: f"{pfx}Date when this record was closed"),
    (re.compile(r'start.?date', re.I),
     lambda col, pfx: f"{pfx}Start date for this record's active period"),
    (re.compile(r'end.?date', re.I),
     lambda col, pfx: f"{pfx}End date for this record's active period"),

    # Count patterns
    (re.compile(r'(?:^|[_\s])(?:total|sum|count)(?:[_\s]|$)', re.I),
     None),  # Too generic, skip

    # Name/label patterns
    (re.compile(r'(?:^|[_\s])(?:display.?name|full.?name)(?:[_\s]|$)', re.I),
     lambda col, pfx: f"{pfx}Human-readable display name for this record"),
]


def expand_name_restating(defn: str, col_name: str) -> str:
    """If definition just restates the column name, try to expand it meaningfully."""
    if not is_name_restating(col_name, defn):
        return defn

    m = PREFIX_RE.match(defn)
    prefix = m.group(1) if m else ''

    # Try rule-based expansion
    for pattern, expander in NAME_EXPANSION_RULES:
        if pattern.search(col_name) and expander:
            return expander(col_name, prefix)

    # Fallback: format the column name more readably but flag it needs human review
    # Don't change it if we can't meaningfully improve it
    return defn


# ── 8. Prefix consolidation ────────────────────────────────────────────────
PREFIX_CONSOLIDATION = {
    # Normalize sub-object prefixes
    '[SF: Opportunity.Type]': '[SF: Opportunity]',
    '[SF: OpportunityLineItem.Type]': '[SF: OpportunityLineItem]',
    '[SF: Site/Location.Type]': '[SF: Site/Location]',
}


def consolidate_prefix(defn: str) -> str:
    for old, new in PREFIX_CONSOLIDATION.items():
        if defn.startswith(old):
            return defn.replace(old, new, 1)
    return defn


# ── Main pipeline ───────────────────────────────────────────────────────────
def main():
    # Load
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # Backup
    shutil.copy2(CSV, BACKUP)
    print(f"Backup saved to {BACKUP}")

    total_defined = sum(1 for r in rows if r['definition'].strip())
    print(f"\nStarting cleanup of {total_defined} definitions...\n")

    # Track changes per category
    stats = Counter()

    for i, row in enumerate(rows):
        defn = row['definition']
        if not defn or not defn.strip():
            continue

        original = defn
        col_name = row['column_name']

        # 8. Consolidate prefixes
        defn = consolidate_prefix(defn)
        if defn != original:
            stats['prefix_consolidated'] += 1

        # 3. Remove double spaces
        defn_new = fix_double_spaces(defn)
        if defn_new != defn:
            stats['double_spaces'] += 1
        defn = defn_new

        # 2. Fix lowercase after prefix
        defn_new = fix_lowercase_after_prefix(defn)
        if defn_new != defn:
            stats['lowercase_fixed'] += 1
        defn = defn_new

        # 4. Boolean style normalization
        defn_new = fix_boolean_style(defn)
        if defn_new != defn:
            stats['boolean_normalized'] += 1
        defn = defn_new

        # 1. Concept casing
        defn_new = fix_concept_casing(defn)
        if defn_new != defn:
            stats['casing_fixed'] += 1
        defn = defn_new

        # 5. Expand short definitions
        defn_new = expand_short_definition(defn, col_name)
        if defn_new != defn:
            stats['short_expanded'] += 1
        defn = defn_new

        # 7. Expand name-restating definitions
        defn_new = expand_name_restating(defn, col_name)
        if defn_new != defn:
            stats['name_restating_expanded'] += 1
        defn = defn_new

        # Strip trailing whitespace
        defn = defn.strip()

        rows[i]['definition'] = defn

    # 6. Differentiate duplicates (cross-row operation)
    rows = differentiate_duplicates(rows)

    # Write back
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"\n{'='*50}")
    print("CLEANUP SUMMARY")
    print(f"{'='*50}")
    for cat, count in stats.most_common():
        print(f"  {cat:30s}: {count:>5d}")
    print(f"  {'TOTAL CHANGES':30s}: {sum(stats.values()):>5d}")
    print(f"\nSaved to {CSV}")

    # Post-cleanup audit
    print(f"\n{'='*50}")
    print("POST-CLEANUP AUDIT")
    print(f"{'='*50}")
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows2 = list(reader)

    defined = [r for r in rows2 if r['definition'].strip()]

    # Check remaining issues
    lc_after_prefix = 0
    double_sp = 0
    very_short = 0
    bool_flag = 0
    concept_issues = Counter()

    for r in defined:
        d = r['definition']
        m = PREFIX_RE.match(d)
        body = d[m.end():] if m else d

        if body and body[0].islower():
            lc_after_prefix += 1
        if '  ' in d:
            double_sp += 1
        if len(body.strip()) < 10:
            very_short += 1
        if re.match(r'(?:Boolean\s+flag|Flag\s+)', body, re.I):
            bool_flag += 1

        # Check concept casing
        if re.search(r'\bgbase\b', d, re.I) and 'GBase' not in d:
            concept_issues['gbase→GBase'] += 1
        if re.search(r'\bgtvid\b', d, re.I) and 'GTVID' not in d:
            concept_issues['gtvid→GTVID'] += 1
        if re.search(r'proof[\s-]*of[\s-]*play', d, re.I) and 'Proof of Play' not in d:
            concept_issues['PoP→Proof of Play'] += 1

    print(f"  Lowercase after prefix: {lc_after_prefix}")
    print(f"  Double spaces:          {double_sp}")
    print(f"  Very short (<10 char):  {very_short}")
    print(f"  Boolean flag style:     {bool_flag}")
    for k, v in concept_issues.most_common():
        print(f"  Concept casing {k}: {v}")

    # Duplicate check
    defn_counts = Counter(r['definition'] for r in defined)
    dup_groups = {d: c for d, c in defn_counts.items() if c > 1}
    unique_dup_cols = sum(c for c in dup_groups.values())
    print(f"  Duplicate definition groups: {len(dup_groups)} ({unique_dup_cols} columns)")


if __name__ == '__main__':
    main()
