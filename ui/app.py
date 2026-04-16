"""GSTV Domo Governance — Streamlit UI.

Run from the project root:

    streamlit run ui/app.py

The UI is a thin layer on top of the existing Python toolkit. It reads the
same `.cache/latest.json` and the CSVs/XLSXs under output/. Use the sidebar
to navigate between pages.
"""
from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from data import (
    CACHE_FILE,
    cache_mtime,
    dataflows_df,
    datasets_df,
    rollout_manifest,
    schemas_df,
)

# Load .env so DOMO_* credentials are visible to subprocess / UI alike.
load_dotenv(dotenv_path=CACHE_FILE.parent.parent / ".env")

st.set_page_config(
    page_title="GSTV Domo Governance",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("GSTV Domo Governance Toolkit")
st.caption(
    "Inventory, cleanup, and AI-readiness dashboard for the GSTV Domo instance. "
    "All pages read from the cache produced by `python3 main.py`."
)

# --------------------------------------------------------------------------
# Domo auth status (sidebar badge)
# --------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Domo auth")
    token = (os.environ.get("DOMO_ACCESS_TOKEN") or "").strip()
    instance = (os.environ.get("DOMO_INSTANCE") or "gstv").strip()
    cid = (os.environ.get("DOMO_CLIENT_ID") or "").strip()
    if token:
        masked = f"{token[:6]}…{token[-4:]}" if len(token) > 12 else "•" * len(token)
        st.success(f"Developer token: `{masked}`")
        st.caption(f"Instance: `{instance}.domo.com`")
    elif cid:
        st.info(f"OAuth2 client: `{cid[:8]}…`")
        st.caption("api.domo.com")
    else:
        st.error("No credentials in `.env`.")
    if st.button("Test token", use_container_width=True):
        import subprocess
        from data import ROOT
        r = subprocess.run(
            ["python3", "test_token.py"], cwd=ROOT, capture_output=True, text=True
        )
        if r.returncode == 0:
            st.success(r.stdout)
        else:
            st.error(r.stdout + r.stderr)

# --------------------------------------------------------------------------
# Cache status banner
# --------------------------------------------------------------------------
col_a, col_b = st.columns([3, 1])
with col_a:
    if not CACHE_FILE.exists():
        st.error(
            "No Domo cache found at `.cache/latest.json`. "
            "Run `python3 main.py` to extract the inventory from Domo, "
            "or `python3 main.py --rebuild` if you already have a cache."
        )
    else:
        st.success(f"Cache last refreshed: **{cache_mtime()}**")
with col_b:
    if st.button("Reload data", help="Clears @st.cache_data and re-reads files"):
        st.cache_data.clear()
        st.rerun()

# --------------------------------------------------------------------------
# Top-line KPIs
# --------------------------------------------------------------------------
ds = datasets_df()
df = dataflows_df()
sc = schemas_df()
mf = rollout_manifest()

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Datasets", f"{len(ds):,}" if not ds.empty else "—")
k2.metric("Dataflows", f"{len(df):,}" if not df.empty else "—")
k3.metric("Columns", f"{len(sc):,}" if not sc.empty else "—")
k4.metric(
    "Owners with cleanup work",
    f"{mf.shape[0]:,}" if not mf.empty else "—",
)
flagged = int(mf["Total Items for Review"].sum()) if "Total Items for Review" in mf.columns else 0
k5.metric("Items flagged for review", f"{flagged:,}")

st.divider()

# --------------------------------------------------------------------------
# Navigation hints
# --------------------------------------------------------------------------
st.subheader("What's in here")
cols = st.columns(3)
with cols[0]:
    st.markdown(
        "**Inventory**\n\n"
        "- Overview — staleness, domains, top-level metrics\n"
        "- Datasets — searchable table with filters\n"
        "- Dataflows — the 904 dataflows (read-only in Domo API)\n"
        "- Columns — 52,971 columns with definitions"
    )
with cols[1]:
    st.markdown(
        "**Governance**\n\n"
        "- Owners — per-owner rollout spreadsheets\n"
        "- Dashboard Impact — 317 cards at risk\n"
        "- Consolidation — 226 duplicate groups\n"
        "- Glossary — 197 GSTV business terms"
    )
with cols[2]:
    st.markdown(
        "**Automation**\n\n"
        "- Run `apply_renames.py`, `apply_descriptions.py`, "
        "`apply_removals.py`, `upload_glossary.py`, and "
        "`transfer_ownership.py` with dry-run preview and logs."
    )

st.divider()

# --------------------------------------------------------------------------
# Rollout manifest snapshot (lives on the home page because it's the headline
# operational artifact right now)
# --------------------------------------------------------------------------
if not mf.empty:
    st.subheader("Cleanup rollout — at a glance")
    st.dataframe(
        mf.drop(columns=[c for c in ("Spreadsheet", "Escalation") if c in mf.columns]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info(
        "`output/rollout_manifest.csv` not found. "
        "Run `python3 generate_owner_rollouts.py` to produce it."
    )
