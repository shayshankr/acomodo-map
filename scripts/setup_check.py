#!/usr/bin/env python3
"""Confirm the Google Sheet is publicly readable (what the sync needs).

    python scripts/setup_check.py
    SHEET_ID=… python scripts/setup_check.py

The availability sync uses no credentials — it just reads the Sheet's public
export. This checks that the Sheet is shared "anyone with the link → Viewer"
by fetching that export and confirming a workbook comes back.
"""

import os
import sys
from urllib.request import Request, urlopen

DEFAULT_SHEET_ID = "1nbjTFLmm3rkWBO-RRdsSrm5_ZvOv4aV9Q7VlJvavODM"
URL = "https://docs.google.com/spreadsheets/d/{}/export?format=xlsx"


def main():
    sheet_id = os.environ.get("SHEET_ID", DEFAULT_SHEET_ID)
    url = URL.format(sheet_id)
    print(f"Checking public read access: {url}")
    try:
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as resp:
            head = resp.read(4)
    except Exception as error:
        sys.exit(f"✗ Could not fetch the Sheet: {error}")

    if head[:2] != b"PK":  # a real .xlsx is a zip
        print("✗ The Sheet is not link-readable (got a login/HTML page, not a workbook).")
        print("  In the Sheet: Share → General access → 'Anyone with the link' → Viewer.")
        sys.exit(1)

    print("✓ The Sheet is publicly readable — the sync will work with no credentials.")
    print("  Schedule scripts/sync_from_google.py (.github/workflows/sync.yml).")


if __name__ == "__main__":
    main()
