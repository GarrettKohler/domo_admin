# GSTV Domo Governance Toolkit — Project Context

## What This Is

An automated extraction, analysis, and cleanup toolkit for GSTV's Domo BI
environment. The goal is to clean up ~2,300 datasets and ~900 dataflows so
GSTV can enable Domo's AI-powered analytics features (natural language querying,
anomaly detection, AI-generated insights).

## Project Owner

Aaron Olson (Data team). Stakeholders: Bill Binkiewicz, Sriram Vepuri,
Garrett Kohler, Michael Girard.

## Key Architecture Decisions

- **Cache-first**: All scripts read from `.cache/latest.json` (~12 MB), never
  hit the Domo API unless explicitly extracting. Run `main.py` to refresh cache.
- **Domain classification**: `analytics.py` → `_classify_domain()` uses ordered
  `DOMAIN_RULES` (regex patterns, first match wins). This is the single source
  of truth for domain assignment everywhere.
- **Two rename modes**: Conservative (mechanical fixes via `generate_renames.py`)
  and aggressive (full restructuring via `generate_aggressive_renames.py`). Both
  appear as columns in owner cleanup spreadsheets.
- **Dry-run by default**: All automation scripts (`apply_*.py`, `upload_glossary.py`,
  `transfer_ownership.py`) default to `--dry-run`. Must pass `--execute` to
  make changes.
- **No dataflow write API**: Domo has no public API for dataflow rename/delete/tags.
  Scripts automatically skip dataflow operations and log warnings.

## File Layout

```
.cache/latest.json          Cached Domo inventory (~12 MB) — DO NOT commit
.env                        API credentials — DO NOT commit
output/                     All generated deliverables — gitignored
  owner_rollouts/           20 per-owner cleanup spreadsheets
  cleanup_emails/           Generated .eml files for mail merge
  automation_logs/          Timestamped logs from automation scripts
  executive_summary.md      Stakeholder overview (for Bill)
  decision_brief.md         6 decisions for Bill with recommendations
  operator_runbook.md       Day-by-day playbook for Garrett & Sriram
  consolidation_playbook.md Phase 3 duplicate merging guide
  cleanup_email_template.md Email template with placeholders
column_definitions.csv      Master data dictionary (6,978 definitions, 81% coverage)
gstv_glossary.csv           197 GSTV business terms for Domo upload
```

## Running Things

```bash
# Use python3 — `python` is not aliased on this machine
python3 main.py --rebuild              # Rebuild workbook from cache
python3 generate_owner_rollouts.py     # Regenerate cleanup spreadsheets
python3 generate_cleanup_emails.py     # Generate .eml files for all owners
python3 apply_renames.py --dry-run     # Preview renames
```

## Important Patterns

- **`python3` not `python`**: The `python` command is not found on this machine.
  Always use `python3`.
- **Imports from project root**: Scripts use `sys.path.insert(0, ...)` to import
  from sibling modules. Always run from the project root directory.
- **openpyxl for Excel**: All workbook generation uses openpyxl. Data validation
  dropdowns, conditional formatting, hyperlinks to Domo are used extensively in
  the owner rollout spreadsheets.
- **CSV column definitions**: `column_definitions.csv` is the master file for
  the data dictionary. Multiple scripts read and write it. The definition pipeline
  runs sequentially (infer v1 → v2 → v3 → glossary → cleanup v1-v4).
- **Error seen before**: `_extract_env()` in `generate_aggressive_renames.py`
  returns `(env_label, body)`. When unpacking, `env_label` can be `None` for
  unclassified items — always handle the None case.
- **Former employee detection**: In the cache, dataflow `owner_name` fields are
  empty strings. Former employees are identified by `owner_id` not matching any
  dataset owner. The 11 known former-employee IDs are hardcoded in
  `transfer_ownership.py` → `FORMER_EMPLOYEE_IDS`.
- **Handoff docs**: Decision brief (for Bill), operator runbook (for Garrett/
  Sriram), and consolidation playbook are in `output/`. Keep them updated if
  the plan changes.

## Domo API

- **Instance**: `gstv.domo.com`
- **Auth**: OAuth2 client_credentials flow, credentials in `.env`
- **Rate limit**: 0.6s delay between calls, exponential backoff on 429
- **Read endpoints**: GET datasets, schemas, dataflows, lineage, CSV export
- **Write endpoints**: PUT (rename, describe, owner), DELETE, POST (create),
  PUT data (upload CSV)
- **No write API for**: dataflows, tags, cards/pages, AI configuration

## Governance Numbers

- 2,295 datasets, 904 dataflows, 52,971 columns
- 1,245 active (54%), 614 abandoned (27%), 166 dormant, 64 stale
- 956 datasets + 582 dataflows flagged for review across 20 owners
- 226 consolidation groups, potential reduction of 859 datasets
- 6,978/8,610 column definitions (81.0%), 1,632 remaining
- 317 dashboard cards at risk across 25 pages
- 525 conservative renames, 1,983 aggressive restructures
- 197 glossary terms, 44 certified datasets, 1,748 tags

## Active Rollout Plan

- **Phase 1** (Weeks 1-3, starting April 15): Send cleanup spreadsheets to owners
- **Phase 2** (Weeks 3-4): Definitions and renames for items marked "Keep"
- **Phase 3** (Weeks 4-6): Consolidation of 226 duplicate groups
- **Phase 4** (Weeks 6-8): AI enablement — glossary upload, certification, config
- **Phase 5**: Ongoing governance and monitoring
- **Hard deadline**: May 1 — no response = remove
