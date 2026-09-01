#!/usr/bin/env python3
"""Confirm the service account can actually read the Sheet and photo folders.

    python scripts/setup_check.py

Run this once after creating the service account and sharing the Sheet + Drive
folders with its email. It reads nothing destructive — it just reports what the
account can see, so you can fix sharing before scheduling the sync.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    print("  → share the Sheet and every photo folder with this address (Viewer).\n")

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    try:
        meta = sheets.spreadsheets().get(spreadsheetId=sheet_id, fields="properties(title),sheets(properties(title))").execute()
        print(f"✓ Sheet reachable: “{meta['properties']['title']}”")
        for s in meta["sheets"]:
            print(f"    tab: {s['properties']['title']}")
    except Exception as error:
        print(f"✗ Cannot read the Sheet: {error}")
        print("  Share it with the service-account email above.")
        return

    links_path = ROOT / "data" / "media-links.json"
    if links_path.exists():
        links = json.loads(links_path.read_text(encoding="utf-8"))
        ok = 0
        print(f"\nChecking {len(links)} photo folders…")
        for name, url in list(links.items())[:5]:
            fid = url.split("/folders/")[-1].split("?")[0].split("/")[0]
            try:
                drive.files().get(fileId=fid, fields="id,name", supportsAllDrives=True).execute()
                ok += 1
            except Exception:
                print(f"    ✗ not shared: {name[:44]}")
        print(f"  {ok}/{min(5, len(links))} sampled folders reachable "
              f"({'share the rest with the account too' if ok < min(5, len(links)) else 'looks good'}).")
    print("\nIf all green, schedule scripts/sync_from_google.py (see .github/workflows/sync.yml).")


if __name__ == "__main__":
    main()
