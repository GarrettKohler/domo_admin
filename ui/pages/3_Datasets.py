"""Datasets — searchable, filterable table of every dataset in the cache."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import datasets_df  # noqa: E402

st.title("Datasets")

ds = datasets_df()
if ds.empty:
    st.warning("No datasets in cache. Run `python3 main.py` first.")
    st.stop()

# -- Filters ----------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    q = st.text_input("Name contains", "")
    owner_options = ["(any)"] + sorted(
        [o for o in ds.get("owner_name", pd.Series(dtype=str)).dropna().unique() if o]
    )
    owner = st.selectbox("Owner", owner_options)

    domain = st.selectbox("Domain (computed)", ["(any)", "(compute)"])
    show_cols = st.multiselect(
        "Columns to show",
        options=list(ds.columns),
        default=[
            c
            for c in (
                "dataset_name",
                "owner_name",
                "row_count",
                "column_count",
                "data_current_at",
                "updated_at",
            )
            if c in ds.columns
        ],
    )

view = ds
if q:
    name_col = "dataset_name" if "dataset_name" in view.columns else view.columns[0]
    view = view[view[name_col].astype(str).str.contains(q, case=False, na=False)]
if owner != "(any)":
    view = view[view["owner_name"] == owner]

# Optional: compute domain on the fly when requested
if domain == "(compute)":
    from analytics import _classify_domain

    name_col = "dataset_name" if "dataset_name" in view.columns else view.columns[0]
    view = view.assign(
        domain=[_classify_domain(str(n))[0] for n in view[name_col]],
        department=[_classify_domain(str(n))[1] for n in view[name_col]],
    )
    show_cols = ["domain", "department"] + [c for c in show_cols if c not in ("domain", "department")]

st.caption(f"{len(view):,} of {len(ds):,} datasets")
st.dataframe(
    view[show_cols] if show_cols else view,
    use_container_width=True,
    hide_index=True,
    height=640,
)

# -- Deep link to a single dataset -----------------------------------------
st.divider()
st.subheader("Dataset detail")

id_col = "dataset_id" if "dataset_id" in ds.columns else ds.columns[0]
pick = st.selectbox("Pick a dataset", view[id_col].tolist() if not view.empty else [])
if pick:
    detail = ds[ds[id_col] == pick].iloc[0].to_dict()
    st.json(detail, expanded=False)
    dom = f"https://gstv.domo.com/datasources/{pick}/details/overview"
    st.markdown(f"[Open in Domo]({dom})")
