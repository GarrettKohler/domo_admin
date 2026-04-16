"""Columns & definitions — explore the 81% coverage data dictionary."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import column_definitions  # noqa: E402

st.title("Column definitions")

defs = column_definitions()
if defs.empty:
    st.warning("`column_definitions.csv` not found.")
    st.stop()

total = len(defs)
defined = defs["definition"].notna().sum() if "definition" in defs.columns else 0
st.caption(f"{defined:,} / {total:,} columns defined ({defined/total*100:.1f}% coverage)")

with st.sidebar:
    st.header("Filters")
    q = st.text_input("Column name contains", "")
    only_undefined = st.checkbox("Only undefined rows")
    type_options = ["(any)"] + sorted(
        defs["column_type"].dropna().unique().tolist()
    ) if "column_type" in defs.columns else ["(any)"]
    ctype = st.selectbox("Type", type_options)

view = defs
if q:
    view = view[view["column_name"].astype(str).str.contains(q, case=False, na=False)]
if only_undefined and "definition" in view.columns:
    view = view[view["definition"].isna() | (view["definition"].astype(str).str.strip() == "")]
if ctype != "(any)" and "column_type" in view.columns:
    view = view[view["column_type"] == ctype]

st.caption(f"{len(view):,} of {total:,} rows")
st.dataframe(view, use_container_width=True, hide_index=True, height=640)

# Export filtered view
st.download_button(
    "Download filtered view as CSV",
    data=view.to_csv(index=False).encode(),
    file_name="column_definitions_filtered.csv",
    mime="text/csv",
)
