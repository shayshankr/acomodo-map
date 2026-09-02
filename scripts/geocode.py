#!/usr/bin/env python3
"""Fill data/geocode-cache.json with coordinates for every address in the sheet.

    python scripts/geocode.py            # only look up addresses that are missing
    python scripts/geocode.py --recheck  # re-run low-confidence hits too

Uses OpenStreetMap's Nominatim: free, no key, but rate limited to one request a
second and it asks for a real contact address in the User-Agent. Results land in
data/geocode-cache.json, which is a plain hand-editable file — if a pin sits in
the wrong street, fix the numbers there and they stick.
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "portfolio.csv"
GEO_PATH = ROOT / "data" / "geocode-cache.json"
HINT_PATH = ROOT / "data" / "address-hints.json"

CONTACT = "acomodo-map/1.0 (bookings@acomodo.in)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"
EIRCODE_RE = re.compile(r"\b([A-Z]\d{2})\s?([A-Z0-9]{4})\b", re.I)

# Rough centres, used to sanity-check and to fall back on.
CITY_ANCHORS = {
    "dublin": (53.3498, -6.2603, "Dublin, Ireland"),
    "limerick": (52.6638, -8.6267, "Limerick, Ireland"),
    "london": (51.5074, -0.1278, "London, United Kingdom"),
}


def clean(value):
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def query(params):
    url = f"{ENDPOINT}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": CONTACT, "Accept-Language": "en"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


UNIT_PREFIX_RE = re.compile(r"^(apartment|apt|flat|unit|no\.?)\s*\d*[a-z]?\s*[-,]?\s*", re.I)


def strip_noise(address):
    """Drop the bits that confuse a gazetteer: unit numbers, parentheticals, eircodes."""
    text = re.sub(r"\([^)]*\)", " ", address)          # "(Flat 1)"
    text = EIRCODE_RE.sub(" ", text)                    # "D08 EY83"
    text = text.replace("/", ",")                       # "City Centre / O'Curry Street"
    chunks = []
    for chunk in text.split(","):
        chunk = UNIT_PREFIX_RE.sub("", chunk.strip(" -")).strip(" -")
        chunk = re.sub(r"\s+", " ", chunk)
        if chunk and not chunk.isdigit():
            chunks.append(chunk.title() if chunk.isupper() else chunk)
    return chunks


UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)


def lookup(address, city, hint=None):
    """Try the most specific form first, then widen. Returns dict or None."""
    country = "gb" if city.lower() == "london" else "ie"
    eircode = EIRCODE_RE.search(address)
    uk_pc = UK_POSTCODE_RE.search(address)

    attempts = []
    if hint:
        attempts.append((hint, "hint"))
    if eircode:
        attempts.append(
            (f"{eircode.group(1).upper()} {eircode.group(2).upper()}", "eircode")
        )
    # A full UK postcode pins a London address far better than its (often
    # duplicated) street name, so try it before the street forms.
    if uk_pc:
        attempts.append((f"{uk_pc.group(1).upper()} {uk_pc.group(2).upper()}, {city}", "postcode"))
    chunks = strip_noise(address) or [address]
    attempts.append((f"{', '.join(chunks)}, {city}", "address"))
    # Peel off the leading house name/number: the street alone is often what OSM knows.
    for start in range(1, len(chunks)):
        attempts.append((f"{', '.join(chunks[start:])}, {city}", "area"))
    attempts.append((f"{chunks[0]}, {city}", "street"))

    for text, precision in attempts:
        try:
            results = query(
                {"q": text, "format": "json", "limit": 1, "countrycodes": country}
            )
        except Exception as error:  # network hiccup: skip, try the next form
            print(f"    ! {precision}: {error}")
            results = []
        time.sleep(1.1)  # Nominatim's published rate limit
        if results:
            hit = results[0]
            return {
                "lat": round(float(hit["lat"]), 6),
                "lng": round(float(hit["lon"]), 6),
                "precision": precision,
                "matched": hit.get("display_name", "")[:160],
                "query": text,
            }
    return None


def addresses_from_csv():
    seen = {}
    for path in (CSV_PATH, CSV_PATH.parent / "portfolio-london.csv"):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        key = None
        city = ""
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                key = None
                continue
            if clean(row[0]):
                key = clean(row[0])
            if len(row) > 1 and clean(row[1]):
                city = clean(row[1])
            if key and key not in seen:
                seen[key] = city or "Dublin"
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recheck", action="store_true", help="redo area/street-level hits")
    args = parser.parse_args()

    cache = json.loads(GEO_PATH.read_text(encoding="utf-8")) if GEO_PATH.exists() else {}
    hints = json.loads(HINT_PATH.read_text(encoding="utf-8")) if HINT_PATH.exists() else {}
    hints = {k: v for k, v in hints.items() if not k.startswith("_")}
    targets = addresses_from_csv()
    print(f"{len(targets)} distinct addresses in {CSV_PATH.name}, {len(cache)} already cached")

    weak = {"area", "street", "city"}
    if args.recheck:
        print("rechecking weak hits: " + ", ".join(sorted(weak)))
    for address, city in targets.items():
        cached = cache.get(address)
        if cached and not (args.recheck and cached.get("precision") in weak):
            continue
        print(f"  → {address[:70]}")
        result = lookup(address, city, hints.get(address))
        if result is None:
            lat, lng, label = CITY_ANCHORS.get(city.lower(), CITY_ANCHORS["dublin"])
            result = {"lat": lat, "lng": lng, "precision": "city", "matched": label, "query": city}
            print(f"    fell back to the {city} city centre — set this one by hand")
        else:
            print(f"    {result['precision']}: {result['lat']}, {result['lng']}")
        cache[address] = result

    GEO_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    by_precision = {}
    for entry in cache.values():
        by_precision[entry["precision"]] = by_precision.get(entry["precision"], 0) + 1
    print(f"\nWrote {GEO_PATH.relative_to(ROOT)}: {by_precision}")
    vague = [a for a, e in cache.items() if e["precision"] in {"city"}]
    if vague:
        print("Only city-level — worth fixing by hand:")
        for address in vague:
            print(f"  - {address}")


if __name__ == "__main__":
    main()
