# Acomodo Availability Map — Project Guide

A complete reference for anyone who wants to run, change, or extend this site.
Read the [README](README.md) for the quick tour; this document goes deeper into
how everything fits together, what every control does, and how to make common
changes safely.

Live site: https://shayshankr.github.io/acomodo-map/
Repository: https://github.com/shayshankr/acomodo-map

---

## 1. What it is, in one breath

A live-availability map for managed student accommodation in Dublin, Limerick
and London. One Google Sheet goes in; one interactive map comes out. There is no
server and no database. A handful of Python scripts turn the Sheet into small
JSON files, and a single-page front end (Leaflet + plain HTML/CSS/JS) renders
them. That means it hosts for free on GitHub Pages and can be moved to any static
host without changes.

The whole system is three moving parts:

```
Google Sheet  ──►  Python build scripts  ──►  static JSON  ──►  the map (browser)
(the source)       (turn rows into data)      (public/data)     (Leaflet UI)
```

Everything after the Sheet is generated and committed, so the site is always
just files on a CDN.

---

## 2. Repository layout

```
acomodo-map/
├── data/                         inputs and caches (the build reads these)
│   ├── portfolio.csv             Ireland/Limerick availability (from the Sheet)
│   ├── portfolio-london.csv      London availability (different Sheet layout)
│   ├── media-links.json          property → Drive photo-folder URL
│   ├── media-cache.json          property → the downloaded photo file paths
│   ├── geocode-cache.json        address → lat/lng (generated, hand-editable)
│   ├── campus-cache.json         campus → lat/lng
│   ├── address-hints.json        manual search strings for tricky addresses
│   └── overrides.json            per-property manual fixes (name, coords, media)
│
├── scripts/                      the pipeline (Python 3, mostly stdlib)
│   ├── sync_from_google.py       ★ credential-free: read the PUBLIC Sheet → rebuild
│   ├── fetch_photos.py           download property photos → public/photos/
│   ├── build_data.py             CSV + caches + photos → public/data/properties.json
│   ├── geocode.py                look up coordinates (OpenStreetMap Nominatim)
│   ├── universities.py           geocode the campus list → universities.json
│   ├── london_to_csv.py          map the London tab of an XLSX to canonical columns
│   ├── extract_media.py          pull photo-folder links out of an XLSX export
│   ├── setup_check.py            confirm the Sheet is publicly readable
│   └── refresh.py                run the whole chain locally in order
│
├── .github/workflows/
│   ├── deploy.yml                publish public/ to GitHub Pages on every push
│   ├── sync.yml                  read the public Sheet every 30 min, commit changes
│   └── photos.yml                refresh photos daily
│
└── public/                       ← this folder IS the website; deploy it as-is
    ├── index.html                markup + the Content-Security-Policy
    ├── assets/
    │   ├── app.js                all behaviour (no framework, no build step)
    │   └── styles.css            all styling, light + dark themes
    ├── photos/<property>/        self-hosted, web-sized property images
    └── data/
        ├── properties.json       the properties the map renders
        └── universities.json     the campuses
```

The two files a front-end change usually touches are `public/index.html` and
`public/assets/app.js`; styling lives in `public/assets/styles.css`. A data or
pipeline change touches `scripts/` and the generated files under `public/data/`.

---

## 3. How the data pipeline works

`build_data.py` is the heart of it. It:

1. Reads `portfolio.csv` (Ireland/Limerick) and `portfolio-london.csv`, grouping
   rows by property name.
2. Reads availability from the four `Bed 1..4` columns. `Available` and
   `Available (ON HOLD)` are counted; anything else is treated as booked. Site
   and per-property totals are summed from these, so the headline numbers always
   match the beds shown.
3. Parses the per-bedspace rent (min–max across rooms), normalises room types
   (`Ensuite Double`, `Double Non ensuite`, … collapse to a clean set), splits
   the "Key Features" prose into a summary plus labelled sections, and parses
   Irish eircodes and UK postcodes out of the address.
4. Attaches each property's photos (from `media-cache.json`) and its Drive folder
   link (from `media-links.json`).
5. Attaches coordinates from `geocode-cache.json`, nudging apart any two
   properties that share a pin so both stay clickable.
6. Writes `public/data/properties.json`.

Nothing in `build_data.py` touches the network — it only reads local files. The
scripts that reach out are `geocode.py` and `universities.py` (OpenStreetMap),
`fetch_photos.py` (public Drive folders), and `sync_from_google.py` (the public
Sheet).

### The Sheet has two differently-shaped tabs

The Ireland tab and the London tab have different column layouts (London adds a
"Rooms size" column, uses GBP, has three bed columns instead of four). The sync
maps **both** onto one canonical column set by matching header names, so either
layout parses without hard-coding column positions. See `resolve_columns()` in
`sync_from_google.py`.

---

## 4. Running and previewing locally

```bash
python -m http.server -d public 4178      # then open http://localhost:4178
```

That serves the already-built site. To rebuild the data first:

```bash
pip install -r requirements.txt           # just openpyxl
python scripts/refresh.py                 # geocode new addresses, fetch photos, build
python scripts/refresh.py --skip-geo --skip-photos   # fast: rebuild JSON only
```

To pull the very latest from the live Sheet (no credentials needed):

```bash
python scripts/sync_from_google.py
```

---

## 5. Every control, and what it does

| Control | What it does |
|---|---|
| **Search box** | First tries to match a property by name, area, street or eircode. If nothing matches (e.g. "Sandymount"), it treats the text as a *place*, geocodes it, flies the map there, drops a pin, and ranks every property by distance to it. Press Enter to trigger it immediately; a shareable `?q=` link resolves the same way. |
| **City segments** (All / Dublin / Limerick / London) | Scope the map, the list, and the header counts to that city. "All" shows the whole portfolio. |
| **Near campus** | Filter to one city's campuses and rank properties by straight-line distance to the chosen campus. Selecting a campus also switches the sort to "Nearest campus". |
| **Max rent** slider | Hide properties whose lowest per-bed rent is above the chosen ceiling. "any" removes the cap. |
| **Room type** | Show only properties that have at least one room of the chosen type (ensuite double, twin, etc.). |
| **Has a free bed** (on by default) | Show only properties with at least one available bed. |
| **Bills included** | Show only properties whose utilities are all-inclusive. |
| **Ensuite** | Show only properties with an ensuite room. |
| **Short stay** | Show only properties offering semester or 4-month tenancies. |
| **★ Saved** | Show only shortlisted properties (see the star buttons on each card). The count next to it is how many you've saved. |
| **Sort** | Most available (default) · Price low→high · Price high→low · Nearest campus (appears once a campus is chosen). |
| **Reset** | Clears every filter, search and sort back to the default. |

All of these are reflected in the URL, so any filtered view is a shareable link.

---

## 6. Every feature

- **Map + list, always in sync.** Filtering updates both; clicking a card opens
  the property and centres the map; clicking a map pin opens the same card.
- **Per-property detail panel** with:
  - a **photo gallery** and a click-to-open **lightbox**, served from the site's
    own files (not hot-linked from Drive);
  - **free / on-hold / bedspaces** counts and a full **rooms table** (type, rent,
    status, gender);
  - **terms** (rent, bills, furnished, move-in, tenancy, deposit);
  - **Plan your commute** — live Google Maps public-transport directions from the
    property to each nearby campus, plus an "any place" option;
  - **Enquire on WhatsApp** (prefilled message), **Directions**, **Save**, **Share**.
- **Per-city header stats.** Beds free / on hold / properties change with the
  selected city.
- **Place search** that flies the map to any typed area.
- **Shortlist** saved in the browser, with a "Saved" filter.
- **Share** — copies a deep link to any property or filtered view.
- **Light / dark theme** (remembers your choice), following the system by default.
- **Mobile:** a List/Map toggle, a proper Back button (closes the panel or returns
  to the map instead of leaving the site), and a logo that returns home.
- **Default landing** opens Dublin, the main market, rather than the sparse
  all-cities view. The logo returns there.
- **Deep links:** every filter, city, campus, search and open property lives in
  the URL, so a bookmarked or shared link restores the exact view.

---

## 7. Deployment and automation

Three GitHub Actions run the whole thing with no servers and no secrets:

- **`deploy.yml`** publishes `public/` to GitHub Pages on every push to `main`.
- **`sync.yml`** runs every 30 minutes: it reads the **public** Sheet, rebuilds
  the data, and commits any change (which triggers a redeploy). The Sheet is
  shared "Anyone with the link → Viewer", so this needs no login, service
  account, or secret.
- **`photos.yml`** refreshes photos daily, also credential-free (the Drive
  folders are public, so `fetch_photos.py` reads them directly).

The result: a staff member edits the Sheet, and within half an hour the map shows
it, automatically. Photos they add to the existing Drive folders appear within a
day.

> The only operational requirement is that the Sheet stays shared *Anyone with
> the link → Viewer*. If it is set back to private the sync fails with a clear
> message; run `python scripts/setup_check.py` to check.

---

## 8. Security

- **Content-Security-Policy** in `index.html` whitelists exactly the hosts the
  page uses. `script-src` has no `unsafe-inline`, so an injected inline script
  cannot run — the strongest defence against cross-site scripting from Sheet
  data.
- **`safeUrl()`** blocks any non-`http(s)` link coming from the Sheet, so a stray
  `javascript:` URL in a "Media Link" cell can never become clickable.
- Every value pulled from the Sheet is **HTML-escaped** before it reaches the DOM.
- The Leaflet library is loaded with **Subresource Integrity** hashes, so a
  tampered CDN file is rejected.
- **No secrets in the repository.** The whole pipeline reads public data.

---

## 9. Common changes (recipes)

**Change a property's availability, price, or details** — edit the Google Sheet.
The sync picks it up within 30 minutes. Nothing else to do.

**Add or move photos** — drop images into the property's Drive folder. `photos.yml`
picks them up daily; or run `python scripts/fetch_photos.py` to pull them now.

**Fix a pin that lands in the wrong place** — add a better search string to
`data/address-hints.json` keyed by the exact property name, then
`python scripts/geocode.py --recheck`; or edit the `lat`/`lng` in
`data/geocode-cache.json` by hand and rebuild. The panel shows an "approximate"
note whenever a pin is coarser than street level.

**Change the WhatsApp number** — edit `CONFIG.whatsapp` in `public/assets/app.js`
(digits only, international format).

**Change the default landing city** — edit `HOME_CITY` in `public/assets/app.js`.

**Change the brand colour** — edit `--brand` / `--brand-2` in
`public/assets/styles.css`.

**Add a campus** — add a line to `CAMPUSES` in `scripts/universities.py`, run it,
and rebuild.

**Add a new city** — add its rows to the Sheet with a `City` value; the sync and
`build_data.py` pick it up. New addresses are geocoded on the next run, and a
segment button appears automatically. (Country is inferred: London → UK, else
Ireland; add another country's postcode pattern in `build_data.py` if needed.)

**Add a new filter** — add the control to `public/index.html`, add its element to
the `els` map in `app.js`, and add a clause in `currentFilters()`. Wire its
`change` event to `applyFilters()`, and (optionally) persist it in
`buildUrl()` / `readUrl()`.

After any front-end edit, preview with the local server and check the browser
console is clean before pushing.

---

## 10. How this build compares to the original acomodomap.com

This site was rebuilt from scratch to mirror `acomodomap.com` and then taken
further on the engineering side. Both show a live map and list with city and
availability filters; the differences are mostly in *how* the data and photos are
handled, and in a few extra front-end capabilities.

| Capability | This build | Notes |
|---|---|---|
| Live map + list, city filters, search, shortlist | ✅ | Parity with the original. |
| Photos | **Self-hosted & size-optimised**, served from the site's own CDN | The original hot-links Google Drive thumbnails, which are slower and break if Google changes the URL format. Here each photo is downloaded at two web sizes and committed, so the gallery is fast and stable. |
| Data pipeline | **Open, documented, credential-free** | The Sheet → map path is a handful of readable scripts anyone can run; the automated sync needs no service account or secret. |
| Automation | **Sheet sync every 30 min + daily photo refresh**, no secrets | Staff edits reach the map on their own. |
| Plan-your-commute | ✅ live transit links per property → each nearby campus | Turns "which bus, how long" into one tap, always current. |
| Place search | ✅ type any area, the map flies there and ranks by distance | Not limited to properties that literally contain the text. |
| Per-city header stats | ✅ counts update with the selected city | |
| Nearest-campus sort + per-card distance | ✅ | |
| Deep-linkable state + proper Back / logo-home | ✅ every view is a shareable URL | |
| Security hardening | ✅ CSP (no inline scripts), SRI, URL sanitisation | |
| Accessibility | ✅ keyboard-operable, ARIA labels, real link semantics | |
| Hosting | **Free static hosting, no vendor lock-in** | Runs on GitHub Pages, movable to any static host unchanged. |

### Honest trade-offs

Because there is no backend, this build deliberately does **not** have:

- user accounts, server-side booking, or a payments flow;
- a synced shortlist (the saved list lives in each browser, not an account);
- a built-in analytics or admin dashboard;
- search-engine indexing (it is `noindex`, matching the original's private-tool
  posture).

Other things to know:

- Galleries are curated to about 12 photos per property to keep pages fast.
- Some pins are approximate where an address does not geocode to street level;
  the panel flags this.
- The credential-free sync requires the Sheet to stay link-readable (read-only).
- London ingestion depends on that tab's columns being recognisable by header
  name; a heavy re-layout of the tab would need a small mapping update.

The net effect is a fast, self-contained, inspectable site that a small team can
run for free and change confidently — with the data, photos, and automation all
out in the open rather than behind a hosted service.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sync workflow fails with "not a workbook" | The Sheet was set back to private. Re-share it *Anyone with the link → Viewer*. |
| A property has no photos | Its Drive folder is empty, or not shared "anyone with link". The panel shows a "Photos on Google Drive" link until photos are added. |
| A pin is in the wrong place | See the geocoding recipe in §9. |
| Map tiles or fonts don't load | Check the Content-Security-Policy in `index.html` allows the host; the browser console names any blocked resource. |
| London properties missing | The London tab's headers changed enough that the column mapper can't find them; check `resolve_columns()` candidates. |
| The daily photo run committed a large diff once | Expected only on the first migration to ID-based filenames; runs are idempotent afterwards. |

---

*Generated as living documentation. Keep it beside the code — when behaviour
changes, update the relevant section here so the next person inherits the full
picture.*
