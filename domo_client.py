"""Domo API client with OAuth2 auth, pagination, rate limiting, and retry logic.

Supports two auth modes:
  1. **Developer Access Token** (preferred when set) — long-lived token from
     Admin → Security → Access tokens on the instance. Sent as the
     ``X-DOMO-Developer-Token`` header against ``https://<instance>.domo.com``.
  2. **OAuth2 client_credentials** — public-API flow via developer.domo.com,
     ``Authorization: Bearer <token>`` against ``https://api.domo.com``.

Both modes expose the same methods. When a developer token is supplied the
OAuth dance is skipped entirely.
"""

import base64
import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.domo.com"
DEFAULT_INSTANCE = "gstv"
PAGE_SIZE = 50
RATE_LIMIT_DELAY = 0.6  # seconds between detail API calls
MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds, doubles each retry


class DomoAuthError(Exception):
    """Raised when authentication fails."""


class DomoClient:
    """Client for the Domo API with built-in auth, pagination, and rate limiting."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        instance: str = DEFAULT_INSTANCE,
        base_url: str | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.instance = instance

        # Developer tokens authenticate against the instance subdomain;
        # OAuth2 uses the public api.domo.com host.
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        elif access_token:
            self.base_url = f"https://{instance}.domo.com"
        else:
            self.base_url = DEFAULT_BASE_URL

        self.session = requests.Session()
        self._access_token: str | None = None
        self._token_acquired_at: float = 0
        self._token_expires_in: int = 3600

        if not access_token and not (client_id and client_secret):
            raise DomoAuthError(
                "DomoClient requires either access_token or client_id/client_secret."
            )

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "DomoClient":
        """Build a DomoClient from environment variables.

        Prefers ``DOMO_ACCESS_TOKEN`` (+ optional ``DOMO_INSTANCE``). Falls
        back to ``DOMO_CLIENT_ID`` / ``DOMO_CLIENT_SECRET``. Raises
        ``DomoAuthError`` if neither is set.
        """
        token = (os.environ.get("DOMO_ACCESS_TOKEN") or "").strip()
        instance = (os.environ.get("DOMO_INSTANCE") or DEFAULT_INSTANCE).strip()
        if token:
            return cls(access_token=token, instance=instance)

        cid = (os.environ.get("DOMO_CLIENT_ID") or "").strip()
        secret = (os.environ.get("DOMO_CLIENT_SECRET") or "").strip()
        if cid and secret:
            return cls(client_id=cid, client_secret=secret)

        raise DomoAuthError(
            "No Domo credentials found. Set DOMO_ACCESS_TOKEN (+ DOMO_INSTANCE) "
            "or DOMO_CLIENT_ID/DOMO_CLIENT_SECRET in .env."
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def authenticate(self) -> None:
        """Establish credentials for subsequent requests.

        - Developer token: set header once, no network call.
        - OAuth2: exchange client_id/secret for a bearer token.
        """
        if self.access_token:
            self.session.headers.update(
                {"X-DOMO-Developer-Token": self.access_token}
            )
            self._access_token = self.access_token
            self._token_acquired_at = time.time()
            self._token_expires_in = 365 * 24 * 3600  # effectively long-lived
            logger.debug("Using developer access token against %s", self.base_url)
            return

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        resp = requests.post(
            f"{self.base_url}/oauth/token",
            params={"grant_type": "client_credentials", "scope": "data workflow"},
            headers={"Authorization": f"Basic {credentials}"},
            timeout=30,
        )

        if resp.status_code == 401:
            raise DomoAuthError(
                "Authentication failed — check that DOMO_CLIENT_ID and DOMO_CLIENT_SECRET are valid."
            )
        resp.raise_for_status()

        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_in = data.get("expires_in", 3600)
        self._token_acquired_at = time.time()
        self.session.headers.update({"Authorization": f"Bearer {self._access_token}"})
        logger.debug("Authenticated successfully, token expires in %ds", self._token_expires_in)

    def _token_is_expired(self) -> bool:
        # Developer tokens never "expire" from the client's perspective — Domo
        # revokes them out of band. Always report fresh when one is in use.
        if self.access_token:
            return self._access_token is None
        if not self._access_token:
            return True
        elapsed = time.time() - self._token_acquired_at
        return elapsed >= (self._token_expires_in - 60)  # refresh 60s before expiry

    def _ensure_auth(self) -> None:
        if self._token_is_expired():
            logger.debug("Token expired or missing, re-authenticating")
            self.authenticate()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an API request with automatic auth refresh and retry on 429/401/network errors."""
        self._ensure_auth()

        url = f"{self.base_url}{path}"

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.session.request(method, url, timeout=30, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < MAX_RETRIES:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Network error on %s, waiting %ds (attempt %d/%d): %s", path, wait, attempt + 1, MAX_RETRIES, e)
                    time.sleep(wait)
                    continue
                else:
                    logger.error("Network error after %d retries: %s — %s", MAX_RETRIES, path, e)
                    raise

            if resp.status_code == 401 and attempt == 0 and not self.access_token:
                # Only re-auth on OAuth path; a revoked developer token can't be
                # fixed by retrying — surface the 401 to the caller instead.
                logger.warning("Got 401, re-authenticating and retrying")
                self.authenticate()
                continue

            if resp.status_code == 429:
                if attempt < MAX_RETRIES:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Rate limited (429), waiting %ds (attempt %d/%d)", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                    continue
                else:
                    logger.error("Rate limited after %d retries: %s", MAX_RETRIES, path)
                    return resp

            return resp

        return resp  # type: ignore[possibly-undefined]

    def _get(self, path: str, **kwargs) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _put(self, path: str, **kwargs) -> requests.Response:
        return self._request("PUT", path, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def _delete(self, path: str, **kwargs) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    def _paginate(self, path: str, sort: str | None = None) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated list endpoint."""
        all_items: list[dict[str, Any]] = []
        offset = 0

        while True:
            params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
            if sort:
                params["sort"] = sort

            resp = self._get(path, params=params)
            resp.raise_for_status()
            page = resp.json()

            if not page:
                break

            all_items.extend(page)
            offset += PAGE_SIZE

            if len(page) < PAGE_SIZE:
                break

        return all_items

    # ------------------------------------------------------------------
    # Internal-API helpers (used when authenticating with a developer token)
    #
    # The developer token authenticates against <instance>.domo.com, which
    # exposes a different set of paths than the public /v1/* API. These
    # helpers hit the internal /api/* paths and normalise responses to
    # match the public-API record shape the rest of the codebase expects.
    # ------------------------------------------------------------------
    def _ms_to_iso(self, ms: Any) -> str:
        if not ms:
            return ""
        try:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            return ""

    def _normalise_datasource(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Convert an internal /api/data/v3/datasources record to public shape."""
        return {
            "id": rec.get("id", ""),
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "owner": rec.get("owner") or {},
            "rows": rec.get("rowCount", 0),
            "columns": rec.get("columnCount", 0),
            "type": rec.get("dataProviderType", rec.get("type", "")),
            "pdpEnabled": rec.get("policies", {}).get("enabled", False)
            if isinstance(rec.get("policies"), dict)
            else False,
            "createdAt": self._ms_to_iso(rec.get("created")),
            "updatedAt": self._ms_to_iso(rec.get("lastUpdated")),
            "dataCurrentAt": self._ms_to_iso(rec.get("lastTouched")),
        }

    def _list_datasets_internal(self) -> list[dict[str, Any]]:
        """Paginated fetch of /api/data/v3/datasources."""
        all_items: list[dict[str, Any]] = []
        offset = 0
        while True:
            resp = self._get(
                "/api/data/v3/datasources",
                params={"limit": PAGE_SIZE, "offset": offset},
            )
            resp.raise_for_status()
            body = resp.json()
            page = body.get("dataSources", []) if isinstance(body, dict) else body
            if not page:
                break
            all_items.extend(page)
            offset += PAGE_SIZE
            if len(page) < PAGE_SIZE:
                break
        return [self._normalise_datasource(r) for r in all_items]

    def _get_dataset_detail_internal(self, dataset_id: str) -> dict[str, Any] | None:
        """Fetch schema from the internal API and wrap it in public-API shape."""
        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._get(
                f"/api/query/v1/datasources/{dataset_id}/schema/indexed"
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error getting dataset %s: %s", dataset_id, e)
            return None

        if resp.status_code == 429:
            logger.error("Skipping dataset %s after rate limit retries", dataset_id)
            return None
        if resp.status_code == 404:
            # Some datasources (e.g. empty or not-yet-indexed) 404 here.
            return {"id": dataset_id, "schema": {"columns": []}}

        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logger.error("Failed to get dataset %s: %s", dataset_id, e)
            return None

        j = resp.json()
        tables = j.get("tables") or []
        columns_raw = tables[0].get("columns") if tables else []
        columns = [
            {"name": c.get("name", ""), "type": c.get("type", "")}
            for c in columns_raw
        ]
        return {
            "id": dataset_id,
            "name": j.get("name", ""),
            "schema": {"columns": columns},
        }

    def _export_dataset_csv_internal(self, dataset_id: str) -> str | None:
        """Use the SQL query endpoint + convert to CSV to match public shape."""
        import csv as _csv
        import io as _io

        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._post(
                f"/api/query/v1/execute/{dataset_id}",
                json={"sql": "SELECT * FROM table"},
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error exporting dataset %s: %s", dataset_id, e)
            return None

        if resp.status_code == 429:
            logger.error("Skipping dataset export %s after rate limit retries", dataset_id)
            return None
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            logger.error("Failed to export dataset %s: %s — %s", dataset_id, e, resp.text[:200])
            return None

        j = resp.json()
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(j.get("columns", []))
        for row in j.get("rows", []):
            writer.writerow(["" if v is None else v for v in row])
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Public methods — route to internal or public based on auth mode
    # ------------------------------------------------------------------
    def list_datasets(self) -> list[dict[str, Any]]:
        """Fetch all datasets (paginated)."""
        logger.info("Fetching dataset list...")
        if self.access_token:
            return self._list_datasets_internal()
        return self._paginate("/v1/datasets", sort="name")

    def get_dataset_detail(self, dataset_id: str) -> dict[str, Any] | None:
        """Fetch full dataset detail including schema. Returns None on failure."""
        if self.access_token:
            return self._get_dataset_detail_internal(dataset_id)

        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._get(f"/v1/datasets/{dataset_id}", params={"fields": "all"})
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error getting dataset %s after retries: %s", dataset_id, e)
            return None

        if resp.status_code == 429:
            logger.error("Skipping dataset %s after rate limit retries exhausted", dataset_id)
            return None

        try:
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logger.error("Failed to get dataset %s: %s", dataset_id, e)
            return None

    def export_dataset_csv(self, dataset_id: str) -> str | None:
        """Export full dataset data as CSV text. Returns None on failure."""
        if self.access_token:
            return self._export_dataset_csv_internal(dataset_id)

        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._get(
                f"/v1/datasets/{dataset_id}/data",
                params={"includeHeader": "true"},
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error exporting dataset %s after retries: %s", dataset_id, e)
            return None

        if resp.status_code == 429:
            logger.error("Skipping dataset export %s after rate limit retries exhausted", dataset_id)
            return None

        try:
            resp.raise_for_status()
            return resp.text
        except requests.HTTPError as e:
            logger.error("Failed to export dataset %s: %s", dataset_id, e)
            return None

    # ── Write Operations ──────────────────────────────────────────────

    def update_dataset(self, dataset_id: str, **fields) -> dict[str, Any] | None:
        """Update dataset metadata (name, description, owner, etc.).

        Accepts keyword arguments that map to the Domo dataset object fields:
            name, description, owner (dict with id key), etc.

        Returns the updated dataset object, or None on failure.
        """
        time.sleep(RATE_LIMIT_DELAY)
        body = {k: v for k, v in fields.items() if v is not None}
        if not body:
            logger.warning("update_dataset called with no fields for %s", dataset_id)
            return None

        try:
            resp = self._put(f"/v1/datasets/{dataset_id}", json=body)
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error updating dataset %s: %s", dataset_id, e)
            return None

        if resp.status_code == 429:
            logger.error("Rate limited updating dataset %s", dataset_id)
            return None

        try:
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logger.error("Failed to update dataset %s: %s — %s", dataset_id, e, resp.text)
            return None

    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset. Returns True on success."""
        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._delete(f"/v1/datasets/{dataset_id}")
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error deleting dataset %s: %s", dataset_id, e)
            return False

        if resp.status_code == 204:
            return True

        if resp.status_code == 429:
            logger.error("Rate limited deleting dataset %s", dataset_id)
            return False

        try:
            resp.raise_for_status()
            return True
        except requests.HTTPError as e:
            logger.error("Failed to delete dataset %s: %s — %s", dataset_id, e, resp.text)
            return False

    def create_dataset(self, name: str, description: str, schema_columns: list[dict]) -> dict[str, Any] | None:
        """Create a new dataset with the given schema.

        schema_columns: list of dicts with 'name' and 'type' keys.
            type values: STRING, LONG, DOUBLE, DECIMAL, DATE, DATETIME

        Returns the created dataset object (including dataset_id), or None.
        """
        body = {
            "name": name,
            "description": description,
            "schema": {
                "columns": schema_columns,
            },
        }

        try:
            resp = self._post("/v1/datasets", json=body)
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error creating dataset: %s", e)
            return None

        try:
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            logger.error("Failed to create dataset: %s — %s", e, resp.text)
            return None

    def upload_dataset_data(self, dataset_id: str, csv_content: str) -> bool:
        """Upload CSV data to an existing dataset (replaces all data).

        csv_content: CSV string with header row.
        Returns True on success.
        """
        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = self._put(
                f"/v1/datasets/{dataset_id}/data",
                data=csv_content.encode("utf-8"),
                headers={"Content-Type": "text/csv"},
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.error("Network error uploading data to %s: %s", dataset_id, e)
            return False

        if resp.status_code in (200, 204):
            return True

        try:
            resp.raise_for_status()
            return True
        except requests.HTTPError as e:
            logger.error("Failed to upload data to %s: %s — %s", dataset_id, e, resp.text)
            return False

    def change_dataset_owner(self, dataset_id: str, new_owner_id: str) -> dict[str, Any] | None:
        """Change the owner of a dataset. Returns the updated dataset or None."""
        return self.update_dataset(dataset_id, owner={"id": new_owner_id})
