/**
 * Proxy de normalisation IIIF pour Allmaps.
 *
 * Routes :
 *   /manifest?u=<URL>
 *       → manifeste IIIF avec services image réécrits vers le proxy (CORS + @id fix)
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
 * Lit les premiers 4 Ko d'un JPEG et extrait width/height via les marqueurs SOF.
 * Renvoie { w, h } ou les valeurs par défaut si la lecture échoue.
 */
async function fetchJpegDimensions(url) {
  try {
    const r = await fetch(url, {
      headers: { ...BROWSER_HEADERS, "Range": "bytes=0-4095" },
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

    // ── 4/5) /static-iiif/<ENC>/... — JPEG statique émulé en IIIF level 0 ─
    if (url.pathname.startsWith("/static-iiif/")) {
      const rest    = url.pathname.slice("/static-iiif/".length);
      const i       = rest.indexOf("/");
      const enc     = i < 0 ? rest : rest.slice(0, i);
      const suffix  = i < 0 ? "" : rest.slice(i);
      const imgBase = decodeURIComponent(enc); // URL sans extension .jpg
      if (!hostAllowed(imgBase)) return bad(400, "hôte non autorisé");

      const proxyBase = `${origin}/static-iiif/${enc}`;

      // 4) info.json synthétique — on déclare level2 pour qu'Allmaps accepte le service ;
      //    toutes les requêtes de tuiles renvoient le JPEG complet (voir bloc 5).
      if (suffix === "/info.json" || suffix === "") {
        const { w, h } = await fetchJpegDimensions(imgBase + ".jpg");
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
          "tiles": [{ "width": 512, "scaleFactors": [1, 2, 4, 8] }],
        });
      }

      // 5) toute requête d'image → renvoie le JPEG original (pleine résolution)
      const r = await fetch(imgBase + ".jpg", { headers: BROWSER_HEADERS });
      if (!r.ok) return bad(502, "image: " + r.status);
      const headers = new Headers();
      headers.set("Content-Type", "image/jpeg");
      Object.entries(CORS).forEach(([k, v]) => headers.set(k, v));
      return new Response(r.body, { status: 200, headers });
    }

    return bad(404, "routes: /manifest?u=… | /iiif/<enc>/… | /static-iiif/<enc>/…");
  },
};
