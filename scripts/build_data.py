#!/usr/bin/env python3
"""Turn the portfolio spreadsheet export into the JSON the map site reads.

    python scripts/build_data.py

Reads   data/portfolio.csv        (CSV export of the Google Sheet)
        data/geocode-cache.json   (address -> lat/lng, hand-editable)
        data/overrides.json       (per-property media links / manual fixes)
Writes  public/data/properties.json

Nothing here talks to the network. Run scripts/geocode.py first when new
addresses show up; it is the only script that does.
"""

import csv
import json
import math
import re
import sys
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "portfolio.csv"
GEO_PATH = ROOT / "data" / "geocode-cache.json"
OVERRIDE_PATH = ROOT / "data" / "overrides.json"
MEDIA_PATH = ROOT / "data" / "media-cache.json"
MEDIA_LINKS_PATH = ROOT / "data" / "media-links.json"
OUT_PATH = ROOT / "public" / "data" / "properties.json"

# Irish routing keys are a letter then two alphanumerics: D01, D6W, V94, K78.
EIRCODE_RE = re.compile(r"\b([A-Z]\d[\dW])\s?([A-Z0-9]{4})\b", re.I)
# The sheet also carries invented eircode-ish suffixes (K78C5T10) on sibling units.
PSEUDO_EIRCODE_RE = re.compile(r"\b[A-Z]\d[\dW][A-Z0-9]{3,6}\b", re.I)
MONEY_RE = re.compile(r"([€£])\s?([\d,]+)")

# Bed-cell vocabulary used in the sheet.
BOOKED = "booked"
AVAILABLE = "available"
ON_HOLD = "onHold"

# Curated gallery cap — keep detail panels quick and the JSON small.
MAX_GALLERY = 12


def clean(value):
    """Collapse the sheet's stray newlines and non-breaking spaces."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def classify_bed(cell):
    """Map one Bed 1..4 cell to a status, or None when the slot doesn't exist."""
    value = clean(cell).lower()
    if not value or value == "na":
        return None
    if "hold" in value:
        return ON_HOLD
    if value.startswith("available"):
        return AVAILABLE
    if value.startswith("booked"):
        return BOOKED
    return BOOKED  # unknown wording: assume taken rather than advertise it


def parse_money(cell):
    match = MONEY_RE.search(clean(cell))
    if not match:
        return None, None
    return match.group(1), int(match.group(2).replace(",", ""))


def normalise_room_type(raw):
    text = clean(raw).lower()
    if not text:
        return "Room"
    text = text.replace("non-ensuite", "non ensuite")
    ensuite = "ensuite" in text and "non ensuite" not in text
    for size in ("quad", "triple", "double", "single", "shared apartment"):
        if size in text:
            base = size.title()
            break
    else:
        return clean(raw).title()
    if base == "Shared Apartment":
        return "Shared apartment"
    if "bunk" in text:
        base += " bunk"
    return f"{base} ensuite" if ensuite else f"{base} non-ensuite"


def normalise_utilities(raw):
    text = clean(raw).lower()
    if not text:
        return ""
    if "all-inclusive" in text or "all inclusive" in text:
        return "Bills included"
    if "actual" in text:
        return "Bills excluded — charged on actuals"
    if "50" in text:
        return "Bills excluded — +€50/bed for all-inclusive"
    return clean(raw)


def split_name(raw):
    """The sheet packs name, area and eircode into one cell. Tease them apart."""
    full = clean(raw)
    note = ""
    upper_tail = re.search(r"\s(SELF-CONTAINED[^,]*)$", full)
    if upper_tail:
        note = upper_tail.group(1).strip()
        full = full[: upper_tail.start()].strip()

    eircode = ""
    match = EIRCODE_RE.search(full)
    if match:
        eircode = f"{match.group(1).upper()} {match.group(2).upper()}"

    parts = [p.strip(" -,") for p in full.split(",") if p.strip(" -,")]
    name = parts[0] if parts else full
    rest = parts[1:]

    # "Apartment 603, Windmill House, Dock Road" reads better as the building name.
    unit = re.match(r"^(?:apartment|apt|flat|unit)\s*(\S+)$", name, re.I)
    if unit and rest:
        name, rest = rest[0], rest[1:]
        name = f"{name} (Apt {unit.group(1)})"

    # Trim a trailing eircode or bare routing key glued onto the name.
    name = PSEUDO_EIRCODE_RE.sub("", EIRCODE_RE.sub("", name)).strip(" -,")
    if " " in name:
        name = re.sub(r"\s+[A-Z]\d[\dW]?$", "", name).strip(" -,")

    area = ", ".join(rest)
    area = PSEUDO_EIRCODE_RE.sub("", EIRCODE_RE.sub("", area)).strip(" -,")
    area = re.sub(r"\s+,", ",", area)
    if area.isupper():
        area = area.title()
    return name.title() if name.isupper() else name, area, eircode, note, full


def parse_features(raw):
    """Key Features is prose with ad-hoc headings. Keep it structured but lossless."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    summary = ""
    sections = []
    current = None
    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        head = lines[0]
        is_heading = len(lines) == 1 and len(head) < 60 and not head.startswith(("-", "•"))
        if is_heading:
            current = {"title": head.rstrip(":"), "items": []}
            sections.append(current)
            continue
        items = []
        for line in lines:
            items.append(re.sub(r"^[-•]\s*", "", line).strip())
        if current is None:
            summary = " ".join(items) if not summary else summary + " " + " ".join(items)
        else:
            current["items"].extend(items)
    return {"summary": summary, "sections": [s for s in sections if s["items"]]}


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main():
    if not CSV_PATH.exists():
        sys.exit(f"Missing {CSV_PATH}. Export the sheet tab as CSV and save it there.")

    geo = load_json(GEO_PATH, {})
    overrides = load_json(OVERRIDE_PATH, {})

    # Photos: media-cache.json holds the curated image ids per property (written
    # by the sync); media-links.json holds the Drive folder URL. Both are keyed
    # by the raw Property Name, so normalise the keys to match our grouping.
    media_raw = load_json(MEDIA_PATH, {}).get("properties", {})
    media = {clean(k): v for k, v in media_raw.items()}
    folder_links = {clean(k): v for k, v in load_json(MEDIA_LINKS_PATH, {}).items()}

    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    grouped = OrderedDict()
    current_key = None
    current_city = ""
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        row = row + [""] * (21 - len(row))
        if clean(row[0]):
            current_key = clean(row[0])
        if clean(row[1]):
            current_city = clean(row[1])
        if current_key is None:
            continue
        grouped.setdefault(current_key, {"city": current_city, "rows": []})
        grouped[current_key]["rows"].append(row)

    properties = []
    seen_ids = {}
    missing_geo = []

    for raw_key, bundle in grouped.items():
        rows_for_prop = bundle["rows"]
        name, area, eircode, note, full_address = split_name(raw_key)
        city = bundle["city"] or "Dublin"

        base_id = slugify(f"{name}-{eircode or area or city}")
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        prop_id = base_id if seen_ids[base_id] == 1 else f"{base_id}-{seen_ids[base_id]}"

        key = clean(raw_key)
        cache_entry = media.get(key, {})
        gallery = []
        for img in cache_entry.get("images", [])[:MAX_GALLERY]:
            # Self-hosted images carry full/thumb paths; older cache entries
            # may still carry only a Drive file id — keep whichever is present.
            entry = {"name": img.get("name", "")}
            if img.get("full"):
                entry["full"] = img["full"]
                entry["thumb"] = img.get("thumb", img["full"])
            elif img.get("id"):
                entry["id"] = img["id"]
            else:
                continue
            gallery.append(entry)
        media_info = {
            "folder": cache_entry.get("folder") or folder_links.get(key),
            "images": gallery,
        }

        rooms = []
        counts = {AVAILABLE: 0, ON_HOLD: 0, BOOKED: 0}
        prices = []
        currency = "€"

        for row in rows_for_prop:
            statuses = [classify_bed(cell) for cell in row[10:14]]
            statuses = [s for s in statuses if s]
            declared = clean(row[5])
            bedspaces = int(declared) if declared.isdigit() else len(statuses)
            symbol, amount = parse_money(row[7])
            if amount:
                prices.append(amount)
                currency = symbol
            room_counts = {
                AVAILABLE: statuses.count(AVAILABLE),
                ON_HOLD: statuses.count(ON_HOLD),
                BOOKED: statuses.count(BOOKED),
            }
            for key in counts:
                counts[key] += room_counts[key]
            room_label = re.sub(r"^(rooms?|rm)\.?\s*", "", clean(row[3]), flags=re.I)
            rooms.append(
                {
                    "room": room_label or "—",
                    "floor": clean(row[2]),
                    "type": normalise_room_type(row[4]),
                    "rawType": clean(row[4]),
                    "bedspaces": bedspaces,
                    "washrooms": clean(row[6]),
                    "rent": amount,
                    "rentDisplay": f"{symbol}{amount:,}" if amount else "",
                    "demography": clean(row[9]),
                    "available": room_counts[AVAILABLE],
                    "onHold": room_counts[ON_HOLD],
                    "booked": room_counts[BOOKED],
                }
            )

        total = sum(counts.values())
        first = rows_for_prop[0]
        features = parse_features(rows_for_prop[0][20] if len(rows_for_prop[0]) > 20 else "")
        if not features:
            for row in rows_for_prop:
                features = parse_features(row[20])
                if features:
                    break

        tenancies = sorted(
            {t.strip() for row in rows_for_prop for t in re.split(r"&|,", clean(row[18])) if t.strip()}
        )
        move_ins = sorted({clean(row[16]) for row in rows_for_prop if clean(row[16])})

        coords = geo.get(full_address) or geo.get(raw_key) or {}
        if "lat" not in coords:
            missing_geo.append(full_address)

        override = overrides.get(prop_id, {})

        properties.append(
            {
                "id": prop_id,
                "name": override.get("name", name),
                "unitNote": note,
                "area": area,
                "city": city,
                "country": "United Kingdom" if city.lower() == "london" else "Ireland",
                "eircode": eircode,
                "address": full_address,
                "lat": override.get("lat", coords.get("lat")),
                "lng": override.get("lng", coords.get("lng")),
                "geoPrecision": coords.get("precision", "unknown"),
                "totalBedspaces": total,
                "available": counts[AVAILABLE],
                "onHold": counts[ON_HOLD],
                "booked": counts[BOOKED],
                "priceMin": min(prices) if prices else None,
                "priceMax": max(prices) if prices else None,
                "currency": currency,
                "priceDisplay": (
                    f"{currency}{min(prices):,}–{currency}{max(prices):,}"
                    if prices and min(prices) != max(prices)
                    else (f"{currency}{prices[0]:,}" if prices else "On request")
                ),
                "utilities": normalise_utilities(first[15]),
                "furnished": clean(first[14]).lower().startswith("y"),
                "moveIn": move_ins,
                "tenancies": tenancies,
                "paymentTerms": clean(first[17]),
                "media": override.get("media", media_info),
                "features": features,
                "rooms": rooms,
            }
        )

    # Sibling units collapse to the same label once the address noise is gone.
    # Give each one back the tail of its raw sheet address so the list stays readable.
    labels = {}
    for prop in properties:
        labels.setdefault((prop["name"].lower(), prop["area"].lower()), []).append(prop)
    for group in labels.values():
        if len(group) < 2:
            continue
        for prop in group:
            tail = prop["address"].replace(",", " ").split()[-1].strip(" -")
            suffix = prop["unitNote"] or (tail if tail.lower() not in prop["name"].lower() else "")
            if suffix:
                prop["name"] = f"{prop['name']} · {suffix}"

    # Two flats in one building share a coordinate; nudge the copies apart by a
    # few metres so both pins stay clickable instead of hiding one another.
    stacked = {}
    for prop in properties:
        if prop["lat"] is None:
            continue
        key = (round(prop["lat"], 5), round(prop["lng"], 5))
        stacked.setdefault(key, []).append(prop)
    for group in stacked.values():
        if len(group) < 2:
            continue
        for index, prop in enumerate(group[1:], start=1):
            angle = 2 * math.pi * index / len(group)
            prop["lat"] = round(prop["lat"] + 0.00018 * math.cos(angle), 6)
            prop["lng"] = round(prop["lng"] + 0.00030 * math.sin(angle), 6)
            prop["geoNudged"] = True

    properties.sort(key=lambda p: (-p["available"], p["city"], p["name"]))

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": CSV_PATH.name,
        "stats": {
            "properties": len(properties),
            "cities": sorted({p["city"] for p in properties}),
            "bedspaces": sum(p["totalBedspaces"] for p in properties),
            "available": sum(p["available"] for p in properties),
            "onHold": sum(p["onHold"] for p in properties),
            "booked": sum(p["booked"] for p in properties),
            "withPhotos": sum(1 for p in properties if p["media"] and p["media"].get("images")),
            "withFolder": sum(1 for p in properties if p["media"] and p["media"].get("folder")),
        },
        "properties": properties,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    stats = payload["stats"]
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print(f"  photos: {stats['withPhotos']} properties have images, {stats['withFolder']} have a folder link")
    print(
        f"  {stats['properties']} properties / {stats['bedspaces']} bedspaces "
        f"({stats['available']} available, {stats['onHold']} on hold, {stats['booked']} booked)"
    )
    if missing_geo:
        print(f"  {len(missing_geo)} addresses have no coordinates. Run: python scripts/geocode.py")
        for address in missing_geo[:5]:
            print(f"    - {address}")


if __name__ == "__main__":
    main()
