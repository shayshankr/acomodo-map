#!/usr/bin/env python3
"""Credential-free availability sync — reads the *public* Google Sheet.

    python scripts/sync_from_google.py
    SHEET_ID=… python scripts/sync_from_google.py

The Sheet is shared "anyone with the link → Viewer", so this needs **no login,
service account, or secret** — it just downloads the public workbook. It:

  1. fetches the workbook (public XLSX export) — which carries every tab's
     values *and* the "Media Link" cell hyperlinks;
  2. maps each tab onto the canonical columns build_data.py reads (by header
     name, so the Ireland and London layouts both parse), injecting the £/€
     symbol per city, and writes data/portfolio.csv + data/portfolio-london.csv
     + data/media-links.json;
  3. runs geocode → universities → build to refresh public/data/*.json.

This is the *availability* path — it stays fast so it can run often. Photos are
refreshed separately by .github/workflows/photos.yml (also credential-free);
the media-links.json this writes is what that job reads. For a manual full
refresh including photos, use scripts/refresh.py.

If the Sheet ever stops being link-readable this will fail; re-share it as
"Anyone with the link → Viewer" (read-only) and it works again.
"""

import csv
import os
import re
import runpy
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import openpyxl
except ImportError:
    sys.exit("Needs openpyxl:  pip install -r requirements.txt")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

DEFAULT_SHEET_ID = "1nbjTFLmm3rkWBO-RRdsSrm5_ZvOv4aV9Q7VlJvavODM"
XLSX_URL = "https://docs.google.com/spreadsheets/d/{}/export?format=xlsx"

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
MEDIA_COL = CANON_HEADERS.index("Media Link")


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def resolve_columns(header):
    """Map each canonical column to a source index in this tab's header."""
    normed = [norm(h) for h in header]
    used, resolved = set(), []
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


def tidy(value):
    """openpyxl hands back bare numbers / datetimes; render them like the sheet."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%-d %b %Y") if sys.platform != "win32" else value.strftime("%#d %b %Y")
    text = str(value)
    if re.fullmatch(r"-?\d+\.0", text):  # "1.0" -> "1"
        text = text[:-2]
    return text


def money_fix(value, currency):
    v = tidy(value)
    if v and not v.startswith(("€", "£")) and re.fullmatch(r"[\d,]+(\.\d+)?", v):
        return f"{currency}{v.split('.')[0]}"
    return v


def download_xlsx(sheet_id):
    url = XLSX_URL.format(sheet_id)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (acomodo-map sync)"})
    with urlopen(req, timeout=60) as resp:
        data = resp.read()
    if data[:2] != b"PK":  # a real .xlsx is a zip; HTML means "not public"
        sys.exit(
            "The Sheet did not return a workbook — it is probably not link-readable.\n"
            "Share it as 'Anyone with the link → Viewer' (read-only) and retry."
        )
    (DATA / "portfolio.xlsx").write_bytes(data)
    return DATA / "portfolio.xlsx"


def pull_tab(ws):
    """One worksheet -> (canonical rows, media links, is_london)."""
    rows = list(ws.iter_rows())
    header_idx = next(
        (i for i, r in enumerate(rows) if any(str(c.value).strip() for c in r if c.value is not None)),
        None,
    )
    if header_idx is None:
        return [], {}, False
    header = [tidy(c.value) for c in rows[header_idx]]
    cols = resolve_columns(header)
    is_london = "london" in ws.title.lower()

    out_rows, links, current_name = [], {}, None
    for r in rows[header_idx + 1:]:
        cells = list(r)
        vals = [c.value for c in cells]
        if not any(str(v).strip() for v in vals if v is not None):
            out_rows.append([])
            current_name = None
            continue
        line = []
        for ci, src in enumerate(cols):
            raw = cells[src].value if src is not None and src < len(cells) else None
            line.append(money_fix(raw, "£" if is_london else "€") if ci == RENT_COL else tidy(raw))
        out_rows.append(line)

        if line[NAME_COL]:
            current_name = line[NAME_COL]
        # Any hyperlinked cell on this property's rows pointing at Drive is its folder.
        if current_name and current_name not in links:
            for cell in cells:
                link = cell.hyperlink.target if cell.hyperlink else None
                if link and "drive.google" in link:
                    links[current_name] = link
                    break
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
    sheet_id = os.environ.get("SHEET_ID", DEFAULT_SHEET_ID)
    print(f"Downloading the public workbook ({sheet_id})…")
    xlsx = download_xlsx(sheet_id)

    import json

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ireland, london, links = [], [], {}
    for ws in wb.worksheets:
        rows, tab_links, is_london = pull_tab(ws)
        (london if is_london else ireland).extend(rows + [[]])
        links.update(tab_links)
        print(f"  tab '{ws.title}': {sum(1 for r in rows if r)} rows{' (London)' if is_london else ''}")

    write_csv(DATA / "portfolio.csv", ireland)
    if london:
        write_csv(DATA / "portfolio-london.csv", london)
    (DATA / "media-links.json").write_text(
        json.dumps(links, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"  {len(links)} properties link a Drive photo folder")

    run("geocode.py")        # only hits the network for addresses not yet cached
    run("universities.py")   # cached campuses; a no-op once built
    run("build_data.py")
    print("\nSync complete. Deploy public/. (Photos refresh via photos.yml.)")


if __name__ == "__main__":
    main()
