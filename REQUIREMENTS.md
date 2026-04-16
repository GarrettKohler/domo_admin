# Domo Inventory Extraction Tool — Requirements Spec

## Overview

Build a Python CLI tool that connects to the Domo API, extracts a full inventory of all datasets (with column-level schemas) and all dataflows (with input/output lineage), and outputs a formatted Excel workbook. This is the foundation for a GSTV data dictionary.

## Environment & Auth

- **Language:** Python 3.10+
- **Authentication:** OAuth2 client_credentials flow against `https://api.domo.com/oauth/token`
- **Credentials:** Read from environment variables:
  - `DOMO_CLIENT_ID` — the Domo API client ID
  - `DOMO_CLIENT_SECRET` — the Domo API client secret
- On startup, validate that both env vars are set. If either is missing, print a clear error message and exit with code 1.
- Support an optional `.env` file in the project root (use `python-dotenv`).

## Domo API Reference

Base URL: `https://api.domo.com`

### Authentication
```
POST /oauth/token?grant_type=client_credentials&scope=data%20workflow
Authorization: Basic {base64(client_id:client_secret)}
```
Returns: `{ "access_token": "...", "token_type": "bearer", "expires_in": 3600 }`

Use the access_token as a Bearer token in all subsequent requests. If a token expires mid-run, re-authenticate automatically.

### Datasets
- **List datasets:** `GET /v1/datasets?limit=50&offset={offset}&sort=name`
  - Paginate by incrementing offset by 50 until an empty array is returned
  - Returns: array of dataset objects with `id`, `name`, `description`, `owner` (object with `id` and `name`), `rows`, `columns`, `createdAt`, `updatedAt`, `dataCurrentAt`, `pdpEnabled`, `type`
- **Get dataset detail (for schema):** `GET /v1/datasets/{id}?fields=all`
  - Returns full dataset object including `schema` → `columns` array
  - Each column has: `name`, `type` (STRING, LONG, DOUBLE, DECIMAL, DATE, DATETIME)

### Dataflows
- **List dataflows:** `GET /v1/dataflows?limit=50&offset={offset}`
  - Paginate same as datasets
  - Returns: array of dataflow objects with `id`, `name`, `description`, `owner`, `type` (MYSQL, REDSHIFT, MAGIC_ETL, etc.), `createdAt`, `updatedAt`, `lastExecution`
- **Get dataflow detail:** `GET /v1/dataflows/{id}`
  - Returns full object including `inputs` and `outputs` arrays
  - Each input/output contains `dataSetId` and `dataSetName`

## Rate Limiting

- Domo enforces rate limits (~100 requests/minute on standard tiers).
- Implement a **0.6-second delay** between individual API calls (dataset detail, dataflow detail).
- On HTTP 429 responses, implement **exponential backoff**: wait 2s, then 4s, then 8s, up to 3 retries. If still 429 after 3 retries, log the error and skip that item (do not crash).
- On HTTP 401 during a run, re-authenticate and retry the request once.

## Data to Extract

### Datasets (one record per dataset)
| Field | Source | Notes |
|---|---|---|
| `dataset_id` | list endpoint → `id` | String, Domo's unique ID |
| `dataset_name` | list endpoint → `name` | |
| `description` | list endpoint → `description` | May be null/empty |
| `owner_id` | list endpoint → `owner.id` | |
| `owner_name` | list endpoint → `owner.name` | |
| `row_count` | list endpoint → `rows` | Integer |
| `column_count` | list endpoint → `columns` | Integer |
| `dataset_type` | list endpoint → `type` | e.g., "api", "webform", "excel" |
| `pdp_enabled` | list endpoint → `pdpEnabled` | Boolean |
| `created_at` | list endpoint → `createdAt` | ISO datetime |
| `updated_at` | list endpoint → `updatedAt` | ISO datetime |
| `data_current_at` | list endpoint → `dataCurrentAt` | ISO datetime, when data was last refreshed |

### Dataset Schemas (one record per column per dataset)
| Field | Source | Notes |
|---|---|---|
| `dataset_id` | detail endpoint | Foreign key to Datasets |
| `dataset_name` | detail endpoint | For readability |
| `column_position` | index in schema.columns array | 1-based |
| `column_name` | schema.columns[].name | |
| `column_type` | schema.columns[].type | STRING, LONG, DOUBLE, DECIMAL, DATE, DATETIME |

### Dataflows (one record per dataflow)
| Field | Source | Notes |
|---|---|---|
| `dataflow_id` | list endpoint → `id` | |
| `dataflow_name` | list endpoint → `name` | |
| `description` | list endpoint → `description` | May be null/empty |
| `owner_id` | list endpoint → `owner.id` | |
| `owner_name` | list endpoint → `owner.name` | |
| `dataflow_type` | list endpoint → `type` | MYSQL, REDSHIFT, MAGIC_ETL, etc. |
| `created_at` | list endpoint → `createdAt` | |
| `updated_at` | list endpoint → `updatedAt` | |
| `last_execution_date` | list endpoint → `lastExecution.startedAt` | May be null |
| `last_execution_status` | list endpoint → `lastExecution.currentState` | e.g., "SUCCESS", "FAILED" |

### Dataflow Lineage (one record per input/output relationship)
| Field | Source | Notes |
|---|---|---|
| `dataflow_id` | detail endpoint | Foreign key to Dataflows |
| `dataflow_name` | detail endpoint | For readability |
| `direction` | derived | "Input" or "Output" |
| `dataset_id` | inputs[]/outputs[] → `dataSetId` | Foreign key to Datasets |
| `dataset_name` | inputs[]/outputs[] → `dataSetName` | |

## Output: Excel Workbook

**Filename:** `domo_inventory_YYYYMMDD.xlsx` (date of extraction)

### Tab 1: "Datasets"
- One row per dataset, columns match the Datasets table above
- Header row: bold white text on navy background (`#3E5170`)
- Font: Arial 10pt throughout
- Column widths auto-fitted to content
- Sort by `dataset_name` ascending
- Freeze top row

### Tab 2: "Dataset Schemas"
- One row per column per dataset
- Columns match the Dataset Schemas table above
- Same header formatting as Tab 1
- Sort by `dataset_name` then `column_position`
- Freeze top row

### Tab 3: "Dataflows"
- One row per dataflow, columns match the Dataflows table above
- Same header formatting
- Sort by `dataflow_name` ascending
- Freeze top row

### Tab 4: "Dataflow Lineage"
- One row per input/output relationship
- Columns match the Dataflow Lineage table above
- Same header formatting
- Sort by `dataflow_name`, then `direction` (Input before Output), then `dataset_name`
- Freeze top row

### Tab 5: "Extraction Log"
- Summary metadata about the run:
  - Extraction date/time
  - Total datasets found
  - Total dataset schemas (columns) extracted
  - Total dataflows found
  - Total lineage relationships mapped
  - Any datasets or dataflows that were skipped due to API errors (list IDs and error messages)
- This tab is for auditability — so we know if any items were missed.

## Project Structure

```
domo-inventory/
├── .env.example          # Template with DOMO_CLIENT_ID= and DOMO_CLIENT_SECRET=
├── requirements.txt      # requests, python-dotenv, openpyxl
├── README.md             # Setup instructions and usage
├── main.py               # Entry point — CLI script
├── domo_client.py        # Domo API client class (auth, pagination, rate limiting)
├── extractors.py         # Functions to extract datasets, schemas, dataflows, lineage
└── excel_writer.py       # Functions to build and format the Excel workbook
```

## CLI Interface

```bash
# Basic usage
python main.py

# Optional: specify output directory
python main.py --output ./exports

# Optional: extract only datasets or only dataflows
python main.py --datasets-only
python main.py --dataflows-only
```

## Progress & Logging

- Print progress to stdout during extraction:
  ```
  Authenticating with Domo API... ✓
  Fetching datasets... 50/500... 100/500... (etc)
  Fetching dataset schemas... 1/523... 50/523... (etc)
  Fetching dataflows... 50/200... (etc)
  Fetching dataflow details... 1/187... 50/187... (etc)
  Writing Excel workbook... ✓
  Done! Output: domo_inventory_20260410.xlsx
  ```
- Use Python `logging` module for debug-level detail (API calls, retries, skips)
- Log level configurable via `--verbose` flag

## Error Handling

- **Missing credentials:** Exit immediately with a message telling the user to set `DOMO_CLIENT_ID` and `DOMO_CLIENT_SECRET`
- **Auth failure (401 on token request):** Exit with message that credentials are invalid
- **Individual item failure:** Log the error, record it in the Extraction Log tab, and continue processing remaining items. Never crash the full run because one dataset or dataflow failed.
- **Network errors:** Retry up to 3 times with exponential backoff, then skip and log.

## Acceptance Criteria

1. Running `python main.py` with valid credentials produces an `.xlsx` file with all 5 tabs populated
2. The Datasets tab contains one row per dataset in the Domo instance
3. The Dataset Schemas tab contains one row per column per dataset — this is the critical deliverable
4. The Dataflows tab contains one row per dataflow
5. The Dataflow Lineage tab correctly maps which datasets are inputs and outputs for each dataflow
6. The Extraction Log tab shows run metadata and any errors encountered
7. The script handles 500+ datasets without crashing, respecting rate limits
8. The script handles API errors gracefully — skipping failed items and logging them rather than crashing
9. All Excel formatting follows the spec (navy headers, Arial font, frozen rows, auto-fitted columns)
10. The script runs in under 15 minutes for a 500-dataset environment

## Dependencies

```
requests>=2.31.0
python-dotenv>=1.0.0
openpyxl>=3.1.0
```

## Testing Notes

- To test without hitting the real API, the `DomoClient` class should accept an optional `base_url` parameter so it can be pointed at a mock server
- Consider adding a `--dry-run` flag that authenticates and fetches the first page of datasets/dataflows only, to validate credentials and connectivity without running the full extraction
