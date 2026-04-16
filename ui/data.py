"""Cached data loaders for the Streamlit UI.

All loaders are decorated with @st.cache_data so the heavy files
(column_definitions.csv, schema_similarity_analysis.csv, cache JSON)
are only read once per session. Mutating scripts should call
`clear_caches()` after writing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Project root is one level up from ui/
ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / ".cache" / "latest.json"
OUTPUT = ROOT / "output"

# Make project modules importable so we can reuse analytics.py etc.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Cache-level loaders
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading Domo cache…")
def load_cache() -> dict | None:
    """Load .cache/latest.json. Returns None if it does not exist yet."""
    if not CACHE_FILE.exists():
        return None
    with CACHE_FILE.open("r") as f:
        return json.load(f)


@st.cache_data
def cache_mtime() -> str | None:
    if not CACHE_FILE.exists():
        return None
    return datetime.fromtimestamp(CACHE_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


@st.cache_data
def datasets_df() -> pd.DataFrame:
    cache = load_cache()
    if not cache:
        return pd.DataFrame()
    df = pd.DataFrame(cache.get("datasets", []))
    # Timestamps come from extractors.extract_datasets as created_at /
    # updated_at / data_current_at — make them pandas-native for sort & filter.
    for col in ("created_at", "updated_at", "data_current_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


@st.cache_data
def dataflows_df() -> pd.DataFrame:
    cache = load_cache()
    if not cache:
        return pd.DataFrame()
    df = pd.DataFrame(cache.get("dataflows", []))
    for col in ("last_execution_date", "last_updated_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


@st.cache_data
def schemas_df() -> pd.DataFrame:
    cache = load_cache()
    if not cache:
        return pd.DataFrame()
    return pd.DataFrame(cache.get("schemas", []))


@st.cache_data
def lineage_df() -> pd.DataFrame:
    cache = load_cache()
    if not cache:
        return pd.DataFrame()
    return pd.DataFrame(cache.get("lineage", []))


# ---------------------------------------------------------------------------
# CSV loaders (rename CSVs, definitions, governance outputs)
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as exc:  # corrupt or empty file
        st.warning(f"Could not read {path.name}: {exc}")
        return pd.DataFrame()


@st.cache_data
def column_definitions() -> pd.DataFrame:
    return _read_csv(ROOT / "column_definitions.csv")


@st.cache_data
def glossary() -> pd.DataFrame:
    return _read_csv(ROOT / "gstv_glossary.csv")


@st.cache_data
def dataset_renames() -> pd.DataFrame:
    return _read_csv(ROOT / "dataset_renames.csv")


@st.cache_data
def dataflow_renames() -> pd.DataFrame:
    return _read_csv(ROOT / "dataflow_renames.csv")


@st.cache_data
def dataset_aggressive_renames() -> pd.DataFrame:
    return _read_csv(ROOT / "dataset_aggressive_renames.csv")


@st.cache_data
def dataset_descriptions() -> pd.DataFrame:
    return _read_csv(ROOT / "dataset_descriptions.csv")


@st.cache_data
def dashboard_impact() -> pd.DataFrame:
    return _read_csv(OUTPUT / "dashboard_impact_report.csv")


@st.cache_data
def certification_status() -> pd.DataFrame:
    return _read_csv(OUTPUT / "certification_status.csv")


@st.cache_data
def dataset_tags() -> pd.DataFrame:
    return _read_csv(OUTPUT / "dataset_tags.csv")


@st.cache_data
def pages_inventory() -> pd.DataFrame:
    return _read_csv(OUTPUT / "pages_inventory.csv")


@st.cache_data
def cards_inventory() -> pd.DataFrame:
    return _read_csv(OUTPUT / "cards_inventory.csv")


@st.cache_data
def schema_similarity() -> pd.DataFrame:
    return _read_csv(OUTPUT / "schema_similarity_analysis.csv")


@st.cache_data
def rollout_manifest() -> pd.DataFrame:
    return _read_csv(OUTPUT / "rollout_manifest.csv")


# ---------------------------------------------------------------------------
# Derived analytics (reuse analytics.py where possible)
# ---------------------------------------------------------------------------

@st.cache_data
def staleness_distribution() -> pd.DataFrame:
    """Staleness tiers for every dataset using analytics._get_staleness."""
    from analytics import _get_staleness, _parse_timestamp

    df = datasets_df()
    if df.empty:
        return pd.DataFrame(columns=["staleness", "count"])

    now = datetime.utcnow()
    tiers = []
    for _, row in df.iterrows():
        ts_val = row.get("data_current_at") or row.get("updated_at")
        if ts_val is None or (isinstance(ts_val, float) and pd.isna(ts_val)):
            tiers.append(_get_staleness(None))
            continue
        # pd.Timestamp is already parsed; str fallthrough for raw cache reads
        if hasattr(ts_val, "to_pydatetime"):
            ts = ts_val.to_pydatetime()
        else:
            ts = _parse_timestamp(str(ts_val))
        days = (now - ts.replace(tzinfo=None)).days if ts else None
        tiers.append(_get_staleness(days))
    out = pd.Series(tiers, name="staleness").value_counts().rename_axis("staleness").reset_index(name="count")
    return out


@st.cache_data
def domain_distribution() -> pd.DataFrame:
    """Dataset count per domain using analytics._classify_domain."""
    from analytics import _classify_domain

    df = datasets_df()
    if df.empty:
        return pd.DataFrame(columns=["domain", "count"])
    name_col = "dataset_name" if "dataset_name" in df.columns else "name"
    domains = [_classify_domain(str(n))[0] for n in df[name_col]]
    return (
        pd.Series(domains, name="domain")
        .value_counts()
        .rename_axis("domain")
        .reset_index(name="count")
    )


def clear_caches() -> None:
    """Clear every @st.cache_data — call after writing a file on disk."""
    st.cache_data.clear()
