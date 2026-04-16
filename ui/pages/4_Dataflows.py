"""Dataflows — read-only view (Domo has no public write API for dataflows)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import dataflows_df, lineage_df  # noqa: E402

st.title("Dataflows")
st.caption(
    ":warning: Dataflow rename / delete / tag operations are not available via the "
    "Domo public API — they must be done manually in the Domo UI. This page is read-only."
)

dfl = dataflows_df()
if dfl.empty:
    st.warning("No dataflows in cache.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    q = st.text_input("Name contains", "")
    owner_options = ["(any)"] + sorted(
        [o for o in dfl.get("owner_name", pd.Series(dtype=str)).dropna().unique() if o]
    )
    owner = st.selectbox("Owner", owner_options)

view = dfl
if q:
    name_col = "dataflow_name" if "dataflow_name" in view.columns else view.columns[0]
    view = view[view[name_col].astype(str).str.contains(q, case=False, na=False)]
if owner != "(any)":
    view = view[view["owner_name"] == owner]

st.caption(f"{len(view):,} of {len(dfl):,} dataflows")
st.dataframe(view, use_container_width=True, hide_index=True, height=480)

st.divider()
st.subheader("Lineage")
lin = lineage_df()
if lin.empty:
    st.info("No lineage records in cache.")
else:
    st.dataframe(lin.head(1000), use_container_width=True, hide_index=True, height=360)
    st.caption(f"Showing first 1,000 of {len(lin):,} lineage records.")
