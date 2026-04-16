"""Consolidation — schema-similarity pairs and 226 proposed merge groups."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import OUTPUT, schema_similarity  # noqa: E402

st.title("Consolidation candidates")
st.caption(
    "Pairs of datasets with overlapping schemas, from `schema_similarity.py`. "
    "Groups of 3+ are bundled in `output/domo_consolidation_report_20260412.xlsx`."
)

ss = schema_similarity()
if ss.empty:
    st.warning("`output/schema_similarity_analysis.csv` missing. Run `python3 schema_similarity.py`.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Similarity pairs", f"{len(ss):,}")
c2.metric("Domains covered", ss["domain"].nunique() if "domain" in ss.columns else 0)
if "overlap_pct" in ss.columns:
    c3.metric("Avg overlap", f"{ss['overlap_pct'].mean():.0%}")

with st.sidebar:
    st.header("Filters")
    min_overlap = st.slider("Min column overlap %", 0, 100, 50, 5)
    min_jaccard = st.slider("Min weighted Jaccard", 0.0, 1.0, 0.3, 0.05)
    if "domain" in ss.columns:
        domains = ["(any)"] + sorted(ss["domain"].dropna().unique().tolist())
        dom = st.selectbox("Domain", domains)
    else:
        dom = "(any)"
    if "recommendation" in ss.columns:
        recs = ["(any)"] + sorted(ss["recommendation"].dropna().unique().tolist())
        rec = st.selectbox("Recommendation", recs)
    else:
        rec = "(any)"

view = ss
if "overlap_pct" in view.columns:
    # overlap_pct stored as 0-1 fraction in schema_similarity.py output
    view = view[view["overlap_pct"] * 100 >= min_overlap]
if "weighted_jaccard" in view.columns:
    view = view[view["weighted_jaccard"] >= min_jaccard]
if dom != "(any)":
    view = view[view["domain"] == dom]
if rec != "(any)":
    view = view[view["recommendation"] == rec]

st.caption(f"{len(view):,} of {len(ss):,} pairs")
st.dataframe(view, use_container_width=True, hide_index=True, height=560)

# Link to the generated workbook if present
st.divider()
workbook = next(OUTPUT.glob("domo_consolidation_report_*.xlsx"), None)
if workbook:
    with workbook.open("rb") as f:
        st.download_button(
            f"Download {workbook.name}",
            data=f.read(),
            file_name=workbook.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
