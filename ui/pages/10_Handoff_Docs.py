"""Handoff docs — inline viewer for the markdown deliverables."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import OUTPUT  # noqa: E402

st.title("Handoff documents")
st.caption("The markdown deliverables that ship with this toolkit, rendered inline.")

DOCS = {
    "Executive summary (Bill)": OUTPUT / "executive_summary.md",
    "Decision brief (Bill)": OUTPUT / "decision_brief.md",
    "Executive summary email": OUTPUT / "executive_summary_email.md",
    "Operator runbook (Garrett/Sriram)": OUTPUT / "operator_runbook.md",
    "Consolidation playbook": OUTPUT / "consolidation_playbook.md",
    "Cleanup email template": OUTPUT / "cleanup_email_template.md",
}

available = {label: p for label, p in DOCS.items() if p.exists()}
missing = [label for label, p in DOCS.items() if not p.exists()]

if not available:
    st.warning("None of the expected handoff docs were found under `output/`.")
    st.stop()

pick = st.selectbox("Document", list(available.keys()))
path = available[pick]
st.caption(f"`{path.relative_to(path.parents[1])}`")
st.markdown(path.read_text())

if missing:
    with st.expander("Missing docs"):
        for m in missing:
            st.text(f"  - {m}  →  {DOCS[m]}")
