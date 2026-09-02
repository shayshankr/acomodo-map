#!/usr/bin/env python3
"""Pull availability straight from the Google Sheet — no manual exports.

    python scripts/sync_from_google.py

The hands-off availability path: a scheduled job (.github/workflows/sync.yml)
runs it and staff just edit the Sheet. It:

  1. reads every tab of the Sheet via the Sheets API — both the *formatted*
     values (so "€700"/"£550" keep their symbol) and the cell hyperlinks (the
     Drive folder behind each "Media Link");
  2. maps each tab onto the canonical columns build_data.py reads (by header
     name, so the Ireland and London layouts both work), writing
     data/portfolio.csv (Ireland/Limerick) + data/portfolio-london.csv (London)
     + data/media-links.json;
  3. runs fetch_photos → geocode → universities → build to refresh
     public/data/*.json. Photos come from the *public* folders via
     fetch_photos.py, so the service account only needs the Sheet.

Configure via env:
    GOOGLE_SERVICE_ACCOUNT_JSON   the service-account key, as JSON (or a path)
    SHEET_ID                      the spreadsheet id
    SHEET_TABS                    optional, comma-separated tab titles (default: all)

Deps (CI installs them): google-api-python-client, google-auth. Share the Sheet
with the service account's email (Viewer). scripts/setup_check.py verifies access.
"""

import csv
import json
import os
import re
import runpy
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Canonical column -> ordered candidate header names (matched against each tab's
# own header, most specific first). None-producing columns are left blank.
CANONICAL = [
    ("Property Name", ["property name", "property address", "property"]),
    ("City", ["city"]),
    ("Floor", ["floor"]),
    ("Room #", ["room #", "room#", "room no", "room number"]),
    ("Room Type", ["room type"]),
    ("Bedspaces", ["bedspaces", "bed spaces"]),
    ("# of washroom", ["# of washroom", "washrooms", "washroom", "bathroom"]),
    ("Monthly Rent\n(Per Bedspace)", ["monthly rent"]),
    ("Monthly rent (For entire Unit)", ["for entire unit", "entire unit"]),
    ("Tenant \nDemography", ["demography", "tenant"]),
    ("Bed 1", ["bed 1"]),
    ("Bed 2", ["bed 2"]),
    ("Bed 3", ["bed 3"]),
    ("Bed 4", ["bed 4"]),
    ("Furnished", ["furnished"]),
    ("Utilities", ["utility", "utilities"]),
    ("Move in Date", ["move in", "move-in"]),
    ("Payment terms", ["payment terms", "payment"]),
    ("Available Tenancies", ["available tenancies", "tenanc"]),
    ("Media Link", ["media"]),
    ("Key Features", ["key features", "feature"]),
]
CANON_HEADERS = [c[0] for c in CANONICAL]
RENT_COL = CANON_HEADERS.index("Monthly Rent\n(Per Bedspace)")
NAME_COL = 0
CITY_COL = 1
MEDIA_COL = CANON_HEADERS.index("Media Link")


def clean(value):
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def credentials():
    from google.oauth2 import service_account

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        sys.exit("Set GOOGLE_SERVICE_ACCOUNT_JSON (the service-account key JSON or a path to it).")
    info = json.loads(Path(raw).read_text(encoding="utf-8")) if Path(raw).exists() else json.loads(raw)
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )


def resolve_columns(header):
    """Map each canonical column to a source index in this tab's header."""
    normed = [norm(h) for h in header]
    used = set()
    resolved = []
    for _, candidates in CANONICAL:
        idx = None
        for cand in candidates:  # exact match first
            for i, h in enumerate(normed):
                if i not in used and h == cand:
                    idx = i
                    break
            if idx is not None:
                break
        if idx is None:
            for cand in candidates:  # then substring
                for i, h in enumerate(normed):
                    if i not in used and cand in h:
                        idx = i
                        break
                if idx is not None:
                    break
        if idx is not None:
            used.add(idx)
        resolved.append(idx)
    return resolved


def money_fix(value, currency):
    """The API usually formats rent as "€700"; if a tab stores a bare number,
    add the right symbol so build_data can parse it."""
    v = clean(value)
    if v and not v.startswith(("€", "£")) and re.fullmatch(r"[\d,]+(\.\d+)?", v):
        return f"{currency}{v.split('.')[0]}"
    return v


def pull_tab(sheet):
    """One tab -> (canonical_rows, media_links, is_london)."""
    grid = sheet.get("data", [{}])[0].get("rowData", [])
    rows = [r.get("values", []) for r in grid]
    # first non-empty row is the header
    header_idx = next((i for i, r in enumerate(rows) if any(clean(c.get("formattedValue")) for c in r)), None)
    if header_idx is None:
        return [], {}, False
    header = [clean(c.get("formattedValue")) for c in rows[header_idx]]
    cols = resolve_columns(header)
    title = sheet["properties"]["title"].lower()
    is_london = "london" in title

    out_rows, links, current_name = [], {}, None
    for r in rows[header_idx + 1:]:
        cells = r.get("values", [])
        vals = [clean(c.get("formattedValue")) for c in cells]
        if not any(vals):
            out_rows.append([])
            current_name = None
            continue
        line = []
        for ci, src in enumerate(cols):
            val = clean(cells[src].get("formattedValue")) if src is not None and src < len(cells) else ""
            if ci == RENT_COL:
                val = money_fix(val, "£" if is_london else "€")
            line.append(val)
        out_rows.append(line)

        if line[NAME_COL]:
            current_name = line[NAME_COL]
        media_src = cols[MEDIA_COL]
        if current_name and media_src is not None and media_src < len(cells):
            link = cells[media_src].get("hyperlink")
            if link and "drive.google" in link and current_name not in links:
                links[current_name] = link
    return out_rows, links, is_london


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CANON_HEADERS)
        writer.writerows(rows)
    print(f"  wrote {path.relative_to(ROOT)} ({sum(1 for r in rows if r)} data rows)")


def run(script, *argv):
    print(f"\n=== {script} ===")
    sys.argv = [script, *argv]
    runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")


def main():
    from googleapiclient.discovery import build

    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        sys.exit("Set SHEET_ID to the spreadsheet id.")
    wanted = {t.strip() for t in os.environ.get("SHEET_TABS", "").split(",") if t.strip()}

    creds = credentials()
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    print("Reading the Sheet…")
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id,
        includeGridData=True,
        fields="sheets(properties(title),data(rowData(values(formattedValue,hyperlink))))",
    ).execute()

    ireland_rows, london_rows, links = [], [], {}
    for sheet in meta.get("sheets", []):
        title = sheet["properties"]["title"]
        if wanted and title not in wanted:
            continue
        rows, tab_links, is_london = pull_tab(sheet)
        (london_rows if is_london else ireland_rows).extend(rows + [[]])
        links.update(tab_links)
        print(f"  tab '{title}': {sum(1 for r in rows if r)} rows{' (London)' if is_london else ''}")

    write_csv(DATA / "portfolio.csv", ireland_rows)
    if london_rows:
        write_csv(DATA / "portfolio-london.csv", london_rows)
    (DATA / "media-links.json").write_text(
        json.dumps(links, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"  {len(links)} properties link a Drive photo folder")

    # Photos come from the public folders (no credentials); then build.
    run("fetch_photos.py", "--limit", "12")
    run("geocode.py")
    run("universities.py")
    run("build_data.py")
    print("\nSync complete. Deploy public/.")


if __name__ == "__main__":
    main()
