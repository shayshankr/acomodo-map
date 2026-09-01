#!/usr/bin/env python3
"""Pull the Drive folder links out of the sheet's XLSX export.

    python scripts/extract_media.py

Google Sheets stores the "Media Link" cells as cell hyperlinks whose *display
text* is just "Media Link" — a CSV export throws the URL away, so we read the
XLSX (data/portfolio.xlsx), where openpyxl hands us cell.hyperlink.target.
Writes data/media-links.json:

    { "<Property Name cell>": "https://drive.google.com/drive/folders/…" }

keyed by the Property Name exactly as it appears in column A, so build_data.py
can attach it and scripts/list_media.py knows which folders to open.
"""

import json
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("This step needs openpyxl:  pip install openpyxl  (or pip install -r requirements.txt)")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "data" / "portfolio.xlsx"
OUT = ROOT / "data" / "media-links.json"


def main():
    if not XLSX.exists():
        sys.exit(
            f"Missing {XLSX}. Export the sheet as .xlsx (File → Download → "
            "Microsoft Excel) and save it there — CSV drops the hyperlinks."
        )

    workbook = openpyxl.load_workbook(XLSX, data_only=True)
    links = {}

    for sheet in workbook.worksheets:
        current_name = None
        for row in sheet.iter_rows():
            first = row[0]
            if first.value and str(first.value).strip():
                current_name = str(first.value).strip()
            if current_name is None:
                continue
            # Any hyperlinked cell on this property's rows that points at Drive
            # is its media folder; the first one wins.
            for cell in row:
                link = cell.hyperlink
                target = link.target if link else None
                if target and "drive.google" in target and current_name not in links:
                    links[current_name] = target

    OUT.write_text(
        json.dumps(links, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(links)} properties have a media folder")
    for name, url in list(links.items())[:8]:
        folder = url.split("/folders/")[-1].split("?")[0]
        print(f"  {name[:46]:46} {folder}")


if __name__ == "__main__":
    main()
