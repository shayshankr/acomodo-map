#!/usr/bin/env python3
"""Download each property's photos from its (public) Google Drive folder and
store optimised copies in public/photos/ so the site serves them from its own
CDN instead of hot-linking Drive.

    python scripts/fetch_photos.py
    python scripts/fetch_photos.py --limit 12   # max images per property

No credentials needed: the folders are shared "anyone with link", so Google's
embeddedfolderview endpoint lists them and the thumbnail endpoint resizes each
image server-side. Reads data/media-links.json (property -> folder URL) and
writes data/media-cache.json plus public/photos/<slug>/*.jpg.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / "data" / "media-links.json"
CACHE = ROOT / "data" / "media-cache.json"
PHOTO_DIR = ROOT / "public" / "photos"

UA = {"User-Agent": "Mozilla/5.0 (compatible; acomodo-map/1.0)"}
EFV = "https://drive.google.com/embeddedfolderview?id={}#list"
THUMB = "https://drive.google.com/thumbnail?id={}&sz=w{}"

FULL_W, THUMB_W = 1600, 480
MAX_DEPTH = 3
# Prefer a spread of these when a folder has more photos than the cap.
PRIORITY = ["exterior", "front", "outside", "kitchen", "living", "dining", "recept",
            "common", "lounge", "garden", "backyard", "bath", "washroom", "ensuite",
            "bedroom", "double", "single", "room"]

ENTRY_RE = re.compile(r'<div class="flip-entry"[^>]*id="entry-([^"]+)".*?</a>', re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
ALT_RE = re.compile(r'alt="([^"]*)"')
TITLE_RE = re.compile(r'flip-entry-title[^>]*>([^<]*)')


def clean(value):
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-"))


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            with urlopen(Request(url, headers=UA), timeout=45) as resp:
                return resp.read()
        except Exception as error:
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return b""


def folder_id(url):
    return url.split("/folders/")[-1].split("?")[0].split("/")[0]


def enumerate_folder(fid, depth=0):
    """Return [{id, name}] of images in this folder and its subfolders."""
    if depth > MAX_DEPTH:
        return []
    try:
        html = fetch(EFV.format(fid)).decode("utf-8", "replace")
    except Exception as error:
        print(f"    ! list failed ({error})")
        return []

    images, subfolders = [], []
    for m in re.finditer(r'(<div class="flip-entry"[^>]*id="entry-([^"]+)".*?</a>)', html, re.S):
        block, eid = m.group(1), m.group(2)
        href = HREF_RE.search(block)
        alt = ALT_RE.search(block)
        title = TITLE_RE.search(block)
        name = clean(title.group(1)) if title else ""
        is_folder = href and "/folders/" in href.group(1)
        alt_text = (alt.group(1) if alt else "").lower()
        if is_folder:
            subfolders.append(eid)
        elif "image" in alt_text:
            images.append({"id": eid, "name": re.sub(r"\.(jpe?g|png|webp|heic)$", "", name, flags=re.I)})
        # videos and other types are skipped
    for sub in subfolders:
        images.extend(enumerate_folder(sub, depth + 1))
    return images


def curate(images, limit):
    seen, unique = set(), []
    for img in images:
        if img["id"] in seen:
            continue
        seen.add(img["id"])
        unique.append(img)
    if len(unique) <= limit:
        return unique

    def rank(img):
        name = img["name"].lower()
        for i, word in enumerate(PRIORITY):
            if word in name:
                return i
        return len(PRIORITY)

    return sorted(unique, key=rank)[:limit]


def download_image(fid, width, dest):
    data = fetch(THUMB.format(fid, width))
    if len(data) < 1200:  # a broken/placeholder response, not a real photo
        raise ValueError(f"tiny response ({len(data)} bytes)")
    dest.write_bytes(data)
    return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12, help="max images per property")
    args = parser.parse_args()

    links = json.loads(LINKS.read_text(encoding="utf-8"))
    links = {k: v for k, v in links.items() if not k.startswith("_")}

    props = {}
    total_files = 0
    for name, url in links.items():
        slug = slugify(name)[:60] or folder_id(url)
        print(f"\n{name[:52]}")
        images = curate(enumerate_folder(folder_id(url)), args.limit)
        if not images:
            print("  (no images found)")
            props[name] = {"folder": url, "images": []}
            continue

        dest_dir = PHOTO_DIR / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        # clear stale files so removals in Drive don't linger
        for old in dest_dir.glob("*.jpg"):
            old.unlink()

        saved = []
        for i, img in enumerate(images, 1):
            full = dest_dir / f"{i:02d}.jpg"
            thumb = dest_dir / f"{i:02d}_t.jpg"
            try:
                fb = download_image(img["id"], FULL_W, full)
                tb = download_image(img["id"], THUMB_W, thumb)
            except Exception as error:
                print(f"  ! {img['name'][:30]}: {error}")
                continue
            saved.append({
                "full": f"photos/{slug}/{full.name}",
                "thumb": f"photos/{slug}/{thumb.name}",
                "name": img["name"],
            })
            total_files += 2
            time.sleep(0.25)  # be gentle with Drive
        print(f"  {len(saved)} photos")
        props[name] = {"folder": url, "images": saved}

    CACHE.write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "fetch_photos.py (public Drive folders)",
        "properties": props,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    withimg = sum(1 for p in props.values() if p["images"])
    print(f"\nWrote {CACHE.relative_to(ROOT)} and {total_files} image files "
          f"({withimg}/{len(props)} properties have photos).")


if __name__ == "__main__":
    main()
