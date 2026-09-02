#!/usr/bin/env python3
"""Confirm the service account can read the availability Sheet.

    GOOGLE_SERVICE_ACCOUNT_JSON=key.json SHEET_ID=… python scripts/setup_check.py

Run this once after creating the service account and sharing the Sheet with its
email. Photos come from the *public* Drive folders (fetch_photos.py), so the
service account only needs read access to the Sheet — nothing in Drive.
"""

import json
import os
import sys
from pathlib import Path


def main():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Install deps first:  pip install -r requirements.txt")

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.environ.get("SHEET_ID")
    if not raw or not sheet_id:
        sys.exit("Set GOOGLE_SERVICE_ACCOUNT_JSON and SHEET_ID first.")

    info = json.loads(Path(raw).read_text(encoding="utf-8")) if Path(raw).exists() else json.loads(raw)
    print(f"Service account: {info.get('client_email')}")
    print("  → share the Sheet with this address (Viewer) if you haven't.\n")

    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    try:
        meta = sheets.spreadsheets().get(
            spreadsheetId=sheet_id, fields="properties(title),sheets(properties(title))"
        ).execute()
    except Exception as error:
        print(f"✗ Cannot read the Sheet: {error}")
        print("  Share it with the service-account email above (Viewer), then retry.")
        return

    print(f"✓ Sheet reachable: “{meta['properties']['title']}”")
    for s in meta["sheets"]:
        print(f"    tab: {s['properties']['title']}")
    print("\nAll good — schedule scripts/sync_from_google.py (.github/workflows/sync.yml).")


if __name__ == "__main__":
    main()
