#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère des manifestes IIIF Presentation v2 minimaux pour les documents
AD21 (Côte-d'Or) en exploitant les fichiers de cache cdo_lvl4_*.html.

Sorties :
  web/manifests/ad21/{image_id}.json   — manifestes statiques (GitHub Pages)
  download/update_cotedor_iiif.sql     — UPDATE Supabase

Usage :
    python harvest/seed_cotedor_iiif.py
"""

import os, re, json, sys

CACHE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
MANIFESTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "web", "manifests", "ad21")
SQL_OUT       = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "download", "update_cotedor_iiif.sql")

BASE_AD21    = "https://archives.cotedor.fr"
PAGES_BASE   = "https://sperrot.github.io/cadastre-napoleonien/manifests/ad21"
VIEWER_BASE  = f"{BASE_AD21}/v2/ad21/visualiseur/cartes_plans.html?ir=23318&id="

# URL de base du Cloudflare Worker déployé (wrangler deploy → iiif-allmaps.<compte>.workers.dev)
# À mettre à jour après le premier `wrangler deploy`.
PROXY_BASE   = "https://iiif-allmaps.sperrot.workers.dev"

# Regex (réutilisés depuis harvest_cotedor.py)
_RE_ITEM     = re.compile(r'<div id="item_(\d+)">')
_RE_TITLE    = re.compile(r'class="titres">\s*<span[^>]*>([^<]*)</span>')
# On cible les spans avec un vrai id (detailn_\d+) pour éviter les spans vides des boutons
_RE_COTE     = re.compile(r'class="cotes"[^>]*>.*?<span[^>]*id="detailn_\d+"[^>]*>([^<]+)</span>', re.S)
_RE_DATE     = re.compile(r'class="dates"[^>]*>.*?<span[^>]*id="detailn_\d+"[^>]*>([^<]+)</span>', re.S)
_RE_LIEN     = re.compile(r'lienImage\((\d+)\)')
_RE_DATA_SRC = re.compile(r'data-src="([^"]+)"')


def parse_lvl4(html):
    items = []
    parts = _RE_ITEM.split(html)
    for item_id, block in zip(parts[1::2], parts[2::2]):
        title_m = _RE_TITLE.search(block)
        img_m   = _RE_LIEN.search(block)
        src_m   = _RE_DATA_SRC.search(block)
        if not title_m or not img_m or not src_m:
            continue
        title    = title_m.group(1).strip()
        cote_m   = _RE_COTE.search(block)
        date_m   = _RE_DATE.search(block)
        items.append({
            "item_id":  item_id,
            "image_id": img_m.group(1),
            "title":    title,
            "cote":     cote_m.group(1).strip() if cote_m else "",
            "date":     date_m.group(1).strip() if date_m else "",
            "data_src": src_m.group(1),         # ex. /num_ext/frad021_3p/...jpg
        })
    return items


def make_manifest(item):
    import urllib.parse
    image_id    = item["image_id"]
    image_url   = BASE_AD21 + item["data_src"]           # .jpg complet
    img_base    = image_url[:-4] if image_url.endswith(".jpg") else image_url
    enc_base    = urllib.parse.quote(img_base, safe="")  # pour l'URL du proxy
    service_id  = f"{PROXY_BASE}/static-iiif/{enc_base}"

    manifest_id = f"{PAGES_BASE}/{image_id}.json"
    canvas_id   = f"{manifest_id}/canvas/1"
    label = item["title"]
    if item["cote"]:
        label += f" — {item['cote']}"
    if item["date"]:
        label += f" ({item['date']})"

    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id":      manifest_id,
        "@type":    "sc:Manifest",
        "label":    label,
        "metadata": [
            {"label": "Cote", "value": item["cote"]},
            {"label": "Date", "value": item["date"]},
        ],
        "attribution": "Archives départementales de la Côte-d'Or",
        "sequences": [{
            "@type": "sc:Sequence",
            "canvases": [{
                "@id":    canvas_id,
                "@type":  "sc:Canvas",
                "label":  item["title"],
                "width":  8000,
                "height": 6000,
                "images": [{
                    "@type":      "oa:Annotation",
                    "motivation": "sc:painting",
                    "resource": {
                        "@id":    image_url,
                        "@type":  "dctypes:Image",
                        "format": "image/jpeg",
                        "width":  8000,
                        "height": 6000,
                        "service": {
                            "@context": "http://iiif.io/api/image/2/context.json",
                            "@id":      service_id,
                            "profile":  "http://iiif.io/api/image/2/level2.json",
                        },
                    },
                    "on": canvas_id,
                }],
            }],
        }],
    }


def main():
    os.makedirs(MANIFESTS_DIR, exist_ok=True)

    lvl4_files = [
        f for f in os.listdir(CACHE_DIR)
        if f.startswith("cdo_lvl4_") and f.endswith(".html")
    ]
    sys.stderr.write(f"{len(lvl4_files)} fichiers lvl4 à traiter\n")

    all_items = []
    for fname in lvl4_files:
        html = open(os.path.join(CACHE_DIR, fname), encoding="utf-8").read()
        all_items.extend(parse_lvl4(html))

    sys.stderr.write(f"{len(all_items)} items trouvés\n")

    with open(SQL_OUT, "w", encoding="utf-8") as sql_fh:
        sql_fh.write("-- UPDATE iiif_manifest AD21 — manifestes statiques GitHub Pages\n\n")

        for item in all_items:
            manifest = make_manifest(item)
            json_path = os.path.join(MANIFESTS_DIR, f"{item['image_id']}.json")
            with open(json_path, "w", encoding="utf-8") as jf:
                json.dump(manifest, jf, ensure_ascii=False, indent=2)

            viewer_url = VIEWER_BASE + item["image_id"]
            manifest_url = f"{PAGES_BASE}/{item['image_id']}.json"
            sql_fh.write(
                f"update document set iiif_manifest = '{manifest_url}'"
                f" where archive_url = '{viewer_url}';\n"
            )

    sys.stderr.write(f"Manifestes → web/manifests/ad21/\n")
    sys.stderr.write(f"SQL        → download/update_cotedor_iiif.sql\n")


if __name__ == "__main__":
    main()
