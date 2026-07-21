/* ------------------------------------------------------------------ *
 * Cadastre napoléonien — V0.0 « Annuaire cartographié »
 *
 * - Carte : MapLibre GL JS (fond OSM raster, sans clé d'API)
 * - Communes : API officielle geo.api.gouv.fr (recherche + contours,
 *   aucune donnée à héberger)
 * - Liens d'archives : table `document` lue dans Supabase (lecture seule)
 *
 * La contribution (ajout de liens) arrive au palier V0.1.
 * ------------------------------------------------------------------ */

const GEO_API = "https://geo.api.gouv.fr/communes";
const COMMUNE_FIELDS = "nom,code,codeDepartement,centre,contour";

/* ------------------------------------------------------------------ *
 * Routage /<region>/<departement>/<commune>  (ex. /bfc/25/25056)
 *
 * GitHub Pages ne sert que des fichiers statiques : une URL profonde
 * tombe en 404. `404.html` la réécrit en `?p=/bfc/25/25056` et renvoie
 * ici, où l'on restaure l'URL propre puis on applique la route.
 * ------------------------------------------------------------------ */
const BASE_PATH = location.hostname.endsWith("github.io")
  ? "/" + (location.pathname.split("/").filter(Boolean)[0] || "") + "/"
  : "/";

// Restaure l'URL propre après le détour par 404.html
(function restoreDeepLink() {
  const p = new URLSearchParams(location.search).get("p");
  if (p) history.replaceState(null, "", BASE_PATH + p.replace(/^\/+/, "") + location.hash);
})();

/* Deux vues symétriques pour une même commune :
 *   /<region>/<dept>/<insee>        → carte
 *   /card/<region>/<dept>/<insee>   → fiche GED  */
function parseRoute() {
  const rest = location.pathname.slice(BASE_PATH.length).replace(/^\/+|\/+$/g, "");
  if (!rest) return null;
  const seg = rest.split("/");
  const vue = seg[0] === "card" ? "ged" : "carte";
  if (vue === "ged") seg.shift();
  const [region, dept, insee] = seg;
  return { vue, region, dept, insee };
}

// insee → chemin public de la commune (null si le département est hors table)
function communePath(insee, deptCode) {
  const dept = deptCode || String(insee || "").slice(0, 2);
  const region = DEPT_TO_REGION[dept];
  return region ? `${BASE_PATH}${region}/${dept}/${insee}` : null;
}

// même commune, côté GED
function cardPath(insee, deptCode) {
  const p = communePath(insee, deptCode);
  return p ? `${BASE_PATH}card/${p.slice(BASE_PATH.length)}` : null;
}

function updateCommuneUrl(c) {
  const path = communePath(c.code, c.codeDepartement);
  if (path && location.pathname !== path) history.replaceState(null, "", path);
}

// Au chargement : ouvre la vue désignée par l'URL (carte ou fiche GED)
async function applyRoute() {
  const r = parseRoute();
  if (!r || !/^\w{5}$/.test(r.insee || "")) return;

  if (r.vue === "ged") {
    showView("docs");
    // openDocs() charge docsStats ; on attend qu'il soit prêt avant d'ouvrir
    await openDocs();
    await openDept(r.dept || r.insee.slice(0, 2));
    revealCard(r.insee);
    return;
  }

  try {
    const res = await fetch(`${GEO_API}/${r.insee}?fields=${COMMUNE_FIELDS}`);
    if (!res.ok) return;
    const c = await res.json();
    if (c && c.code) {
      showView("map");
      selectCommune(c);
    }
  } catch (e) {
    /* deep-link invalide → on reste sur la vue par défaut */
  }
}

/* --- Supabase (optionnel en V0.0 : la carte marche sans) --- */
const sb =
  window.CONFIG && window.CONFIG.SUPABASE_URL && window.CONFIG.SUPABASE_ANON_KEY
    ? window.supabase.createClient(
        window.CONFIG.SUPABASE_URL,
        window.CONFIG.SUPABASE_ANON_KEY
      )
    : null;

/* --- Fonds de carte (OSM + cartes historiques IGN Géoplateforme, WMTS) --- */
const IGN_ATTRIB = "© IGN — Géoplateforme";
function ignWmts(layer, format, tms) {
  return (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
    `&LAYER=${layer}&STYLE=normal&TILEMATRIXSET=${tms}` +
    `&FORMAT=${encodeURIComponent(format)}&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}`
  );
}
const BASEMAPS = {
  osm: {
    label: "OpenStreetMap",
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    attribution: "© OpenStreetMap contributors",
  },
  etatmajor40: {
    label: "État-major 1/40 000 (1820-1866)",
    tiles: [ignWmts("GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40", "image/jpeg", "PM_6_15")],
    attribution: IGN_ATTRIB,
    minzoom: 6,
    maxzoom: 15,
  },
  etatmajor10: {
    label: "État-major environs de Paris (1818-1824)",
    tiles: [ignWmts("GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR10", "image/jpeg", "PM_6_16")],
    attribution: IGN_ATTRIB,
    minzoom: 6,
    maxzoom: 16,
  },
  bdcarto_em3: {
    label: "BD CARTO état-major N3",
    tiles: [ignWmts("BDCARTO_ETAT-MAJOR.NIVEAU3", "image/png", "PM_6_16")],
    attribution: IGN_ATTRIB,
    minzoom: 6,
    maxzoom: 16,
  },
  bdcarto_em4: {
    label: "BD CARTO état-major N4",
    tiles: [ignWmts("BDCARTO_ETAT-MAJOR.NIVEAU4", "image/png", "PM_6_16")],
    attribution: IGN_ATTRIB,
    minzoom: 6,
    maxzoom: 16,
  },
};

/* --- Calques historiques superposables ------------------------------ *
 * Mosaïques déjà géoréférencées publiées par les départements, servies en
 * WMS et affichées PAR-DESSUS le fond courant (à la différence des fonds
 * de BASEMAPS, qui s'excluent mutuellement).
 * MapLibre substitue {bbox-epsg-3857} → le service doit accepter EPSG:3857
 * et renvoyer du PNG transparent avec CORS (vérifié pour le Vaucluse).
 * -------------------------------------------------------------------- */
const OVERLAYS = {
  napo84: {
    label: "Cadastre napoléonien — Vaucluse (84)",
    tiles: [
      "https://imageries.datasud.fr/napo?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap" +
        "&LAYERS=napo84&CRS=EPSG:3857&BBOX={bbox-epsg-3857}" +
        "&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true&STYLES=",
    ],
    attribution:
      '<a href="https://www.data.gouv.fr/datasets/cadastre-napoleonien-geo-reference-vaucluse-et-sections-cadastrales-associees-1-2" target="_blank" rel="noopener">© Département de Vaucluse — Licence Ouverte 2.0</a>',
    opacity: 0.9,
    bounds: [[4.63, 43.65], [5.80, 44.45]], // Vaucluse — cadrage à l'activation
  },
};

/* --- Carte --- */
const baseStyle = { version: 8, sources: {}, layers: [] };
for (const [id, bm] of Object.entries(BASEMAPS)) {
  baseStyle.sources[id] = {
    type: "raster",
    tiles: bm.tiles,
    tileSize: 256,
    attribution: bm.attribution,
    ...(bm.minzoom != null ? { minzoom: bm.minzoom } : {}),
    ...(bm.maxzoom != null ? { maxzoom: bm.maxzoom } : {}),
  };
  baseStyle.layers.push({
    id: `basemap-${id}`,
    type: "raster",
    source: id,
    layout: { visibility: id === "osm" ? "visible" : "none" },
  });
}
// Les calques viennent après les fonds (donc au-dessus), mais avant les
// couches départements/communes ajoutées au `load`.
for (const [id, ov] of Object.entries(OVERLAYS)) {
  baseStyle.sources[`ov-${id}`] = {
    type: "raster",
    tiles: ov.tiles,
    tileSize: 256,
    attribution: ov.attribution,
  };
  baseStyle.layers.push({
    id: `overlay-${id}`,
    type: "raster",
    source: `ov-${id}`,
    layout: { visibility: "none" },
    paint: { "raster-opacity": ov.opacity ?? 1 },
  });
}
const map = new maplibregl.Map({
  container: "map",
  style: baseStyle,
  center: [2.5, 46.6], // France métropolitaine
  zoom: 5,
  maxPitch: 0, // le plugin Allmaps (overlay) ne supporte pas le pitch
});
map.addControl(new maplibregl.NavigationControl(), "top-right");

/* Sélecteur de fond de carte (peuplé depuis BASEMAPS) */
const basemapSelect = document.getElementById("basemap-select");
if (basemapSelect) {
  for (const [id, bm] of Object.entries(BASEMAPS)) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = bm.label;
    basemapSelect.appendChild(opt);
  }
  basemapSelect.addEventListener("change", () => {
    for (const id of Object.keys(BASEMAPS))
      map.setLayoutProperty(
        `basemap-${id}`,
        "visibility",
        id === basemapSelect.value ? "visible" : "none"
      );
  });
}

/* Calques superposables : case à cocher + opacité (un bloc par overlay) */
const overlayListEl = document.getElementById("overlay-list");
if (overlayListEl) {
  for (const [id, ov] of Object.entries(OVERLAYS)) {
    const row = document.createElement("div");
    row.className = "overlay-row";
    row.innerHTML = `
      <label><input type="checkbox" data-overlay="${id}"> ${escape(ov.label)}</label>
      <input type="range" class="overlay-opacity" data-overlay="${id}"
             min="0" max="100" value="${Math.round((ov.opacity ?? 1) * 100)}"
             aria-label="Opacité du calque" disabled>`;
    overlayListEl.appendChild(row);
  }
  // Le style peut ne pas être prêt si l'utilisateur coche très tôt : on
  // diffère alors l'appel, sinon MapLibre lève « non-existing layer ».
  const quandStylePret = (fn) =>
    map.isStyleLoaded() ? fn() : map.once("load", fn);

  overlayListEl.addEventListener("change", (e) => {
    const cb = e.target.closest('input[type="checkbox"][data-overlay]');
    if (!cb) return;
    const id = cb.dataset.overlay;
    quandStylePret(() =>
      map.setLayoutProperty(`overlay-${id}`, "visibility", cb.checked ? "visible" : "none")
    );
    const slider = overlayListEl.querySelector(`.overlay-opacity[data-overlay="${id}"]`);
    if (slider) slider.disabled = !cb.checked;
    // premier affichage : cadrer sur l'emprise du calque
    if (cb.checked && OVERLAYS[id].bounds) map.fitBounds(OVERLAYS[id].bounds, { padding: 30 });
  });
  overlayListEl.addEventListener("input", (e) => {
    const sl = e.target.closest(".overlay-opacity[data-overlay]");
    if (!sl) return;
    quandStylePret(() =>
      map.setPaintProperty(`overlay-${sl.dataset.overlay}`, "raster-opacity", +sl.value / 100)
    );
  });
}

/* ------------------------------------------------------------------ *
 * Codes couleur de statut — partagés par les contours communes ET
 * départements (même stroke / même fill).
 * ------------------------------------------------------------------ */
const STATUS_COLOR = {
  georef: "#2e9e4f",       // vert
  georef_ready: "#e0a800", // jaune
  iiif_only: "#e07b1a",    // orange
  absent: "#c0392b",       // rouge
  loading: "#9a948c",      // gris (neutre / en cours)
};

/* Niveau d'avancement par département — échelle N1 (rouge) → N5 (vert) de
 * l'état des lieux national (voir ETAT_DES_LIEUX.md / CSV, 2026-07-20). */
const NIVEAU_COLOR = {
  N5: "#2e9e4f", // vert       — vectorisé disponible
  N4: "#7cb342", // vert clair — géoréférencé / moissonnable FA+IIIF
  N3: "#e0a800", // jaune      — open data téléchargeable
  N2: "#e07b1a", // orange     — visualiseur AD uniquement
  N1: "#c0392b", // rouge      — partiel / incertain
};
const DEPT_NIVEAU = {
  // N5 — vectorisé disponible
  "22":"N5","29":"N5","35":"N5","56":"N5","84":"N5","85":"N5","92":"N5",
  // N4 — géoréférencé et/ou moissonnable FranceArchives + IIIF
  "01":"N4","16":"N4","79":"N4","82":"N4","88":"N4","93":"N4","95":"N4",
  // N3 — open data téléchargeable
  "25":"N3","31":"N3","71":"N3",
  // N2 — visualiseur AD uniquement (75 hors périmètre stats, renseigné quand même)
  "02":"N2","03":"N2","04":"N2","05":"N2","06":"N2","07":"N2","08":"N2","10":"N2","11":"N2",
  "12":"N2","13":"N2","14":"N2","15":"N2","17":"N2","18":"N2","19":"N2","21":"N2","23":"N2",
  "24":"N2","26":"N2","27":"N2","28":"N2","30":"N2","32":"N2","33":"N2","34":"N2","36":"N2",
  "37":"N2","38":"N2","39":"N2","40":"N2","41":"N2","42":"N2","43":"N2","44":"N2","45":"N2",
  "46":"N2","47":"N2","48":"N2","49":"N2","50":"N2","51":"N2","52":"N2","53":"N2","54":"N2",
  "55":"N2","57":"N2","58":"N2","59":"N2","60":"N2","61":"N2","62":"N2","63":"N2","64":"N2",
  "65":"N2","66":"N2","67":"N2","68":"N2","69":"N2","70":"N2","72":"N2","73":"N2","74":"N2",
  "75":"N2","76":"N2","77":"N2","78":"N2","80":"N2","81":"N2","83":"N2","86":"N2","87":"N2",
  "89":"N2","90":"N2","91":"N2","94":"N2",
  // N1 — partiel / incertain
  "09":"N1","2A":"N1","2B":"N1",
};
const DEPT_NEUTRAL = "#b8b2a8"; // stroke des départements hors métropole/inconnus

// code département → couleur de niveau, sinon neutre
function deptColorExpr() {
  const expr = ["match", ["get", "code"]];
  for (const [code, niveau] of Object.entries(DEPT_NIVEAU))
    expr.push(code, NIVEAU_COLOR[niveau]);
  expr.push(DEPT_NEUTRAL);
  return expr;
}
// fill seulement pour les départements à niveau connu (même opacité que les communes)
function deptFillOpacityExpr() {
  return ["case", ["in", ["get", "code"], ["literal", Object.keys(DEPT_NIVEAU)]], 0.12, 0];
}

/* Source + couches : départements (au démarrage) puis commune sélectionnée */
map.on("load", () => {
  // Contours des départements — sous les couches commune
  map.addSource("departements", {
    type: "geojson",
    data: "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/departements-version-simplifiee.geojson",
  });
  map.addLayer({
    id: "departements-fill",
    type: "fill",
    source: "departements",
    paint: {
      "fill-color": deptColorExpr(),
      "fill-opacity": deptFillOpacityExpr(),
    },
  });
  map.addLayer({
    id: "departements-line",
    type: "line",
    source: "departements",
    paint: {
      "line-color": deptColorExpr(),
      "line-width": 2,
    },
  });

  map.addSource("commune", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "commune-fill",
    type: "fill",
    source: "commune",
    paint: { "fill-color": "#8a5a2b", "fill-opacity": 0.12 },
  });
  map.addLayer({
    id: "commune-line",
    type: "line",
    source: "commune",
    paint: { "line-color": "#8a5a2b", "line-width": 2 },
  });
});

/* --- Sélection d'une commune (objet { nom, code, codeDepartement, centre, contour }) --- */
let selectionToken = 0; // ignore les résolutions async d'une commune déjà remplacée

async function selectCommune(c) {
  const token = ++selectionToken;
  hideResults();
  searchInput.value = c.nom;
  clearOverlay();
  updateCommuneUrl(c); // URL partageable /<region>/<dept>/<insee>

  if (c.contour && map.getSource("commune")) {
    map.getSource("commune").setData({
      type: "Feature",
      geometry: c.contour,
      properties: {},
    });
    setCommuneColor(STATUS_COLOR.loading); // gris : statut en cours d'évaluation
    const b = new maplibregl.LngLatBounds();
    eachCoord(c.contour, ([lng, lat]) => b.extend([lng, lat]));
    map.fitBounds(b, { padding: 40, maxZoom: 14 });
  } else if (c.centre) {
    map.flyTo({ center: c.centre.coordinates, zoom: 13 });
  }

  renderCommune(c, null, true); // état "chargement"
  const docs = await fetchDocuments(c.code);
  if (token !== selectionToken) return;
  renderCommune(c, docs, false);

  // Statut de géoréférencement → couleur du contour (+ overlay Allmaps si calé)
  if (Array.isArray(docs)) {
    const st = await communeStatus(docs);
    if (token !== selectionToken) return;
    setCommuneColor(STATUS_COLOR[st.status]);
    if (st.status === "georef" && st.annotationUrl) showOverlay(st.annotationUrl);
  } else {
    setCommuneColor(STATUS_COLOR.loading); // Supabase non connecté : neutre
  }
}

/* --- Lecture des liens d'archives dans Supabase --- */
async function fetchDocuments(insee) {
  if (!sb) return null; // Supabase non configuré
  const { data, error } = await sb
    .from("document")
    .select("type, section_lettre, feuille_num, annee, cote, archive_url, iiif_manifest, licence_overlay_ok, source, source_url, statut")
    .eq("insee", insee)
    .order("type")
    .order("section_lettre", { nullsFirst: true })
    .order("feuille_num", { nullsFirst: true });
  if (error) {
    console.error("Supabase:", error.message);
    return null;
  }
  return data;
}

/* ------------------------------------------------------------------ *
 * Rendu de la fiche commune
 * ------------------------------------------------------------------ */
const TYPE_LABEL = {
  tableau_assemblage: "Tableau d'assemblage",
  section: "Sections",
  feuille: "Feuilles",
};
const TYPE_ORDER = ["tableau_assemblage", "section", "feuille"];

function renderCommune(c, docs, loading) {
  const el = document.getElementById("commune-info");
  el.classList.remove("placeholder");

  let html = `
    <h2 class="commune-title">${escape(c.nom)}</h2>
    <p class="commune-sub">INSEE ${escape(c.code)} · département ${escape(
    c.codeDepartement || c.code.slice(0, 2)
  )}</p>`;

  if (loading) {
    html += `<p class="empty-state">Recherche des plans disponibles…</p>`;
  } else if (docs === null) {
    html += `<div class="empty-state">
      <strong>Base de liens non connectée.</strong><br>
      Renseignez Supabase dans <code>config.js</code> pour afficher les plans,
      ou ouvrez directement le portail d'archives du département.
    </div>`;
  } else if (docs.length === 0) {
    html += `<div class="empty-state">
      <strong>Aucun plan référencé pour cette commune.</strong>
    </div>`;
  } else {
    html += sourceFooter(docs); // attribution en tête de fiche
    for (const type of TYPE_ORDER) {
      const group = docs.filter((d) => d.type === type);
      if (!group.length) continue;
      html += `<div class="doc-group"><h3>${TYPE_LABEL[type] || type}</h3>`;
      for (const d of group) html += docItem(d);
      html += `</div>`;
    }
  }
  el.innerHTML = html;
  if (!loading && Array.isArray(docs) && docs.length) hydrateGeoref(el, c.code);
}

/* ------------------------------------------------------------------ *
 * Géoréférencement via Allmaps (zéro infra : Allmaps stocke + rend)
 *
 * - Détection : generateId(manifeste) → annotations.allmaps.org/manifests/{id}
 * - Déjà calé   → badge + lien Allmaps Viewer (se centre seul sur l'emprise)
 * - Pas calé    → bouton vers Allmaps Editor, manifeste IIIF pré-saisi
 * Aucune annotation n'est stockée chez nous en V1 (cf. dump open-data Allmaps
 * pour un mirroring ultérieur si besoin de curation).
 * ------------------------------------------------------------------ */
const editorLink = (manifest) =>
  `https://editor.allmaps.org/?url=${encodeURIComponent(manifest)}`;
const viewerLink = (annotationUrl) =>
  `https://viewer.allmaps.org/?url=${encodeURIComponent(annotationUrl)}`;

// `@allmaps/id` chargé en import() dynamique → app.js reste un script classique.
// Variant `/sync` (SHA-1 pur-JS) : pas de SubtleCrypto, marche aussi en file://.
let allmapsIdMod = null;
const loadAllmapsId = () =>
  (allmapsIdMod ||= import("https://esm.run/@allmaps/id/sync"));

// manifeste → URL d'annotation (ou null si pas encore géoréférencé). Mis en cache.
const annotationCache = new Map();
async function resolveAnnotation(manifest) {
  if (annotationCache.has(manifest)) return annotationCache.get(manifest);
  let result = null;
  try {
    const { generateId } = await loadAllmapsId();
    const id = await generateId(manifest);
    const url = `https://annotations.allmaps.org/manifests/${id}`;
    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      if ((data.items?.length ?? 0) > 0) result = url;
    }
  } catch (e) {
    console.warn("Allmaps:", e); // hors-ligne / API down → on propose d'éditer
  }
  annotationCache.set(manifest, result);
  return result;
}

async function hydrateGeoref(root, fallbackInsee) {
  for (const block of root.querySelectorAll(".georef[data-manifest]")) {
    const manifest = block.dataset.manifest;
    const annotationUrl = await resolveAnnotation(manifest);
    if (!block.isConnected) return; // commune changée pendant le fetch
    if (!annotationUrl) {
      block.innerHTML = `<a class="georef-btn" href="${escape(
        editorLink(manifest)
      )}" target="_blank" rel="noopener">Géoréférencer ce plan ↗</a>`;
      continue;
    }
    // Plan calé : on renvoie vers NOTRE carte (l'overlay y est rendu par
    // @allmaps/maplibre), avec repli sur le viewer Allmaps si la commune
    // n'est pas résoluble en route locale.
    const insee = block.dataset.insee || fallbackInsee;
    const local = insee ? communePath(insee) : null;
    block.innerHTML =
      `<span class="georef-badge">✓ géoréférencé</span>` +
      (local
        ? `<a class="georef-link" href="${escape(local)}" data-insee="${escape(
            insee
          )}">Voir l'overlay</a>`
        : `<a class="georef-link" href="${escape(
            viewerLink(annotationUrl)
          )}" target="_blank" rel="noopener">Voir l'overlay ↗</a>`);
  }
}

/* Navigation interne (sans rechargement) — deux sens :
 *  · vers la carte : « Voir l'overlay » et titre d'une card GED
 *  · vers la GED   : titre d'une fiche du panneau carte             */
document.addEventListener("click", async (e) => {
  const versCarte = e.target.closest("a.georef-link[data-insee], a.ged-to-map[data-map-insee]");
  if (versCarte) {
    e.preventDefault();
    const insee = versCarte.dataset.insee || versCarte.dataset.mapInsee;
    try {
      const res = await fetch(`${GEO_API}/${insee}?fields=${COMMUNE_FIELDS}`);
      if (!res.ok) return;
      showView("map");
      selectCommune(await res.json());
    } catch (err) {
      location.href = versCarte.getAttribute("href"); // repli
    }
    return;
  }

  const versGed = e.target.closest("a.map-to-ged[data-ged-insee]");
  if (versGed) {
    e.preventDefault();
    const insee = versGed.dataset.gedInsee;
    showView("docs");
    await openDocs();
    await openDept(insee.slice(0, 2));
    revealCard(insee);
  }
});

/* ------------------------------------------------------------------ *
 * Statut de géoréférencement par commune → couleur du contour
 *   vert    : annotation Allmaps existante (overlay affiché)
 *   jaune   : tableau d'assemblage IIIF + licence OK, pas encore calé
 *   orange  : assemblage présent mais géoréf non accessible
 *             (licence overlay refusée, ou pas de manifeste IIIF)
 *   rouge   : aucun tableau d'assemblage
 * (codes couleur définis en tête de fichier : STATUS_COLOR)
 * ------------------------------------------------------------------ */
function setCommuneColor(color) {
  if (!map.getLayer("commune-fill")) return;
  map.setPaintProperty("commune-fill", "fill-color", color);
  map.setPaintProperty("commune-line", "line-color", color);
}

async function communeStatus(docs) {
  const assemblages = docs.filter((d) => d.type === "tableau_assemblage");
  if (!assemblages.length) return { status: "absent" };

  const withIiif = assemblages.find((d) => d.iiif_manifest);
  if (!withIiif) return { status: "iiif_only" }; // assemblage sans IIIF → non géoréférençable
  if (!withIiif.licence_overlay_ok)
    return { status: "iiif_only", manifest: withIiif.iiif_manifest }; // licence overlay refusée

  const annotationUrl = await resolveAnnotation(withIiif.iiif_manifest);
  return annotationUrl
    ? { status: "georef", manifest: withIiif.iiif_manifest, annotationUrl }
    : { status: "georef_ready", manifest: withIiif.iiif_manifest };
}

/* ------------------------------------------------------------------ *
 * Overlay du plan calé, rendu sur NOTRE carte via @allmaps/maplibre.
 * Import dynamique isolé : si le module échoue (CDN…), seul l'overlay est
 * désactivé — la carte et la coloration des contours restent intactes.
 * ------------------------------------------------------------------ */
let warpedCtorPromise = null;
const loadWarpedLayer = () =>
  (warpedCtorPromise ||= import("https://esm.run/@allmaps/maplibre").then(
    (m) => m.WarpedMapLayer
  ));

let warpedLayer = null;
async function showOverlay(annotationUrl) {
  try {
    if (!warpedLayer) {
      const WarpedMapLayer = await loadWarpedLayer();
      warpedLayer = new WarpedMapLayer({ layerId: "allmaps-overlay" });
      // sous le contour pour garder la couleur de statut visible au-dessus
      map.addLayer(warpedLayer, "commune-fill");
    }
    await warpedLayer.clear();
    await warpedLayer.addGeoreferenceAnnotationByUrl(annotationUrl);
  } catch (e) {
    console.warn("Overlay Allmaps indisponible:", e);
  }
}

function clearOverlay() {
  if (warpedLayer) {
    try {
      warpedLayer.clear();
    } catch (e) {
      /* no-op */
    }
  }
}

/* Mention d'attribution (CRPA) : une ligne par source distincte. */
function sourceFooter(docs) {
  const seen = new Map();
  for (const d of docs) {
    if (d.source && !seen.has(d.source)) seen.set(d.source, d.source_url);
  }
  if (!seen.size) return "";
  const items = [...seen]
    .map(([name, url]) =>
      url
        ? `<a href="${escape(url)}" target="_blank" rel="noopener">${escape(name)}</a>`
        : escape(name)
    )
    .join(", ");
  return `<p class="source-note">Source : ${items}</p>`;
}

function docItem(d) {
  let label = "Plan";
  if (d.type === "section")
    label = d.section_lettre ? `Section ${d.section_lettre}` : (d.cote || "Section");
  else if (d.type === "feuille")
    label = d.section_lettre
      ? `Section ${d.section_lettre} — feuille ${d.feuille_num ?? "?"}`
      : (d.cote || "Feuille");
  else if (d.type === "tableau_assemblage") label = "Tableau d'assemblage";

  // cote en meta si elle ne sert pas déjà de libellé
  const metaParts = [d.annee];
  if (label !== d.cote) metaParts.push(d.cote);
  const meta = metaParts.filter(Boolean).join(" · ");
  let html = `<div class="doc-item">
    <a href="${escape(d.archive_url)}" target="_blank" rel="noopener">${escape(
    label
  )} ↗</a>
    ${meta ? `<span class="meta">${escape(meta)}</span>` : ""}
  </div>`;

  // Géoréférencement Allmaps : seulement sur l'assemblage, avec manifeste IIIF,
  // et uniquement si la licence autorise l'overlay (règle CRPA). Le statut réel
  // (déjà géoréférencé ou non) est résolu en asynchrone par hydrateGeoref().
  if (d.type === "tableau_assemblage" && d.iiif_manifest && d.licence_overlay_ok) {
    html += `<div class="georef" data-manifest="${escape(d.iiif_manifest)}">
      <span class="georef-loading">Vérification du géoréférencement…</span>
    </div>`;
  }
  return html;
}

/* ------------------------------------------------------------------ *
 * Recherche par nom (autocomplete sur geo.api.gouv.fr)
 * ------------------------------------------------------------------ */
const searchInput = document.getElementById("search-input");
const resultsEl = document.getElementById("search-results");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 2) return hideResults();
  searchTimer = setTimeout(() => runSearch(q), 220);
});

async function runSearch(q) {
  const url = `${GEO_API}?nom=${encodeURIComponent(
    q
  )}&fields=${COMMUNE_FIELDS}&boost=population&limit=8`;
  try {
    const res = await fetch(url);
    const communes = await res.json();
    showResults(communes);
  } catch (e) {
    console.error("geo.api.gouv.fr:", e);
  }
}

function showResults(communes) {
  if (!communes.length) return hideResults();
  resultsEl.innerHTML = communes
    .map(
      (c) =>
        `<li data-code="${c.code}">${escape(c.nom)} <span class="dep">(${
          c.codeDepartement || ""
        })</span></li>`
    )
    .join("");
  resultsEl.hidden = false;
  resultsEl.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => {
      const c = communes.find((x) => x.code === li.dataset.code);
      if (c) selectCommune(c);
    });
  });
}

function hideResults() {
  resultsEl.hidden = true;
  resultsEl.innerHTML = "";
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".search")) hideResults();
});

/* ------------------------------------------------------------------ *
 * Clic sur la carte → commune au point (recherche géographique inverse)
 * ------------------------------------------------------------------ */
map.on("click", async (e) => {
  const { lng, lat } = e.lngLat;
  const url = `${GEO_API}?lat=${lat}&lon=${lng}&fields=${COMMUNE_FIELDS}`;
  try {
    const res = await fetch(url);
    const communes = await res.json();
    if (communes.length) selectCommune(communes[0]);
  } catch (err) {
    console.error("geo.api.gouv.fr (clic):", err);
  }
});

/* ------------------------------------------------------------------ *
 * Utilitaires
 * ------------------------------------------------------------------ */
function eachCoord(geometry, fn) {
  const walk = (a) => {
    if (typeof a[0] === "number") fn(a);
    else a.forEach(walk);
  };
  walk(geometry.coordinates);
}

function escape(s) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (m) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m])
  );
}

/* ================================================================== *
 * Onglet « Documents » — GED (drill-down Départements → Communes)
 *
 * Données : un seul fetch de la table `document`, regroupé par
 * département (préfixe INSEE) puis commune. Les noms (dépt + communes)
 * sont résolus via geo.api.gouv.fr (la table `commune` peut être vide).
 * ================================================================== */

const docsGridEl = () => document.getElementById("docs-grid");

/* --- Bascule Carte / Documents --- */
function showView(view) {
  const isMap = view === "map";
  document.getElementById("layout").hidden = !isMap;
  document.getElementById("docs-view").hidden = isMap;
  document
    .querySelectorAll("#view-toggle button")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (isMap) map.resize(); // MapLibre recalcule sa taille au retour de l'onglet
  else openDocs();
}
document.querySelectorAll("#view-toggle button").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view))
);

/* --- Données -----------------------------------------------------------
 * docsStats : Map(dept → {code, nom, total, overlay_ok, with_iiif,
 *   nb_assemblages, nb_sections, nb_feuilles, nb_communes}) — 1 requête
 *   sur la vue v_document_stats_dept, chargée à l'ouverture de l'onglet.
 * docsData : Map(dept → {code, nom, communes: Map(insee → {...docs[]})})
 *   — chargée département par département via loadDeptData(code),
 *   la première fois qu'on entre dans le dept.
 * Cette approche remplace le download initial de ~30 000 lignes (30 requêtes
 * séquentielles) par 1 requête d'agrégats + N requêtes par dept à la demande.
 * ---------------------------------------------------------------------- */
let docsStats = null;
let docsData = new Map();
const _deptNamesCache = new Map(); // code → nom

async function loadDocsStats() {
  if (docsStats || !sb) return docsStats;
  // Résoudre les noms de départements (1 seule requête geo.api)
  try {
    const res = await fetch("https://geo.api.gouv.fr/departements?fields=nom,code");
    for (const { code, nom } of await res.json()) _deptNamesCache.set(code, nom);
  } catch (e) { /* les codes serviront de nom */ }

  // Chemin rapide : la vue d'agrégats (Phase 4, 1 requête légère).
  const { data, error } = await sb
    .from("v_document_stats_dept")
    .select("*")
    .order("dept");
  if (!error && data) {
    docsStats = new Map();
    for (const row of data)
      docsStats.set(row.dept, {
        code: row.dept,
        nom: _deptNamesCache.get(row.dept) || row.dept,
        ...row,
      });
    await addGeorefCounts();
    return docsStats;
  }
  console.warn("Vue v_document_stats_dept indisponible, fallback agrégation côté client :", error?.message);

  // Fallback : agréger côté client depuis document.insee. On ne remonte que
  // l'insee (pas de colonnes lourdes) → PostgREST plafonné à 1000 lignes,
  // on pagine. Sur 30 000 lignes ≈ 30 requêtes légères.
  const PAGE = 1000;
  const all = [];
  for (let from = 0; ; from += PAGE) {
    const { data: page, error: e2 } = await sb
      .from("document")
      .select("insee,type,iiif_manifest,licence_overlay_ok")
      .order("insee")
      .range(from, from + PAGE - 1);
    if (e2) { console.error("Supabase (fallback stats):", e2.message); return null; }
    all.push(...page);
    if (page.length < PAGE) break;
  }
  const agg = new Map();
  for (const d of all) {
    const dept = (d.insee || "").slice(0, 2);
    const s = agg.get(dept) || {
      total: 0, overlay_ok: 0, with_iiif: 0,
      nb_assemblages: 0, nb_sections: 0, nb_feuilles: 0,
      _communes: new Set(),
    };
    s.total++;
    if (d.licence_overlay_ok) s.overlay_ok++;
    if (d.iiif_manifest) s.with_iiif++;
    if (d.type === "tableau_assemblage") s.nb_assemblages++;
    else if (d.type === "section") s.nb_sections++;
    else if (d.type === "feuille") s.nb_feuilles++;
    s._communes.add(d.insee);
    agg.set(dept, s);
  }
  docsStats = new Map();
  for (const [dept, s] of agg) {
    s.nb_communes = s._communes.size;
    delete s._communes;
    docsStats.set(dept, { code: dept, nom: _deptNamesCache.get(dept) || dept, dept, ...s });
  }
  return docsStats;
}

/* Nombre de tableaux d'assemblage réellement géoréférencés (colonne `georef`,
 * alimentée par harvest/refresh_georef_status.py depuis l'API Allmaps).
 * Une seule requête : les plans calés restent peu nombreux. */
async function addGeorefCounts() {
  for (const s of docsStats.values()) s.nb_georef = 0;
  const { data, error } = await sb
    .from("document")
    .select("insee")
    .eq("type", "tableau_assemblage")
    .not("georef", "is", null)
    .limit(10000);
  if (error || !data) return;
  for (const d of data) {
    const s = docsStats.get((d.insee || "").slice(0, 2));
    if (s) s.nb_georef++;
  }
}

// « X documents · Y communes · Z % géoréférencé » (Z = part des tableaux
// d'assemblage effectivement calés dans Allmaps)
function deptMeta(s) {
  const pct = s.nb_assemblages
    ? Math.round((100 * (s.nb_georef || 0)) / s.nb_assemblages)
    : 0;
  return `${s.total.toLocaleString("fr")} document${s.total > 1 ? "s" : ""} · ` +
         `${s.nb_communes} commune${s.nb_communes > 1 ? "s" : ""} · ` +
         `${pct} % géoréférencé`;
}

async function loadDeptData(code) {
  if (docsData.has(code) && docsData.get(code)._loaded) return docsData.get(code);
  const PAGE = 1000;
  const data = [];
  for (let from = 0; ; from += PAGE) {
    const { data: page, error } = await sb
      .from("document")
      .select(
        "insee,type,section_lettre,feuille_num,annee,cote,archive_url,iiif_manifest,image_url,licence_overlay_ok,georef"
      )
      .like("insee", `${code}%`)
      .order("insee")
      .range(from, from + PAGE - 1);
    if (error) { console.error("Supabase (dept):", error.message); break; }
    data.push(...page);
    if (page.length < PAGE) break;
  }
  const db = {
    code,
    nom: _deptNamesCache.get(code) || code,
    communes: new Map(),
    _loaded: true,
  };
  for (const d of data) {
    if (!db.communes.has(d.insee))
      db.communes.set(d.insee, { insee: d.insee, nom: d.insee, docs: [] });
    db.communes.get(d.insee).docs.push(d);
  }
  // Noms de communes via geo.api (1 requête / dept)
  try {
    const res = await fetch(
      `https://geo.api.gouv.fr/communes?codeDepartement=${code}&fields=nom,code`
    );
    const map = new Map((await res.json()).map((x) => [x.code, x.nom]));
    for (const [insee, c] of db.communes) if (map.has(insee)) c.nom = map.get(insee);
  } catch (e) { /* garde l'insee */ }
  docsData.set(code, db);
  return db;
}

/* --- Entrée dans l'onglet --- */
async function openDocs() {
  const grid = docsGridEl();
  if (!sb) {
    grid.innerHTML = `<p class="empty-state">Base non connectée — renseignez Supabase dans <code>config.js</code>.</p>`;
    return;
  }
  if (!docsStats) {
    grid.innerHTML = `<p class="empty-state">Chargement des documents…</p>`;
    await loadDocsStats();
  }
  if (docsStats) renderRegionCards();
}

/* --- Bouton rafraîchir --- */
document.getElementById("docs-refresh-btn")?.addEventListener("click", async () => {
  docsStats = null;
  docsData = new Map();
  await openDocs();
});

/* --- Realtime : refresh automatique à chaque INSERT dans document ------ *
 * Debounce 500 ms : un chargement de seed (~5 000 lignes) déclenche
 * autant d'events INSERT, on les regroupe pour ne recharger qu'une fois.
 * ---------------------------------------------------------------------- */
let _rtTimer = null;
if (sb) {
  sb.channel("document-inserts")
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "document" }, () => {
      clearTimeout(_rtTimer);
      _rtTimer = setTimeout(() => {
        docsStats = null;
        docsData = new Map();
        if (!document.getElementById("docs-view").hidden) openDocs();
      }, 500);
    })
    .subscribe();
}

/* --- Régions administratives (17 : métropole + Corse + DROM/Paris hors nav) -- *
 * Mapping code_dept → id_région ; libellés dans REGIONS. Une région peut
 * n'être qu'une case grisée si aucun de ses départements n'est chargé.
 * -------------------------------------------------------------------------- */
const REGIONS = {
  ara:  { nom: "Auvergne-Rhône-Alpes",         depts: ["01","03","07","15","26","38","42","43","63","69","73","74"] },
  bfc:  { nom: "Bourgogne-Franche-Comté",      depts: ["21","25","39","58","70","71","89","90"] },
  bre:  { nom: "Bretagne",                     depts: ["22","29","35","56"] },
  cvl:  { nom: "Centre-Val de Loire",          depts: ["18","28","36","37","41","45"] },
  cor:  { nom: "Corse",                        depts: ["2A","2B"] },
  ges:  { nom: "Grand Est",                    depts: ["08","10","51","52","54","55","57","67","68","88"] },
  hdf:  { nom: "Hauts-de-France",              depts: ["02","59","60","62","80"] },
  idf:  { nom: "Île-de-France",                depts: ["75","77","78","91","92","93","94","95"] },
  nor:  { nom: "Normandie",                    depts: ["14","27","50","61","76"] },
  naq:  { nom: "Nouvelle-Aquitaine",           depts: ["16","17","19","23","24","33","40","47","64","79","86","87"] },
  occ:  { nom: "Occitanie",                    depts: ["09","11","12","30","31","32","34","46","48","65","66","81","82"] },
  pdl:  { nom: "Pays de la Loire",             depts: ["44","49","53","72","85"] },
  pac:  { nom: "Provence-Alpes-Côte d'Azur",   depts: ["04","05","06","13","83","84"] },
};
const DEPT_TO_REGION = Object.fromEntries(
  Object.entries(REGIONS).flatMap(([id, r]) => r.depts.map((d) => [d, id]))
);

/* --- Niveau -1 : cards régions --- */
function renderRegionCards() {
  setBreadcrumb([{ label: "Régions" }]);
  hideDeptFacets();
  const grid = docsGridEl();
  // Agréger par région les compteurs depuis la vue docsStats (aucun accès
  // aux docs détaillés — la card région n'a pas de vignette IIIF).
  const stats = new Map();
  for (const s of docsStats.values()) {
    const r = DEPT_TO_REGION[s.code];
    if (!r) continue;
    const acc = stats.get(r) || { nbDocs: 0, nbDepts: 0 };
    acc.nbDocs += s.total;
    acc.nbDepts += 1;
    stats.set(r, acc);
  }
  const cards = Object.entries(REGIONS).map(([id, r]) => {
    const s = stats.get(id) || { nbDocs: 0, nbDepts: 0 };
    const empty = s.nbDepts === 0;
    const meta = empty
      ? `<span class="ged-muted">${r.depts.length} départements · données à venir</span>`
      : `${s.nbDepts} / ${r.depts.length} départements · ${s.nbDocs.toLocaleString("fr")} documents`;
    return `<button class="ged-card region${empty ? " ged-empty" : ""}" data-region="${id}">
      <div class="ged-thumb"><span class="ged-thumb-ph">🗺️</span></div>
      <div class="ged-card-body">
        <h3>${escape(r.nom)}</h3>
        <p class="ged-meta">${meta}</p>
      </div>
    </button>`;
  });
  grid.innerHTML = cards.join("");
  grid.querySelectorAll("[data-region]").forEach((el) => {
    el.addEventListener("click", () => openRegion(el.dataset.region));
  });
}

/* --- Niveau 0 : cards départements d'une région --- */
function openRegion(regId) {
  const region = REGIONS[regId];
  if (!region) return;
  setBreadcrumb([
    { label: "Régions", onClick: renderRegionCards },
    { label: region.nom },
  ]);
  hideDeptFacets();
  const grid = docsGridEl();
  // Cards depuis docsStats (aucun accès aux docs détaillés à ce niveau)
  const cards = region.depts.map((code) => {
    const s = docsStats.get(code);
    if (s) {
      return `<button class="ged-card" data-dept="${escape(code)}">
        <div class="ged-thumb"><span class="ged-thumb-ph">🗺️</span></div>
        <div class="ged-card-body">
          <h3>${escape(s.nom)} <span class="ged-code">${escape(code)}</span></h3>
          <p class="ged-meta">${deptMeta(s)}</p>
        </div>
      </button>`;
    }
    return `<div class="ged-card ged-empty">
      <div class="ged-thumb"><span class="ged-thumb-ph">🗺️</span></div>
      <div class="ged-card-body">
        <h3>Département ${escape(code)} <span class="ged-code">${escape(code)}</span></h3>
        <p class="ged-meta ged-muted">Aucun document chargé pour l'instant</p>
      </div>
    </div>`;
  });
  grid.innerHTML = cards.join("");
  grid.querySelectorAll("[data-dept]").forEach((el) => {
    el.addEventListener("click", () => openDept(el.dataset.dept));
  });
}

/* --- Fil d'Ariane --- */
function setBreadcrumb(crumbs) {
  const nav = document.getElementById("docs-breadcrumb");
  nav.innerHTML = crumbs
    .map((c, i) =>
      c.onClick
        ? `<a href="#" data-i="${i}">${escape(c.label)}</a>`
        : `<span>${escape(c.label)}</span>`
    )
    .join(`<span class="sep">›</span>`);
  nav.querySelectorAll("a[data-i]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      crumbs[+a.dataset.i].onClick();
    })
  );
}

/* --- Niveau 0 (plat, non utilisé par l'entrée principale ; conservé pour
 * les liens directs éventuels et le bouton refresh) --- */
function renderDeptCards() {
  setBreadcrumb([
    { label: "Régions", onClick: renderRegionCards },
    { label: "Tous les départements" },
  ]);
  hideDeptFacets();
  const grid = docsGridEl();
  const depts = [...docsStats.values()].sort((a, b) => a.code.localeCompare(b.code));
  grid.innerHTML = depts
    .map(
      (s) => `<button class="ged-card" data-dept="${escape(s.code)}">
        <div class="ged-thumb"><span class="ged-thumb-ph">🗺️</span></div>
        <div class="ged-card-body">
          <h3>${escape(s.nom)} <span class="ged-code">${escape(s.code)}</span></h3>
          <p class="ged-meta">${deptMeta(s)}</p>
        </div>
      </button>`
    )
    .join("");
  grid
    .querySelectorAll("[data-dept]")
    .forEach((el) => el.addEventListener("click", () => openDept(el.dataset.dept)));
}

/* --- Niveau 1 : cards communes d'un département (charge à la demande) --- */
async function openDept(code) {
  const grid = docsGridEl();
  grid.innerHTML = `<p class="empty-state">Chargement de ${escape(
    docsStats?.get(code)?.nom || code
  )}…</p>`;
  const db = await loadDeptData(code);
  if (!db) return;
  const regId = DEPT_TO_REGION[code];
  const region = regId ? REGIONS[regId] : null;
  setBreadcrumb([
    { label: "Régions", onClick: renderRegionCards },
    ...(region
      ? [{ label: region.nom, onClick: () => openRegion(regId) }]
      : [{ label: "Départements", onClick: renderDeptCards }]),
    { label: `${db.nom} (${db.code})` },
  ]);
  // Filtres/tri par département : partager l'état via un objet léger.
  deptFacetState = {
    db,
    filters: { type: null, decennie: null, iiif: null, georef: null },
    sort: "type-asc",
  };
  renderDeptView();
}

/* --- Rendu filtré + trié du département courant (Phase 3) --- */
let deptFacetState = null;

function allDeptDocs(db) {
  const out = [];
  for (const c of db.communes.values())
    for (const d of c.docs) out.push({ ...d, _commune: c });
  return out;
}

function applyFilters(docs, f) {
  return docs.filter(
    (d) =>
      (!f.type || d.type === f.type) &&
      (!f.decennie ||
        (d.annee && Math.floor(d.annee / 10) * 10 === f.decennie)) &&
      (!f.iiif || (f.iiif === "yes" ? !!d.iiif_manifest : !d.iiif_manifest)) &&
      (!f.georef || (f.georef === "yes" ? !!d.georef : !d.georef))
  );
}

const SORT_FNS = {
  "type-asc": (a, b) => TYPE_RANK(a) - TYPE_RANK(b) || (a._commune.nom || "").localeCompare(b._commune.nom || "", "fr"),
  "annee-asc":  (a, b) => (a.annee ?? 9999) - (b.annee ?? 9999),
  "annee-desc": (a, b) => (b.annee ?? -1) - (a.annee ?? -1),
  "cote-asc":   (a, b) => (a.cote || "").localeCompare(b.cote || "", "fr", { numeric: true }),
  "commune-asc": (a, b) => (a._commune.nom || "").localeCompare(b._commune.nom || "", "fr"),
};
const _TYPE_RANK = { tableau_assemblage: 0, section: 1, feuille: 2 };
const TYPE_RANK = (d) => _TYPE_RANK[d.type] ?? 9;

function renderFacets(baseDocs, f) {
  const count = (predicate) => baseDocs.filter(predicate).length;
  const byType = [
    ["tableau_assemblage", "Tableau d'assemblage"],
    ["section", "Section"],
    ["feuille", "Feuille"],
  ].map(([v, l]) => ({ v, l, n: count((d) => d.type === v) })).filter((x) => x.n);
  const decennies = new Map();
  for (const d of baseDocs) if (d.annee) {
    const k = Math.floor(d.annee / 10) * 10;
    decennies.set(k, (decennies.get(k) || 0) + 1);
  }
  const decs = [...decennies.entries()].sort((a, b) => a[0] - b[0]);
  const withIiif = count((d) => d.iiif_manifest);
  const georefOk = count((d) => d.georef);
  const total = baseDocs.length;

  const grp = (title, key, values, active) =>
    `<div class="facet-group">
      <h4>${escape(title)}</h4>
      <ul>
        ${values.map(({ v, l, n }) =>
          `<li><button data-facet="${key}" data-value="${escape(String(v))}"
              class="${active === v ? "active" : ""}">
              ${escape(l)} <span class="facet-n">${n}</span></button></li>`).join("")}
        ${active ? `<li><button class="facet-clear" data-facet="${key}">Effacer</button></li>` : ""}
      </ul>
    </div>`;

  return (
    grp("Type de document", "type", byType, f.type) +
    (decs.length
      ? grp("Décennie", "decennie",
          decs.map(([k, n]) => ({ v: k, l: `${k}-${k + 9}`, n })), f.decennie)
      : "") +
    grp("IIIF disponible", "iiif",
      [{ v: "yes", l: "Oui", n: withIiif }, { v: "no", l: "Non", n: total - withIiif }].filter((x) => x.n),
      f.iiif) +
    grp("Géoréférencé", "georef",
      [{ v: "yes", l: "Oui", n: georefOk }, { v: "no", l: "Non", n: total - georefOk }].filter((x) => x.n),
      f.georef)
  );
}

function renderDeptView() {
  const { db, filters, sort } = deptFacetState;
  const baseDocs = allDeptDocs(db);
  const filtered = applyFilters(baseDocs, filters);
  // Regrouper par commune, en tri global secondaire pour l'affichage
  const communes = new Map();
  for (const d of filtered) {
    if (!communes.has(d.insee))
      communes.set(d.insee, { insee: d.insee, nom: d._commune.nom, docs: [] });
    communes.get(d.insee).docs.push(d);
  }
  // Tri des docs à l'intérieur de chaque commune
  for (const c of communes.values()) c.docs.sort(SORT_FNS[sort]);
  // Tri des communes
  const communesArr = [...communes.values()];
  if (sort === "commune-asc")
    communesArr.sort((a, b) => (a.nom || "").localeCompare(b.nom || "", "fr"));
  else if (sort === "annee-asc")
    communesArr.sort((a, b) => (a.docs[0].annee ?? 9999) - (b.docs[0].annee ?? 9999));
  else if (sort === "annee-desc")
    communesArr.sort((a, b) => (b.docs[0].annee ?? -1) - (a.docs[0].annee ?? -1));
  else
    communesArr.sort((a, b) => (a.nom || "").localeCompare(b.nom || "", "fr"));

  // Sidebar facettes + toolbar tri
  document.getElementById("docs-layout")?.classList.remove("no-facets");
  document.getElementById("docs-facets").hidden = false;
  document.getElementById("docs-facets").innerHTML = renderFacets(baseDocs, filters);
  document.getElementById("docs-sortbar").hidden = false;
  document.getElementById("docs-sortbar").querySelector(".docs-count").textContent =
    `${filtered.length.toLocaleString("fr")} document${filtered.length > 1 ? "s" : ""} · ${communesArr.length} commune${communesArr.length > 1 ? "s" : ""}`;
  document.getElementById("docs-sort").value = sort;

  const grid = docsGridEl();
  grid.innerHTML = communesArr.map((c) => communeCard(c, { vers: "carte" })).join("");
  hydrateGeoref(grid);
  hydrateThumbs(grid);

  // Handlers
  document.getElementById("docs-facets").onclick = (e) => {
    const btn = e.target.closest("button[data-facet]");
    if (!btn) return;
    const key = btn.dataset.facet;
    if (btn.classList.contains("facet-clear")) {
      deptFacetState.filters[key] = null;
    } else {
      const v = btn.dataset.value;
      const val = /^-?\d+$/.test(v) ? +v : v;
      deptFacetState.filters[key] = deptFacetState.filters[key] === val ? null : val;
    }
    renderDeptView();
  };
  document.getElementById("docs-sort").onchange = (e) => {
    deptFacetState.sort = e.target.value;
    renderDeptView();
  };
}

// À masquer quand on quitte la vue département
function hideDeptFacets() {
  const f = document.getElementById("docs-facets");
  const s = document.getElementById("docs-sortbar");
  if (f) f.hidden = true;
  if (s) s.hidden = true;
  // sans sidebar → la grille prend toute la largeur (cf. .no-facets)
  document.getElementById("docs-layout")?.classList.add("no-facets");
  deptFacetState = null;
}

/* Repli/dépli des planches d'une card communale — écouteur délégué unique
 * (la grille est ré-rendue à chaque navigation/filtre, on ne peut pas
 * attacher les handlers card par card). */
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".ged-more");
  if (!btn) return;
  const list = btn.previousElementSibling; // .ged-sections
  if (!list) return;
  const open = list.classList.toggle("expanded");
  btn.setAttribute("aria-expanded", String(open));
  const n = list.children.length;
  btn.textContent = open
    ? "voir moins"
    : `${n} planche${n > 1 ? "s" : ""} · voir plus`;
});

function communeCard(c, { vers = "carte" } = {}) {
  const assemblage = c.docs.find((d) => d.type === "tableau_assemblage");
  const sections = c.docs.filter((d) => d.type === "section");
  const manifest =
    assemblage?.iiif_manifest ||
    c.docs.find((d) => d.iiif_manifest)?.iiif_manifest ||
    null;
  const imageUrl =
    assemblage?.image_url || c.docs.find((d) => d.image_url)?.image_url || null;

  let actions = "";
  if (assemblage) {
    actions += `<a class="ged-link" href="${escape(
      assemblage.archive_url
    )}" target="_blank" rel="noopener">Tableau d'assemblage ↗</a>`;
    if (assemblage.iiif_manifest && assemblage.licence_overlay_ok)
      actions += `<div class="georef" data-manifest="${escape(
        assemblage.iiif_manifest
      )}" data-insee="${escape(c.insee)}"><span class="georef-loading">Vérification du géoréférencement…</span></div>`;
  } else {
    actions += `<span class="ged-empty">Pas de tableau d'assemblage</span>`;
  }
  // Sections ET feuilles : repliées à une seule ligne, dépliables au clic.
  // (Doubs et Saône-et-Loire n'ont que des `feuille` : sans ceci, leurs
  // documents n'apparaissaient nulle part dans la carte communale.)
  const planches = [...sections, ...c.docs.filter((d) => d.type === "feuille")];
  if (planches.length) {
    const chips = planches
      .map((s) => {
        const label =
          (s.section_lettre ? `Sect. ${s.section_lettre}` : s.cote || null) ||
          (s.feuille_num ? `Feuille ${s.feuille_num}` : "Planche");
        const suffix = s.section_lettre && s.feuille_num ? ` f.${s.feuille_num}` : "";
        return `<a class="ged-chip" href="${escape(
          s.archive_url
        )}" target="_blank" rel="noopener">${escape(label + suffix)} ↗</a>`;
      })
      .join("");
    const n = planches.length;
    actions += `<div class="ged-sections">${chips}</div>
      <button class="ged-more" type="button" aria-expanded="false">
        ${n} planche${n > 1 ? "s" : ""} · voir plus
      </button>`;
  }

  // Le titre bascule vers l'AUTRE vue : depuis la GED il mène à la carte,
  // depuis le panneau carte il mène à la fiche GED. `vers` porte ce choix.
  const lien =
    vers === "ged"
      ? { href: cardPath(c.insee), cls: "map-to-ged", attr: "data-ged-insee", t: "Voir dans la GED" }
      : { href: communePath(c.insee), cls: "ged-to-map", attr: "data-map-insee", t: "Voir sur la carte" };
  const titre = lien.href
    ? `<a class="${lien.cls}" href="${escape(lien.href)}" ${lien.attr}="${escape(
        c.insee
      )}" title="${lien.t}">${escape(c.nom)}</a>`
    : escape(c.nom);

  return `<div class="ged-card commune" id="ged-${escape(c.insee)}">
    ${thumbMarkup(manifest, imageUrl, "📄", (c.insee || "").slice(0, 2))}
    <div class="ged-card-body">
      <h3>${titre} <span class="ged-code">${escape(c.insee)}</span></h3>
      ${actions}
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ *
 * Vignettes IIIF — dérivées du manifeste (parser tolérant v2/v3).
 * Rendu en 2 temps : placeholder à l'affichage, image injectée quand
 * elle est résolue puis chargée (pas de flash d'image cassée). Cache.
 * ------------------------------------------------------------------ */
/* Vignette figée par département — dernier recours, pour les fonds qui n'ont
 * ni JPEG open data ni manifeste IIIF exploitable. (Côte-d'Or : le cache
 * d'images archives.cotedor.fr renvoie 404 → aucune source valable à figer
 * aujourd'hui ; à renseigner quand la source sera rétablie.) */
const DEPT_THUMB = {};

/* Ordre de préférence : JPEG direct > manifeste IIIF > image figée > emoji.
 * Le JPEG open data (25/71/95/93) passe avant le IIIF car les manifestes
 * générés par le worker pointent vers une chaîne d'image non résolue ; le
 * chemin IIIF ne sert donc plus qu'aux vrais serveurs IIIF (Vosges). */
function thumbMarkup(manifest, imageUrl, emoji, dept) {
  if (imageUrl)
    return `<div class="ged-thumb"><img loading="lazy" decoding="async" src="${escape(
      imageUrl
    )}" alt=""></div>`;
  if (manifest)
    return `<div class="ged-thumb" data-manifest="${escape(
      manifest
    )}"><span class="ged-thumb-ph">${emoji}</span></div>`;
  const figee = dept && DEPT_THUMB[dept];
  if (figee)
    return `<div class="ged-thumb"><img loading="lazy" src="${escape(
      figee
    )}" alt=""></div>`;
  return `<div class="ged-thumb"><span class="ged-thumb-ph">${emoji}</span></div>`;
}

const thumbCache = new Map(); // manifeste → URL de vignette (ou null)
async function iiifThumbnail(manifestUrl) {
  if (thumbCache.has(manifestUrl)) return thumbCache.get(manifestUrl);
  let result = null;
  try {
    const res = await fetch(manifestUrl);
    if (res.ok) result = thumbFromManifest(await res.json());
  } catch (e) {
    /* réseau / CORS → on garde le placeholder */
  }
  thumbCache.set(manifestUrl, result);
  return result;
}

const asArray = (x) => (Array.isArray(x) ? x : x ? [x] : []);
const stripInfo = (id) =>
  String(id).replace(/\/info\.json$/, "").replace(/\/$/, "");

function thumbFromManifest(m) {
  const SIZE = "200,";
  // 1) thumbnail explicite (v2 string/{@id}, v3 [{id}])
  const t = m.thumbnail;
  if (typeof t === "string") return t;
  if (t && t["@id"]) return t["@id"];
  if (Array.isArray(t) && (t[0]?.id || t[0]?.["@id"])) return t[0].id || t[0]["@id"];

  // 2) service image du 1er canvas — Presentation v3
  const canvasV3 = m.items?.[0];
  const bodyV3 = canvasV3?.items?.[0]?.items?.[0]?.body;
  const svcV3 = asArray(bodyV3?.service)[0];
  const svcIdV3 = svcV3?.id || svcV3?.["@id"];
  if (svcIdV3) return `${stripInfo(svcIdV3)}/full/${SIZE}/0/default.jpg`;
  if (canvasV3?.thumbnail?.[0]?.id) return canvasV3.thumbnail[0].id;

  // 3) service image du 1er canvas — Presentation v2
  const canvasV2 = m.sequences?.[0]?.canvases?.[0];
  const resV2 = canvasV2?.images?.[0]?.resource;
  const svcV2 = asArray(resV2?.service)[0];
  const svcIdV2 = svcV2?.["@id"] || svcV2?.id;
  if (svcIdV2) return `${stripInfo(svcIdV2)}/full/${SIZE}/0/default.jpg`;
  if (typeof canvasV2?.thumbnail === "string") return canvasV2.thumbnail;
  if (canvasV2?.thumbnail?.["@id"]) return canvasV2.thumbnail["@id"];
  if (resV2?.["@id"]) return resV2["@id"];

  return null;
}

/* --- Chargement paresseux des vignettes IIIF --------------------------
 * L'ancien Promise.all lançait ~450 fetches manifestes en parallèle : la
 * limite navigateur (~6 connexions/hôte) faisait piétiner la file et aucune
 * vignette n'atteignait le DOM avant que l'utilisateur change de vue.
 *
 * Nouveau : IntersectionObserver + file d'attente à concurrence limitée
 * (MAX_INFLIGHT). Un thumb n'est demandé qu'à son entrée dans le viewport
 * (rootMargin 200 px). Le placeholder emoji reste visible tant que le
 * manifeste + son image ne sont pas résolus.
 * ---------------------------------------------------------------------- */
const MAX_INFLIGHT_THUMBS = 6;
let inflightThumbs = 0;
const thumbQueue = [];

function drainThumbQueue() {
  while (inflightThumbs < MAX_INFLIGHT_THUMBS && thumbQueue.length) {
    const el = thumbQueue.shift();
    if (!el.isConnected) continue;
    inflightThumbs++;
    (async () => {
      try {
        const url = await iiifThumbnail(el.dataset.manifest);
        if (!el.isConnected || !url) return;
        const img = new Image();
        // NB : pas de `img.loading = "lazy"` ici — la spec bloque le fetch tant
        // que l'IMG n'est pas attachée au DOM, or on utilise `new Image()`
        // détachée puis on l'injecte via replaceChildren dans onload.
        img.alt = "";
        img.onload = () => {
          if (el.isConnected) el.replaceChildren(img);
        };
        img.src = url;
      } finally {
        inflightThumbs--;
        drainThumbQueue();
      }
    })();
  }
}

const thumbObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const el = entry.target;
      thumbObserver.unobserve(el);
      thumbQueue.push(el);
    }
    drainThumbQueue();
  },
  { rootMargin: "200px" }
);

function hydrateThumbs(root) {
  const vh = window.innerHeight;
  const vw = window.innerWidth;
  const MARGIN = 200;
  for (const el of root.querySelectorAll(".ged-thumb[data-manifest]")) {
    // Fallback : pousser immédiatement à la queue les thumbs déjà visibles.
    // Sinon on dépend uniquement d'IntersectionObserver, qui ne firing pas
    // dans certains renderers headless (Browser pane MCP) ou avant premier
    // scroll. L'observer prend le relais pour les thumbs plus bas.
    const r = el.getBoundingClientRect();
    if (r.bottom > -MARGIN && r.top < vh + MARGIN && r.right > -MARGIN && r.left < vw + MARGIN) {
      thumbQueue.push(el);
    } else {
      thumbObserver.observe(el);
    }
  }
  drainThumbQueue();
}

/* --- Recherche / autocomplétion (≥ 3 caractères) --- */
let docsSearchTimer = null;
(function initDocsSearch() {
  const input = document.getElementById("docs-search-input");
  if (!input) return;
  input.addEventListener("input", () => {
    clearTimeout(docsSearchTimer);
    const q = input.value.trim().toLowerCase();
    if (q.length < 3) return hideDocsResults();
    docsSearchTimer = setTimeout(() => runDocsSearch(q), 150);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".docs-search")) hideDocsResults();
  });
})();

/* Recherche GED — interroge geo.api puis ne garde que les communes dont le
 * département est présent en base. (L'ancien index en mémoire ne servait plus
 * à rien depuis le chargement paresseux : il restait vide tant qu'aucun
 * département n'avait été ouvert.) */
async function runDocsSearch(q) {
  const el = document.getElementById("docs-search-results");
  let hits = [];
  try {
    const res = await fetch(
      `${GEO_API}?nom=${encodeURIComponent(q)}&fields=nom,code,codeDepartement` +
        `&boost=population&limit=25`
    );
    if (res.ok) {
      hits = (await res.json())
        .filter((c) => docsStats?.has(c.codeDepartement))
        .slice(0, 8)
        .map((c) => ({
          insee: c.code,
          nom: c.nom,
          dept: c.codeDepartement,
          deptNom: docsStats.get(c.codeDepartement)?.nom || c.codeDepartement,
        }));
    }
  } catch (e) {
    /* hors ligne → « aucun résultat » */
  }
  if (!hits.length) {
    el.innerHTML = `<li class="no-hit">Aucun résultat</li>`;
    el.hidden = false;
    return;
  }
  el.innerHTML = hits
    .map(
      (h) =>
        `<li data-dept="${escape(h.dept)}" data-insee="${escape(
          h.insee
        )}">${escape(h.nom)} <span class="dep">(${escape(h.deptNom)} ${escape(
          h.dept
        )})</span></li>`
    )
    .join("");
  el.hidden = false;
  el.querySelectorAll("li[data-insee]").forEach((li) =>
    li.addEventListener("click", async () => {
      hideDocsResults();
      document.getElementById("docs-search-input").value = "";
      // openDept est asynchrone (chargement du département à la demande) :
      // sans l'attendre, la card n'existe pas encore au moment du défilement.
      await openDept(li.dataset.dept);
      revealCard(li.dataset.insee);
    })
  );
}

/* Défile jusqu'à une card, la met en évidence, et rend son URL partageable. */
function revealCard(insee) {
  const card = document.getElementById(`ged-${insee}`);
  if (!card) return false;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("ged-highlight");
  setTimeout(() => card.classList.remove("ged-highlight"), 1600);
  const p = cardPath(insee);
  if (p && location.pathname !== p) history.replaceState(null, "", p);
  return true;
}

function hideDocsResults() {
  const el = document.getElementById("docs-search-results");
  if (el) {
    el.hidden = true;
    el.innerHTML = "";
  }
}

/* --- Deep-link : applique /<region>/<dept>/<insee> au chargement ---------
 * En fin de fichier : DEPT_TO_REGION et selectCommune sont alors définis. */
applyRoute();
