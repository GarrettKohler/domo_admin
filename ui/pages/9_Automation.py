"""Automation — run the apply_*.py scripts with dry-run by default.

Every command defaults to `--dry-run`. To actually push changes to Domo
the user must tick the 'Execute for real' checkbox, which adds `--execute`.
Stdout is streamed into the UI and logs are saved to output/automation_logs/.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import ROOT  # noqa: E402

st.title("Automation runner")
st.caption(
    "Thin wrapper around the existing CLI scripts. All commands default to "
    "`--dry-run` — nothing touches Domo unless you explicitly check *Execute for real*."
)

AUTO_LOGS = ROOT / "output" / "automation_logs"
AUTO_LOGS.mkdir(parents=True, exist_ok=True)

SCRIPTS = {
    "Refresh cache (main.py --rebuild)": {
        "cmd": ["python3", "main.py", "--rebuild"],
        "supports_execute": False,
        "blurb": "Rebuilds the workbook from `.cache/latest.json` — no API calls.",
    },
    "Full extraction (main.py)": {
        "cmd": ["python3", "main.py"],
        "supports_execute": False,
        "blurb": "Pulls a fresh inventory from Domo. Takes several minutes.",
    },
    "Apply renames": {
        "cmd": ["python3", "apply_renames.py"],
        "supports_execute": True,
        "blurb": "Pushes approved renames via PUT /v1/datasets/{id}.",
    },
    "Apply descriptions": {
        "cmd": ["python3", "apply_descriptions.py"],
        "supports_execute": True,
        "blurb": "Pushes generated descriptions to datasets missing them.",
    },
    "Apply removals": {
        "cmd": ["python3", "apply_removals.py"],
        "supports_execute": True,
        "blurb": "Deletes items marked Remove. Requires typing DELETE in the terminal.",
    },
    "Upload glossary": {
        "cmd": ["python3", "upload_glossary.py"],
        "supports_execute": True,
        "blurb": "Creates 'Reference - GSTV Business Glossary' and uploads 197 terms.",
    },
    "Transfer ownership": {
        "cmd": ["python3", "transfer_ownership.py"],
        "supports_execute": True,
        "blurb": "Reassigns former-employee datasets to a target owner.",
    },
    "Generate owner rollouts": {
        "cmd": ["python3", "generate_owner_rollouts.py"],
        "supports_execute": False,
        "blurb": "Rebuilds the 20 per-owner cleanup spreadsheets.",
    },
    "Generate cleanup emails": {
        "cmd": ["python3", "generate_cleanup_emails.py"],
        "supports_execute": False,
        "blurb": "Rebuilds the .eml mail-merge files.",
    },
}

choice = st.selectbox("Script", list(SCRIPTS.keys()))
meta = SCRIPTS[choice]
st.info(meta["blurb"])

extra = st.text_input("Extra args (space-separated)", "")

execute = False
if meta["supports_execute"]:
    execute = st.checkbox(
        "Execute for real (adds --execute). Leave unchecked for dry-run.",
        value=False,
    )
    if execute:
        st.warning(
            ":warning: You're about to push changes to Domo. Make sure you've reviewed "
            "the dry-run output first."
        )

cmd = list(meta["cmd"])
if execute:
    cmd.append("--execute")
else:
    if meta["supports_execute"] and "--dry-run" not in cmd:
        cmd.append("--dry-run")
if extra.strip():
    cmd.extend(shlex.split(extra))

st.code(" ".join(shlex.quote(c) for c in cmd), language="bash")

if st.button("Run", type="primary"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = choice.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("--", "")
    log_path = AUTO_LOGS / f"ui_{safe}_{ts}.log"

    with st.spinner(f"Running: {' '.join(cmd)}"):
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    log_path.write_text(
        f"$ {' '.join(cmd)}\n"
        f"exit={proc.returncode}\n\n"
        f"--- STDOUT ---\n{proc.stdout}\n"
        f"--- STDERR ---\n{proc.stderr}\n"
    )
    st.success(f"Finished (exit {proc.returncode}) — log saved to `{log_path.relative_to(ROOT)}`")

    if proc.stdout:
        st.subheader("stdout")
        st.code(proc.stdout[-20000:] or "(empty)")
    if proc.stderr:
        st.subheader("stderr")
        st.code(proc.stderr[-20000:] or "(empty)")

    # Refresh caches so the next page view picks up any new files
    st.cache_data.clear()
