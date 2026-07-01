#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Connecteur Archives Côte-d'Or (archives.cotedor.fr) — EAD/AJAX.

Le portail sert un instrument de recherche EAD via des appels AJAX :
  GET ir_ead_visu_action.php?ir=23318&general=1          → TOC complet
  GET ir_ead_visu_action.php?ir=23318&id=N&toc=1         → enfants d'un nœud
  GET ir_ead_visu_action.php?ir=23318&id=N&level=4       → notice + lien ARK

Permaliens IIIF (à tester par commune) :
  https://archives.cotedor.fr/v2/ark:/71137/<hash>/manifest

⚠️  À LANCER EN LOCAL — le portail bloque les fetch serveur.
Dépendances : pip install requests
Usage :
    python harvest_cotedor.py --out seed_cotedor.sql
    python harvest_cotedor.py --out seed_cotedor.sql --iiif   # tente IIIF
"""

import sys
import os
import re
import time
import json
import argparse
import requests

BASE = "https://archives.cotedor.fr"
IR   = "23318"
EADID = "FRAD021_000000905"
DEPT  = "21"
GEO_API = "https://geo.api.gouv.fr/communes"
SLEEP   = 0.35
TIMEOUT = 60
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

session = requests.Session()
session.verify = False
session.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                   "Gecko/20100101 Firefox/128.0"),
    "Accept": "text/html,*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/console/ir_ead_visu.php?eadid={EADID}&ir={IR}",
})

_phpsid   = None   # extrait après prime()
_insee_cache = {}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def prime():
    """Initialise la session : pose les cookies + récupère le PHPSID.
    Sauvegarde aussi la page principale pour analyser l'arbre JS."""
    global _phpsid
    os.makedirs(CACHE_DIR, exist_ok=True)
    main_path = os.path.join(CACHE_DIR, "cdo_main_page.html")
    # Toujours frapper le serveur pour obtenir les cookies de session,
    # même si le HTML est en cache (sans cookies, les AJAX échouent).
    r = session.get(
        f"{BASE}/console/ir_ead_visu.php",
        params={"eadid": EADID, "ir": IR},
        timeout=30,
        verify=False,
    )
    phpsessid = session.cookies.get("PHPSESSID", "")
    if phpsessid:
        _phpsid = phpsessid
    else:
        m = re.search(r"PHPSID=([a-f0-9]{26,})", r.text)
        if m:
            _phpsid = m.group(1)
    sys.stderr.write(f"PHPSID: {_phpsid or '(non trouvé — mode cookie)'}\n")
    if os.path.exists(main_path):
        # HTML déjà en cache, mais session initialisée via la requête ci-dessus
        return open(main_path, encoding="utf-8").read()
    with open(main_path, "w", encoding="utf-8") as fh:
        fh.write(r.text)
    return r.text


def _params(**extra):
    p = {"ir": IR}
    if _phpsid:
        p["PHPSID"] = _phpsid
    p.update(extra)
    return p


# ---------------------------------------------------------------------------
# Cache + fetch HTML
# ---------------------------------------------------------------------------

def _get_html(cache_key, params):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"cdo_{cache_key}.html")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    url = f"{BASE}/console/ir_ead_visu_action.php"
    for attempt in range(4):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT, verify=False)
            if r.status_code == 200:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(r.text)
                time.sleep(SLEEP)
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    sys.stderr.write(f"  ⚠ échec fetch {cache_key}\n")
    return ""


def get_general_toc(main_html=""):
    """
    La liste des communes est directement dans la page principale :
      <a href='javascript:showEntry(ID)'>Nom commune</a>
    Aucun appel API supplémentaire nécessaire — on réutilise main_html.
    """
    return main_html


def get_commune_toc(node_id):
    return _get_html(f"toc_{node_id}", _params(id=node_id, toc=1))


def get_plan_detail(node_id):
    return _get_html(f"lvl4_{node_id}", _params(id=node_id, level=4))


def resolve_ark(item_id, debug=False):
    """
    Résout l'ARK permalien d'un item EAD via l'endpoint XML du portail :
      GET /console/ir_ead_notice_lien.php?ir=23318&id=<item_id>
      → XML <resultat><titre>…</titre><lien>ARK_URL</lien></resultat>

    C'est cet endpoint qu'utilise le bouton « Ajouter à mes albums » du portail ;
    il contient le permalien public de chaque feuille (TA, section A/B/…).
    """
    cache_path = os.path.join(CACHE_DIR, f"cdo_ark_{item_id}.txt")
    if os.path.exists(cache_path):
        v = open(cache_path, encoding="utf-8").read().strip()
        return v or None

    ark = None
    url = f"{BASE}/console/ir_ead_notice_lien.php"
    try:
        r = session.get(url, params={"ir": IR, "id": item_id}, timeout=30)
        if debug:
            sys.stderr.write(f"  [debug] notice_lien({item_id}) status={r.status_code} "
                             f"body={r.text!r}\n")
        # Le corps est du XML : <resultat><titre>…</titre><lien>URL</lien></resultat>
        m = re.search(r'<lien>([^<]+)</lien>', r.text)
        if m:
            ark = m.group(1).strip()
            if not ark.startswith("http"):
                ark = BASE + ark if ark.startswith("/") else None
    except requests.RequestException as e:
        if debug:
            sys.stderr.write(f"  [debug] notice_lien({item_id}) erreur : {e}\n")

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        fh.write(ark or "")
    time.sleep(SLEEP)
    return ark


# ---------------------------------------------------------------------------
# Parsing HTML
# ---------------------------------------------------------------------------


# Portail Archinoë AD21 — pattern commun à tous les niveaux du TOC.
# L'attribut `alt=` ou `title=` peut précéder le `>`, d'où `[^>]*`.
_RE_SHOW_ENTRY = re.compile(r"showEntry\((\d+)\)'[^>]*>([^<]+)</a>")

# Groupes à descendre pour trouver les feuilles de plans
_RE_PLANS_GROUP = re.compile(r"plan|cadastre\s+napo", re.I)
# Nœuds à ignorer (états de section, matrices, tables de correspondance)
_RE_SKIP = re.compile(r"état|matrice|table\s+de\s+corresp", re.I)


def _parse_toc(html):
    """Extrait [(title, node_id), …] depuis n'importe quel fragment TOC AD21."""
    return [
        (title.strip(), nid)
        for nid, title in _RE_SHOW_ENTRY.findall(html)
        if title.strip()
    ]


def parse_communes(html, debug=False):
    """
    Extrait la liste des communes depuis la page principale Archinoë (AD21).
    Pattern dans le panneau de sommaire gauche :
      <a href='javascript:showEntry(ID)' alt='...' title='...'>Nom</a>
    """
    result = _parse_toc(html)
    if debug and not result:
        sys.stderr.write(html[:3000].replace("\n", " "))
    return result


_RE_ITEM_BLOCK  = re.compile(r'<div id="item_(\d+)">')
_RE_TITLE_SPAN  = re.compile(r'class="titres">\s*<span[^>]*>([^<]*)</span>')
_RE_COTE_SPAN   = re.compile(r'class="cotes"[^>]*>.*?<span[^>]*>([^<]*)</span>', re.S)
_RE_DATE_SPAN   = re.compile(r'class="dates"[^>]*>.*?<span[^>]*>([^<]*)</span>', re.S)
_RE_LIEN_IMAGE  = re.compile(r'lienImage\((\d+)\)')
_RE_DATA_SRC    = re.compile(r'data-src="([^"]+)"')

_RE_ARK = re.compile(
    r'https://archives\.cotedor\.fr/v2/ark:/71137/[a-z0-9]+',
    re.I,
)


def parse_plan_group_detail(html):
    """
    Parse la réponse `?id=<groupe Plans>&level=4` : liste des feuilles
    (Tableau d'assemblage + sections A/B/…), chacune avec :
      - item_id  : id du <div id="item_N"> → utilisé pour resolve_ark()
      - title    : "Tableau d'assemblage", "Section A", …
      - cote     : "3 P PLAN 4/1", …
      - date     : "1827", …
      - direct_image : chemin JPG (fallback si ARK indisponible)
    """
    items = []
    # Splitons sur les balises ouvrantes <div id="item_N"> pour capturer l'id
    parts = _RE_ITEM_BLOCK.split(html)
    # parts[0] = texte avant le 1er item ; parts[1::2] = ids, parts[2::2] = blocs
    # (car split avec groupe de capture → [avant, id1, bloc1, id2, bloc2, …])
    ids_and_blocks = list(zip(parts[1::2], parts[2::2]))
    for item_id, block in ids_and_blocks:
        title_m = _RE_TITLE_SPAN.search(block)
        img_m   = _RE_LIEN_IMAGE.search(block)
        if not title_m or not img_m:
            continue
        title = title_m.group(1).strip()
        if not title:
            continue
        cote_m   = _RE_COTE_SPAN.search(block)
        date_m   = _RE_DATE_SPAN.search(block)
        direct_m = _RE_DATA_SRC.search(block)
        image_id = img_m.group(1)
        # URL du viewer v2 — lien stable et public, pas besoin de l'ARK
        viewer_url = (f"{BASE}/v2/ad21/visualiseur/cartes_plans.html"
                      f"?ir={IR}&id={image_id}")
        items.append({
            "title": title,
            "cote": cote_m.group(1).strip() if cote_m else None,
            "date": date_m.group(1).strip() if date_m else None,
            "item_id": item_id,
            "image_id": image_id,
            "viewer_url": viewer_url,
            "direct_image": f"{BASE}/num_ext{direct_m.group(1)}" if direct_m else None,
        })
    return items


def fetch_leaf_plans(commune_id, debug=False):
    """
    Récupère les feuilles de plans napoléoniens (TA + sections A/B/…) d'une commune.

    Structure observée AD21 :
      commune (L1)  →  ?id=cid&toc=1
        "Plans du cadastre napoléonien" (L2)  →  ?id=gid&level=4
          → liste de feuilles avec cote/titre/date/image_id (PAS de sous-toc=1)
        "États de section" (L2)  ← ignoré
    """
    commune_html = get_commune_toc(commune_id)
    groups = _parse_toc(commune_html)

    leaves = []
    for title, gid in groups:
        if _RE_SKIP.search(title):
            continue
        if not _RE_PLANS_GROUP.search(title):
            continue
        group_detail_html = get_plan_detail(gid)
        items = parse_plan_group_detail(group_detail_html)
        if debug:
            sys.stderr.write(f"  [debug] groupe '{title}' (id={gid}) → "
                             f"{len(items)} feuilles\n")
        leaves.extend(items)

    return leaves


def classify_type(title):
    """Déduit le type de document à partir du titre EAD."""
    t = (title or "").lower()
    if re.search(r"tableau\s+d.assemb|atlas|ta\b", t):
        return "tableau_assemblage"
    if re.search(r"section\s+[a-z]|^[a-z]\b|feuille", t):
        return "feuille"
    return "feuille"   # défaut pour les sections cadastrales


# ---------------------------------------------------------------------------
# INSEE
# ---------------------------------------------------------------------------

def _normalize(commune):
    name = (commune or "").replace("’", "'").replace("‘", "'")
    m = re.match(r"^(.*?),?\s*\((Le|La|Les|L')\)\s*$", name, re.I)
    if m:
        art, base = m.group(2), m.group(1).strip()
        sep = "" if art.lower() == "l'" else " "
        name = f"{art}{sep}{base}"
    return re.sub(r"\(.*?\)|\[.*?\]", "", name).split(",")[0].strip(" .")


def insee_of(commune):
    name = _normalize(commune)
    if not name:
        return None
    if name in _insee_cache:
        return _insee_cache[name]
    try:
        r = session.get(GEO_API, params={
            "nom": name, "codeDepartement": DEPT,
            "fields": "code", "limit": 1,
        }, timeout=15)
        data = r.json()
        code = data[0]["code"] if data else None
    except Exception:
        code = None
    _insee_cache[name] = code
    time.sleep(0.15)
    return code


# ---------------------------------------------------------------------------
# IIIF check (optionnel)
# ---------------------------------------------------------------------------

def iiif_manifest(ark_url):
    """
    Tente de construire l'URL du manifeste IIIF depuis l'ARK.
    Patterns testés sur archives.cotedor.fr :
      {ark_url}/manifest
      {ark_url}/manifest.json
    Retourne l'URL si le manifeste répond 200, sinon None.
    """
    for suffix in ("/manifest", "/manifest.json"):
        url = ark_url.rstrip("/") + suffix
        try:
            r = session.head(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return url
        except Exception:
            pass
        time.sleep(0.2)
    return None


# ---------------------------------------------------------------------------
# SQL output
# ---------------------------------------------------------------------------

def _q(v):
    if v is None:
        return "null"
    return "'" + str(v).replace("'", "''") + "'"


COLS = ("insee", "type", "archive_url", "iiif_manifest",
        "source", "source_url", "licence", "licence_overlay_ok", "statut")


def emit_sql(rows, out, check_iiif=False):
    total = len(rows)
    with_insee = sum(1 for r in rows if r["insee"])
    print(f"-- Côte-d'Or (AD21 EAD) — {with_insee} notices avec INSEE / {total} total\n",
          file=out)
    for row in rows:
        if not row["insee"]:
            sys.stderr.write(f"  ⚠ INSEE manquant : {row['commune']} — {row['title']}\n")
            continue
        manifest = None
        if check_iiif and row["archive_url"]:
            manifest = iiif_manifest(row["archive_url"])
            if manifest:
                sys.stderr.write(f"  ✓ IIIF : {row['commune']} {row['title']}\n")
        vals = [
            row["insee"],
            row["type"],
            row["archive_url"],
            manifest,
            "Archives départementales de la Côte-d'Or",
            BASE,
            "Réutilisation soumise aux CGU AD21",
            "false",
            "lien",
        ]
        print(
            f"insert into document ({', '.join(COLS)}) values "
            f"({', '.join(_q(v) for v in vals)});",
            file=out,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Harvest cadastre napoléonien — AD Côte-d'Or")
    ap.add_argument("--out", help="Fichier SQL de sortie (défaut : stdout)")
    ap.add_argument("--iiif", action="store_true",
                    help="Teste les manifestes IIIF pour chaque ARK")
    ap.add_argument("--commune", metavar="NOM",
                    help="Limite à une commune (test rapide)")
    ap.add_argument("--debug", action="store_true",
                    help="Affiche les 3000 premiers cars du TOC pour diagnostiquer")
    ap.add_argument("--resolve-ark", metavar="IMAGE_ID",
                    help="Test isolé : résout l'ARK d'un seul id image et quitte")
    args = ap.parse_args()

    sys.stderr.write("Ouverture de session…\n")
    main_html = prime()

    if args.resolve_ark:
        # Test : mode diagnostic — trouve les scripts du viewer + cherche l'ARK
        image_id = args.resolve_ark
        viewer_url = f"{BASE}/v2/ad21/visualiseur/cartes_plans.html"
        sys.stderr.write(f"Fetch viewer avec image_id={image_id}…\n")
        r = session.get(viewer_url, params={"ir": IR, "id": image_id},
                        timeout=30, allow_redirects=True)
        viewer_html = r.text
        dump_path = os.path.join(CACHE_DIR, f"cdo_viewer_{image_id}_full.html")
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(dump_path, "w", encoding="utf-8") as fh:
            fh.write(viewer_html)
        sys.stderr.write(f"Viewer HTML ({len(viewer_html)} cars) sauvegardé : {dump_path}\n\n")

        # Extrait tous les <script src="..."> et <link href="...*.js...">
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', viewer_html)
        sys.stderr.write(f"Scripts trouvés ({len(scripts)}) :\n")
        for s in scripts:
            sys.stderr.write(f"  {s}\n")

        # Fetch chaque JS et cherche "ark" ou "permalink"
        for src in scripts:
            js_url = src if src.startswith("http") else BASE + src.split("?")[0]
            js_url_clean = src if src.startswith("http") else BASE + src
            sys.stderr.write(f"\n→ Fetch {js_url_clean[:80]}…\n")
            try:
                rjs = session.get(js_url_clean, timeout=20)
                js = rjs.text
                hits = [l.strip() for l in js.split("\n")
                        if re.search(r'ark|permalink|md5|sha|hash', l, re.I)]
                if hits:
                    sys.stderr.write(f"  Lignes pertinentes :\n")
                    for h in hits[:10]:
                        sys.stderr.write(f"    {h[:200]}\n")
                else:
                    sys.stderr.write(f"  (rien trouvé)\n")
            except Exception as e:
                sys.stderr.write(f"  Erreur : {e}\n")
        sys.exit(0)

    sys.stderr.write("Recherche du TOC communes…\n")
    general_html = get_general_toc(main_html or "")
    communes = parse_communes(general_html, debug=args.debug)
    if not communes:
        sys.stderr.write(
            "⚠ Aucune commune trouvée dans le TOC général.\n"
            "  → Relancez avec --debug pour voir le HTML brut.\n"
            f"  → Fichiers cache : {CACHE_DIR}/cdo_root_toc.html etc.\n"
        )
        # Affichage automatique du début du HTML pour orienter le diagnostic
        sys.stderr.write("\n--- Début du HTML TOC (1500 cars) ---\n")
        sys.stderr.write(general_html[:1500].replace("\n", " "))
        sys.stderr.write("\n---\n")
        sys.exit(1)

    sys.stderr.write(f"{len(communes)} communes trouvées.\n\n")

    if args.commune:
        communes = [(n, i) for n, i in communes
                    if args.commune.lower() in n.lower()]
        sys.stderr.write(f"Filtre --commune : {len(communes)} retenu(e)s.\n")

    rows = []
    for idx, (name, cid) in enumerate(communes, 1):
        sys.stderr.write(f"[{idx}/{len(communes)}] {name} (id={cid})\n")
        plans = fetch_leaf_plans(cid, debug=args.debug)
        if not plans:
            sys.stderr.write(f"  ⚠ aucun plan trouvé pour {name}\n")
            continue
        insee = insee_of(name)
        for item in plans:
            rows.append({
                "commune": name,
                "insee": insee,
                "title": item["title"],
                "cote": item["cote"],
                "date": item["date"],
                "type": classify_type(item["title"]),
                "archive_url": item["viewer_url"],
            })
            sys.stderr.write(f"    {item['title']} ({item['cote']}) → {item['viewer_url']}\n")

    sys.stderr.write(f"\n{len(rows)} notices collectées.\n")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            emit_sql(rows, fh, check_iiif=args.iiif)
        sys.stderr.write(f"→ SQL écrit dans {args.out}\n")
    else:
        emit_sql(rows, sys.stdout, check_iiif=args.iiif)


if __name__ == "__main__":
    main()
