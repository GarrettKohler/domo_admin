"""Overview — staleness and domain distribution."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import datasets_df, domain_distribution, staleness_distribution  # noqa: E402

st.title("Overview")

ds = datasets_df()
if ds.empty:
    st.warning("No datasets in cache. Run `python3 main.py` first.")
    st.stop()

left, right = st.columns(2)

with left:
    st.subheader("Staleness distribution")
    st.caption(
        "Tiers come from `analytics._get_staleness()` — Active / Aging / Stale / "
        "Dormant / Abandoned based on days since last touch."
    )
    stale = staleness_distribution()
    if stale.empty:
        st.info("Staleness could not be computed — timestamps missing.")
    else:
        st.bar_chart(stale.set_index("staleness"), horizontal=False)
        st.dataframe(stale, use_container_width=True, hide_index=True)

with right:
    st.subheader("Domain distribution")
    st.caption(
        "Domains come from `analytics._classify_domain()` — ordered regex rules, "
        "first match wins. Edit `DOMAIN_RULES` in `analytics.py` to refine."
    )
    dom = domain_distribution()
    if dom.empty:
        st.info("Domain could not be computed.")
    else:
        st.bar_chart(dom.set_index("domain"), horizontal=False)
        st.dataframe(dom, use_container_width=True, hide_index=True)

st.divider()

# -- Owner distribution -----------------------------------------------------
st.subheader("Dataset ownership")
if "owner_name" in ds.columns:
    owners = (
        ds["owner_name"]
        .fillna("(unassigned)")
        .replace("", "(unassigned)")
        .value_counts()
        .rename_axis("owner")
        .reset_index(name="datasets")
    )
    st.dataframe(owners, use_container_width=True, hide_index=True, height=420)
else:
    st.info("No `owner_name` column in cache.")
