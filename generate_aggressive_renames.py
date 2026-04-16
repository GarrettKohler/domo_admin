#!/usr/bin/env python3
"""Generate aggressive rename suggestions that restructure names to the full
GSTV naming convention: [Environment] - [Domain] - [Description] - [Qualifier]

This produces a SECOND rename column (alongside the conservative mechanical
fixes from generate_renames.py). The aggressive pass:
  1. Applies all conservative fixes first
  2. Extracts environment prefix (PROD/DEV/TEST/DEPRECATED)
  3. Extracts modifiers (COPY/View/Editable View)
  4. Classifies the domain via analytics._classify_domain()
  5. Strips redundant domain words from the description
  6. Extracts trailing qualifiers (dates, versions)
  7. Reassembles as: [Env -] Domain - Description [- Qualifier]
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics import _classify_domain  # noqa: E402
from generate_renames import apply_rename_rules  # noqa: E402

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"
OUT_DIR = Path(__file__).resolve().parent

# ── Domain → short prefix mapping ─────────────────────────────────────────
DOMAIN_SHORT = {
    "Test / Temp / Archive":     None,  # env prefix handles this
    "Monitoring & Governance":   "Governance",
    "Traffic Instructions":      "Traffic Instructions",
    "RPA":                       "RPA",
    "Revenue & Monetization":    "Revenue",
    "Sites & Locations":         "Sites",
    "Proof of Play":             "POP",
    "Impressions":               "Impressions",
    "Transactions":              "Transactions",
    "Salesforce / CRM":          "Salesforce",
    "Programmatic Operations":   "Programmatic Ops",
    "Programmatic":              "Programmatic",
    "Campaigns & Delivery":      "Campaigns",
    "Site Analytics":             "Analytics",
    "Managed Services":          "Managed Services",
    "Engineering":               "Engineering",
    "Other / Unclassified":      None,  # can't classify → skip restructure
}

# ── Domain-specific keywords to strip from description (they'd be redundant
#    once the domain prefix is present) ─────────────────────────────────────
DOMAIN_STRIP_WORDS: dict[str, list[re.Pattern]] = {
    "Monitoring & Governance": [
        re.compile(r"^DomoStats\s*[-:]?\s*", re.I),
        re.compile(r"\bDomo\s+(System|Admin|Governance)\s*[-:]?\s*", re.I),
        re.compile(r"\bGovernance\s*[-:]?\s*", re.I),
        re.compile(r"\bObservability\s*[-:]?\s*", re.I),
    ],
    "Traffic Instructions": [
        re.compile(r"\bTraffic\s+Instructions?\s*[-:]?\s*", re.I),
    ],
    "RPA": [
        re.compile(r"^\s*RPA\s*[-:]?\s*", re.I),
    ],
    "Revenue & Monetization": [
        re.compile(r"^\s*Revenue\s*[-:]?\s*", re.I),
    ],
    "Proof of Play": [
        re.compile(r"\bProof\s+of\s+Play\s*[-:]?\s*", re.I),
        re.compile(r"\bPOP\s*[-:]?\s*", re.I),
    ],
    "Impressions": [
        re.compile(r"^\s*Impressions?\s*[-:]?\s*", re.I),
    ],
    "Transactions": [
        re.compile(r"^\s*Transactions?\s*[-:]?\s*", re.I),
    ],
    "Salesforce / CRM": [
        re.compile(r"^\s*Salesforce\s*[-:]?\s*", re.I),
        re.compile(r"^\s*SF\s*[-:]?\s*", re.I),
    ],
    "Programmatic Operations": [
        re.compile(r"^\s*Programmatic\s+(Operations?|Ops)\s*[-:]?\s*", re.I),
    ],
    "Programmatic": [
        re.compile(r"^\s*Programmatic\s*[-:]?\s*", re.I),
    ],
    "Campaigns & Delivery": [
        re.compile(r"^\s*Campaign\s+(Delivery|Impact|Tracking)\s*[-:]?\s*", re.I),
    ],
    "Sites & Locations": [
        re.compile(r"^\s*Sites?\s+(and|&)\s+Locations?\s*[-:]?\s*", re.I),
    ],
    "Managed Services": [
        re.compile(r"^\s*Managed\s+Services?\s*[-:]?\s*", re.I),
    ],
    "Engineering": [
        re.compile(r"^\s*Engineering\s*[-:]?\s*", re.I),
    ],
    "Site Analytics": [],
}

# ── Environment prefixes to extract ───────────────────────────────────────
ENV_PREFIXES = [
    ("DEPRECATED - ", "DEPRECATED"),
    ("PROD - ",       "PROD"),
    ("TEST - ",       "TEST"),
    ("DEV - ",        "DEV"),
]

# ── Modifier prefixes to extract ──────────────────────────────────────────
MODIFIER_PREFIXES = [
    ("Editable View - ", "Editable View"),
    ("COPY - ",          "Copy"),
    ("View - ",          "View"),
]

# ── Qualifier patterns (extracted from end of name) ───────────────────────
TRAILING_QUALIFIER_PATTERNS = [
    # Version strings: V2.0, v3, V4
    re.compile(r"\s*-\s*(V\d+(?:\.\d+)?)\s*$", re.I),
    # Date-like qualifiers: 2024-01-15, Q3 2024, 2024
    re.compile(r"\s*-\s*(Q[1-4]\s+\d{4})\s*$", re.I),
    re.compile(r"\s*-\s*(\d{4}-\d{2}-\d{2})\s*$"),
    re.compile(r"\s*-\s*(\d{4}-\d{2})\s*$"),
    # Time windows: 2w, 30d, 13w
    re.compile(r"\s*-\s*(\d+[dwm])\s*$", re.I),
    # Part N
    re.compile(r"\s*-\s*(Part\s+\d+)\s*$", re.I),
    # Slot counts like "4 Slots"
    re.compile(r"\s*-\s*(\d+\s+Slots?)\s*$", re.I),
]

# Leading date/period qualifiers (move to end)
LEADING_DATE_RE = re.compile(
    r"^(\d{4}(?:-\d{2})?(?:-\d{2})?)\s*-\s*", re.I
)
LEADING_QUARTER_RE = re.compile(
    r"^(Q[1-4]\s+\d{4})\s*-\s*", re.I
)

# ── Retailer/brand → Managed Services sub-prefix ─────────────────────────
RETAILER_NAMES = {
    "casey": "Casey's", "casey's": "Casey's",
    "speedway": "Speedway", "circle k": "Circle K",
    "kwik": "Kwik Trip", "wawa": "Wawa", "pilot": "Pilot",
    "sheetz": "Sheetz", "marathon": "Marathon",
    "tesoro": "Tesoro", "holiday station": "Holiday Station",
    "bp": "BP", "shell": "Shell", "chevron": "Chevron",
    "exxon": "Exxon", "cumberland": "Cumberland Farms",
    "7-eleven": "7-Eleven", "7 eleven": "7-Eleven",
    "loves": "Love's", "love's": "Love's",
    "murphy": "Murphy", "sunoco": "Sunoco",
    "phillips": "Phillips 66", "valero": "Valero",
    "arco": "ARCO", "citgo": "Citgo",
}

# SSP/exchange names → Programmatic sub-prefix
SSP_NAMES = {
    "vistar": "Vistar", "place exchange": "Place Exchange",
    "px": "PX", "magnite": "Magnite",
    "hivestack": "Hivestack", "broadsign": "Broadsign",
}

# System names that serve as description prefixes
SYSTEM_NAMES = {
    "gbase": "GBase", "pluto": "Pluto", "odyssey": "Odyssey",
    "krypton": "Krypton", "jupiter": "Jupiter",
    "comscore": "Comscore", "gilbarco": "Gilbarco",
    "ics": "ICS", "applause": "Applause",
    "tdlinx": "TDLinx", "dxpromote": "DXPromote", "dxp": "DXP",
    "jira": "Jira", "salesforce": "Salesforce",
    "noc": "NOC", "iotv": "IOTV",
}


def _extract_env(name: str) -> tuple[str | None, str]:
    """Extract environment prefix from start of name."""
    for prefix_str, env_label in ENV_PREFIXES:
        if name.startswith(prefix_str):
            return env_label, name[len(prefix_str):]
    return None, name


def _extract_modifier(name: str) -> tuple[str | None, str]:
    """Extract COPY/View/Editable View from start of name."""
    for prefix_str, mod_label in MODIFIER_PREFIXES:
        if name.startswith(prefix_str):
            return mod_label, name[len(prefix_str):]
    return None, name


def _extract_trailing_qualifiers(name: str) -> tuple[str, list[str]]:
    """Extract trailing qualifiers (dates, versions, parts) from end of name."""
    qualifiers = []
    changed = True
    while changed:
        changed = False
        for pat in TRAILING_QUALIFIER_PATTERNS:
            m = pat.search(name)
            if m:
                qualifiers.insert(0, m.group(1))
                name = name[:m.start()].rstrip()
                changed = True
                break
    return name, qualifiers


def _extract_leading_date(name: str) -> tuple[str, list[str]]:
    """Move leading date qualifiers to the qualifier position."""
    qualifiers = []
    m = LEADING_QUARTER_RE.match(name)
    if m:
        qualifiers.append(m.group(1))
        name = name[m.end():]
    else:
        m = LEADING_DATE_RE.match(name)
        if m:
            qualifiers.append(m.group(1))
            name = name[m.end():]
    return name, qualifiers


def _strip_domain_words(name: str, domain: str) -> str:
    """Remove words that are redundant given the domain prefix."""
    patterns = DOMAIN_STRIP_WORDS.get(domain, [])
    for pat in patterns:
        name = pat.sub("", name).strip()
    # Clean up leading separators left behind
    name = re.sub(r"^\s*[-:]\s*", "", name).strip()
    return name


def _detect_sub_prefix(name: str, domain: str) -> tuple[str | None, str]:
    """For certain domains, extract a sub-prefix (retailer name, SSP name, system name)."""
    name_lower = name.lower()

    # Managed Services → extract retailer name
    if domain == "Managed Services":
        for key, label in RETAILER_NAMES.items():
            if re.search(r"\b" + re.escape(key) + r"\b", name_lower):
                # Remove the retailer name from the description
                cleaned = re.sub(r"\b" + re.escape(key) + r"'?s?\b", "", name, flags=re.I).strip()
                cleaned = re.sub(r"^\s*[-:]\s*", "", cleaned).strip()
                cleaned = re.sub(r"\s*[-:]\s*$", "", cleaned).strip()
                if cleaned:
                    return label, cleaned
                return label, name

    # Programmatic / Programmatic Ops → extract SSP name
    if domain in ("Programmatic", "Programmatic Operations"):
        for key, label in SSP_NAMES.items():
            if re.search(r"\b" + re.escape(key) + r"\b", name_lower):
                cleaned = re.sub(r"\b" + re.escape(key) + r"\b", "", name, flags=re.I).strip()
                cleaned = re.sub(r"^\s*[-:]\s*", "", cleaned).strip()
                cleaned = re.sub(r"\s*[-:]\s*$", "", cleaned).strip()
                if cleaned:
                    return label, cleaned
                return label, name

    return None, name


def _clean_separators(name: str) -> str:
    """Clean up messy separators: double dashes, leading/trailing dashes, etc."""
    name = re.sub(r"\s*-\s*-\s*", " - ", name)
    name = re.sub(r"^\s*-\s*", "", name)
    name = re.sub(r"\s*-\s*$", "", name)
    name = re.sub(r"\s+-\s+", " - ", name)
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip()


def _already_well_structured(name: str, domain: str) -> bool:
    """Check if a name already follows Domain - Description - Qualifier pattern."""
    short = DOMAIN_SHORT.get(domain)
    if not short:
        return False
    # Check if it starts with the domain prefix (or close variant)
    if name.startswith(f"{short} - "):
        return True
    return False


def aggressive_restructure(
    name: str, domain: str, dept: str, item_type: str = "dataset"
) -> tuple[str, bool]:
    """Restructure a name to full convention compliance.

    Returns (restructured_name, was_changed).
    """
    # 1. Apply conservative fixes first
    clean, _ = apply_rename_rules(name)

    # 2. Get domain short prefix
    domain_prefix = DOMAIN_SHORT.get(domain)

    # If we can't classify (Other/Unclassified) or it's Test/Temp (env-only),
    # just return the conservative fix
    if domain_prefix is None:
        if domain == "Test / Temp / Archive":
            # Conservative fix already handles env prefixes correctly
            return clean, clean != name.strip()
        # Unclassified — can't restructure meaningfully
        return clean, clean != name.strip()

    # 3. Check if already well-structured after conservative fix
    # Extract env to check the body
    env, body = _extract_env(clean)
    if _already_well_structured(body, domain):
        return clean, clean != name.strip()

    # 4. Extract modifier (COPY/View)
    modifier, body = _extract_modifier(body)

    # 5. Extract trailing qualifiers
    body, trailing_quals = _extract_trailing_qualifiers(body)

    # 6. Extract leading date qualifiers (move to end)
    body, leading_quals = _extract_leading_date(body)
    all_qualifiers = leading_quals + trailing_quals

    # 7. Strip redundant domain words from description
    body = _strip_domain_words(body, domain)

    # 8. Detect sub-prefix (retailer, SSP, system)
    sub_prefix, body = _detect_sub_prefix(body, domain)

    # 9. Clean up the description body
    body = _clean_separators(body)

    # If body is empty after all stripping, reconstruct from conservative name
    if not body or len(body) < 3:
        # Try to get meaningful body from conservative fix (strip env prefix)
        _, fallback_body = _extract_env(clean)
        _, fallback_body = _extract_modifier(fallback_body)
        fallback_body = _clean_separators(fallback_body)
        if fallback_body and len(fallback_body) >= 3:
            body = fallback_body
        else:
            # Fallback: just return conservative fix
            return clean, clean != name.strip()

    # 10. Reassemble
    parts = []

    # Environment prefix
    if env:
        parts.append(env)

    # Domain prefix
    parts.append(domain_prefix)

    # Sub-prefix (retailer/SSP name)
    if sub_prefix:
        parts.append(sub_prefix)

    # Description body
    parts.append(body)

    # Modifier (View/Copy) as qualifier
    if modifier:
        all_qualifiers.insert(0, modifier)

    # Qualifiers
    for q in all_qualifiers:
        parts.append(q)

    result = " - ".join(parts)

    # Final cleanup
    result = _clean_separators(result)
    result = re.sub(r"\s{2,}", " ", result)

    # Sanity checks — fall back to conservative fix if restructure is bad
    # 1. Result is same as conservative fix
    if result == clean:
        return clean, clean != name.strip()

    # 2. Result is just the domain label (empty description)
    _, result_no_env = _extract_env(result)  # strip env for comparison
    check_vals = {domain_prefix, domain}
    if sub_prefix:
        check_vals.add(f"{domain_prefix} - {sub_prefix}")
    if result_no_env and result_no_env.strip() in check_vals:
        return clean, clean != name.strip()

    # 3. Result is shorter than 10 chars (too aggressively stripped)
    if len(result) < 10:
        return clean, clean != name.strip()

    return result, True


def main() -> None:
    """Generate aggressive rename CSVs for all datasets and dataflows."""
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache file not found at {CACHE_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CACHE_PATH) as f:
        cache = json.load(f)

    datasets = cache.get("datasets", [])
    dataflows = cache.get("dataflows", [])
    print(f"Loaded {len(datasets)} datasets and {len(dataflows)} dataflows\n")

    # Build owner lookup
    owner_lookup: dict[int, str] = {}
    for ds in datasets:
        oid = ds.get("owner_id")
        oname = ds.get("owner_name", "")
        if oid and oname:
            owner_lookup[int(oid)] = oname

    # --- Load conservative renames for comparison ---
    conservative_ds: dict[str, str] = {}  # dataset_id → proposed_name
    conservative_df: dict[str, str] = {}  # dataflow_id → proposed_name
    try:
        with open(OUT_DIR / "dataset_renames.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conservative_ds[row["dataset_id"]] = row["proposed_name"]
    except FileNotFoundError:
        pass
    try:
        with open(OUT_DIR / "dataflow_renames.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conservative_df[row["dataflow_id"]] = row["proposed_name"]
    except FileNotFoundError:
        pass

    # --- Process datasets ---
    ds_results: list[dict] = []
    ds_existing_names: set[str] = {ds["dataset_name"].strip() for ds in datasets}
    ds_proposed_names: dict[str, str] = {}  # proposed → ds_id (for dup check)

    for ds in datasets:
        ds_id = ds["dataset_id"]
        current = ds["dataset_name"]
        owner = ds.get("owner_name", "")
        domain, dept = _classify_domain(current)

        restructured, changed = aggressive_restructure(current, domain, dept, "dataset")

        if not changed or restructured == current.strip():
            continue

        # Skip if same as conservative rename (no added value)
        cons_name = conservative_ds.get(ds_id, current.strip())
        if restructured == cons_name:
            continue

        ds_results.append({
            "dataset_id": ds_id,
            "current_name": current,
            "conservative_name": cons_name if cons_name != current.strip() else "",
            "restructured_name": restructured,
            "domain": domain,
            "department": dept,
            "owner_name": owner,
        })

        if restructured in ds_proposed_names:
            ds_proposed_names[restructured] = "DUPLICATE"
        else:
            ds_proposed_names[restructured] = ds_id

    # Remove duplicates
    dup_names = {n for n, v in ds_proposed_names.items() if v == "DUPLICATE"}
    renamed_originals = {r["current_name"].strip() for r in ds_results}
    existing_keeping = ds_existing_names - renamed_originals
    ds_clean = []
    ds_dup_count = 0
    for r in ds_results:
        if r["restructured_name"] in dup_names or r["restructured_name"] in existing_keeping:
            ds_dup_count += 1
            continue
        ds_clean.append(r)
    ds_results = ds_clean

    # --- Process dataflows ---
    df_results: list[dict] = []
    df_existing_names: set[str] = {df["dataflow_name"].strip() for df in dataflows}
    df_proposed_names: dict[str, str] = {}

    for df in dataflows:
        df_id = str(df["dataflow_id"])
        current = df["dataflow_name"]
        owner_id_str = str(df.get("owner_id", ""))
        try:
            owner = owner_lookup.get(int(owner_id_str), "")
        except (ValueError, TypeError):
            owner = ""

        domain, dept = _classify_domain(current)
        restructured, changed = aggressive_restructure(current, domain, dept, "dataflow")

        if not changed or restructured == current.strip():
            continue

        cons_name = conservative_df.get(df_id, current.strip())
        if restructured == cons_name:
            continue

        df_results.append({
            "dataflow_id": df_id,
            "current_name": current,
            "conservative_name": cons_name if cons_name != current.strip() else "",
            "restructured_name": restructured,
            "domain": domain,
            "department": dept,
            "owner_name": owner,
        })

        if restructured in df_proposed_names:
            df_proposed_names[restructured] = "DUPLICATE"
        else:
            df_proposed_names[restructured] = df_id

    # Remove duplicates
    dup_names_df = {n for n, v in df_proposed_names.items() if v == "DUPLICATE"}
    renamed_originals_df = {r["current_name"].strip() for r in df_results}
    existing_keeping_df = df_existing_names - renamed_originals_df
    df_clean = []
    df_dup_count = 0
    for r in df_results:
        if r["restructured_name"] in dup_names_df or r["restructured_name"] in existing_keeping_df:
            df_dup_count += 1
            continue
        df_clean.append(r)
    df_results = df_clean

    # --- Write CSVs ---
    ds_csv = OUT_DIR / "dataset_aggressive_renames.csv"
    with open(ds_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset_id", "current_name", "conservative_name",
                         "restructured_name", "domain", "department", "owner_name"],
        )
        writer.writeheader()
        writer.writerows(ds_results)

    df_csv = OUT_DIR / "dataflow_aggressive_renames.csv"
    with open(df_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataflow_id", "current_name", "conservative_name",
                         "restructured_name", "domain", "department", "owner_name"],
        )
        writer.writeheader()
        writer.writerows(df_results)

    # --- Summary ---
    total = len(datasets) + len(dataflows)
    total_restructured = len(ds_results) + len(df_results)

    # Domain breakdown
    domain_counter: Counter = Counter()
    for r in ds_results + df_results:
        domain_counter[r["domain"]] += 1

    print("=" * 70)
    print("AGGRESSIVE RESTRUCTURE SUMMARY")
    print("=" * 70)
    print()
    print(f"  Total items processed:           {total:,}")
    print(f"  Items with restructured names:   {total_restructured:,} "
          f"({100 * total_restructured / total:.1f}%)")
    print(f"    Dataset restructures:          {len(ds_results):,} "
          f"({100 * len(ds_results) / len(datasets):.1f}% of datasets)")
    print(f"    Dataflow restructures:         {len(df_results):,} "
          f"({100 * len(df_results) / len(dataflows):.1f}% of dataflows)")
    print()
    if ds_dup_count or df_dup_count:
        print(f"  Skipped (would create duplicates):")
        print(f"    Datasets:                      {ds_dup_count}")
        print(f"    Dataflows:                     {df_dup_count}")
        print()
    print("  Breakdown by domain:")
    for dom, count in domain_counter.most_common():
        print(f"    {dom:<35s} {count:>5,}")
    print()

    # Show some examples
    print("  EXAMPLES (first 15 dataset restructures):")
    print(f"  {'Current Name':<50s} → {'Restructured Name':<50s}")
    print(f"  {'-'*50}   {'-'*50}")
    for r in ds_results[:15]:
        cur = r["current_name"][:48]
        new = r["restructured_name"][:48]
        print(f"  {cur:<50s} → {new:<50s}")
    print()

    print(f"  EXAMPLES (first 10 dataflow restructures):")
    print(f"  {'Current Name':<50s} → {'Restructured Name':<50s}")
    print(f"  {'-'*50}   {'-'*50}")
    for r in df_results[:10]:
        cur = r["current_name"][:48]
        new = r["restructured_name"][:48]
        print(f"  {cur:<50s} → {new:<50s}")

    print()
    print(f"  Output files:")
    print(f"    {ds_csv}")
    print(f"    {df_csv}")


if __name__ == "__main__":
    main()
