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
      <strong>Aucun plan référencé pour cette commune.</strong><br>
      La contribution participative (ajout de liens) arrive au palier V0.1.
    </div>`;
  } else {
    for (const type of TYPE_ORDER) {
      const group = docs.filter((d) => d.type === type);
      if (!group.length) continue;
      html += `<div class="doc-group"><h3>${TYPE_LABEL[type] || type}</h3>`;
      for (const d of group) html += docItem(d);
      html += `</div>`;
    }
    html += sourceFooter(docs);
  }
  el.innerHTML = html;
  if (!loading && Array.isArray(docs) && docs.length) hydrateGeoref(el);
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

async function hydrateGeoref(root) {
  for (const block of root.querySelectorAll(".georef[data-manifest]")) {
    const manifest = block.dataset.manifest;
    const annotationUrl = await resolveAnnotation(manifest);
    if (!block.isConnected) return; // commune changée pendant le fetch
    block.innerHTML = annotationUrl
      ? `<span class="georef-badge">✓ géoréférencé</span>
         <a class="georef-link" href="${escape(
           viewerLink(annotationUrl)
         )}" target="_blank" rel="noopener">Voir l'overlay ↗</a>`
      : `<a class="georef-btn" href="${escape(
          editorLink(manifest)
        )}" target="_blank" rel="noopener">Géoréférencer ce plan ↗</a>`;
  }
}

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

/* --- Données : Map(dept -> { code, nom, communes: Map(insee -> {insee,nom,docs[]}) }) --- */
let docsData = null;
let docsSearchList = []; // index plat pour l'autocomplétion

async function loadDocsData() {
  if (docsData || !sb) return docsData;
  // Supabase/PostgREST plafonne à 1000 lignes/requête → on pagine pour tout
  // récupérer (l'ordre stable sur insee est indispensable à la pagination).
  const PAGE = 1000;
  const data = [];
  for (let from = 0; ; from += PAGE) {
    const { data: page, error } = await sb
      .from("document")
      .select(
        "insee,type,section_lettre,feuille_num,annee,cote,archive_url,iiif_manifest,image_url,licence_overlay_ok"
      )
      .order("insee")
      .range(from, from + PAGE - 1);
    if (error) {
      console.error("Supabase (docs):", error.message);
      if (!data.length) return null;
      break;
    }
    data.push(...page);
    if (page.length < PAGE) break; // dernière page atteinte
  }
  const byDept = new Map();
  for (const d of data) {
    const dept = (d.insee || "").slice(0, 2);
    if (!byDept.has(dept))
      byDept.set(dept, { code: dept, nom: dept, communes: new Map() });
    const db = byDept.get(dept);
    if (!db.communes.has(d.insee))
      db.communes.set(d.insee, { insee: d.insee, nom: d.insee, docs: [] });
    db.communes.get(d.insee).docs.push(d);
  }
  docsData = byDept;
  await resolveNames(byDept);
  buildDocsSearch();
  return docsData;
}

// Noms dépt + communes via geo.api (1 appel/dept). Tolérant aux erreurs.
async function resolveNames(byDept) {
  try {
    const res = await fetch("https://geo.api.gouv.fr/departements?fields=nom,code");
    const map = new Map((await res.json()).map((x) => [x.code, x.nom]));
    for (const [code, db] of byDept) if (map.has(code)) db.nom = map.get(code);
  } catch (e) {
    /* garde le code dept */
  }
  await Promise.all(
    [...byDept.values()].map(async (db) => {
      try {
        const res = await fetch(
          `https://geo.api.gouv.fr/communes?codeDepartement=${db.code}&fields=nom,code`
        );
        const map = new Map((await res.json()).map((x) => [x.code, x.nom]));
        for (const [insee, c] of db.communes)
          if (map.has(insee)) c.nom = map.get(insee);
      } catch (e) {
        /* garde l'insee */
      }
    })
  );
}

function buildDocsSearch() {
  docsSearchList = [];
  for (const db of docsData.values())
    for (const c of db.communes.values())
      docsSearchList.push({
        insee: c.insee,
        nom: c.nom,
        dept: db.code,
        deptNom: db.nom,
        hay: `${c.nom} ${c.insee} ${db.nom}`.toLowerCase(),
      });
}

/* --- Entrée dans l'onglet --- */
async function openDocs() {
  const grid = docsGridEl();
  if (!sb) {
    grid.innerHTML = `<p class="empty-state">Base non connectée — renseignez Supabase dans <code>config.js</code>.</p>`;
    return;
  }
  if (!docsData) {
    grid.innerHTML = `<p class="empty-state">Chargement des documents…</p>`;
    await loadDocsData();
  }
  if (docsData) renderDeptCards();
}

/* --- Bouton rafraîchir --- */
document.getElementById("docs-refresh-btn")?.addEventListener("click", async () => {
  docsData = null;
  await openDocs();
});

/* --- Realtime : refresh automatique à chaque INSERT dans document --- */
if (sb) {
  sb.channel("document-inserts")
    .on("postgres_changes", { event: "INSERT", schema: "public", table: "document" }, () => {
      docsData = null;
      if (!document.getElementById("docs-view").hidden) openDocs();
    })
    .subscribe();
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

/* --- Niveau 0 : cards départements --- */
function renderDeptCards() {
  setBreadcrumb([{ label: "Départements" }]);
  const grid = docsGridEl();
  const depts = [...docsData.values()].sort((a, b) => a.code.localeCompare(b.code));
  grid.innerHTML = depts.map(deptCard).join("");
  grid
    .querySelectorAll("[data-dept]")
    .forEach((el) => el.addEventListener("click", () => openDept(el.dataset.dept)));
  hydrateThumbs(grid);
}

function firstImageOfDept(db) {
  for (const c of db.communes.values())
    for (const d of c.docs) if (d.image_url) return d.image_url;
  return null;
}

function firstManifestOfDept(db) {
  for (const c of db.communes.values())
    for (const d of c.docs) if (d.iiif_manifest) return d.iiif_manifest;
  return null;
}

function deptCard(db) {
  const nbCommunes = db.communes.size;
  const nbDocs = [...db.communes.values()].reduce((n, c) => n + c.docs.length, 0);
  return `<button class="ged-card" data-dept="${escape(db.code)}">
    ${thumbMarkup(firstManifestOfDept(db), firstImageOfDept(db), "🗺️")}
    <div class="ged-card-body">
      <h3>${escape(db.nom)} <span class="ged-code">${escape(db.code)}</span></h3>
      <p class="ged-meta">${nbCommunes} commune${nbCommunes > 1 ? "s" : ""} · ${nbDocs} document${
    nbDocs > 1 ? "s" : ""
  }</p>
    </div>
  </button>`;
}

/* --- Niveau 1 : cards communes d'un département --- */
function openDept(code) {
  const db = docsData.get(code);
  if (!db) return;
  setBreadcrumb([
    { label: "Départements", onClick: renderDeptCards },
    { label: `${db.nom} (${db.code})` },
  ]);
  const grid = docsGridEl();
  const communes = [...db.communes.values()].sort((a, b) =>
    a.nom.localeCompare(b.nom, "fr")
  );
  grid.innerHTML = communes.map(communeCard).join("");
  hydrateGeoref(grid); // réutilise badge/bouton Allmaps
  hydrateThumbs(grid);
}

function communeCard(c) {
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
      )}"><span class="georef-loading">Vérification du géoréférencement…</span></div>`;
  } else {
    actions += `<span class="ged-empty">Pas de tableau d'assemblage</span>`;
  }
  if (sections.length) {
    const chips = sections
      .map((s) => {
        const label =
          (s.section_lettre ? `Sect. ${s.section_lettre}` : s.cote || "Section") +
          (s.feuille_num ? ` f.${s.feuille_num}` : "");
        return `<a class="ged-chip" href="${escape(
          s.archive_url
        )}" target="_blank" rel="noopener">${escape(label)} ↗</a>`;
      })
      .join("");
    actions += `<div class="ged-sections">${chips}</div>`;
  }

  return `<div class="ged-card commune" id="ged-${escape(c.insee)}">
    ${thumbMarkup(manifest, imageUrl, "📄")}
    <div class="ged-card-body">
      <h3>${escape(c.nom)} <span class="ged-code">${escape(c.insee)}</span></h3>
      ${actions}
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ *
 * Vignettes IIIF — dérivées du manifeste (parser tolérant v2/v3).
 * Rendu en 2 temps : placeholder à l'affichage, image injectée quand
 * elle est résolue puis chargée (pas de flash d'image cassée). Cache.
 * ------------------------------------------------------------------ */
function thumbMarkup(manifest, imageUrl, emoji) {
  if (manifest)
    return `<div class="ged-thumb" data-manifest="${escape(
      manifest
    )}"><span class="ged-thumb-ph">${emoji}</span></div>`;
  if (imageUrl)
    return `<div class="ged-thumb"><img loading="lazy" src="${escape(
      imageUrl
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

async function hydrateThumbs(root) {
  await Promise.all(
    [...root.querySelectorAll(".ged-thumb[data-manifest]")].map(async (el) => {
      const url = await iiifThumbnail(el.dataset.manifest);
      if (!el.isConnected || !url) return;
      const img = new Image();
      img.loading = "lazy";
      img.alt = "";
      img.onload = () => {
        if (el.isConnected) el.replaceChildren(img);
      };
      img.src = url; // si erreur de chargement → le placeholder reste
    })
  );
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

function runDocsSearch(q) {
  const hits = docsSearchList.filter((x) => x.hay.includes(q)).slice(0, 8);
  const el = document.getElementById("docs-search-results");
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
    li.addEventListener("click", () => {
      hideDocsResults();
      document.getElementById("docs-search-input").value = "";
      openDept(li.dataset.dept);
      const card = document.getElementById(`ged-${li.dataset.insee}`);
      if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.classList.add("ged-highlight");
        setTimeout(() => card.classList.remove("ged-highlight"), 1600);
      }
    })
  );
}

function hideDocsResults() {
  const el = document.getElementById("docs-search-results");
  if (el) {
    el.hidden = true;
    el.innerHTML = "";
  }
}
