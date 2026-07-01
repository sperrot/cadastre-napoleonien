#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Connecteur PORTAIL DOUBS (archives.doubs.fr) — annuaire de liens (sans IIIF).

Le Doubs n'est PAS sur FranceArchives et son portail ne sert pas de IIIF
(→ liens seuls, pas d'overlay). On exploite son API interne de plan de
classement :

    GET /api/classificationPlan/v1/children/{nodeUuid}_{rootUuid}
        → enfants d'un nœud : {id, title, data:{childrenUrl, url, contentUrl,
          children, isLoaded}, dataType}  (dataType "branch" sinon feuille)
    `data.url` = lien ark public de la fiche  ← c'est le lien de l'annuaire.

Auth : cookies PHPSESSID (posé par une 1ʳᵉ requête) + license=true (bandeau).

⚠️  À LANCER EN LOCAL (TLS du poste OK ; les outils Claude n'ont pas la CA).

Dépendances : pip install requests
Usage :
    python harvest_doubs.py --out seed_doubs.sql
    # options : --start <uuid> (défaut = cadastre napoléonien)
    #           --root  <uuid> (défaut = fonds 3P, sert de suffixe de session)
"""

import sys
import os
import json
import re
import time
import argparse
import urllib.parse
import requests

BASE = "https://archives.doubs.fr"
GEO_API = "https://geo.api.gouv.fr/communes"
DEPT = "25"

# uuids stables (relevés dans le HAR) :
ROOT = "dff59721-4c89-4651-ad58-59520c634851"   # fonds « 3P Délimitation… » = suffixe
START = "f6a19119-8ef1-4f03-a3e4-07333bb3c66e"  # « Cadastre parcellaire dit napoléonien »

# Titres de feuilles à RETENIR pour l'annuaire cadastre (1 lien/commune)
KEEP_LEAF_RE = re.compile(r"atlas\s+parcellaire|tableau\s+d|plan", re.I)
SLEEP = 0.3
TIMEOUT = 60

# Cache disque (réutilise le dossier déjà gitignoré .cache/) : un re-run reprend
# là où il s'était arrêté (les nœuds déjà lus ne sont pas refaits).
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

session = requests.Session()
session.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                   "Gecko/20100101 Firefox/128.0"),
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
})
_insee_cache = {}


def prime():
    """1ʳᵉ requête : pose le cookie PHPSESSID + accepte le bandeau licence."""
    session.cookies.set("license", "true", domain="archives.doubs.fr")
    session.cookies.set("footerDisplayState", "false", domain="archives.doubs.fr")
    session.get(f"{BASE}/ark:/25993/r3vptqs9ndh2", timeout=30)


def _extract_children(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        d = data.get("data") or {}
        return d.get("children") or data.get("children") or []
    return []


def children(node_uuid: str):
    """Enfants d'un nœud, avec cache disque + retries (saute le nœud si KO)."""
    cache_path = os.path.join(CACHE_DIR, f"doubs_{node_uuid}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                return _extract_children(json.load(fh))
        except Exception:
            pass
    url = f"{BASE}/api/classificationPlan/v1/children/{node_uuid}_{ROOT}"
    for attempt in range(4):                 # résilience : timeouts/aléas réseau
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 404:
            break
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                break
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)            # ne cache que les succès
            time.sleep(SLEEP)
            return _extract_children(data)
        time.sleep(2 * (attempt + 1))
    sys.stderr.write(f"  ⚠ enfants illisibles pour {node_uuid} — nœud ignoré\n")
    return []


def uuid_of(node):
    return (node.get("id") or "").split("_")[0]


def kids_of(node):
    """enfants préchargés si présents, sinon requête."""
    d = node.get("data") or {}
    if d.get("isLoaded") and d.get("children"):
        return d["children"]
    return children(uuid_of(node))


def is_branch(node):
    return node.get("dataType") == "branch"


def walk(node, parent_title, leaves, seen, depth=0):
    nid = node.get("id")
    if not nid or nid in seen or depth > 12:
        return
    seen.add(nid)
    title = (node.get("title") or "").strip()
    if is_branch(node):
        for k in kids_of(node):
            walk(k, parent_title=title, leaves=leaves, seen=seen, depth=depth + 1)
    else:
        # Feuille : on ne garde que l'« Atlas parcellaire » (le plan napoléonien).
        if KEEP_LEAF_RE.search(title):
            url = (node.get("data") or {}).get("url")
            commune = parent_title          # le nœud commune est le parent direct
            leaves.append({"commune": commune, "title": title, "url": url})
            sys.stderr.write(f"  feuille : {commune or '?'} — {title}\n")


def normalize_commune(commune):
    """Apostrophe typographique → droite, et article inversé « X (Les) » → « Les X »."""
    name = (commune or "").replace("’", "'").replace("‘", "'")
    m = re.match(r"^(.*?),?\s*\((Le|La|Les|L')\)\s*$", name, re.I)
    if m:                                   # « Allemands (Les) » → « Les Allemands »
        art = m.group(2)
        sep = "" if art.lower() == "l'" else " "
        name = f"{art}{sep}{m.group(1).strip()}"
    return re.sub(r"\(.*?\)|\[.*?\]", "", name).split(",")[0].strip(" .")


def insee_of(commune):
    name = normalize_commune(commune)
    if not name:
        return None
    if name in _insee_cache:
        return _insee_cache[name]
    try:
        r = session.get(GEO_API, params={"nom": name, "codeDepartement": DEPT,
                                          "fields": "code", "limit": 1}, timeout=15)
        data = r.json()
        code = data[0]["code"] if data else None
    except Exception:
        code = None
    _insee_cache[name] = code
    time.sleep(0.2)
    return code


def sql_escape(v):
    if v is None:
        return "null"
    return "'" + str(v).replace("'", "''") + "'"


def emit_sql(leaves, out):
    cols = ("insee", "type", "archive_url", "source", "source_url",
            "licence", "licence_overlay_ok", "statut")
    n_ok = sum(1 for l in leaves if insee_of(l["commune"]))
    print(f"-- Doubs (portail propre, sans IIIF) — {n_ok} liens avec INSEE / "
          f"{len(leaves)} feuilles\n", file=out)
    for l in leaves:
        insee = insee_of(l["commune"])
        if not insee:
            sys.stderr.write(f"  ⚠ INSEE introuvable : {l['commune']} ({l['title']})\n")
            continue
        vals = [insee, "tableau_assemblage", l["url"],
                "Archives départementales du Doubs", BASE,
                "Réutilisation OK (CGU AD25)", "false", "lien"]
        print(f"insert into document ({', '.join(cols)}) values "
              f"({sql_escape(vals[0])}, {sql_escape(vals[1])}, {sql_escape(vals[2])}, "
              f"{sql_escape(vals[3])}, {sql_escape(vals[4])}, {sql_escape(vals[5])}, "
              f"{vals[6]}, {sql_escape(vals[7])});", file=out)


# Page de recherche par commune (mène aux documents numérisés, dont l'atlas).
SEARCH_URL = ("https://archives.doubs.fr/search/results"
              "?target=controlledAccessGeographicName&keyword={kw}")


def emit_update(leaves, out):
    """Repointe les liens Doubs (notice morte) vers la recherche-commune.
    Clé = l'ancien ark notice (déjà en base) ; pas de re-crawl, pas d'INSEE."""
    print("-- Repointage liens Doubs → recherche par commune (UPDATE)\n", file=out)
    done = set()
    for l in leaves:
        old, commune = l.get("url"), l.get("commune")
        if not old or not commune or old in done:
            continue
        done.add(old)
        new = SEARCH_URL.format(kw=urllib.parse.quote(commune))
        print(f"update document set archive_url = {sql_escape(new)} "
              f"where archive_url = {sql_escape(old)};", file=out)
    sys.stderr.write(f"{len(done)} UPDATE générés.\n")


def main():
    global ROOT
    ap = argparse.ArgumentParser(description="Connecteur portail Doubs → SQL")
    ap.add_argument("--start", default=START, help="uuid du nœud de départ")
    ap.add_argument("--root", default=ROOT, help="uuid racine (suffixe de session)")
    ap.add_argument("--out", help="fichier SQL (UTF-8). Défaut : stdout.")
    ap.add_argument("--update-search", action="store_true",
                    help="émet des UPDATE repointant vers la recherche-commune "
                         "(au lieu des INSERT). Réutilise le cache, pas de re-crawl.")
    args = ap.parse_args()
    ROOT = args.root
    emit = emit_update if args.update_search else emit_sql

    sys.stderr.write("Ouverture de session (PHPSESSID)…\n")
    prime()
    sys.stderr.write(f"Descente depuis {args.start} …\n")
    leaves, seen = [], set()
    # nœud de départ : on liste directement ses enfants
    for k in children(args.start):
        walk(k, parent_title=None, leaves=leaves, seen=seen)
    sys.stderr.write(f"\n{len(leaves)} feuilles « Atlas parcellaire » collectées.\n")

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            emit(leaves, fh)
        sys.stderr.write(f"→ SQL écrit dans {args.out}\n")
    else:
        emit(leaves, sys.stdout)


if __name__ == "__main__":
    main()
