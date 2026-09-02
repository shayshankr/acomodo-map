#!/usr/bin/env python3
"""Geocode the campus list once and write public/data/universities.json.

    python scripts/universities.py

Students search by campus, not by postcode, so the map needs the campuses as
first-class points. Edit CAMPUSES below to add or drop one, delete the matching
entry from data/campus-cache.json, and re-run.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "campus-cache.json"
OUT_PATH = ROOT / "public" / "data" / "universities.json"

CONTACT = "acomodo-map/1.0 (bookings@acomodo.in)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"

# (short label, search string, city, country code)
CAMPUSES = [
    ("Trinity College Dublin", "Trinity College Dublin, College Green, Dublin", "Dublin", "ie"),
    ("UCD Belfield", "University College Dublin, Belfield, Dublin", "Dublin", "ie"),
    ("DCU Glasnevin", "Dublin City University, Glasnevin, Dublin", "Dublin", "ie"),
    ("DCU St Patrick's", "Dublin City University St Patrick's Campus", "Dublin", "ie"),
    ("TU Dublin Grangegorman", "TU Dublin Grangegorman, Dublin", "Dublin", "ie"),
    ("TU Dublin Tallaght", "Institute of Technology Tallaght, Dublin", "Dublin", "ie"),
    ("TU Dublin Blanchardstown", "TU Dublin Blanchardstown Campus, Dublin", "Dublin", "ie"),
    ("RCSI", "Royal College of Surgeons in Ireland, St Stephen's Green, Dublin", "Dublin", "ie"),
    ("Griffith College Dublin", "Griffith College Dublin", "Dublin", "ie"),
    ("National College of Ireland", "National College of Ireland, IFSC, Dublin", "Dublin", "ie"),
    ("Dublin Business School", "Dublin Business School, Aungier Street, Dublin", "Dublin", "ie"),
    ("Maynooth University", "Maynooth University, Maynooth, County Kildare", "Dublin", "ie"),
    ("IADT Dun Laoghaire", "IADT, Kill Avenue, Dun Laoghaire", "Dublin", "ie"),
    ("University of Limerick", "University of Limerick, Castletroy, Limerick", "Limerick", "ie"),
    ("TUS Moylish", "Limerick Institute of Technology, Limerick", "Limerick", "ie"),
    ("Mary Immaculate College", "Mary Immaculate College, South Circular Road, Limerick", "Limerick", "ie"),
    ("Griffith College Limerick", "O'Connell Avenue, Limerick", "Limerick", "ie"),
    # London
    ("Queen Mary University", "Queen Mary University of London, Mile End Road, London", "London", "gb"),
    ("University of East London", "University of East London, University Way, London", "London", "gb"),
    ("UCL", "University College London, London", "London", "gb"),
    ("King's College London", "King's College London, Strand, London", "London", "gb"),
    ("Imperial College", "Imperial College London, South Kensington, London", "London", "gb"),
    ("LSE", "London School of Economics, Houghton Street, London", "London", "gb"),
    ("City, University of London", "City University of London, Northampton Square, London", "London", "gb"),
    ("University of Westminster", "University of Westminster, Regent Street, London", "London", "gb"),
    ("London Metropolitan", "London Metropolitan University, Holloway Road, London", "London", "gb"),
    ("University of Greenwich", "University of Greenwich, Park Row, London", "London", "gb"),
]


def slugify(text):
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-"))


def geocode(query, country):
    url = f"{ENDPOINT}?{urlencode({'q': query, 'format': 'json', 'limit': 1, 'countrycodes': country})}"
    request = Request(url, headers={"User-Agent": CONTACT, "Accept-Language": "en"})
    with urlopen(request, timeout=30) as response:
        results = json.load(response)
    time.sleep(1.1)
    if not results:
        return None
    hit = results[0]
    return {
        "lat": round(float(hit["lat"]), 6),
        "lng": round(float(hit["lon"]), 6),
        "matched": hit.get("display_name", "")[:120],
    }


def main():
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    campuses = []
    for name, query, city, country in CAMPUSES:
        if query not in cache:
            print(f"  looking up {name}")
            hit = geocode(query, country)
            if hit is None:
                print(f"    no match — add coordinates to {CACHE_PATH.name} by hand")
                continue
            cache[query] = hit
        entry = cache[query]
        campuses.append(
            {
                "id": slugify(name),
                "name": name,
                "city": city,
                "lat": entry["lat"],
                "lng": entry["lng"],
            }
        )

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps({"universities": campuses}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}: {len(campuses)} campuses")


if __name__ == "__main__":
    main()
