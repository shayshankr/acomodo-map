#!/usr/bin/env python3
"""Pull everything the site needs straight from Google — no manual exports.

    python scripts/sync_from_google.py

This is the hands-off path chosen for the project: a scheduled job (see
.github/workflows/sync.yml) runs it, and staff just edit the Sheet and drop
photos into the Drive folders. It:

  1. reads the availability Sheet via the Sheets API — both the *formatted*
     values (so "€700" keeps its symbol) and the cell hyperlinks (the Drive
     folder behind each "Media Link") — and writes data/portfolio.csv +
     data/media-links.json;
  2. walks each Drive photo folder via the Drive API and writes a curated
     data/media-cache.json (image ids per property);
  3. runs geocode → universities → build so public/data/*.json is refreshed.

It needs a Google service account with read access to the Sheet and the photo
folders (share them with the service account's email). Configure via env:

    GOOGLE_SERVICE_ACCOUNT_JSON   the service-account key, as JSON (or a path)
    SHEET_ID                      the spreadsheet id
    SHEET_TABS                    optional, comma-separated tab titles to read
                                  (default: the first tab)

Dependencies (CI installs these): google-api-python-client, google-auth.
Run scripts/setup_check.py to verify access before the first sync.
"""

import csv
import json
import os
import re
import runpy
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MAX_GALLERY = 12
# Prefer these words when picking a curated spread from a big folder.
PRIORITY = ["exterior", "front", "kitchen", "living", "dining", "common", "bath", "garden", "bedroom", "room"]
IMAGE_MIME_PREFIX = "image/"
FOLDER_MIME = "application/vnd.google-apps.folder"


def clean(value):
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def credentials():
    from google.oauth2 import service_account

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        sys.exit("Set GOOGLE_SERVICE_ACCOUNT_JSON (the service-account key JSON or a path to it).")
    info = json.loads(Path(raw).read_text(encoding="utf-8")) if Path(raw).exists() else json.loads(raw)
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )


# --- 1. Sheet → CSV + media links --------------------------------------------


def pull_sheet(sheets, sheet_id, tabs):
    """Return (header, rows, media_links) using formatted values + hyperlinks."""
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id,
        includeGridData=True,
        ranges=tabs or None,
        fields="sheets(properties(title),data(rowData(values(formattedValue,hyperlink))))",
    ).execute()

    wanted = {t.strip() for t in tabs} if tabs else None
    header, all_rows, links = None, [], {}

    for sheet in meta.get("sheets", []):
        title = sheet["properties"]["title"]
        if wanted and title not in wanted:
            continue
        grid = sheet.get("data", [{}])[0].get("rowData", [])

        media_col = None
        current_name = None
        for r, row in enumerate(grid):
            cells = row.get("values", [])
            values = [clean(c.get("formattedValue", "")) for c in cells]
            if not any(values):
                all_rows.append([])
                continue
            if header is None:
                header = values
                media_col = next((i for i, h in enumerate(values) if "media" in h.lower()), None)
                continue
            if wanted is None and header and values == header:
                continue  # a repeated header on another tab
            all_rows.append(values)

            if values and values[0]:
                current_name = values[0]
            if media_col is not None and media_col < len(cells):
                link = cells[media_col].get("hyperlink")
                if link and "drive.google" in link and current_name and current_name not in links:
                    links[current_name] = link

    return header, all_rows, links


def write_csv(header, rows):
    path = DATA / "portfolio.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
    print(f"  wrote {path.relative_to(ROOT)} ({sum(1 for r in rows if r)} data rows)")


# --- 2. Drive folders → curated media cache ----------------------------------


def list_children(drive, folder_id):
    items, token = [], None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        items.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def walk_images(drive, folder_id, depth=0, budget=60):
    """Depth-first gather of images, one folder then its subfolders (capped)."""
    if depth > 3 or budget <= 0:
        return []
    images, subfolders = [], []
    for item in list_children(drive, folder_id):
        if item["mimeType"].startswith(IMAGE_MIME_PREFIX):
            images.append({"id": item["id"], "name": Path(item["name"]).stem})
        elif item["mimeType"] == FOLDER_MIME:
            subfolders.append(item["id"])
    for sub in subfolders:
        if len(images) >= budget:
            break
        images.extend(walk_images(drive, sub, depth + 1, budget - len(images)))
    return images


def curate(images):
    """Pick a spread of up to MAX_GALLERY, de-duplicated, priority shots first."""
    seen, unique = set(), []
    for img in images:
        if img["id"] in seen:
            continue
        seen.add(img["id"])
        unique.append(img)

    def rank(img):
        name = img["name"].lower()
        for i, word in enumerate(PRIORITY):
            if word in name:
                return i
        return len(PRIORITY)

    unique.sort(key=rank)
    return unique[:MAX_GALLERY]


def build_media_cache(drive, links):
    props = {}
    for name, url in links.items():
        folder_id = url.split("/folders/")[-1].split("?")[0].split("/")[0]
        try:
            images = curate(walk_images(drive, folder_id))
        except Exception as error:  # keep going; one bad folder shouldn't stop the sync
            print(f"    ! {name[:40]}: {error}")
            images = []
        props[name] = {"folder": url, "images": images}
        print(f"  {name[:44]:44} {len(images)} images")

    from datetime import datetime, timezone

    (DATA / "media-cache.json").write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "sync_from_google.py",
                "properties": props,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  wrote {(DATA / 'media-cache.json').relative_to(ROOT)}")


# --- 3. run the build --------------------------------------------------------


def run_builds():
    for script in ("geocode.py", "universities.py", "build_data.py"):
        print(f"\n=== {script} ===")
        sys.argv = [script]
        runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")


def main():
    from googleapiclient.discovery import build

    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        sys.exit("Set SHEET_ID to the spreadsheet id.")
    tabs = [t for t in os.environ.get("SHEET_TABS", "").split(",") if t.strip()]

    creds = credentials()
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    print("Reading the Sheet…")
    header, rows, links = pull_sheet(sheets, sheet_id, tabs)
    write_csv(header, rows)
    (DATA / "media-links.json").write_text(
        json.dumps(links, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"  {len(links)} properties link a Drive photo folder")

    print("\nWalking the photo folders…")
    build_media_cache(drive, links)

    run_builds()
    print("\nSync complete. Deploy public/.")


if __name__ == "__main__":
    main()
