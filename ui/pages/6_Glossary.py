"""GSTV business glossary — 197 terms staged for Domo upload."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import glossary  # noqa: E402

st.title("Business glossary")
st.caption(
    "Source of truth for the 'Reference - GSTV Business Glossary' dataset that "
    "`upload_glossary.py` pushes to Domo. Edit `gstv_glossary.csv` to update."
)

gl = glossary()
if gl.empty:
    st.warning("`gstv_glossary.csv` not found.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Terms", len(gl))
if "domain" in gl.columns:
    c2.metric("Domains", gl["domain"].nunique())
if "category" in gl.columns:
    c3.metric("Categories", gl["category"].nunique())

with st.sidebar:
    st.header("Filters")
    q = st.text_input("Term or definition contains", "")
    if "domain" in gl.columns:
        domains = ["(any)"] + sorted(gl["domain"].dropna().unique().tolist())
        dom = st.selectbox("Domain", domains)
    else:
        dom = "(any)"

view = gl
if q:
    mask = view.apply(
        lambda r: q.lower() in str(r.get("term", "")).lower()
        or q.lower() in str(r.get("definition", "")).lower(),
        axis=1,
    )
    view = view[mask]
if dom != "(any)":
    view = view[view["domain"] == dom]

st.dataframe(view, use_container_width=True, hide_index=True, height=640)
