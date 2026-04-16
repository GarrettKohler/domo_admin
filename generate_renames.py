#!/usr/bin/env python3
"""Generate rename suggestions for Domo datasets and dataflows.

Applies the GSTV naming convention to all items in the cache and produces
two CSV files (dataset_renames.csv, dataflow_renames.csv) containing only
rows where the proposed name differs from the current name.

Convention: [Environment] - [Domain/System] - [Description] - [Qualifier]
Separator:  ' - ' (space-dash-space)
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Import domain classifier from analytics module
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analytics import _classify_domain  # noqa: E402

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "latest.json"
OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# File extensions to strip (case-insensitive, anchored at end)
# ---------------------------------------------------------------------------
FILE_EXT_RE = re.compile(r"\.(csv|xlsx|xls|json|txt)\s*$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Bracketed environment prefix replacements  (order matters — longest first)
# ---------------------------------------------------------------------------
BRACKET_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    # Multi-word / special cases first
    (re.compile(r"^\s*\[Flag for Deletion\]\s*", re.IGNORECASE), "DEPRECATED - "),
    (re.compile(r"^\s*\[AM Test Copy\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[TEST\s*-\s*VEGAS\]\s*", re.IGNORECASE), "TEST - Vegas - "),
    (re.compile(r"^\s*\[Test Casey'?s\]\s*", re.IGNORECASE), "TEST - Casey's - "),
    (re.compile(r"^\s*\[Casey'?s Test\]\s*", re.IGNORECASE), "TEST - Casey's - "),
    (re.compile(r"^\s*\[Reetu Copy for Test\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[GK TEST\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[Do Not Use\]\s*", re.IGNORECASE), "DEPRECATED - "),
    (re.compile(r"^\s*\[V-RAP-AND-DE\]\s*", re.IGNORECASE), "DEV - "),
    (re.compile(r"^\s*\[Troubleshooting\]\s*", re.IGNORECASE), "DEV - "),
    (re.compile(r"^\s*\[Development\]\s*", re.IGNORECASE), "DEV - "),
    (re.compile(r"^\s*\[Deactivated\]\s*", re.IGNORECASE), "DEPRECATED - "),
    (re.compile(r"^\s*\[Testing\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[Production\]\s*", re.IGNORECASE), "PROD - "),
    (re.compile(r"^\s*\[DELETE\]\s*", re.IGNORECASE), "DEPRECATED - "),
    (re.compile(r"^\s*\[DNU\]\s*", re.IGNORECASE), "DEPRECATED - "),
    (re.compile(r"^\s*\[PROD\]\s*", re.IGNORECASE), "PROD - "),
    (re.compile(r"^\s*\[TEMP\]\s*", re.IGNORECASE), "DEV - "),
    (re.compile(r"^\s*\[Temp\]\s*", re.IGNORECASE), "DEV - "),
    (re.compile(r"^\s*\[TEST\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[Test\]\s*", re.IGNORECASE), "TEST - "),
    (re.compile(r"^\s*\[DEV\]\s*", re.IGNORECASE), "DEV - "),
    # Catch-all for remaining [VEGAS] tags
    (re.compile(r"^\s*\[VEGAS\]\s*", re.IGNORECASE), "TEST - Vegas - "),
    # Pluto is a system name, not an env — keep as-is but remove brackets
    (re.compile(r"^\s*\[Pluto\]\s*", re.IGNORECASE), "Pluto - "),
]

# Nested bracket combos like [TEST][VEGAS] or [TEMP] [TEST - VEGAS]
NESTED_BRACKET_RE = re.compile(
    r"^\s*\[(?:TEST|TEMP)\]\s*\[(?:VEGAS|TEST\s*-\s*VEGAS)\]\s*",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# View / Copy / Editable patterns
# ---------------------------------------------------------------------------
VIEW_OF_VIEW_RE = re.compile(r"^View of\s+View of\s+", re.IGNORECASE)
VIEW_OF_RE = re.compile(r"^View of\s+", re.IGNORECASE)
# "View of - " pattern (already has dash)
VIEW_OF_DASH_RE = re.compile(r"^View of\s+-\s+", re.IGNORECASE)
COPY_OF_RE = re.compile(r"^Copy of\s+", re.IGNORECASE)
EDITABLE_VIEW_RE = re.compile(
    r"^Editable DataSet for View of\s+(?:View of\s+)?", re.IGNORECASE
)
VW_PREFIX_RE = re.compile(r"^vw_", re.IGNORECASE)

# Possessive views like "DanJ's View of" or "Scott View of"
PERSON_VIEW_RE = re.compile(
    r"^(\w+(?:'s)?)\s+View of\s+", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Underscore heuristics — names that look like word separators vs technical IDs
# ---------------------------------------------------------------------------
# Patterns where underscores are part of technical identifiers — don't replace
TECHNICAL_UNDERSCORE_PATTERNS = [
    re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}"),  # UUID fragments
    re.compile(r"_[A-Z]{2,}_[A-Z]{2,}_[A-Z]{2,}"),  # SCHEMA_NAME_PATTERN
    re.compile(r"\b[A-Z]+_[A-Z]+\.[A-Z]+_[A-Z]+\.[A-Z]+"),  # DB.SCHEMA.TABLE
    re.compile(r"_[0-9a-f]{8,}"),  # hex suffixes
]

# ---------------------------------------------------------------------------
# Date patterns to normalize
# ---------------------------------------------------------------------------
# MMDDYY or MMDDYYYY
DATE_MMDDYY_RE = re.compile(
    r"\b(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d{2})\b"
)
DATE_MMDDYYYY_RE = re.compile(
    r"\b(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(20\d{2})\b"
)
# Month names in dates like "Jan4-Jan6" or standalone month+year
MONTH_NAMES = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}
# Pattern: 08_15_2024 style (from filenames)
DATE_UNDERSCORE_RE = re.compile(
    r"\b(0[1-9]|1[0-2])_(0[1-9]|[12]\d|3[01])_(20\d{2})\b"
)

# ---------------------------------------------------------------------------
# Standard term casing fixes
# ---------------------------------------------------------------------------
CASING_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bProof Of Play\b"), "Proof of Play"),
    (re.compile(r"\bproof of play\b", re.IGNORECASE), "Proof of Play"),
    (re.compile(r"\bSell Through\b"), "Sell Through"),
    (re.compile(r"\bsell through\b", re.IGNORECASE), "Sell Through"),
    (re.compile(r"\bRev Share\b", re.IGNORECASE), "Revenue Share"),
    (re.compile(r"\bData Set\b"), "Dataset"),
    (re.compile(r"\bDataSet\b"), "Dataset"),
    (re.compile(r"\bdata set\b", re.IGNORECASE), "Dataset"),
    (re.compile(r"\bLine Items?\b", re.IGNORECASE), lambda m: m.group(0).title()),
]

# Network name abbreviation expansions
NETWORK_ABBREVS: list[tuple[re.Pattern, str]] = [
    # GVR → Gilbarco — but only as a standalone word, not inside other words
    (re.compile(r"\bGVR\b"), "Gilbarco"),
]

# ---------------------------------------------------------------------------
# TEMP / DEV prefix normalization (non-bracketed)
# ---------------------------------------------------------------------------
TEMP_PREFIX_RE = re.compile(r"^\s*TEMP\s*-\s*", re.IGNORECASE)
DEV_PREFIX_PATTERNS = [
    re.compile(r"^DEV_", re.IGNORECASE),
]


def _is_technical_underscore_name(name: str) -> bool:
    """Return True if underscores in the name look like technical identifiers."""
    for pat in TECHNICAL_UNDERSCORE_PATTERNS:
        if pat.search(name):
            return True
    # Database-style paths: SCHEMA.TABLE_NAME
    if re.search(r"\.\w+_\w+", name):
        return True
    # Starts with known Domo system prefixes
    if re.match(r"^(DS_|V_|ddx_|APP_|FP\d_)", name):
        return True
    return False


def _convert_mmddyy_to_iso(m: re.Match) -> str:
    """Convert MMDDYY match to YYYY-MM-DD."""
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    year = int(yy)
    if year < 100:
        year = 2000 + year if year < 50 else 1900 + year
    return f"{year:04d}-{mm}-{dd}"


def _convert_mmddyyyy_to_iso(m: re.Match) -> str:
    """Convert MMDDYYYY match to YYYY-MM-DD."""
    mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def _convert_underscore_date_to_iso(m: re.Match) -> str:
    """Convert MM_DD_YYYY to YYYY-MM-DD."""
    mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
    return f"{yyyy}-{mm}-{dd}"


def _normalize_allcaps(name: str) -> str:
    """Convert ALL CAPS names (>5 chars) to Title Case, preserving acronyms.

    Only applies to names where the alphabetic characters are entirely uppercase.
    Preserves known acronyms: PROD, DEV, TEST, DEPRECATED, PATCH, POP, ICS,
    NVI, CVI, RPA, DXP, IO, PX, SSP, SQL, ETL, NOC, DMA, YTD, IOTV, etc.
    """
    # Check if the alpha portion is all uppercase
    alpha_chars = [c for c in name if c.isalpha()]
    if not alpha_chars or len(name) <= 5:
        return name
    if not all(c.isupper() for c in alpha_chars):
        return name

    # Don't title-case names that look like technical/system identifiers
    if _is_technical_underscore_name(name):
        return name

    ACRONYMS = {
        "PROD", "DEV", "TEST", "DEPRECATED", "PATCH", "COPY",
        "POP", "ICS", "NVI", "CVI", "RPA", "DXP", "IO", "PX",
        "SSP", "SQL", "ETL", "NOC", "DMA", "YTD", "IOTV", "API",
        "CSV", "FP4", "FP6", "PMAR", "GVR", "TEMP", "REV", "MOM",
        "CC", "DF", "S3", "V2", "V3", "QB", "SF",
    }

    words = name.split()
    result = []
    for word in words:
        # Strip punctuation for matching
        stripped = word.strip(" -:,.")
        if stripped.upper() in ACRONYMS:
            result.append(word)  # keep as-is
        else:
            result.append(word.title())
    return " ".join(result)


def apply_rename_rules(name: str) -> tuple[str, list[str]]:
    """Apply all rename rules to a name. Returns (new_name, list_of_changes)."""
    changes: list[str] = []
    original = name

    # --- a. Strip leading/trailing whitespace ---
    name = name.strip()
    if name != original.strip() or name != original:
        if original != original.strip():
            changes.append("strip_whitespace")

    # --- b. Remove file extensions (loop to handle double extensions like .csv.csv) ---
    while True:
        new = FILE_EXT_RE.sub("", name).rstrip()
        if new == name:
            break
        if "remove_extension" not in changes:
            changes.append("remove_extension")
        name = new

    # --- c. Replace bracketed environment prefixes ---
    # Handle nested brackets first: [TEST][VEGAS] or [TEMP] [TEST - VEGAS]
    new = NESTED_BRACKET_RE.sub("TEST - Vegas - ", name)
    if new != name:
        changes.append("env_prefix")
        name = new
    else:
        for pat, repl in BRACKET_REPLACEMENTS:
            new = pat.sub(repl, name)
            if new != name:
                changes.append("env_prefix")
                name = new
                break

    # Handle non-bracketed TEMP prefix → DEV
    if "env_prefix" not in changes:
        new = TEMP_PREFIX_RE.sub("DEV - ", name)
        if new != name:
            changes.append("env_prefix")
            name = new

    # Handle DEV_ prefix (like DEV_AssembleTransactions)
    if "env_prefix" not in changes:
        for pat in DEV_PREFIX_PATTERNS:
            new = pat.sub("DEV - ", name)
            if new != name:
                changes.append("env_prefix")
                name = new
                break

    # --- d. Replace "View of" → "View - " ---
    # First handle "Editable DataSet for View of" (rule f, but order matters)
    new = EDITABLE_VIEW_RE.sub("Editable View - ", name)
    if new != name:
        changes.append("editable_view")
        name = new
    else:
        # Handle person's "View of" like "DanJ's View of"
        m = PERSON_VIEW_RE.match(name)
        if m:
            person = m.group(1)
            rest = name[m.end():]
            name = f"View - {rest} ({person})"
            changes.append("view_prefix")
        else:
            # "View of - X" → "View - X"
            new = VIEW_OF_DASH_RE.sub("View - ", name)
            if new != name:
                changes.append("view_prefix")
                name = new
            else:
                # "View of View of X" → "View - X"
                new = VIEW_OF_VIEW_RE.sub("View - ", name)
                if new != name:
                    changes.append("view_prefix")
                    name = new
                else:
                    # "View of X" → "View - X"
                    new = VIEW_OF_RE.sub("View - ", name)
                    if new != name:
                        changes.append("view_prefix")
                        name = new

    # Also handle "View of" appearing mid-name (e.g., after env prefix: "DEV - View of Sites")
    MID_VIEW_OF_RE = re.compile(r"(\s-\s)View of\s+", re.IGNORECASE)
    new = MID_VIEW_OF_RE.sub(r"\1View - ", name)
    if new != name:
        if "view_prefix" not in changes:
            changes.append("view_prefix")
        name = new

    # --- e. Replace "Copy of " → "COPY - " (handle nested "Copy of Copy of") ---
    COPY_OF_COPY_RE = re.compile(r"^Copy of\s+Copy of\s+", re.IGNORECASE)
    new = COPY_OF_COPY_RE.sub("COPY - ", name)
    if new != name:
        changes.append("copy_prefix")
        name = new
    else:
        new = COPY_OF_RE.sub("COPY - ", name)
        if new != name:
            changes.append("copy_prefix")
            name = new

    # After Copy replacement, a bracketed prefix may now be at the start
    # e.g. "COPY - [Production] ..." → "COPY - PROD - ..."
    if "copy_prefix" in changes:
        for pat, repl in BRACKET_REPLACEMENTS:
            # Adjust pattern to match after "COPY - "
            inner = name
            if inner.startswith("COPY - "):
                rest = inner[7:]  # len("COPY - ") == 7
                for bpat, brepl in BRACKET_REPLACEMENTS:
                    new_rest = bpat.sub(brepl, rest)
                    if new_rest != rest:
                        name = "COPY - " + new_rest
                        if "env_prefix" not in changes:
                            changes.append("env_prefix")
                        break
            break  # only do this once

    # --- g. Replace vw_ prefix → "View - " ---
    new = VW_PREFIX_RE.sub("View - ", name)
    if new != name:
        changes.append("view_prefix")
        name = new

    # --- j. Replace abbreviated network names ---
    for pat, repl in NETWORK_ABBREVS:
        new = pat.sub(repl, name)
        if new != name:
            changes.append("network_name")
            name = new

    # --- k. Fix date formats ---
    new = DATE_UNDERSCORE_RE.sub(_convert_underscore_date_to_iso, name)
    if new != name:
        changes.append("date_format")
        name = new

    new = DATE_MMDDYYYY_RE.sub(_convert_mmddyyyy_to_iso, name)
    if new != name:
        changes.append("date_format")
        name = new

    new = DATE_MMDDYY_RE.sub(_convert_mmddyy_to_iso, name)
    if new != name:
        if "date_format" not in changes:
            changes.append("date_format")
        name = new

    # --- i. Replace underscores with spaces (word separators only) ---
    if "_" in name and not _is_technical_underscore_name(name):
        # Replace underscores that look like word separators
        new = re.sub(r"_", " ", name)
        if new != name:
            changes.append("underscore_to_space")
            name = new

    # --- h. Collapse double spaces ---
    new = re.sub(r"  +", " ", name)
    if new != name:
        changes.append("collapse_spaces")
        name = new

    # --- l. Normalize ALL CAPS to Title Case ---
    new = _normalize_allcaps(name)
    if new != name:
        changes.append("allcaps_to_titlecase")
        name = new

    # --- m. Fix inconsistent casing on standard terms ---
    for pat, repl in CASING_FIXES:
        if callable(repl):
            new = pat.sub(repl, name)
        else:
            new = pat.sub(repl, name)
        if new != name:
            if "casing_fix" not in changes:
                changes.append("casing_fix")
            name = new

    # --- Clean up separator issues ---
    # Fix "- -" that might result from transformations
    name = re.sub(r"\s*-\s*-\s*", " - ", name)

    # Fix leading "- " after environment prefix was already there
    name = re.sub(r"^(\w+)\s*-\s*-\s*", r"\1 - ", name)

    # Ensure consistent ' - ' separator (no extra spaces around dashes that
    # act as separators). Only fix dashes surrounded by spaces.
    name = re.sub(r"\s+-\s+", " - ", name)

    # Strip any trailing/leading whitespace from the final result
    name = name.strip()

    # Collapse double spaces one more time after all transformations
    name = re.sub(r"  +", " ", name)

    return name, changes


def check_convention_conformance(name: str) -> list[str]:
    """Check if a name conforms to the naming convention. Returns list of issues."""
    issues = []

    # Check for file extensions
    if FILE_EXT_RE.search(name):
        issues.append("has_file_extension")

    # Check for bracketed prefixes still present
    if re.match(r"^\[", name):
        issues.append("has_bracketed_prefix")

    # Check for "View of" instead of "View - "
    if re.search(r"View of\s", name, re.IGNORECASE):
        issues.append("has_view_of")

    # Check for underscores used as word separators
    if "_" in name and not _is_technical_underscore_name(name):
        issues.append("has_underscores")

    # Check for double spaces
    if "  " in name:
        issues.append("has_double_spaces")

    # Check for ALL CAPS (>5 alpha chars), but exclude technical identifiers
    alpha = [c for c in name if c.isalpha()]
    if len(alpha) > 5 and all(c.isupper() for c in alpha):
        if not _is_technical_underscore_name(name):
            issues.append("is_all_caps")

    return issues


def main() -> None:
    """Main entry point."""
    # --- Load cache ---
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache file not found at {CACHE_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(CACHE_PATH) as f:
        cache = json.load(f)

    datasets = cache.get("datasets", [])
    dataflows = cache.get("dataflows", [])

    print(f"Loaded {len(datasets)} datasets and {len(dataflows)} dataflows")
    print()

    # --- Build owner lookup from datasets (int-keyed) ---
    owner_lookup: dict[int, str] = {}
    for ds in datasets:
        oid = ds.get("owner_id")
        oname = ds.get("owner_name", "")
        if oid and oname:
            owner_lookup[int(oid)] = oname

    # --- Process datasets ---
    ds_renames: list[dict] = []
    ds_all_proposed: dict[str, str] = {}  # proposed_name → dataset_id (for dup check)
    ds_existing_names: set[str] = {ds["dataset_name"].strip() for ds in datasets}

    for ds in datasets:
        ds_id = ds["dataset_id"]
        current = ds["dataset_name"]
        owner = ds.get("owner_name", "")

        proposed, changes = apply_rename_rules(current)

        if not changes:
            continue

        # Don't propose if proposed == current (after strip)
        if proposed == current.strip():
            continue

        ds_renames.append({
            "dataset_id": ds_id,
            "current_name": current,
            "proposed_name": proposed,
            "change_type": ", ".join(changes),
            "owner_name": owner,
        })
        # Track proposed names for dup detection
        if proposed in ds_all_proposed:
            ds_all_proposed[proposed] = "DUPLICATE"
        else:
            ds_all_proposed[proposed] = ds_id

    # Remove renames that would create duplicates (same proposed name as another
    # proposed rename OR same as an existing name that isn't being renamed)
    dup_proposed = {name for name, val in ds_all_proposed.items() if val == "DUPLICATE"}
    # Also check against existing names that are NOT being renamed
    renamed_originals = {r["current_name"].strip() for r in ds_renames}
    existing_keeping = ds_existing_names - renamed_originals

    ds_renames_clean = []
    ds_dup_count = 0
    for r in ds_renames:
        proposed = r["proposed_name"]
        if proposed in dup_proposed or proposed in existing_keeping:
            ds_dup_count += 1
            continue
        ds_renames_clean.append(r)
    ds_renames = ds_renames_clean

    # --- Process dataflows ---
    df_renames: list[dict] = []
    df_all_proposed: dict[str, str] = {}
    df_existing_names: set[str] = {df["dataflow_name"].strip() for df in dataflows}

    for df in dataflows:
        df_id = str(df["dataflow_id"])
        current = df["dataflow_name"]
        owner_id_str = str(df.get("owner_id", ""))
        # Resolve owner name
        try:
            owner = owner_lookup.get(int(owner_id_str), "")
        except (ValueError, TypeError):
            owner = ""

        proposed, changes = apply_rename_rules(current)

        if not changes:
            continue

        if proposed == current.strip():
            continue

        df_renames.append({
            "dataflow_id": df_id,
            "current_name": current,
            "proposed_name": proposed,
            "change_type": ", ".join(changes),
            "owner_name": owner,
        })
        if proposed in df_all_proposed:
            df_all_proposed[proposed] = "DUPLICATE"
        else:
            df_all_proposed[proposed] = df_id

    # Remove dataflow dups
    dup_proposed_df = {name for name, val in df_all_proposed.items() if val == "DUPLICATE"}
    renamed_originals_df = {r["current_name"].strip() for r in df_renames}
    existing_keeping_df = df_existing_names - renamed_originals_df

    df_renames_clean = []
    df_dup_count = 0
    for r in df_renames:
        proposed = r["proposed_name"]
        if proposed in dup_proposed_df or proposed in existing_keeping_df:
            df_dup_count += 1
            continue
        df_renames_clean.append(r)
    df_renames = df_renames_clean

    # --- Domain suggestion pass ---
    # For items that still don't look well-structured, suggest domain prefix
    for rlist in [ds_renames, df_renames]:
        for r in rlist:
            proposed = r["proposed_name"]
            domain, dept = _classify_domain(proposed)
            if domain != "Other / Unclassified":
                r["suggested_domain"] = domain
                r["suggested_department"] = dept
            else:
                r["suggested_domain"] = ""
                r["suggested_department"] = ""

    # --- Check for items that still don't conform ---
    # Build a map from current_name to best proposed name (including dup-skipped)
    # For conformance checking, we want to see what the name WOULD be after rename
    ds_proposed_all: dict[str, str] = {}
    for ds in datasets:
        proposed, ch = apply_rename_rules(ds["dataset_name"])
        if ch and proposed != ds["dataset_name"].strip():
            ds_proposed_all[ds["dataset_id"]] = proposed

    df_proposed_all: dict[str, str] = {}
    for df in dataflows:
        proposed, ch = apply_rename_rules(df["dataflow_name"])
        if ch and proposed != df["dataflow_name"].strip():
            df_proposed_all[str(df["dataflow_id"])] = proposed

    nonconforming_ds = 0
    all_ds_issues: Counter = Counter()
    seen_ds_names: set[str] = set()
    for ds in datasets:
        ds_id = ds["dataset_id"]
        name = ds["dataset_name"].strip()
        check_name = ds_proposed_all.get(ds_id, name)
        # Deduplicate by check_name to avoid inflated counts
        if check_name in seen_ds_names:
            continue
        seen_ds_names.add(check_name)
        issues = check_convention_conformance(check_name)
        if issues:
            nonconforming_ds += 1
            for issue in issues:
                all_ds_issues[issue] += 1

    nonconforming_df = 0
    all_df_issues: Counter = Counter()
    seen_df_names: set[str] = set()
    for df in dataflows:
        df_id = str(df["dataflow_id"])
        name = df["dataflow_name"].strip()
        check_name = df_proposed_all.get(df_id, name)
        if check_name in seen_df_names:
            continue
        seen_df_names.add(check_name)
        issues = check_convention_conformance(check_name)
        if issues:
            nonconforming_df += 1
            for issue in issues:
                all_df_issues[issue] += 1

    # --- Write CSVs ---
    ds_csv_path = OUT_DIR / "dataset_renames.csv"
    with open(ds_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataset_id", "current_name", "proposed_name",
                         "change_type", "owner_name"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(ds_renames)

    df_csv_path = OUT_DIR / "dataflow_renames.csv"
    with open(df_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["dataflow_id", "current_name", "proposed_name",
                         "change_type", "owner_name"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(df_renames)

    # --- Summary ---
    total = len(datasets) + len(dataflows)
    total_renames = len(ds_renames) + len(df_renames)

    # Change type breakdown
    change_counter: Counter = Counter()
    for r in ds_renames + df_renames:
        for ct in r["change_type"].split(", "):
            change_counter[ct] += 1

    print("=" * 70)
    print("RENAME SUGGESTION SUMMARY")
    print("=" * 70)
    print()
    print(f"  Total items processed:         {total:,}")
    print(f"    Datasets:                    {len(datasets):,}")
    print(f"    Dataflows:                   {len(dataflows):,}")
    print()
    print(f"  Items with proposed renames:    {total_renames:,} "
          f"({100 * total_renames / total:.1f}%)")
    print(f"    Dataset renames:             {len(ds_renames):,} "
          f"({100 * len(ds_renames) / len(datasets):.1f}% of datasets)")
    print(f"    Dataflow renames:            {len(df_renames):,} "
          f"({100 * len(df_renames) / len(dataflows):.1f}% of dataflows)")
    print()
    if ds_dup_count or df_dup_count:
        print(f"  Skipped (would create duplicates):")
        print(f"    Datasets:                    {ds_dup_count}")
        print(f"    Dataflows:                   {df_dup_count}")
        print()

    print("  Breakdown by change type:")
    for ct, count in change_counter.most_common():
        print(f"    {ct:<30s} {count:>5,}")
    print()

    print("  Remaining non-conforming items (after renames):")
    print(f"    Datasets:                    {nonconforming_ds:,}")
    print(f"    Dataflows:                   {nonconforming_df:,}")
    if all_ds_issues or all_df_issues:
        combined = all_ds_issues + all_df_issues
        print("    Issue breakdown:")
        for issue, count in combined.most_common():
            print(f"      {issue:<30s} {count:>5,}")
    print()

    print(f"  Output files:")
    print(f"    {ds_csv_path}")
    print(f"    {df_csv_path}")
    print()


if __name__ == "__main__":
    main()
