"""Dashboard impact — which cards/pages break if we remove flagged datasets?"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import dashboard_impact  # noqa: E402

st.title("Dashboard impact")
st.caption(
    "Cards and pages that reference a flagged dataset. Removing a dataset where "
    "`all_datasets_flagged` is True will break the card outright."
)

di = dashboard_impact()
if di.empty:
    st.warning(
        "`output/dashboard_impact_report.csv` missing. Run `python3 extract_governance.py`."
    )
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("At-risk cards", di["card_id"].nunique())
c2.metric("Flagged datasets referenced", di["flagged_dataset_id"].nunique())
if "pages" in di.columns:
    # pages is a pipe-delimited string — count unique page names conservatively
    pages = set()
    for p in di["pages"].dropna().astype(str):
        for part in p.split("|"):
            if part.strip():
                pages.add(part.strip())
    c3.metric("Pages involved", len(pages))

with st.sidebar:
    st.header("Filters")
    only_broken = st.checkbox("Only fully broken cards (all_datasets_flagged)", value=True)
    q = st.text_input("Card title contains", "")

view = di
if only_broken and "all_datasets_flagged" in view.columns:
    # CSV stores booleans as strings, so normalise
    view = view[view["all_datasets_flagged"].astype(str).str.lower().isin({"true", "1", "yes"})]
if q:
    view = view[view["card_title"].astype(str).str.contains(q, case=False, na=False)]

st.caption(f"{len(view):,} of {len(di):,} rows")
st.dataframe(view, use_container_width=True, hide_index=True, height=640)
