#!/usr/bin/env python3
"""Quick-and-dirty validator for Domo credentials in .env.

Usage::

    python3 test_token.py          # smoke test: auth + 1 API call
    python3 test_token.py --full   # additionally list first 5 datasets

Exits non-zero on any failure so it can gate CI / pre-commit steps.
"""
from __future__ import annotations

import argparse
import sys

import requests
from dotenv import load_dotenv

from domo_client import DomoAuthError, DomoClient

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Domo credentials.")
    parser.add_argument("--full", action="store_true", help="Also list datasets")
    args = parser.parse_args()

    try:
        client = DomoClient.from_env()
    except DomoAuthError as exc:
        print(f"FAIL (config): {exc}")
        return 1

    mode = "developer token" if client.access_token else "OAuth2 client_credentials"
    print(f"Auth mode:  {mode}")
    print(f"Base URL:   {client.base_url}")

    try:
        client.authenticate()
    except Exception as exc:  # network / auth
        print(f"FAIL (authenticate): {exc}")
        return 1
    print("Authenticate: OK")

    # Minimal probe — list datasets page 0. Works for both auth modes against
    # the public `/v1/datasets` endpoint; developer tokens hit the same path
    # on the instance domain.
    try:
        resp = client._get("/v1/datasets", params={"limit": 1, "offset": 0})
    except requests.RequestException as exc:
        print(f"FAIL (probe network): {exc}")
        return 1

    if resp.status_code == 200:
        print(f"Probe /v1/datasets: OK (HTTP {resp.status_code})")
    else:
        print(f"FAIL (probe): HTTP {resp.status_code} — {resp.text[:200]}")
        return 1

    if args.full:
        datasets = client.list_datasets()
        print(f"Total datasets visible: {len(datasets):,}")
        for d in datasets[:5]:
            print(f"  - {d.get('name') or d.get('id')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
