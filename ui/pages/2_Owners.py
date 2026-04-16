"""Owners — drill into per-owner rollout spreadsheets."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import OUTPUT, rollout_manifest  # noqa: E402

st.title("Owner rollout")

mf = rollout_manifest()
if mf.empty:
    st.warning("`output/rollout_manifest.csv` is missing. Run `python3 generate_owner_rollouts.py`.")
    st.stop()

st.caption(
    f"{len(mf)} owners · "
    f"{int(mf['Total Items for Review'].sum()):,} items flagged · "
    f"Deadline {mf['Deadline'].iloc[0] if 'Deadline' in mf.columns else 'TBD'}"
)

st.dataframe(mf, use_container_width=True, hide_index=True)

st.divider()

# -- Per-owner drill-in -----------------------------------------------------
st.subheader("Open an owner spreadsheet")

owner = st.selectbox("Owner", mf["Owner"].tolist())
row = mf[mf["Owner"] == owner].iloc[0]

# Resolve the actual spreadsheet on disk (the manifest uses sanitised names)
rollout_dir = OUTPUT / "owner_rollouts"
safe = owner.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "")
candidates = list(rollout_dir.glob(f"cleanup_review_{safe}*.xlsx"))

cols = st.columns(3)
cols[0].metric("Datasets flagged", int(row.get("Datasets Flagged", 0)))
cols[1].metric("Dataflows flagged", int(row.get("Dataflows Flagged", 0)))
cols[2].metric("Total", int(row.get("Total Items for Review", 0)))

if not candidates:
    st.warning(f"No cleanup_review_{safe}*.xlsx found in `output/owner_rollouts/`.")
else:
    xlsx = candidates[0]
    st.success(f"Found spreadsheet: `{xlsx.name}`")
    with xlsx.open("rb") as f:
        st.download_button(
            "Download spreadsheet",
            data=f.read(),
            file_name=xlsx.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # Try to preview the "Datasets" sheet inline
    try:
        sheets = pd.read_excel(xlsx, sheet_name=None, engine="openpyxl")
        tab_names = list(sheets.keys())
        picked = st.selectbox("Preview sheet", tab_names, index=0)
        st.dataframe(sheets[picked], use_container_width=True, hide_index=True)
    except Exception as exc:
        st.info(f"Could not preview Excel inline: {exc}")
