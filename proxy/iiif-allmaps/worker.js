/**
 * Proxy de normalisation IIIF pour Allmaps.
 *
 * Routes :
 *   /manifest?u=<URL>
 *       → manifeste IIIF avec services image réécrits vers le proxy (CORS + @id fix)
 *   /static-manifest?u=<URL.jpg>
 *       → manifeste IIIF Presentation v2 généré à la volée depuis un JPEG nu
 *         (pas de serveur IIIF côté source). Le service image du canvas pointe
 *         vers /static-iiif/ (level 0). Réutilisable pour tout JPEG open data :
 *         Saône-et-Loire, Bretagne, Doubs, etc. C'est LE chemin JPEG → IIIF.
 *   /iiif/<ENC>/info.json | /iiif/<ENC>/<tuile>
 *       → serveur IIIF réel proxifié (fix @id interne → URI publique)
 *   /static-iiif/<ENC>/info.json | /static-iiif/<ENC>/...
 *       → émulation IIIF Image API level 0 pour JPEG statiques sans serveur IIIF
 *         (ex. AD21 Côte-d'Or num_ext)
 */

const ALLOWED = new Set([
  "www.archives.ain.fr",
  "recherche-archives.vosges.fr",
  "archives.haute-garonne.fr",
  "archives.valdoise.fr",
  "archives.cotedor.fr",                       // AD21 — static JPEG via /static-iiif/
  "kartenn.region-bretagne.fr",                // Bretagne — assemblage communal JPG
  "saone-et-loire71.fr",                       // Saône-et-Loire (71) — opendata JPEG (http)
  "download.doubs.fr",                         // Doubs (25) — opendata JPEG
  "data.haute-garonne.fr",                     // Haute-Garonne (31) — opendata Opendatasoft (JPEG)
]);

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  "Accept": "*/*",
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Max-Age": "86400",
};

function hostAllowed(u) {
  try { return ALLOWED.has(new URL(u).host); } catch { return false; }
}

function json(obj, extra = {}) {
  return new Response(JSON.stringify(obj), {
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS, ...extra },
  });
}

function bad(status, msg) {
  return new Response(msg + "\n", { status, headers: { ...CORS } });
}

function serviceId(s) { return s["@id"] || s["id"] || null; }

function isImageService(s) {
  const flat = (x) => (Array.isArray(x) ? x.join(" ") : x || "");
  const ctx  = flat(s["@context"]);
  const prof = flat(s["profile"]);
  const type = s["type"] || s["@type"] || "";
  return /api\/image/i.test(ctx) || /api\/image/i.test(prof) || /^ImageService/i.test(type);
}

function rewriteServices(node, map) {
  if (Array.isArray(node)) { node.forEach((n) => rewriteServices(n, map)); return; }
  if (node && typeof node === "object") {
    if (node.service) {
      const svcs = Array.isArray(node.service) ? node.service : [node.service];
      for (const s of svcs) {
        const id = serviceId(s);
        if (id && isImageService(s)) {
          const proxied = map(id);
          if ("@id" in s) s["@id"] = proxied; else s["id"] = proxied;
        }
      }
    }
    for (const k of Object.keys(node)) rewriteServices(node[k], map);
  }
}

/**
 * Lit les premiers 64 Ko d'un JPEG et extrait width/height via les marqueurs SOF.
 * Renvoie { w, h } ou les valeurs par défaut si la lecture échoue.
 *
 * 64 Ko (et non 4) : les scans d'archives (ex. Saône-et-Loire) placent un gros
 * segment EXIF/ICC avant le SOF, qui tombe alors vers l'octet ~9900. 4 Ko
 * ratait ces images → fallback erroné → géoréf Allmaps décalée.
 */
async function fetchJpegDimensions(url) {
  try {
    const r = await fetch(url, {
      headers: { ...BROWSER_HEADERS, "Range": "bytes=0-65535" },
    });
    const buf = await r.arrayBuffer();
    const v   = new DataView(buf);
    // Cherche marqueur SOF : FF C0..C3 C5..C7 C9..CB CD..CF
    let pos = 2; // skip FF D8 (SOI)
    while (pos + 8 < v.byteLength) {
      if (v.getUint8(pos) !== 0xFF) break;
      const marker = v.getUint8(pos + 1);
      const segLen = v.getUint16(pos + 2);
      const isSOF  = (marker >= 0xC0 && marker <= 0xC3) ||
                     (marker >= 0xC5 && marker <= 0xC7) ||
                     (marker >= 0xC9 && marker <= 0xCB) ||
                     (marker >= 0xCD && marker <= 0xCF);
      if (isSOF) {
        const h = v.getUint16(pos + 5);
        const w = v.getUint16(pos + 7);
        if (w > 0 && h > 0) return { w, h };
      }
      pos += 2 + segLen;
    }
  } catch (_) {}
  return { w: 8000, h: 6000 }; // fallback
}

/**
 * Construit un manifeste IIIF Presentation v2 depuis une URL de JPEG nu.
 * Le service image du canvas pointe vers /static-iiif/ (level 0) : c'est lui
 * qu'Allmaps (et le parser de vignette de l'app) utilisent réellement.
 *   jpgUrl  : URL complète du JPEG source (http ou https), finit par .jpg
 *   origin  : origine du worker (https) — sert de préfixe aux URLs proxifiées
 *   w, h    : dimensions lues dans le JPEG
 */
function buildStaticManifest(jpgUrl, origin, w, h) {
  // URL complète (extension comprise) : /static-iiif/ la re-fetch telle quelle.
  const enc  = encodeURIComponent(jpgUrl);
  const serviceId  = `${origin}/static-iiif/${enc}`;
  const manifestId = `${origin}/static-manifest?u=${encodeURIComponent(jpgUrl)}`;
  const canvasId   = `${manifestId}/canvas/1`;
  const label      = decodeURIComponent(jpgUrl.split("/").pop() || "plan");

  return {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id":   manifestId,
    "@type": "sc:Manifest",
    "label": label,
    "sequences": [{
      "@type": "sc:Sequence",
      "canvases": [{
        "@id":    canvasId,
        "@type":  "sc:Canvas",
        "label":  label,
        "width":  w,
        "height": h,
        "images": [{
          "@type": "oa:Annotation",
          "motivation": "sc:painting",
          "resource": {
            "@id":   jpgUrl,
            "@type": "dctypes:Image",
            "format": "image/jpeg",
            "width":  w,
            "height": h,
            "service": {
              "@context": "http://iiif.io/api/image/2/context.json",
              "@id":     serviceId,
              "profile": "http://iiif.io/api/image/2/level0.json",
            },
          },
          "on": canvasId,
        }],
      }],
    }],
  };
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS")
      return new Response(null, { status: 204, headers: CORS });
    if (request.method !== "GET") return bad(405, "GET only");

    const url    = new URL(request.url);
    const origin = url.origin;

    // ── 1) /manifest?u=<URL> ──────────────────────────────────────────────
    if (url.pathname === "/manifest") {
      const src = url.searchParams.get("u");
      if (!src || !hostAllowed(src)) return bad(400, "param ?u manquant ou hôte non autorisé");
      const r = await fetch(src, { headers: BROWSER_HEADERS });
      if (!r.ok) return bad(502, "manifeste origine: " + r.status);
      const manifest = await r.json();
      rewriteServices(manifest, (base) => `${origin}/iiif/${encodeURIComponent(base)}`);
      return json(manifest);
    }

    // ── 1bis) /static-manifest?u=<URL.jpg> — JPEG nu → manifeste Presentation ─
    if (url.pathname === "/static-manifest") {
      const src = url.searchParams.get("u");
      if (!src || !hostAllowed(src)) return bad(400, "param ?u manquant ou hôte non autorisé");
      const { w, h } = await fetchJpegDimensions(src);
      return json(buildStaticManifest(src, origin, w, h));
    }

    // ── 2/3) /iiif/<ENC>/... — serveur IIIF réel proxifié ─────────────────
    if (url.pathname.startsWith("/iiif/")) {
      const rest    = url.pathname.slice("/iiif/".length);
      const i       = rest.indexOf("/");
      const enc     = i < 0 ? rest : rest.slice(0, i);
      const suffix  = i < 0 ? "" : rest.slice(i);
      const base    = decodeURIComponent(enc);
      if (!hostAllowed(base)) return bad(400, "hôte non autorisé");

      if (suffix === "/info.json") {
        const r = await fetch(base + "/info.json", { headers: BROWSER_HEADERS });
        if (!r.ok) return bad(502, "info.json: " + r.status);
        const info = await r.json();
        const proxiedBase = `${origin}/iiif/${enc}`;
        if ("@id" in info) info["@id"] = proxiedBase; else info["id"] = proxiedBase;
        return json(info);
      }
      const r = await fetch(base + suffix, { headers: BROWSER_HEADERS });
      const h = new Headers(r.headers);
      Object.entries(CORS).forEach(([k, v]) => h.set(k, v));
      return new Response(r.body, { status: r.status, headers: h });
    }

    // ── 4/5) /static-iiif/<ENC>/... — AD21 Archinoë via genereImage + cache ─
    // ENC = percent-encoded chemin data-original : /mnt/lustre/ad21/num_ext/...jpg
    // Le Worker demande à genereImage.html (sans session) un rendu à TARGET_PX px de côté,
    // puis sert le JPEG depuis /cache/ avec CORS. Le nom du fichier cache encode la taille
    // DEMANDÉE (_{TARGET}_{TARGET}_0_0_0_0_img.jpg) → URL déterministe, dérivable sans I/O.
    if (url.pathname.startsWith("/static-iiif/")) {
      const TARGET_PX = 4000; // résolution servie (max natif ~8015 ; 4000 ≈ 560 Ko, net pour la géoréf)

      const rest    = url.pathname.slice("/static-iiif/".length);
      const i       = rest.indexOf("/");
      const enc     = i < 0 ? rest : rest.slice(0, i);
      const suffix  = i < 0 ? "" : rest.slice(i);
      const dataOrig = decodeURIComponent(enc); // /mnt/lustre/ad21/num_ext/.../xxx.jpg

      // ── A) JPEG nu accessible en HTTP(S) (Doubs, Saône-et-Loire, Bretagne…) ──
      // Émulation IIIF Image API level 0 : une seule « tuile » = l'image entière.
      // C'est ce que consomme Allmaps pour géoréférencer un JPEG open data.
      if (/^https?:\/\//i.test(dataOrig)) {
        if (!hostAllowed(dataOrig)) return bad(400, "hôte non autorisé");
        const selfBase = `${origin}/static-iiif/${enc}`;
        // L'URL est prise telle quelle : certaines sources n'ont pas
        // d'extension (API de fichiers Opendatasoft, ex. Haute-Garonne).
        // `.jpg` n'est retenté qu'en repli, pour les manifestes générés
        // avant que l'extension ne soit conservée dans l'URL du service.
        const candidats = /\.jpe?g$/i.test(dataOrig)
          ? [dataOrig]
          : [dataOrig, dataOrig + ".jpg"];

        if (suffix === "/info.json" || suffix === "") {
          const { w, h } = await fetchJpegDimensions(candidats[0]);
          return json({
            "@context": "http://iiif.io/api/image/2/context.json",
            "@id":      selfBase,
            "protocol": "http://iiif.io/api/image",
            "width":    w,
            "height":   h,
            "profile":  [
              "http://iiif.io/api/image/2/level0.json",
              { "formats": ["jpg"], "qualities": ["default"] },
            ],
            "tiles": [{ "width": w, "height": h, "scaleFactors": [1] }],
          });
        }
        // toute requête d'image → l'unique tuile, c'est le JPEG source
        let rr = null;
        for (const c of candidats) {
          rr = await fetch(c, { headers: BROWSER_HEADERS });
          if (rr.ok) break;
        }
        if (!rr || !rr.ok) return bad(502, "image source: " + (rr ? rr.status : "?"));
        const hh = new Headers();
        hh.set("Content-Type", rr.headers.get("content-type") || "image/jpeg");
        Object.entries(CORS).forEach(([k, v]) => hh.set(k, v));
        return new Response(rr.body, { status: 200, headers: hh });
      }

      // ── B) AD21 Archinoë : chemin interne /mnt/lustre/… via genereImage ──

      // URL cache déterministe (même logique que seed_cotedor_iiif.py)
      const suffixName = `_${TARGET_PX}_${TARGET_PX}_0_0_0_0_img.jpg`;
      const cachePath  = dataOrig.slice(1).replace(/\//g, "_").replace(/\.jpg$/i, suffixName);
      const cacheUrl   = `https://archives.cotedor.fr/cache/${cachePath}`;
      if (!hostAllowed(cacheUrl)) return bad(400, "hôte non autorisé");

      const proxyBase = `${origin}/static-iiif/${enc}`;
      const genUrl = () => {
        const p = new URLSearchParams({
          l: TARGET_PX, h: TARGET_PX, r: 0, n: 0, b: 0, c: 0,
          o: "IMG", id: "visu_image_1", image: dataOrig,
        });
        return `https://archives.cotedor.fr/v2/images/genereImage.html?${p}`;
      };

      // 4) info.json — genereImage renvoie les dims de sortie (parts[2]/parts[3]).
      // scaleFactors:[1] + tile_width=w → Allmaps demande UNE tuile = image complète.
      if (suffix === "/info.json" || suffix === "") {
        let w = TARGET_PX, h = Math.round(TARGET_PX * 0.7);
        try {
          const gr = await fetch(genUrl(), { headers: BROWSER_HEADERS });
          if (gr.ok) {
            const parts = (await gr.text()).split("\t");
            if (parts.length >= 4) {
              const pw = parseInt(parts[2]); // largeur de sortie
              const ph = parseInt(parts[3]); // hauteur de sortie
              if (pw > 0 && ph > 0) { w = pw; h = ph; }
            }
          }
        } catch (_) {}
        return json({
          "@context": "http://iiif.io/api/image/2/context.json",
          "@id":      proxyBase,
          "protocol": "http://iiif.io/api/image",
          "width":    w,
          "height":   h,
          "profile":  [
            "http://iiif.io/api/image/2/level2.json",
            { "supports": ["regionByPx", "sizeByWh"] },
          ],
          "tiles": [{ "width": w, "scaleFactors": [1] }],
        });
      }

      // 5) toute requête d'image → sert depuis /cache/ avec CORS
      let r = await fetch(cacheUrl, { headers: BROWSER_HEADERS });
      if (!r.ok) {
        // Cache pas encore générée : déclenche genereImage puis réessaie
        await fetch(genUrl(), { headers: BROWSER_HEADERS });
        r = await fetch(cacheUrl, { headers: BROWSER_HEADERS });
      }
      if (!r.ok) return bad(502, "image cache: " + r.status);
      const headers = new Headers();
      headers.set("Content-Type", "image/jpeg");
      Object.entries(CORS).forEach(([k, v]) => headers.set(k, v));
      return new Response(r.body, { status: 200, headers });
    }

    return bad(404, "routes: /manifest?u=… | /static-manifest?u=… | /iiif/<enc>/… | /static-iiif/<enc>/…");
  },
};
