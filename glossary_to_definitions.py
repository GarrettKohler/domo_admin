#!/usr/bin/env python3
"""Cross-reference the GSTV glossary with undefined columns to auto-populate
definitions (Option B).

Reads:
  - gstv_glossary.csv (term, acronym, definition, domain, category)
  - column_definitions.csv (column_name, column_type, dataset_count, ...)

For each undefined column, checks if any glossary term or acronym appears
in the column name. If so, generates a definition using the glossary context.
"""

import csv
import re
from collections import Counter
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parent / "gstv_glossary.csv"
DEFINITIONS_PATH = Path(__file__).resolve().parent / "column_definitions.csv"


def load_glossary() -> list[dict]:
    """Load glossary terms."""
    with open(GLOSSARY_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_definitions() -> list[dict]:
    """Load column definitions."""
    with open(DEFINITIONS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return rows, fieldnames


def build_term_index(glossary: list[dict]) -> dict[str, dict]:
    """Build a lookup from normalized term/acronym to glossary entry.

    Returns {lowercase_term: glossary_row} and {lowercase_acronym: glossary_row}
    """
    index = {}
    for entry in glossary:
        term = entry["term"].strip().lower()
        if term:
            index[term] = entry
        acronym = entry.get("acronym", "").strip().lower()
        if acronym and acronym != term:
            # Split multi-acronyms like "GRP/TRP"
            for acr in acronym.split("/"):
                acr = acr.strip().lower()
                if acr and len(acr) >= 2:
                    index[acr] = entry
    return index


def match_column_to_glossary(
    col_name: str,
    term_index: dict[str, dict],
) -> list[dict]:
    """Find glossary entries that match a column name.

    Returns list of matching glossary entries, best match first.
    """
    col_lower = col_name.lower()
    # Normalize column name for matching
    col_words = set(re.split(r"[\s_\-\.]+", col_lower))
    col_words = {w for w in col_words if len(w) >= 2}

    matches = []
    for term_key, entry in term_index.items():
        term_words = set(re.split(r"[\s_\-\.\/]+", term_key))

        # Exact match on acronym (whole word)
        if entry.get("acronym"):
            for acr in entry["acronym"].split("/"):
                acr_clean = acr.strip()
                if acr_clean and re.search(
                    r"\b" + re.escape(acr_clean) + r"\b", col_name, re.IGNORECASE
                ):
                    matches.append((entry, "acronym", len(acr_clean)))

        # Term name appears in column (as substring or word boundary)
        if len(term_key) >= 4:  # avoid short false positives
            if re.search(r"\b" + re.escape(term_key) + r"\b", col_lower):
                matches.append((entry, "term", len(term_key)))

        # Multi-word term: all words present in column
        if len(term_words) >= 2 and term_words.issubset(col_words):
            matches.append((entry, "words", len(term_words)))

    # Deduplicate and sort by match quality (longer matches first)
    seen = set()
    unique_matches = []
    for entry, match_type, score in sorted(matches, key=lambda x: -x[2]):
        key = entry["term"]
        if key not in seen:
            seen.add(key)
            unique_matches.append(entry)

    return unique_matches


def generate_definition(col_name: str, glossary_entry: dict) -> str:
    """Generate a column definition from a glossary match."""
    term = glossary_entry["term"]
    acronym = glossary_entry.get("acronym", "").strip()
    gloss_def = glossary_entry["definition"]
    domain = glossary_entry.get("domain", "")

    # Build a concise definition
    # If column is just the acronym, expand it
    if acronym and col_name.strip().upper() == acronym.upper():
        # Column is exactly the acronym
        short_def = gloss_def.split(".")[0].strip()  # first sentence
        if len(short_def) > 120:
            short_def = short_def[:117] + "..."
        prefix = f"[Glossary] {term}"
        if acronym:
            prefix = f"[Glossary] {acronym} ({term})"
        return f"{prefix} — {short_def}"

    # Column contains the term — contextualize
    short_def = gloss_def.split(".")[0].strip()
    if len(short_def) > 100:
        short_def = short_def[:97] + "..."

    prefix = f"[Glossary]"
    if domain:
        prefix = f"[Glossary: {domain}]"

    return f"{prefix} {short_def}"


def main():
    glossary = load_glossary()
    print(f"Loaded {len(glossary)} glossary terms")

    rows, fieldnames = load_definitions()
    print(f"Loaded {len(rows)} column definitions")

    term_index = build_term_index(glossary)
    print(f"Built term index with {len(term_index)} lookup keys")

    # Find undefined columns
    undefined = [(i, row) for i, row in enumerate(rows)
                 if not row.get("definition", "").strip()]
    print(f"Found {len(undefined)} undefined columns\n")

    # Match columns to glossary
    matched = 0
    match_stats = Counter()
    examples = []

    for idx, row in undefined:
        col_name = row["column_name"]
        matches = match_column_to_glossary(col_name, term_index)

        if matches:
            best = matches[0]
            definition = generate_definition(col_name, best)
            rows[idx]["definition"] = definition
            matched += 1
            match_stats[best["term"]] += 1
            if len(examples) < 20:
                examples.append((col_name, best["term"], definition[:80]))

    # Write updated definitions
    with open(DEFINITIONS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Report
    print(f"{'='*70}")
    print("GLOSSARY → COLUMN DEFINITIONS RESULTS")
    print(f"{'='*70}")
    print(f"  Undefined columns:          {len(undefined)}")
    print(f"  Matched to glossary:        {matched}")
    print(f"  Remaining undefined:        {len(undefined) - matched}")
    print(f"  New coverage:               {matched}/{len(undefined)} "
          f"({100*matched/len(undefined):.1f}% of undefined)")

    # Total coverage
    total = len(rows)
    defined = sum(1 for r in rows if r.get("definition", "").strip())
    print(f"\n  Overall column coverage:    {defined}/{total} "
          f"({100*defined/total:.1f}%)")

    print(f"\n  Top glossary terms matched:")
    for term, count in match_stats.most_common(15):
        print(f"    {term:<40s} {count:>4} columns")

    if examples:
        print(f"\n  EXAMPLES:")
        print(f"  {'Column Name':<35s} | {'Matched Term':<25s} | {'Definition'}")
        print(f"  {'-'*35}-+-{'-'*25}-+-{'-'*50}")
        for col, term, defn in examples:
            print(f"  {col[:33]:<35s} | {term[:23]:<25s} | {defn}")


if __name__ == "__main__":
    main()
