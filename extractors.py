"""Extraction functions that pull data from Domo and produce flat record lists."""

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

from domo_client import DomoClient

logger = logging.getLogger(__name__)

DEFINITIONS_FILE = Path(__file__).parent / "column_definitions.csv"
CACHE_DIR = Path(__file__).parent / ".cache"

# DomoStats dataset IDs for dataflow/lineage data (from Domo Governance)
DOMOSTATS_DATAFLOWS_ID = "d33ee5a2-c009-45d7-a358-de3c466e148d"
DOMOSTATS_DATAFLOW_INPUTS_ID = "bc3c561c-ecf5-40bc-be67-b6c51d88bb09"
DOMOSTATS_DATAFLOW_OUTPUTS_ID = "3ab0d4fe-81b8-42ac-b990-74ed8a210cba"


def _parse_csv(csv_text: str) -> list[dict[str, str]]:
    """Parse CSV text into a list of dicts."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def save_cache(
    datasets: list[dict[str, Any]],
    schemas: list[dict[str, Any]],
    dataflows: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
    errors: list[dict[str, str]],
    extraction_time: str,
) -> Path:
    """Save extracted data to a JSON cache file.

    Schemas are saved WITHOUT definitions — definitions are merged fresh
    at rebuild time from column_definitions.csv.
    """
    CACHE_DIR.mkdir(exist_ok=True)

    # Strip definitions from schemas before caching (they're merged at build time)
    schemas_no_defs = [
        {k: v for k, v in s.items() if k != "definition"} for s in schemas
    ]

    cache_data = {
        "extraction_time": extraction_time,
        "datasets": datasets,
        "schemas": schemas_no_defs,
        "dataflows": dataflows,
        "lineage": lineage,
        "errors": errors,
    }

    cache_path = CACHE_DIR / "latest.json"
    with open(cache_path, "w") as f:
        json.dump(cache_data, f, default=str)

    size_mb = cache_path.stat().st_size / (1024 * 1024)
    logger.info("Cache saved to %s (%.1f MB)", cache_path, size_mb)
    return cache_path


def load_cache() -> dict[str, Any] | None:
    """Load cached extraction data. Returns None if no cache exists."""
    cache_path = CACHE_DIR / "latest.json"
    if not cache_path.exists():
        return None

    with open(cache_path) as f:
        data = json.load(f)

    logger.info("Cache loaded from %s (extracted %s)", cache_path, data.get("extraction_time", "unknown"))
    return data


def rebuild_from_cache() -> tuple[
    list[dict[str, Any]],  # datasets
    list[dict[str, Any]],  # schemas (with fresh definitions)
    list[dict[str, Any]],  # dataflows
    list[dict[str, Any]],  # lineage
    list[dict[str, str]],  # errors
    str,                   # extraction_time
] | None:
    """Rebuild all data from cache, merging fresh definitions into schemas.

    Returns None if no cache is available.
    """
    cache = load_cache()
    if cache is None:
        return None

    # Merge fresh definitions into cached schemas
    definitions = _load_definitions()
    schemas = cache["schemas"]
    for schema in schemas:
        col_name = schema.get("column_name", "")
        col_type = schema.get("column_type", "")
        schema["definition"] = definitions.get((col_name, col_type), "")

    return (
        cache["datasets"],
        schemas,
        cache["dataflows"],
        cache["lineage"],
        cache["errors"],
        cache["extraction_time"],
    )


def _load_definitions() -> dict[tuple[str, str], str]:
    """Load column definitions from the definitions CSV file.

    Returns:
        dict mapping (column_name, column_type) -> definition text.
    """
    if not DEFINITIONS_FILE.exists():
        logger.info("No definitions file found at %s", DEFINITIONS_FILE)
        return {}

    defs = {}
    with open(DEFINITIONS_FILE, newline="") as f:
        for row in csv.DictReader(f):
            defn = row.get("definition", "").strip()
            if defn:
                defs[(row["column_name"], row["column_type"])] = defn
    logger.info("Loaded %d column definitions", len(defs))
    return defs


def extract_datasets(client: DomoClient) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract all datasets from Domo.

    Returns:
        (dataset_records, errors) — flat dicts ready for Excel, plus any errors.
    """
    raw_datasets = client.list_datasets()
    records = []

    for ds in raw_datasets:
        owner = ds.get("owner") or {}
        records.append({
            "dataset_id": ds.get("id", ""),
            "dataset_name": ds.get("name", ""),
            "description": ds.get("description", ""),
            "owner_id": owner.get("id", ""),
            "owner_name": owner.get("name", ""),
            "row_count": ds.get("rows", 0),
            "column_count": ds.get("columns", 0),
            "dataset_type": ds.get("type", ""),
            "pdp_enabled": ds.get("pdpEnabled", False),
            "created_at": ds.get("createdAt", ""),
            "updated_at": ds.get("updatedAt", ""),
            "data_current_at": ds.get("dataCurrentAt", ""),
        })

    records.sort(key=lambda r: (r["dataset_name"] or "").lower())
    logger.info("Extracted %d datasets", len(records))
    return records, []


def extract_dataset_schemas(
    client: DomoClient,
    dataset_records: list[dict[str, Any]],
    progress_callback=None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch detail for each dataset to get column schemas.

    Returns:
        (schema_records, errors)
    """
    definitions = _load_definitions()
    schema_records = []
    errors = []
    total = len(dataset_records)

    for idx, ds in enumerate(dataset_records, 1):
        ds_id = ds["dataset_id"]
        ds_name = ds["dataset_name"]

        if progress_callback:
            progress_callback(idx, total)

        detail = client.get_dataset_detail(ds_id)
        if detail is None:
            errors.append({"id": ds_id, "name": ds_name, "type": "dataset", "error": "Failed to fetch detail"})
            continue

        schema = detail.get("schema") or {}
        columns = schema.get("columns") or []

        for pos, col in enumerate(columns, 1):
            col_name = col.get("name", "")
            col_type = col.get("type", "")
            schema_records.append({
                "dataset_id": ds_id,
                "dataset_name": ds_name,
                "column_position": pos,
                "column_name": col_name,
                "column_type": col_type,
                "definition": definitions.get((col_name, col_type), ""),
            })

    schema_records.sort(key=lambda r: ((r["dataset_name"] or "").lower(), r["column_position"]))
    logger.info("Extracted %d schema columns across %d datasets", len(schema_records), total)
    return schema_records, errors


def extract_dataflows(
    client: DomoClient,
    dataset_id_to_name: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract dataflows from the DomoStats - Dataflows governance dataset.

    Args:
        client: Authenticated DomoClient.
        dataset_id_to_name: Lookup dict mapping dataset_id -> dataset_name (for owner resolution).

    Returns:
        (dataflow_records, errors)
    """
    errors = []
    csv_text = client.export_dataset_csv(DOMOSTATS_DATAFLOWS_ID)
    if csv_text is None:
        errors.append({
            "id": DOMOSTATS_DATAFLOWS_ID,
            "name": "DomoStats - Dataflows",
            "type": "dataflow",
            "error": "Failed to export DomoStats - Dataflows dataset",
        })
        return [], errors

    rows = _parse_csv(csv_text)
    records = []
    for row in rows:
        records.append({
            "dataflow_id": row.get("ID", ""),
            "dataflow_name": row.get("Display Name", ""),
            "description": row.get("Description", ""),
            "owner_id": row.get("Owner ID", ""),
            "owner_name": "",  # Not in DomoStats; could be resolved via People dataset
            "dataflow_type": row.get("Type", ""),
            "status": row.get("Status", ""),
            "input_count": row.get("Inputs", ""),
            "output_count": row.get("Outputs", ""),
            "last_execution_date": row.get("Last Executed Date", ""),
            "last_updated_date": row.get("Last Updated Date", ""),
        })

    records.sort(key=lambda r: (r["dataflow_name"] or "").lower())
    logger.info("Extracted %d dataflows from DomoStats", len(records))
    return records, errors


def extract_dataflow_lineage(
    client: DomoClient,
    dataflow_records: list[dict[str, Any]],
    dataset_id_to_name: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract dataflow input/output lineage from DomoStats governance datasets.

    Args:
        client: Authenticated DomoClient.
        dataflow_records: List of dataflow records (for ID-to-name lookup).
        dataset_id_to_name: Lookup dict mapping dataset_id -> dataset_name.

    Returns:
        (lineage_records, errors)
    """
    errors = []
    lineage_records = []

    # Build dataflow ID -> name lookup
    df_id_to_name = {str(df["dataflow_id"]): df["dataflow_name"] for df in dataflow_records}

    # Fetch inputs
    inputs_csv = client.export_dataset_csv(DOMOSTATS_DATAFLOW_INPUTS_ID)
    if inputs_csv is None:
        errors.append({
            "id": DOMOSTATS_DATAFLOW_INPUTS_ID,
            "name": "DomoStats - DataFlow Input Datasources",
            "type": "dataflow",
            "error": "Failed to export DomoStats - DataFlow Input Datasources dataset",
        })
    else:
        for row in _parse_csv(inputs_csv):
            df_id = row.get("Dataflow ID", "")
            ds_id = row.get("Datasource Input ID", "")
            lineage_records.append({
                "dataflow_id": df_id,
                "dataflow_name": df_id_to_name.get(df_id, ""),
                "direction": "Input",
                "dataset_id": ds_id,
                "dataset_name": dataset_id_to_name.get(ds_id, ""),
            })

    # Fetch outputs
    outputs_csv = client.export_dataset_csv(DOMOSTATS_DATAFLOW_OUTPUTS_ID)
    if outputs_csv is None:
        errors.append({
            "id": DOMOSTATS_DATAFLOW_OUTPUTS_ID,
            "name": "DomoStats - DataFlow Output Datasources",
            "type": "dataflow",
            "error": "Failed to export DomoStats - DataFlow Output Datasources dataset",
        })
    else:
        for row in _parse_csv(outputs_csv):
            df_id = row.get("Dataflow ID", "")
            ds_id = row.get("Datasource Output ID", "")
            lineage_records.append({
                "dataflow_id": df_id,
                "dataflow_name": df_id_to_name.get(df_id, ""),
                "direction": "Output",
                "dataset_id": ds_id,
                "dataset_name": dataset_id_to_name.get(ds_id, ""),
            })

    # Sort: dataflow_name, direction (Input before Output), dataset_name
    direction_order = {"Input": 0, "Output": 1}
    lineage_records.sort(
        key=lambda r: (
            (r["dataflow_name"] or "").lower(),
            direction_order.get(r["direction"], 2),
            (r["dataset_name"] or "").lower(),
        )
    )
    logger.info("Extracted %d lineage relationships", len(lineage_records))
    return lineage_records, errors
