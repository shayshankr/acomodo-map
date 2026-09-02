/* ---------------------------------------------------------------------------
   Availability map.

   Reads two static JSON files written by scripts/build_data.py and
   scripts/universities.py. No framework, no build step, no backend: whatever
   static host you drop /public on will serve this as-is.
--------------------------------------------------------------------------- */

const CONFIG = {
  contactEmail: "bookings@acomodo.in",
  // WhatsApp number in international format, digits only (country code + number).
  whatsapp: "919875835669",
  brand: "Availability Map",
  // Drive image endpoints. `w` is the requested pixel width; Drive resizes.
  driveThumb: (id, w) => `https://drive.google.com/thumbnail?id=${id}&sz=w${w}`,
  driveFull: (id, w) => `https://lh3.googleusercontent.com/d/${id}=w${w}`,
  // Fallback view when nothing is filtered in.
  home: { center: [53.33, -6.9], zoom: 8 },
  // OpenStreetMap's standard tiles need no API key. Dark mode is a CSS filter
  // on the tile pane (see styles.css) rather than a second, key-gated provider.
  tiles: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

// Inline WhatsApp glyph so the button reads at a glance and needs no external asset.
const WHATSAPP_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">' +
  '<path d="M17.47 14.38c-.29-.15-1.7-.84-1.96-.93-.26-.1-.45-.15-.64.14-.19.29-.74.93-.9 1.12-.17.19-.33.21-.62.07-.29-.15-1.22-.45-2.33-1.44-.86-.77-1.44-1.72-1.61-2-.17-.29-.02-.45.13-.59.13-.13.29-.34.43-.51.15-.17.19-.29.29-.48.1-.19.05-.36-.02-.51-.07-.14-.64-1.55-.88-2.12-.23-.55-.47-.48-.64-.49h-.55c-.19 0-.5.07-.76.36-.26.29-1 .98-1 2.38s1.02 2.76 1.17 2.95c.14.19 2.01 3.06 4.87 4.29.68.29 1.21.47 1.62.6.68.22 1.3.19 1.79.12.55-.08 1.7-.7 1.94-1.37.24-.67.24-1.25.17-1.37-.07-.12-.26-.19-.55-.34zM12.05 21.5h-.01c-1.67 0-3.31-.45-4.74-1.29l-.34-.2-3.52.92.94-3.43-.22-.35a9.4 9.4 0 01-1.44-5.02c0-5.2 4.24-9.44 9.45-9.44 2.52 0 4.89.98 6.67 2.77a9.36 9.36 0 012.76 6.68c-.01 5.2-4.24 9.44-9.44 9.44zM20.52 3.48A11.78 11.78 0 0012.05.99C5.55.99.28 6.26.28 12.74c0 2.07.54 4.1 1.57 5.88L.18 24l5.53-1.45a11.8 11.8 0 005.64 1.44h.01c6.5 0 11.78-5.27 11.78-11.75 0-3.14-1.22-6.09-3.44-8.31z"/></svg>';

const $ = (id) => document.getElementById(id);

// Resolve a gallery image to a URL. Prefer the self-hosted copy under
// public/photos/ (written by scripts/fetch_photos.py); fall back to Drive for
// any entry that still only carries a Drive file id.
const imgThumb = (img) => img.thumb || CONFIG.driveThumb(img.id, 480);
const imgFull = (img) => img.full || CONFIG.driveFull(img.id, 1600);

// Only let http(s) links from the sheet become clickable hrefs — a stray
// javascript:/data: URL in a "Media Link" cell must not become an XSS vector.
const safeUrl = (url) => (/^https?:\/\//i.test(String(url || "").trim()) ? String(url).trim() : "#");
const els = {
  results: $("results"),
  count: $("result-count"),
  q: $("q"),
  seg: document.querySelector(".seg"),
  campus: $("campus"),
  price: $("price"),
  priceOut: $("price-out"),
  roomtype: $("roomtype"),
  onlyAvailable: $("only-available"),
  billsInc: $("bills-inc"),
  ensuite: $("ensuite"),
  shortStay: $("short-stay"),
  reset: $("reset"),
  drawer: $("drawer"),
  drawerInner: $("drawer-inner"),
  scrim: $("scrim"),
  viewToggle: $("view-toggle"),
  themeToggle: $("theme-toggle"),
  lightbox: $("lightbox"),
  sort: $("sort"),
  sortDistance: $("sort-distance"),
  savedOnly: $("saved-only"),
  savedCount: $("saved-count"),
  placeNote: $("place-note"),
  placeNoteText: $("place-note-text"),
  placeClear: $("place-clear"),
};

const state = {
  properties: [],
  universities: [],
  filtered: [],
  city: "all",
  campus: null,
  selectedId: null,
  markers: new Map(),
  uniLayer: null,
  map: null,
  tileLayer: null,
  maxPrice: Infinity,
  sort: "availability",
  saved: new Set(),
  searchPlace: null, // {lat,lng,label} when a place (not a property) was searched
  searchMarker: null,
  placeMode: false, // true when the query matched no property and we flew to a place
  lastGeocoded: "",
};

/* --- place search (type any area → fly the map there) -------------------- */

async function geocodePlace(query) {
  const cc = state.city === "London" ? "gb" : state.city === "all" ? "ie,gb" : "ie";
  const url =
    "https://nominatim.openstreetmap.org/search?format=json&limit=1" +
    `&countrycodes=${cc}&q=${encodeURIComponent(query)}`;
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    const hits = await res.json();
    if (!hits.length) return null;
    return {
      lat: parseFloat(hits[0].lat),
      lng: parseFloat(hits[0].lon),
      label: hits[0].display_name.split(",").slice(0, 2).join(", ").trim(),
    };
  } catch {
    return null; // offline / blocked — just skip the fly-to
  }
}

function showSearchMarker(place) {
  if (state.searchMarker) state.searchMarker.remove();
  state.searchMarker = L.marker([place.lat, place.lng], {
    icon: L.divIcon({ className: "", html: '<div class="search-pin"></div>', iconSize: [20, 20], iconAnchor: [10, 10] }),
    zIndexOffset: 1000,
    interactive: false,
  }).addTo(state.map);
}

async function runPlaceSearch(query, { fly = true } = {}) {
  const place = await geocodePlace(query);
  if (!place) {
    state.placeMode = false;
    return false;
  }
  state.searchPlace = place;
  state.placeMode = true;
  showSearchMarker(place);
  els.placeNoteText.textContent = `Rooms nearest ${place.label}`;
  els.placeNote.hidden = false;
  // setView with an explicit zoom is safe even before the map has a size
  // (unlike fitBounds); tiles fill in once the container is measured.
  if (fly) state.map.setView([place.lat, place.lng], 14, { animate: false });
  applyFilters({ fit: false });
  return true;
}

function clearPlaceSearch({ refit = true } = {}) {
  state.searchPlace = null;
  state.placeMode = false;
  state.lastGeocoded = "";
  els.placeNote.hidden = true;
  if (state.searchMarker) {
    state.searchMarker.remove();
    state.searchMarker = null;
  }
  if (refit) applyFilters();
}

/* --- shortlist (saved properties, kept in the browser) ------------------- */

const SAVED_KEY = "map-saved";

function loadSaved() {
  try {
    const raw = JSON.parse(localStorage.getItem(SAVED_KEY) || "[]");
    state.saved = new Set(Array.isArray(raw) ? raw : []);
  } catch {
    state.saved = new Set();
  }
}

function persistSaved() {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify([...state.saved]));
  } catch {
    /* private window: shortlist just won't persist */
  }
}

function toggleSaved(id) {
  if (state.saved.has(id)) state.saved.delete(id);
  else state.saved.add(id);
  persistSaved();
  updateSavedUI();
}

function updateSavedUI() {
  const count = state.saved.size;
  els.savedCount.textContent = count ? `(${count})` : "";
  for (const btn of document.querySelectorAll(".save-btn")) {
    const on = state.saved.has(btn.dataset.save);
    btn.classList.toggle("is-on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "Saved — click to remove" : "Save to shortlist";
    const label = btn.querySelector(".save-label");
    if (label) label.textContent = on ? "Saved" : "Save";
  }
  // If the Saved filter is on, re-filter as items are toggled.
  if (els.savedOnly.checked) applyFilters({ fit: false });
}

function shareProperty(id, btn) {
  const url = location.href; // syncUrl keeps this pointing at the open property + filters
  const flash = (msg) => {
    const original = btn.textContent;
    btn.textContent = msg;
    setTimeout(() => (btn.textContent = original), 1600);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(url).then(() => flash("Link copied ✓")).catch(() => flash("Copy failed"));
  } else if (navigator.share) {
    navigator.share({ url }).catch(() => {});
  } else {
    window.prompt("Copy this link:", url);
  }
}

/* --- helpers ------------------------------------------------------------- */

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );

const money = (amount, symbol = "€") =>
  amount == null ? "—" : `${symbol}${amount.toLocaleString("en-IE")}`;

function distanceKm(a, b) {
  const R = 6371;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function statusOf(property) {
  if (property.available > 0) return "free";
  if (property.onHold > 0) return "hold";
  return "full";
}

function statusLabel(property) {
  if (property.available > 0) {
    return `${property.available} bed${property.available > 1 ? "s" : ""} free`;
  }
  if (property.onHold > 0) return `${property.onHold} on hold`;
  return "Fully booked";
}

/* --- theme --------------------------------------------------------------- */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("map-theme", theme);
  } catch {
    /* private window: the choice just does not persist */
  }
  if (state.map) {
    state.map.getContainer().classList.toggle("map-dark", theme === "dark");
  }
}

function initTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem("map-theme");
  } catch {
    /* ignore */
  }
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  applyTheme(stored || (prefersLight ? "light" : "dark"));
  els.themeToggle.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}

/* --- data ---------------------------------------------------------------- */

async function loadData() {
  const [properties, universities] = await Promise.all([
    fetch("./data/properties.json").then((r) => r.json()),
    fetch("./data/universities.json")
      .then((r) => r.json())
      .catch(() => ({ universities: [] })),
  ]);

  state.properties = properties.properties.filter((p) => p.lat != null && p.lng != null);
  state.universities = universities.universities || [];

  $("stat-available").textContent = properties.stats.available;
  $("stat-hold").textContent = properties.stats.onHold;
  $("stat-props").textContent = properties.stats.properties;
  $("brand-sub").textContent = `Managed student rooms · ${properties.stats.cities.join(" & ")}`;

  const stamp = new Date(properties.generatedAt);
  $("updated").textContent = `Updated ${stamp.toLocaleDateString("en-IE", {
    day: "numeric",
    month: "short",
  })}, ${stamp.toLocaleTimeString("en-IE", { hour: "2-digit", minute: "2-digit" })}`;

  const areaText = "Hi Acomodo, I'm looking for student accommodation. My area, budget and move-in date:";
  const areaLink = $("request-area");
  areaLink.href = `https://wa.me/${CONFIG.whatsapp}?text=${encodeURIComponent(areaText)}`;
  areaLink.target = "_blank";
  areaLink.rel = "noopener";
}

/* --- controls ------------------------------------------------------------ */

function buildControls() {
  const cities = [...new Set(state.properties.map((p) => p.city))].sort();
  els.seg.innerHTML = "";
  for (const city of ["all", ...cities]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "seg-btn" + (city === "all" ? " is-on" : "");
    button.dataset.city = city;
    button.textContent = city === "all" ? "All" : city;
    els.seg.append(button);
  }

  const grouped = {};
  for (const uni of state.universities) (grouped[uni.city] ||= []).push(uni);
  for (const [city, list] of Object.entries(grouped)) {
    const group = document.createElement("optgroup");
    group.label = city;
    for (const uni of list) {
      const option = document.createElement("option");
      option.value = uni.id;
      option.textContent = uni.name;
      group.append(option);
    }
    els.campus.append(group);
  }

  const types = [...new Set(state.properties.flatMap((p) => p.rooms.map((r) => r.type)))].sort();
  for (const type of types) {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    els.roomtype.append(option);
  }

  const prices = state.properties.map((p) => p.priceMax).filter(Boolean);
  const ceiling = Math.ceil(Math.max(...prices, 1000) / 50) * 50;
  els.price.max = String(ceiling);
  els.price.value = String(ceiling);
  state.maxPrice = Infinity;
}

/* --- filtering ----------------------------------------------------------- */

function sortList(list) {
  const byAvailability = (a, b) =>
    b.available - a.available ||
    (a.priceMin ?? 9e9) - (b.priceMin ?? 9e9) ||
    a.name.localeCompare(b.name);
  const byPrice = (dir) => (a, b) =>
    ((a.priceMin ?? 9e9) - (b.priceMin ?? 9e9)) * dir || a.name.localeCompare(b.name);

  // A place search ranks by proximity by default; an explicit sort still wins.
  let sort = state.sort;
  if (state.searchPlace && sort === "availability") sort = "distance";
  const anchored = state.campus || state.searchPlace;
  if (sort === "distance" && !anchored) sort = "availability";

  if (sort === "distance") list.sort((a, b) => (a._km ?? 9e9) - (b._km ?? 9e9));
  else if (sort === "price-asc") list.sort(byPrice(1));
  else if (sort === "price-desc") list.sort(byPrice(-1));
  else list.sort(byAvailability);
}

function currentFilters() {
  const query = els.q.value.trim().toLowerCase();
  const campus = state.campus;
  return (property) => {
    if (state.city !== "all" && property.city !== state.city) return false;
    if (els.onlyAvailable.checked && property.available < 1) return false;
    if (property.priceMin != null && property.priceMin > state.maxPrice) return false;

    if (els.billsInc.checked && !/included/i.test(property.utilities)) return false;
    if (els.ensuite.checked && !property.rooms.some((r) => /(^|\s)ensuite/i.test(r.type))) {
      return false;
    }
    if (els.shortStay.checked) {
      const short = property.tenancies.some((t) => /4 month|semester/i.test(t));
      if (!short) return false;
    }

    const type = els.roomtype.value;
    if (type && !property.rooms.some((r) => r.type === type)) return false;

    if (els.savedOnly.checked && !state.saved.has(property.id)) return false;

    // In place mode the query named an area, not a property, so don't text-filter
    // it away — every property is shown, ranked by distance to that place.
    if (query && !state.placeMode) {
      const haystack = [
        property.name,
        property.area,
        property.city,
        property.eircode,
        property.address,
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    if (campus && property.city !== campus.city) return false;
    return true;
  };
}

function applyFilters({ fit = true } = {}) {
  const predicate = currentFilters();
  let list = state.properties.filter(predicate);

  // Distance anchor: a chosen campus, or a searched place. Compute _km to it so
  // the list can be ranked by proximity.
  const anchor = state.campus || state.searchPlace;
  if (anchor) {
    for (const property of list) {
      property._km = distanceKm([anchor.lat, anchor.lng], [property.lat, property.lng]);
    }
  } else {
    for (const property of state.properties) delete property._km;
  }
  sortList(list);

  state.filtered = list;
  renderList();
  // A place search flies to its own view; don't yank the map back to fit bounds.
  renderMarkers({ fit: fit && !state.searchPlace });
  syncUrl();
}

/* --- list ---------------------------------------------------------------- */

function cardMarkup(property) {
  const status = statusOf(property);
  const total = Math.max(property.totalBedspaces, 1);
  const pct = (n) => `${(n / total) * 100}%`;
  // Distance label points at whichever anchor set _km: a campus or a searched place.
  const anchor = state.campus || state.searchPlace;
  const anchorName = anchor ? anchor.name || anchor.label || "" : "";
  const near =
    property._km != null && anchor
      ? `<span class="sep">·</span><span>${property._km.toFixed(1)} km to ${esc(anchorName)}</span>`
      : "";

  return `
    <li>
      <article class="card" data-id="${esc(property.id)}" tabindex="0" role="button"
               aria-label="${esc(property.name)}, ${esc(statusLabel(property))}">
        <div class="card-head">
          <div class="card-title">
            <h3>${esc(property.name)}</h3>
            <p>${esc([property.area, property.eircode].filter(Boolean).join(" · "))}</p>
          </div>
          <span class="pill pill-${status}">${esc(statusLabel(property))}</span>
          <button type="button" class="save-btn${state.saved.has(property.id) ? " is-on" : ""}"
                  data-save="${esc(property.id)}" aria-pressed="${state.saved.has(property.id)}"
                  title="Save to shortlist" aria-label="Save ${esc(property.name)} to shortlist">★</button>
        </div>
        <div class="card-facts">
          <span><b>${esc(property.priceDisplay)}</b> /bed</span>
          <span class="sep">·</span>
          <span>${property.totalBedspaces} bedspaces</span>
          ${near}
        </div>
        <div class="bar" aria-hidden="true">
          ${property.available ? `<i class="b-free" style="flex:0 0 ${pct(property.available)}"></i>` : ""}
          ${property.onHold ? `<i class="b-hold" style="flex:0 0 ${pct(property.onHold)}"></i>` : ""}
          ${property.booked ? `<i class="b-full" style="flex:0 0 ${pct(property.booked)}"></i>` : ""}
        </div>
      </article>
    </li>`;
}

function renderList() {
  const list = state.filtered;
  els.count.textContent = `${list.length} propert${list.length === 1 ? "y" : "ies"}`;

  if (!list.length) {
    els.results.innerHTML = `<li><p class="empty">Nothing matches those filters.<br>Try widening the price, or clear the campus.</p></li>`;
    return;
  }
  els.results.innerHTML = list.map(cardMarkup).join("");
}

/* --- map ----------------------------------------------------------------- */

function initMap() {
  state.map = L.map("map", {
    center: CONFIG.home.center,
    zoom: CONFIG.home.zoom,
    zoomControl: false,
    scrollWheelZoom: true,
  });
  L.control.zoom({ position: "bottomright" }).addTo(state.map);

  state.tileLayer = L.tileLayer(CONFIG.tiles, {
    attribution: CONFIG.attribution,
    maxZoom: 19,
  }).addTo(state.map);
  state.map
    .getContainer()
    .classList.toggle("map-dark", document.documentElement.dataset.theme === "dark");

  state.uniLayer = L.layerGroup().addTo(state.map);

  // The map is built before the CSS grid has given its cell a height, so
  // Leaflet starts with a 0×0 size and any early fit collapses to zoom 0.
  // Watch the container: re-measure on every size change, and the first time
  // it reports a real size, fit to the results (unless a card is already open).
  const observer = new ResizeObserver(() => {
    state.map.invalidateSize();
    if (!state.fittedOnce && state.map.getSize().x > 0) {
      state.fittedOnce = true;
      const picked = state.selectedId && state.properties.find((p) => p.id === state.selectedId);
      if (state.searchPlace) {
        state.map.setView([state.searchPlace.lat, state.searchPlace.lng], 14, { animate: false });
      } else if (picked) {
        state.map.setView([picked.lat, picked.lng], 14, { animate: false });
        state.markers.get(picked.id)?.openPopup();
      } else {
        fitToResults({ animate: false });
      }
    }
  });
  observer.observe(document.getElementById("map"));

  if (location.hostname === "127.0.0.1" || location.hostname === "localhost") {
    window.__state = state; // dev-only handle for debugging
  }
}

function markerIcon(property) {
  const status = statusOf(property);
  const label = property.available || property.onHold || "·";
  return L.divIcon({
    className: "",
    html: `<div class="marker marker-${status}" data-id="${esc(property.id)}"><span>${label}</span></div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 28],
    popupAnchor: [0, -26],
  });
}

function popupMarkup(property) {
  return `
    <h4>${esc(property.name)}</h4>
    <p>${esc(property.area || property.city)}</p>
    <p class="pop-price">${esc(property.priceDisplay)} <span style="font-weight:400">/bed/month</span></p>
    <p>${esc(statusLabel(property))} of ${property.totalBedspaces}</p>
    <button type="button" data-open="${esc(property.id)}">View rooms</button>`;
}

function renderMarkers({ fit = true } = {}) {
  for (const marker of state.markers.values()) marker.remove();
  state.markers.clear();

  for (const property of state.filtered) {
    const marker = L.marker([property.lat, property.lng], {
      icon: markerIcon(property),
      title: property.name,
      riseOnHover: true,
    })
      .addTo(state.map)
      .bindPopup(popupMarkup(property));

    marker.on("click", () => selectProperty(property.id, { pan: false }));
    state.markers.set(property.id, marker);
  }

  renderCampusMarkers();

  if (fit) fitToResults();
}

function fitToResults({ animate = true } = {}) {
  // Fitting to a zero-size viewport projects to NaN and throws; the
  // ResizeObserver re-fits the moment the map has real dimensions.
  if (state.map.getSize().x === 0) return;
  const points = state.filtered.map((p) => [p.lat, p.lng]);
  if (state.campus) points.push([state.campus.lat, state.campus.lng]);
  if (points.length > 1) {
    state.map.fitBounds(L.latLngBounds(points).pad(0.18), { animate });
  } else if (points.length === 1) {
    state.map.setView(points[0], 14, { animate });
  } else {
    state.map.setView(CONFIG.home.center, CONFIG.home.zoom, { animate });
  }
}

function renderCampusMarkers() {
  state.uniLayer.clearLayers();
  const visibleCities = new Set(state.filtered.map((p) => p.city));
  if (state.campus) visibleCities.add(state.campus.city);

  for (const uni of state.universities) {
    if (!visibleCities.has(uni.city)) continue;
    const isPicked = state.campus?.id === uni.id;
    L.marker([uni.lat, uni.lng], {
      icon: L.divIcon({
        className: "",
        html: `<div class="uni-marker"></div>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }),
      zIndexOffset: -500,
      interactive: !isPicked,
    })
      .bindTooltip(uni.name, {
        permanent: isPicked,
        direction: "top",
        className: "uni-label",
        offset: [0, -8],
      })
      .addTo(state.uniLayer);
  }
}

/* --- selection & drawer -------------------------------------------------- */

function selectProperty(id, { pan = true } = {}) {
  state.selectedId = id;
  const property = state.properties.find((p) => p.id === id);
  if (!property) return;

  for (const card of els.results.querySelectorAll(".card")) {
    card.classList.toggle("is-active", card.dataset.id === id);
  }
  const card = els.results.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  card?.scrollIntoView({ block: "nearest", behavior: "smooth" });

  // Open the drawer first, so a map hiccup can never block the detail panel.
  openDrawer(property);

  const marker = state.markers.get(id);
  // Popups and flyTo both divide by the map's pixel size; both throw on a
  // still-zero-size map (initial preselect). The ResizeObserver opens the
  // popup once the map has a size, so it is safe to skip here.
  if (marker && state.map.getSize().x > 0) {
    if (pan) {
      state.map.flyTo([property.lat, property.lng], Math.max(state.map.getZoom(), 14), {
        duration: 0.6,
      });
    }
    marker.openPopup();
  }
  syncUrl();
}

function roomRow(room) {
  const tag = room.available
    ? `<span class="tag tag-free">${room.available} free</span>`
    : room.onHold
    ? `<span class="tag tag-hold">${room.onHold} on hold</span>`
    : `<span class="tag tag-full">Booked</span>`;
  const who = room.demography ? ` · ${esc(room.demography)}` : "";
  return `
    <tr>
      <td>
        <strong>${esc(room.type)}</strong><br>
        <span style="color:var(--ink-3)">Room ${esc(room.room)}${
    room.floor ? ` · ${esc(room.floor)}` : ""
  }${who}</span>
      </td>
      <td class="rent">${room.rentDisplay ? esc(room.rentDisplay) : "—"}</td>
      <td>${tag}</td>
    </tr>`;
}

function featureMarkup(features) {
  if (!features) return "";
  const parts = [];
  if (features.summary) parts.push(`<p>${esc(features.summary)}</p>`);
  for (const section of features.sections) {
    parts.push(`<h5>${esc(section.title)}</h5>`);
    if (section.items.length === 1) {
      parts.push(`<p>${esc(section.items[0])}</p>`);
    } else {
      parts.push(`<ul>${section.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`);
    }
  }
  return `<div class="d-section"><h4>About this house</h4><div class="prose">${parts.join("")}</div></div>`;
}

function galleryMarkup(property) {
  const media = property.media || {};
  const images = media.images || [];

  if (images.length) {
    const hero = images[0];
    const thumbs = images
      .map(
        (img, index) => `
        <button type="button" class="g-thumb${index === 0 ? " is-on" : ""}"
                data-gallery="${index}" aria-label="Photo ${index + 1}${
          img.name ? ": " + esc(img.name) : ""
        }">
          <img loading="lazy" src="${esc(imgThumb(img))}" alt="">
        </button>`
      )
      .join("");
    return `
      <figure class="gallery" data-count="${images.length}">
        <button type="button" class="g-hero" data-gallery="0" aria-label="Open photo viewer">
          <img id="g-hero-img" src="${esc(imgFull(hero))}"
               alt="${esc(property.name)} — ${esc(hero.name || "photo")}">
          <span class="g-count">${images.length} photos</span>
        </button>
        <div class="g-strip">${thumbs}</div>
      </figure>`;
  }

  // No cached images yet, but staff have linked a Drive folder — offer it.
  if (media.folder) {
    return `
      <a class="gallery-empty" href="${esc(safeUrl(media.folder))}" target="_blank" rel="noopener">
        <span class="ge-icon" aria-hidden="true">▦</span>
        <span>Photos on Google Drive<small>Opens the property's photo folder</small></span>
        <span class="ge-arrow" aria-hidden="true">↗</span>
      </a>`;
  }
  return "";
}

function setHero(property, index, thumbEl) {
  const img = property?.media?.images?.[index];
  if (!img) return;
  const hero = document.getElementById("g-hero-img");
  if (hero) hero.src = imgFull(img);
  const heroBtn = document.querySelector(".g-hero");
  if (heroBtn) heroBtn.dataset.gallery = String(index);
  for (const t of els.drawerInner.querySelectorAll(".g-thumb")) t.classList.remove("is-on");
  thumbEl?.classList.add("is-on");
}

// Lightbox state for the currently open property's gallery.
const lightbox = { images: [], index: 0 };

function openLightbox(images, index) {
  lightbox.images = images;
  lightbox.index = index;
  renderLightbox();
  els.lightbox.hidden = false;
  document.body.classList.add("lightbox-open");
  els.lightbox.focus();
}

function renderLightbox() {
  const img = lightbox.images[lightbox.index];
  const total = lightbox.images.length;
  els.lightbox.querySelector(".lb-img").src = imgFull(img);
  els.lightbox.querySelector(".lb-img").alt = img.name || "";
  els.lightbox.querySelector(".lb-caption").textContent = img.name || "";
  els.lightbox.querySelector(".lb-index").textContent = `${lightbox.index + 1} / ${total}`;
}

function stepLightbox(delta) {
  const total = lightbox.images.length;
  lightbox.index = (lightbox.index + delta + total) % total;
  renderLightbox();
}

function closeLightbox() {
  els.lightbox.hidden = true;
  document.body.classList.remove("lightbox-open");
}

function openDrawer(property) {
  const waText = `Hi, I'm interested in ${property.name}${
    property.area ? ` (${property.area})` : ""
  } — is it still available?`;
  const whatsapp = `https://wa.me/${CONFIG.whatsapp}?text=${encodeURIComponent(waText)}`;
  const directions = `https://www.google.com/maps/dir/?api=1&destination=${property.lat},${property.lng}`;

  // Live public-transport directions from this property, opened in Google Maps
  // (always current — no timetable to maintain). `dest` may be a place name or
  // be left blank for the visitor to type their own.
  const origin = `${property.lat},${property.lng}`;
  const commuteUrl = (dest) =>
    `https://www.google.com/maps/dir/?api=1&origin=${origin}` +
    (dest ? `&destination=${encodeURIComponent(dest)}` : "") +
    `&travelmode=transit`;

  const nearest = state.universities
    .filter((u) => u.city === property.city)
    .map((u) => ({ ...u, km: distanceKm([property.lat, property.lng], [u.lat, u.lng]) }))
    .sort((a, b) => a.km - b.km)
    .slice(0, 4);

  els.drawerInner.innerHTML = `
    <button type="button" class="d-close" id="d-close" aria-label="Close">×</button>
    <h2 class="d-title">${esc(property.name)}</h2>
    <p class="d-sub">${esc([property.area, property.eircode, property.city].filter(Boolean).join(" · "))}</p>

    ${galleryMarkup(property)}

    <div class="d-stats">
      <dl class="d-stat"><dt>Free</dt><dd style="color:var(--free)">${property.available}</dd></dl>
      <dl class="d-stat"><dt>On hold</dt><dd>${property.onHold}</dd></dl>
      <dl class="d-stat"><dt>Bedspaces</dt><dd>${property.totalBedspaces}</dd></dl>
    </div>

    <div class="d-section">
      <h4>Terms</h4>
      <dl class="facts">
        <dt>Rent</dt><dd>${esc(property.priceDisplay)} per bed / month</dd>
        <dt>Bills</dt><dd>${esc(property.utilities || "—")}</dd>
        <dt>Furnished</dt><dd>${property.furnished ? "Yes" : "—"}</dd>
        <dt>Move in</dt><dd>${esc(property.moveIn.join(" · ") || "—")}</dd>
        <dt>Tenancy</dt><dd>${esc(property.tenancies.join(" · ") || "—")}</dd>
        <dt>Deposit</dt><dd>${esc(property.paymentTerms || "—")}</dd>
      </dl>
    </div>

    <div class="d-section">
      <h4>Rooms</h4>
      <table class="rooms">
        <thead><tr><th>Room</th><th>Rent</th><th>Status</th></tr></thead>
        <tbody>${property.rooms.map(roomRow).join("")}</tbody>
      </table>
    </div>

    <div class="d-section">
      <h4>Plan your commute</h4>
      ${
        nearest.length
          ? `<ul class="commute">${nearest
              .map(
                (u) => `
        <li>
          <span class="commute-name">${esc(u.name)}</span>
          <span class="commute-km">${u.km.toFixed(1)} km</span>
          <a class="commute-go" href="${commuteUrl(`${u.name}, ${u.city}`)}"
             target="_blank" rel="noopener" aria-label="Transit directions to ${esc(u.name)}">
            Route&nbsp;↗
          </a>
        </li>`
              )
              .join("")}</ul>`
          : ""
      }
      <a class="commute-any" href="${commuteUrl("")}" target="_blank" rel="noopener">
        Plan a route to any place ↗
      </a>
      <p class="commute-hint">Live public-transport times, opened in Google Maps.</p>
    </div>

    ${featureMarkup(property.features)}

    <div class="d-actions">
      <a class="btn btn-whatsapp" href="${whatsapp}" target="_blank" rel="noopener">
        ${WHATSAPP_ICON} Enquire on WhatsApp
      </a>
      <a class="btn btn-quiet" href="${directions}" target="_blank" rel="noopener">Directions</a>
    </div>
    <div class="d-actions d-actions-sub">
      <button type="button" class="btn btn-quiet save-btn${state.saved.has(property.id) ? " is-on" : ""}"
              data-save="${esc(property.id)}" aria-pressed="${state.saved.has(property.id)}">
        <span class="save-star">★</span> <span class="save-label">${state.saved.has(property.id) ? "Saved" : "Save"}</span>
      </button>
      <button type="button" class="btn btn-quiet share-btn" data-share="${esc(property.id)}">Share</button>
    </div>
    ${
      property.geoPrecision && property.geoPrecision !== "address"
        ? `<p class="geo-note">Pin is approximate — placed at ${esc(
            property.geoPrecision
          )} level from the address on file.</p>`
        : ""
    }`;

  els.drawer.classList.add("is-open");
  els.drawer.setAttribute("aria-hidden", "false");
  els.scrim.hidden = false;
  $("d-close").focus();
}

function closeDrawer() {
  els.drawer.classList.remove("is-open");
  els.drawer.setAttribute("aria-hidden", "true");
  els.scrim.hidden = true;
  state.selectedId = null;
  for (const card of els.results.querySelectorAll(".card")) card.classList.remove("is-active");
  syncUrl();
}

/* --- url state ----------------------------------------------------------- */

function syncUrl() {
  const params = new URLSearchParams();
  if (state.city !== "all") params.set("city", state.city);
  if (state.campus) params.set("near", state.campus.id);
  if (els.q.value.trim()) params.set("q", els.q.value.trim());
  if (state.maxPrice !== Infinity) params.set("max", String(state.maxPrice));
  if (els.roomtype.value) params.set("type", els.roomtype.value);
  if (!els.onlyAvailable.checked) params.set("all", "1");
  if (els.billsInc.checked) params.set("bills", "1");
  if (els.ensuite.checked) params.set("ensuite", "1");
  if (els.shortStay.checked) params.set("short", "1");
  if (els.savedOnly.checked) params.set("saved", "1");
  if (state.sort !== "availability") params.set("sort", state.sort);
  if (state.selectedId) params.set("p", state.selectedId);

  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function readUrl() {
  const params = new URLSearchParams(location.search);
  if (params.has("city")) state.city = params.get("city");
  if (params.has("q")) els.q.value = params.get("q");
  if (params.has("type")) els.roomtype.value = params.get("type");
  if (params.has("max")) {
    els.price.value = params.get("max");
    state.maxPrice = Number(params.get("max"));
    els.priceOut.textContent = money(state.maxPrice);
  }
  els.onlyAvailable.checked = !params.has("all");
  els.billsInc.checked = params.has("bills");
  els.ensuite.checked = params.has("ensuite");
  els.shortStay.checked = params.has("short");
  els.savedOnly.checked = params.has("saved");

  if (params.has("near")) {
    const uni = state.universities.find((u) => u.id === params.get("near"));
    if (uni) {
      state.campus = uni;
      els.campus.value = uni.id;
      els.sortDistance.hidden = false;
      if (!params.has("city")) state.city = uni.city; // keep the segment in sync
    }
  }
  if (params.has("sort")) {
    state.sort = params.get("sort");
    els.sort.value = state.sort;
  }
  for (const button of els.seg.querySelectorAll(".seg-btn")) {
    button.classList.toggle("is-on", button.dataset.city === state.city);
  }
  return params.get("p");
}

/* --- events -------------------------------------------------------------- */

function wireEvents() {
  els.seg.addEventListener("click", (event) => {
    const button = event.target.closest(".seg-btn");
    if (!button) return;
    state.city = button.dataset.city;
    for (const other of els.seg.querySelectorAll(".seg-btn")) {
      other.classList.toggle("is-on", other === button);
    }
    if (state.campus && state.city !== "all" && state.campus.city !== state.city) {
      state.campus = null;
      els.campus.value = "";
    }
    if (state.searchPlace) clearPlaceSearch({ refit: false });
    applyFilters();
  });

  els.campus.addEventListener("change", () => {
    state.campus = state.universities.find((u) => u.id === els.campus.value) || null;
    if (state.campus) {
      state.city = state.campus.city;
      for (const button of els.seg.querySelectorAll(".seg-btn")) {
        button.classList.toggle("is-on", button.dataset.city === state.city);
      }
      // Picking a campus makes "nearest" available and the natural default.
      els.sortDistance.hidden = false;
      state.sort = "distance";
      els.sort.value = "distance";
    } else {
      els.sortDistance.hidden = true;
      if (state.sort === "distance") {
        state.sort = "availability";
        els.sort.value = "availability";
      }
    }
    applyFilters();
  });

  els.price.addEventListener("input", () => {
    const value = Number(els.price.value);
    state.maxPrice = value >= Number(els.price.max) ? Infinity : value;
    els.priceOut.textContent = state.maxPrice === Infinity ? "any" : money(value);
    applyFilters({ fit: false });
  });

  let searchTimer;
  const handleSearch = async () => {
    const query = els.q.value.trim();
    if (!query) {
      clearPlaceSearch();
      return;
    }
    state.placeMode = false; // try a plain property text-match first
    applyFilters({ fit: !state.searchPlace });
    if (state.filtered.length > 0) {
      if (state.searchPlace) {
        clearPlaceSearch({ refit: false });
        applyFilters();
      }
      return;
    }
    // No property matched the text — treat it as a place and fly there.
    if (query.length >= 3 && query !== state.lastGeocoded) {
      state.lastGeocoded = query;
      await runPlaceSearch(query);
    }
  };
  els.q.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(handleSearch, 350);
  });
  els.q.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      clearTimeout(searchTimer);
      handleSearch();
    }
  });
  els.placeClear.addEventListener("click", () => {
    els.q.value = "";
    els.q.focus();
    clearPlaceSearch();
  });

  for (const box of [els.onlyAvailable, els.billsInc, els.ensuite, els.shortStay, els.roomtype, els.savedOnly]) {
    box.addEventListener("change", () => applyFilters());
  }

  els.sort.addEventListener("change", () => {
    state.sort = els.sort.value;
    applyFilters({ fit: false });
  });

  els.reset.addEventListener("click", () => {
    els.q.value = "";
    els.roomtype.value = "";
    els.campus.value = "";
    els.price.value = els.price.max;
    els.priceOut.textContent = "any";
    els.onlyAvailable.checked = true;
    els.billsInc.checked = els.ensuite.checked = els.shortStay.checked = false;
    els.savedOnly.checked = false;
    els.sort.value = "availability";
    els.sortDistance.hidden = true;
    state.city = "all";
    state.campus = null;
    state.maxPrice = Infinity;
    state.sort = "availability";
    clearPlaceSearch({ refit: false });
    for (const button of els.seg.querySelectorAll(".seg-btn")) {
      button.classList.toggle("is-on", button.dataset.city === "all");
    }
    applyFilters();
  });

  els.results.addEventListener("click", (event) => {
    const save = event.target.closest(".save-btn");
    if (save) {
      event.stopPropagation();
      toggleSaved(save.dataset.save);
      return;
    }
    const card = event.target.closest(".card");
    if (card) selectProperty(card.dataset.id);
  });
  els.results.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".card");
    if (!card) return;
    event.preventDefault();
    selectProperty(card.dataset.id);
  });

  document.addEventListener("click", (event) => {
    const open = event.target.closest("[data-open]");
    if (open) selectProperty(open.dataset.open, { pan: false });
    if (event.target.id === "d-close") closeDrawer();

    // Save / Share buttons inside the drawer.
    const save = event.target.closest(".drawer .save-btn");
    if (save) {
      toggleSaved(save.dataset.save);
      return;
    }
    const share = event.target.closest(".share-btn");
    if (share) {
      shareProperty(share.dataset.share, share);
      return;
    }

    const thumb = event.target.closest("[data-gallery]");
    if (thumb) {
      const property = state.properties.find((p) => p.id === state.selectedId);
      const images = property?.media?.images || [];
      const index = Number(thumb.dataset.gallery);
      // A strip thumbnail just swaps the hero; the hero opens the lightbox.
      if (thumb.classList.contains("g-thumb")) {
        setHero(property, index, thumb);
      } else if (images.length) {
        openLightbox(images, index);
      }
    }
  });

  // Lightbox controls.
  els.lightbox.addEventListener("click", (event) => {
    if (event.target.closest(".lb-next")) return stepLightbox(1);
    if (event.target.closest(".lb-prev")) return stepLightbox(-1);
    if (event.target.closest(".lb-close") || event.target === els.lightbox) closeLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if (els.lightbox.hidden) return;
    if (event.key === "Escape") closeLightbox();
    if (event.key === "ArrowRight") stepLightbox(1);
    if (event.key === "ArrowLeft") stepLightbox(-1);
  });

  els.scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.drawer.classList.contains("is-open")) closeDrawer();
  });

  els.viewToggle.addEventListener("click", () => {
    document.body.classList.toggle("map-view");
    els.viewToggle.textContent = document.body.classList.contains("map-view") ? "List" : "Map";
    if (document.body.classList.contains("map-view")) state.map.invalidateSize();
  });

  window.addEventListener("resize", () => state.map?.invalidateSize());
}

/* --- boot ---------------------------------------------------------------- */

async function main() {
  initTheme();
  try {
    await loadData();
  } catch (error) {
    els.results.innerHTML = `<li><p class="empty">Could not load the availability data.<br><small>${esc(
      error.message
    )}</small></p></li>`;
    return;
  }

  loadSaved();
  buildControls();
  initMap();
  const preselect = readUrl();
  wireEvents();
  applyFilters();
  updateSavedUI();

  // A shared link like ?q=sandymount with no property match should fly there.
  const q = els.q.value.trim();
  if (!preselect && q && state.filtered.length === 0 && q.length >= 3) {
    state.lastGeocoded = q;
    runPlaceSearch(q);
  }

  if (preselect) selectProperty(preselect);

  // Mobile opens on the map; the toggle label always names the other view.
  if (window.matchMedia("(max-width: 860px)").matches) {
    document.body.classList.add("map-view");
    els.viewToggle.textContent = "List";
  }
}

main();
