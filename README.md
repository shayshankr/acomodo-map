# Availability Map

A live-availability map for managed student accommodation — the same idea as
`acomodomap.com`, rebuilt from scratch. One Google Sheet in, one interactive map
out: filter by campus, price, room type and move-in date, and see exactly which
beds are free right now.

Visitors can filter by city, campus, price, room type and move-in; sort by
availability, price or nearest campus; **shortlist** properties (saved in the
browser); **share** a deep link to any listing; and enquire in one tap over
WhatsApp.

Everything is **static**. There is no server and no database — a Python script
turns the spreadsheet into JSON, and the front end is plain HTML/CSS/JS using
Leaflet. That means it hosts for free almost anywhere (see **Hosting** below).

```
acomodo-map/
├── data/                     inputs & caches
│   ├── portfolio.csv         availability data (Sheet export, or written by the sync)
│   ├── media-links.json      property → Drive photo-folder URL (from the Sheet's links)
│   ├── media-cache.json      property → curated image ids (from walking the folders)
│   ├── address-hints.json    manual search strings for tricky addresses
│   ├── geocode-cache.json    address → lat/lng (generated, hand-editable)
│   └── campus-cache.json     campus → lat/lng (generated, hand-editable)
├── scripts/                  the pipeline (Python 3)
│   ├── fetch_photos.py       download property photos from Drive → public/photos/
│   ├── sync_from_google.py   ★ automatic: Sheet + Drive photos → data → build
│   ├── setup_check.py        verify the service account can read Sheet + folders
│   ├── extract_media.py      manual: pull photo-folder links out of an XLSX export
│   ├── geocode.py            look up coordinates via OpenStreetMap
│   ├── universities.py       geocode the campus list
│   ├── build_data.py         data + photos → public/data/properties.json
│   └── refresh.py            manual: run the build chain in order
├── .github/workflows/sync.yml   scheduled runner for sync_from_google.py
└── public/                   ← this folder is the website; deploy it as-is
    ├── index.html
    ├── assets/{styles.css, app.js}
    ├── photos/<property>/      self-hosted property images
    └── data/{properties.json, universities.json}
```

## Staying in sync — how updates reach the map

Staff edit the Google Sheet (availability, prices) and drop photos into each
property's Google Drive folder. The map picks both up automatically once the
scheduled sync is switched on (below). Prefer that; the manual path is a
fallback.

### Automatic sync (no setup, no credentials)

The Sheet is shared **"Anyone with the link → Viewer"**, so
`scripts/sync_from_google.py` just reads its **public** export — no service
account, no login, no secrets. It maps both tabs onto the canonical columns,
refreshes `data/media-links.json` from the cell hyperlinks, rebuilds the data,
and (in CI) commits it back so Pages redeploys. `.github/workflows/sync.yml`
runs it every 30 minutes and on demand; `photos.yml` refreshes photos daily
(also credential-free).

Nothing to configure. To confirm the Sheet is still link-readable:

```bash
pip install -r requirements.txt
python scripts/setup_check.py
```

The only requirement is that the Sheet stays shared *Anyone with the link →
Viewer* (read-only). If it's ever set back to private, the sync fails with a
clear message and you re-share it. To point at a different Sheet, set the
`SHEET_ID` repo **variable** (Settings → Secrets and variables → Actions →
Variables); otherwise it uses the id baked into the script.

### Manual rebuild (no credentials)

1. In the Sheet, **File → Download → CSV** over `data/portfolio.csv`. To refresh
   the photo-folder links too, also **File → Download → Microsoft Excel (.xlsx)**
   over `data/portfolio.xlsx` (CSV drops the links; the XLSX keeps them).
2. Rebuild and preview:

   ```bash
   python scripts/refresh.py              # geocode new addresses, extract links, build
   python scripts/refresh.py --skip-geo   # faster: rebuild JSON only, no network
   python -m http.server -d public 4178   # preview at http://localhost:4178
   ```

3. Redeploy `public/` (a `git push` if your host is connected to the repo, or a
   drag-and-drop — see **Hosting**).

### When a pin lands in the wrong place

Geocoding is approximate. `geocode.py` labels each hit by precision
(`address` > `area` > `street` > `city`); anything that falls back to `city`
prints a warning. To fix one:

- add a better search string to `data/address-hints.json`, keyed by the exact
  `Property Name` cell, then `python scripts/geocode.py --recheck`, **or**
- just edit the `lat`/`lng` in `data/geocode-cache.json` by hand and rebuild.

The detail panel shows an "approximate" note whenever a pin is coarser than
street level, so nothing is silently misplaced.

## Photos

Each property's detail panel has a gallery with a click-to-open lightbox, served
from the site's own CDN — **not** hot-linked from Google Drive (Drive is slow,
rate-limited, and its embed URLs break without notice).

The pipeline (`scripts/fetch_photos.py`, no credentials needed):

1. Reads each property's Drive folder URL from `data/media-links.json` (the
   "Media Link" hyperlinks in the Sheet).
2. Lists the folder — and its room subfolders — through Google's public
   `embeddedfolderview` endpoint. This works because the folders are shared
   "Anyone with the link", the same setting that lets the photos display.
3. Downloads a curated spread (max 12/property) at two web sizes using Drive's
   own resizer — a ~480px thumbnail and a ~1600px view image — into
   `public/photos/<slug>/`.
4. Records the local paths in `data/media-cache.json`; `build_data.py` attaches
   them and the page loads them straight from `public/photos/`.

So the images are **committed to the repo and served from GitHub Pages** —
fast, reliable, versioned, and independent of Drive being up. Refresh them with:

```bash
python scripts/fetch_photos.py          # re-pull everything
python scripts/refresh.py               # photos + data in one go
```

Photos also refresh **automatically**: `.github/workflows/photos.yml` runs the
fetch daily (and on demand) with no credentials — because the folders are public
— and commits any changes, which redeploys the site. So photos staff add to the
existing Drive folders appear on the map on their own.

A property whose folder is empty simply shows a "Photos on Google Drive" link
instead of a gallery, and fills in on the next fetch once photos are added.

> The photo folders must stay shared "Anyone with the link → Viewer" for the
> fetch to see them (they already are).

## How the sheet is read

`build_data.py` groups the CSV rows by `Property Name`, then per property:

- **Availability** comes from the four `Bed 1..4` columns — `Available`,
  `Available (ON HOLD)`, anything else counts as booked. Property and site totals
  are summed from these, so the headline numbers always match the beds shown.
- **Price** is parsed from the per-bedspace rent (min–max across rooms).
- **Room type** is normalised (`Ensuite Double`, `Double Non ensuite`, … all
  collapse to a consistent set) so the room-type filter has clean options.
- **Key Features** prose is split into a summary plus labelled sections for the
  detail panel.

Nothing about the sheet's exact column order is assumed beyond the header names,
and unknown bed wording is treated as *booked* rather than advertised as free.

### Known gap: the London tab

The workbook has a second tab, **London Sept'26 Portfolio details**, with a
*different* column layout (`Property Address`, an extra `Rooms size` column, £
rents). The current build reads the Ireland/Limerick tab only, so the ~5 London
properties are not on the map yet. Their photo folders are already picked up by
the media extractor; wiring the London columns into `build_data.py` is a small,
self-contained follow-up.

## Hosting

The site is a folder of static files, so use any static host. All of these have
a free tier that comfortably covers a site like this.

| Host | How | Custom domain | Notes |
|------|-----|---------------|-------|
| **Cloudflare Pages** | Connect the repo, set output dir to `public`. Or `npx wrangler pages deploy public`. | Free, on Cloudflare DNS | Fast global CDN; generous free tier. A good match. |
| **Netlify** | Drag the `public` folder onto app.netlify.com, or connect the repo (`netlify.toml` is already set). | Free | Easiest drag-and-drop. |
| **GitHub Pages** | Push the repo, set Pages to serve `/` from a branch, and move `public/`'s contents to the root **or** use an action. | Free (`*.github.io`) | Serves from repo root, so publishing a subfolder needs an action or a `docs/` layout. |
| **Vercel** | Import the repo; framework preset "Other", output dir `public`. | Free | Fine, though aimed more at app frameworks. |

Because the app is a Leaflet map that pulls **map tiles from OpenStreetMap** at
run time, it will not work as a single sandboxed HTML file (e.g. a Claude
Artifact) — those block external tile requests. A normal static host is the
right home for it.

### Domain

`acomodomap.com` sits behind Cloudflare. If this is replacing it, point the same
domain at whichever host you pick (each host's dashboard walks you through the
DNS record). Until then every host above gives you a free URL to share.

## Design notes

- **No build step, no framework.** `index.html` loads Leaflet from a CDN and one
  ES module. Editing the site is editing three files in `public/`.
- **Themes.** Light and dark; the choice persists in `localStorage`. The dark
  basemap is OpenStreetMap's own tiles recoloured with a CSS filter, so there is
  no second, API-key-gated tile provider to maintain.
- **Shareable state.** Filters and the open property are written to the URL, so a
  link like `?near=trinity-college-dublin&max=800` reopens the same view.
- **Contact.** "Enquire" and "Ask us to look" build `mailto:` links to the
  address in `public/assets/app.js` (`CONFIG.contactEmail`) — change it there.
```
