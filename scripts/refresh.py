#!/usr/bin/env python3
"""One command to rebuild everything the site serves (manual path).

    python scripts/refresh.py            # geocode new addresses, then build
    python scripts/refresh.py --skip-geo # rebuild JSON only (no network)

Run this after you export the sheet over data/portfolio.csv (data) and, if you
want photo links refreshed, data/portfolio.xlsx (hyperlinks). For the fully
automatic path use scripts/sync_from_google.py instead — this one is the
no-credentials fallback.
"""

import argparse
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(script):
    print(f"\n=== {script} ===")
    runpy.run_path(str(ROOT / script), run_name="__main__")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-geo", action="store_true", help="do not hit the geocoder")
    parser.add_argument("--skip-photos", action="store_true", help="do not re-download photos")
    args = parser.parse_args()

    # Refresh photo folder links if a fresh XLSX export is present.
    if (ROOT.parent / "data" / "portfolio.xlsx").exists():
        sys.argv = ["extract_media.py"]
        run("extract_media.py")

    if not args.skip_photos and (ROOT.parent / "data" / "media-links.json").exists():
        sys.argv = ["fetch_photos.py"]
        run("fetch_photos.py")

    if not args.skip_geo:
        sys.argv = ["geocode.py"]
        run("geocode.py")
        sys.argv = ["universities.py"]
        run("universities.py")
    sys.argv = ["build_data.py"]
    run("build_data.py")
    print("\nDone. Preview with:  python -m http.server -d public 4178")


if __name__ == "__main__":
    main()
