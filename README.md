# GSTV Domo Governance Toolkit

Automated extraction, analysis, and cleanup toolkit for GSTV's Domo environment.
Built to prepare the Domo instance for AI-powered analytics by inventorying all
datasets and dataflows, identifying stale/duplicate/poorly named items, generating
per-owner cleanup assignments, and automating the remediation via the Domo API.

**Scale:** 2,295 datasets, 904 dataflows, 52,971 columns, 20 dataset owners.


## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure Domo API credentials
cp .env.example .env
# Edit .env with your DOMO_CLIENT_ID and DOMO_CLIENT_SECRET

# 3. Run a full extraction (or use --rebuild to skip API calls and use cache)
python3 main.py
python3 main.py --rebuild
```

**Requirements:** Python 3.10+, packages: `requests`, `python-dotenv`, `openpyxl`


## Governance Workflow

The toolkit follows a 5-phase pipeline. Each phase builds on the previous.

```
Phase 1: EXTRACT          Phase 2: ANALYZE           Phase 3: ROLLOUT
main.py ──────────────►  analytics pipeline ──────►  generate_owner_rollouts.py
  Domo API → cache         domain classification       20 personalized spreadsheets
  2,295 datasets           staleness scoring           cleanup_email_template.md
  52,971 columns           lineage mapping             rollout_manifest.csv
  904 dataflows            naming convention
                           duplicate detection
                           schema similarity

Phase 4: AUTOMATE         Phase 5: ONGOING
apply_renames.py          Monitoring & enforcement
apply_descriptions.py     (future: automated staleness
apply_removals.py          alerts, naming enforcement)
upload_glossary.py
transfer_ownership.py
```


## Phase 1: Extract

Pull a complete inventory from the Domo API into a local cache and Excel workbook.

| Script | Purpose |
|--------|---------|
| `main.py` | CLI entry point. Extracts datasets, schemas, dataflows, and lineage. Outputs `domo_inventory_YYYYMMDD.xlsx` (5 tabs). |
| `domo_client.py` | Domo API client with OAuth2 auth, pagination, rate limiting, retry logic, and write operations. |
| `extractors.py` | Extraction functions that pull data from Domo and produce flat record lists. Manages the `.cache/latest.json` file. |
| `excel_writer.py` | Builds and formats the 5-tab inventory workbook. |

```bash
# Full extraction from Domo API
python3 main.py

# Rebuild workbook from cache (no API calls, picks up fresh definitions)
python3 main.py --rebuild

# Validate credentials only
python3 main.py --dry-run
```

**Cache:** All extracted data is saved to `.cache/latest.json` (~12 MB). Every
downstream script reads from this cache rather than hitting the API again.


## Phase 2: Analyze

Run analytical scripts against the cache to classify, score, and identify issues.

### Domain Classification & Staleness

| Script | Purpose |
|--------|---------|
| `analytics.py` | Core analytical functions: `_classify_domain()` maps every dataset to a business domain (Impressions, Revenue, Transactions, Sites, Programmatic, etc.) and department. Computes staleness tiers (Active/Aging/Stale/Dormant/Abandoned). |
| `analyze_unclassified.py` | Clusters unclassified datasets by naming patterns to suggest new domain rules. |

### Naming Convention & Renames

Convention: `[Environment] - [Domain] - [Description] - [Qualifier]`

| Script | Purpose | Output |
|--------|---------|--------|
| `generate_renames.py` | Conservative mechanical fixes: casing, bracket removal, extension stripping. | `dataset_renames.csv`, `dataflow_renames.csv` (525 renames) |
| `generate_aggressive_renames.py` | Full restructuring to naming convention compliance. Detects environment prefixes, domains, sub-prefixes, qualifiers. | `dataset_aggressive_renames.csv`, `dataflow_aggressive_renames.csv` (1,983 restructures) |

```bash
python3 generate_renames.py
python3 generate_aggressive_renames.py
```

### Data Dictionary & Definitions

| Script | Purpose | Coverage |
|--------|---------|----------|
| `infer_definitions.py` | First pass: pattern-based rules for common column naming conventions. | +2,598 columns |
| `infer_definitions_v2.py` | Second pass: OOH fields, ALL_CAPS system fields, compound metrics. | +additional |
| `infer_definitions_v3.py` | Third pass: mop up remaining interpretable columns. | +additional |
| `glossary_to_definitions.py` | Cross-reference 197 GSTV glossary terms against undefined columns. | +218 columns |
| `cleanup_definitions.py` through `cleanup_definitions_v4.py` | Quality passes: standardize casing, fix booleans, expand short definitions, add prefixes. | Quality improvement |
| `validate_definitions.py` | Audit: runs 5 consistency checks on the definition file. | Report |
| `infer_descriptions.py` | Generate descriptions for datasets/dataflows missing them. | ~1,200 datasets |

**Result:** `column_definitions.csv` — 6,978 definitions covering 81.0% of 8,610 columns.

```bash
# Full definition pipeline (run in order)
python3 infer_definitions.py
python3 infer_definitions_v2.py
python3 infer_definitions_v3.py
python3 glossary_to_definitions.py
python3 cleanup_definitions.py
python3 cleanup_definitions_v2.py
python3 cleanup_definitions_v3.py
python3 cleanup_definitions_v4.py
python3 validate_definitions.py
```

### Duplicate & Similarity Detection

| Script | Purpose | Output |
|--------|---------|--------|
| `detect_duplicates.py` | Name-based duplicate detection. Adds a tab to the workspace planner. | Tab in workspace planner |
| `schema_similarity.py` | Schema fingerprinting with IDF-weighted Jaccard similarity. Compares column structures within domains. | `output/schema_similarity_analysis.csv` (5,059 pairs) |
| `build_consolidation_workbook.py` | Clusters similar datasets into 226 consolidation groups using union-find. | `output/domo_consolidation_report_20260412.xlsx` (4 tabs) |

```bash
python3 schema_similarity.py
python3 build_consolidation_workbook.py
```

### Governance Data Extraction

| Script | Purpose | Output |
|--------|---------|--------|
| `extract_governance.py` | Pulls DomoStats governance datasets (cards, pages, card-datasource mappings, tags). Builds dashboard impact report. | `output/dashboard_impact_report.csv`, `output/dataset_tags.csv`, `output/certification_status.csv`, `output/pages_inventory.csv`, `output/cards_inventory.csv` |

```bash
python3 extract_governance.py
```

### Planning Workbooks

| Script | Purpose | Output |
|--------|---------|--------|
| `workspace_planner.py` | Workspace planning workbook with domain assignments, naming standards, proposed renames. | `output/domo_workspace_plan_20260411.xlsx` (11 tabs) |
| `runbook.py` | Team runbook and interview worksheets added to the workspace planner. | Tabs in workspace planner |
| `interview.py` | Interactive CLI tool for filling in missing column definitions with domain context. | Updates `column_definitions.csv` |


## Phase 3: Rollout

Generate personalized cleanup assignments for each dataset owner.

| Script | Purpose | Output |
|--------|---------|--------|
| `generate_owner_rollouts.py` | Builds per-owner Excel spreadsheets with flagged items, rename suggestions (conservative + aggressive), dashboard impact (cards/pages affected), staleness, lineage, domain, and a decision dropdown (Keep/Remove/Need Discussion/Not My Dataset). | `output/owner_rollouts/cleanup_review_{Owner}.xlsx` (20 files), `output/rollout_manifest.csv` |

```bash
python3 generate_owner_rollouts.py
```

Each owner spreadsheet contains:
- **Summary tab** — Totals by staleness category and dashboard impact count
- **Datasets tab** — Each flagged dataset with description, rename suggestions, dashboard impact, domain, staleness, lineage, decision dropdown
- **Dataflows tab** — Same structure for flagged dataflows
- **Instructions tab** — Step-by-step guide for the owner

**Communication & handoff materials:**
- `output/cleanup_email_template.md` — Email template with placeholders
- `generate_cleanup_emails.py` — Mail merge script that fills the template from the rollout manifest and generates .eml files for all 20 owners
- `output/executive_summary.md` — Stakeholder overview of the full initiative
- `output/decision_brief.md` — 6 decisions for exec sponsor with recommendations
- `output/operator_runbook.md` — Day-by-day playbook for the Data team (Phases 1-4)
- `output/consolidation_playbook.md` — Step-by-step guide for Phase 3 duplicate merging

```bash
python3 generate_owner_rollouts.py      # Generate spreadsheets
python3 generate_cleanup_emails.py      # Generate .eml files
python3 generate_cleanup_emails.py --preview  # Preview first
```


## Phase 4: Automate

Push approved changes to Domo via the API. All scripts default to `--dry-run`.

| Script | Purpose | API Method |
|--------|---------|------------|
| `apply_renames.py` | Reads approved renames from returned spreadsheets or master CSVs, pushes to Domo. | `PUT /v1/datasets/{id}` |
| `apply_descriptions.py` | Pushes auto-generated descriptions to datasets missing them. | `PUT /v1/datasets/{id}` |
| `apply_removals.py` | Deletes items marked "Remove" or no-response after deadline. Creates rollback manifest first. | `DELETE /v1/datasets/{id}` |
| `upload_glossary.py` | Creates "Reference - GSTV Business Glossary" dataset and uploads 197-term CSV. | `POST /v1/datasets` + `PUT /v1/datasets/{id}/data` |
| `transfer_ownership.py` | Reassigns datasets from former employees to current owners. | `PUT /v1/datasets/{id}` (owner field) |

```bash
# Always dry-run first
python3 apply_renames.py --dry-run
python3 apply_renames.py --execute --source spreadsheets

python3 apply_descriptions.py --dry-run
python3 apply_descriptions.py --execute --only-empty

python3 apply_removals.py --dry-run
python3 apply_removals.py --execute --include-no-response

python3 upload_glossary.py --dry-run
python3 upload_glossary.py --execute

python3 transfer_ownership.py --dry-run
python3 transfer_ownership.py --execute --target-owner "Garrett Kohler"
```

**Safety features:**
- All scripts default to `--dry-run` — nothing touches Domo without `--execute`
- `apply_removals.py` requires typing `DELETE` to confirm, warns about dashboard-breaking deletions, and saves a rollback manifest with full cached metadata
- All scripts write timestamped logs to `output/automation_logs/`
- Dataflow operations are automatically skipped (no public API endpoint)

**What requires manual UI work (Garrett & Sriram):**
- Dataflow renames and deletions (~383 dataflows)
- Dataset tags and certification
- Card and dashboard cleanup
- Domo AI configuration and enablement


## Output Reference

### Workbooks (Excel)

| File | Size | Tabs | Description |
|------|------|------|-------------|
| `output/domo_inventory_20260411.xlsx` | 3.97 MB | 10 | Full environment inventory |
| `output/domo_workspace_plan_20260411.xlsx` | 488 KB | 11 | Workspace planning with naming standards |
| `output/domo_consolidation_report_20260412.xlsx` | 209 KB | 4 | Schema similarity with 226 consolidation groups |
| `output/owner_rollouts/cleanup_review_*.xlsx` | varies | 4 each | 20 personalized owner cleanup spreadsheets |

### CSVs

| File | Description |
|------|-------------|
| `column_definitions.csv` | 6,978 column definitions (81.0% coverage) |
| `gstv_glossary.csv` | 197 GSTV business terms for Domo upload |
| `dataset_renames.csv` / `dataflow_renames.csv` | 525 conservative rename mappings |
| `dataset_aggressive_renames.csv` / `dataflow_aggressive_renames.csv` | 1,983 full restructure mappings |
| `output/dashboard_impact_report.csv` | 317 cards across 25 pages at risk |
| `output/schema_similarity_analysis.csv` | 5,059 similar dataset pairs |
| `output/dataset_tags.csv` | 1,748 tag entries across 215 unique tags |
| `output/certification_status.csv` | 44 certified datasets |
| `output/rollout_manifest.csv` | Owner summary with item counts |
| `output/pages_inventory.csv` | 225 Domo pages with view counts |
| `output/cards_inventory.csv` | Full card inventory |

### Communication & Handoff

| File | Audience | Description |
|------|----------|-------------|
| `output/executive_summary.md` | Bill (exec sponsor) | Stakeholder overview with stats, rollout plan, AI use cases, automation plan |
| `output/decision_brief.md` | Bill (exec sponsor) | 6 decisions needed with recommendations — designed for quick approval |
| `output/operator_runbook.md` | Garrett, Sriram | Day-by-day playbook for Phases 1-4 with exact commands, timelines, and troubleshooting |
| `output/consolidation_playbook.md` | Garrett, Sriram | Step-by-step guide for Phase 3 duplicate merging with common patterns and priority order |
| `output/cleanup_email_template.md` | (template) | Email template with placeholders for owner cleanup assignments |
| `output/cleanup_emails/*.eml` | (generated) | Pre-filled .eml files for all 20 owners, generated by `generate_cleanup_emails.py` |


## Architecture

```
.env                          Domo API credentials
    |
    v
domo_client.py                API client (auth, pagination, rate limiting, CRUD)
    |
    v
extractors.py                 Pull datasets, schemas, dataflows, lineage
    |
    v
.cache/latest.json            Complete environment snapshot (~12 MB)
    |
    +---> analytics.py         Domain classification, staleness scoring
    |         |
    |         +---> generate_renames.py              Conservative renames
    |         +---> generate_aggressive_renames.py   Full restructures
    |         +---> infer_descriptions.py            Dataset descriptions
    |
    +---> infer_definitions.py (v1-v3)    Pattern-based column definitions
    |         |
    |         +---> glossary_to_definitions.py       Glossary cross-reference
    |         +---> cleanup_definitions.py (v1-v4)   Quality passes
    |
    +---> schema_similarity.py             Duplicate detection by schema
    |         |
    |         +---> build_consolidation_workbook.py  Consolidation groups
    |
    +---> extract_governance.py            Dashboard impact, tags, certification
    |
    +---> generate_owner_rollouts.py       Per-owner cleanup spreadsheets
    |         (merges: renames, dashboard impact, staleness, lineage, domains)
    |
    +---> Automation scripts               Push changes to Domo API
          apply_renames.py
          apply_descriptions.py
          apply_removals.py
          upload_glossary.py
          transfer_ownership.py
```

### Key Data Structures

**Cache** (`.cache/latest.json`):
```json
{
  "datasets": [{"dataset_id": "...", "dataset_name": "...", "owner_name": "...", "columns": [...], ...}],
  "schemas": [{"dataset_id": "...", "column_name": "...", "column_type": "...", ...}],
  "dataflows": [{"dataflow_id": "...", "dataflow_name": "...", ...}],
  "lineage": [{"dataflow_id": "...", "direction": "Input|Output", "dataset_id": "...", ...}],
  "extraction_time": "2026-04-11 14:30:00"
}
```

**Domain Classification** (`analytics.py`):
The `_classify_domain()` function uses an ordered list of `DOMAIN_RULES` —
regex patterns matched against dataset names. First match wins. Domains include:
Impressions & Proof of Play, Revenue & Monetization, Transactions, Sites & Locations,
Programmatic, Salesforce & CRM, HR & People, Finance & Accounting, and more.


## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DOMO_CLIENT_ID` | Yes | Domo API client ID |
| `DOMO_CLIENT_SECRET` | Yes | Domo API client secret |

Set via `.env` file or shell environment. The Domo instance subdomain is `gstv`
(i.e., `https://gstv.domo.com`).


## Domo API Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/oauth/token` | OAuth2 client_credentials authentication |
| `GET` | `/v1/datasets` | List all datasets (paginated) |
| `GET` | `/v1/datasets/{id}?fields=all` | Get dataset detail with schema |
| `GET` | `/v1/datasets/{id}/data` | Export dataset as CSV |
| `PUT` | `/v1/datasets/{id}` | Update dataset name, description, or owner |
| `DELETE` | `/v1/datasets/{id}` | Delete a dataset |
| `POST` | `/v1/datasets` | Create a new dataset |
| `PUT` | `/v1/datasets/{id}/data` | Upload CSV data to a dataset |

**Not available via API** (requires Domo UI):
- Dataflow rename/delete
- Dataset tag management
- Card/page management
- AI feature configuration
