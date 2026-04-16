# GSTV Domo Governance — UI

A Streamlit dashboard over the existing Python toolkit. It does **no new work**
— every page reads either `.cache/latest.json` or one of the CSV/XLSX outputs
the CLI scripts already produce.

## Run it

```bash
# from the project root
./run_ui.sh                # auto-installs streamlit + pandas if needed
# or manually
pip install -r requirements.txt
python3 -m streamlit run ui/app.py
```

Streamlit opens at `http://localhost:8501`.

## Pages

| # | Page | Data source |
|---|------|-------------|
| — | Home | `.cache/latest.json`, `output/rollout_manifest.csv` |
| 1 | Overview | `analytics._classify_domain` + `_get_staleness` on the cache |
| 2 | Owners | `output/rollout_manifest.csv` + `output/owner_rollouts/*.xlsx` |
| 3 | Datasets | `cache.datasets` — searchable, filterable |
| 4 | Dataflows | `cache.dataflows` (read-only — no Domo API for writes) |
| 5 | Columns | `column_definitions.csv` (6,978 / 8,610 defined) |
| 6 | Glossary | `gstv_glossary.csv` (197 GSTV business terms) |
| 7 | Dashboard Impact | `output/dashboard_impact_report.csv` (317 at-risk cards) |
| 8 | Consolidation | `output/schema_similarity_analysis.csv` (5,059 pairs) |
| 9 | Automation | subprocess wrapper over `apply_*.py`, `main.py`, etc. |
| 10 | Handoff Docs | inline viewer for `output/*.md` |

## Layout

```
ui/
  app.py            # home page + KPIs + rollout snapshot
  data.py           # cached loaders for cache/CSVs + domain/staleness analytics
  pages/            # Streamlit multi-page routing — filenames define the order
    1_Overview.py
    2_Owners.py
    …
```

## Safety — automation page

The Automation page (page 9) is a thin wrapper around `subprocess.run`. Every
apply_*.py script is invoked with `--dry-run` unless the **Execute for real**
checkbox is ticked. Execute appends `--execute` to the command. Logs land in
`output/automation_logs/ui_<script>_<timestamp>.log`.

The underlying scripts already have their own safeguards (e.g. `apply_removals.py`
prompts for the word `DELETE` in the terminal) and those still apply — the UI
just triggers the CLI.

## When to reload

The UI caches everything with `@st.cache_data`, so if you edit a CSV or rerun
`main.py` outside the app, hit the **Reload data** button in the top-right of
the home page (it calls `st.cache_data.clear()`).
