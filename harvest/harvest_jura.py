#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Connecteur PORTAIL JURA (archives39.fr, Mnesys) → harvest/seed_jura.sql

Même logiciel que le Doubs (harvest_doubs.py) : l'arbre se lit par l'API du
plan de classement, relevée dans un HAR (2026-09-29) :

    GET /api/classificationPlan/v1/children/{nodeUuid}_{rootUuid}
        → {id, title, data:{childrenUrl, children, isLoaded, url, contentUrl},
           dataType: "branch" | "leaf"}

Arbre du fonds « Cadastre » (racine 1fcfd6ea…) :

    Documents cadastraux dits napoléoniens          ← START
      Communes commençant par la lettre A
        Abergement-la-Ronce                         ← commune
          Plans parcellaires napoléoniens           ← retenu
            « Abergement-La-Ronce, tableau d'assemblage.géomètre : … »  (leaf)
            « Abergement-La-Ronce, section A, Nouhe-Merceret. … »       (leaf)
          Etats de sections et matrices             ← écarté

Une feuille porte `data.url` (ark public) et `data.contentUrl`
(/record/36595/<ark>/content). Le JPEG se télécharge par
/ark:/36595/<ark>/<uuid_média> ; l'uuid média est cherché dans la réponse de
contentUrl. Référence connue (--check) :
    7kbm3w2qnglr → 09015152-973c-47cf-8c36-995ca8c72371

Licence : Licence Ouverte Etalab sur les feuilles du cadastre, par accord
écrit de l'AD39 (2026-09) → overlay autorisé. Le JPEG passe en IIIF par le
worker (/static-manifest), comme le Doubs et la Saône-et-Loire.

⚠️  À LANCER EN LOCAL (archives39.fr est hors de portée des outils Claude).

Dépendances : pip install requests
Usage :
    python harvest/harvest_jura.py --check            # 1. auto-test sur 1 planche
    python harvest/harvest_jura.py --limit 30         # 2. essai (30 planches)
    python harvest/harvest_jura.py                    # 3. complet → seed_jura.sql
    python harvest/load_seed_to_supabase.py harvest/seed_jura.sql

Si le portail renvoie un captcha (hCaptcha) au lieu du JSON : copier le cookie
PHPSESSID d'un navigateur ayant ouvert archives39.fr et relancer avec
    --phpsessid <valeur>
Tout est mis en cache (harvest/.cache/jura_*) : un rerun reprend là où il
s'est arrêté.
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse

import requests

BASE = "https://archives39.fr"
NAAN = "36595"
GEO_API = "https://geo.api.gouv.fr/communes"
DEPT = "39"
WORKER = "https://iiif-allmaps.sperrot.workers.dev"

# uuids relevés dans le HAR
ROOT = "1fcfd6ea-9d0d-412a-acda-da315013c1f2"    # fonds « Cadastre » (suffixe de session)
START = "5d09a609-34a0-4805-95af-ec46d2c1388b"   # « Documents cadastraux dits napoléoniens »

REF_ARK = "7kbm3w2qnglr"                          # Abergement-la-Ronce, TA
REF_MEDIA = "09015152-973c-47cf-8c36-995ca8c72371"

SOURCE = "Archives départementales du Jura"
LICENCE = "Licence Ouverte Etalab (accord écrit AD39)"

# Branches à ne pas descendre (on ne veut que les plans)
SKIP_BRANCH_RE = re.compile(r"matrice|[ée]tats?\s+de\s+section", re.I)
# Titres de regroupement qui ne sont pas des communes
GROUP_RE = re.compile(r"^communes?\s+commen|^plans?\s+parcellaires|^documents\s+cadastraux", re.I)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SLEEP = 0.3
TIMEOUT = 60
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_jura.sql")

try:                       # console Windows en cp1252
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

session = requests.Session()
session.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                   "Gecko/20100101 Firefox/128.0"),
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
})


class Captcha(Exception):
    pass


# --------------------------------------------------------------------------
# HTTP + cache
# --------------------------------------------------------------------------
def prime(phpsessid=None):
    """Pose license=true (bandeau CGU) + PHPSESSID (fourni ou obtenu)."""
    session.cookies.set("license", "true", domain="archives39.fr")
    if phpsessid:
        session.cookies.set("PHPSESSID", phpsessid, domain="archives39.fr")
    else:
        session.get(f"{BASE}/ark:/{NAAN}/{REF_ARK}", timeout=30)


def cached_get(key, url, want_json=True):
    """GET avec cache disque (succès seulement) et 4 essais."""
    path = os.path.join(CACHE_DIR, f"jura_{key}.{'json' if want_json else 'txt'}")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) if want_json else fh.read()
    for attempt in range(4):
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            if want_json:
                try:
                    data = r.json()
                except ValueError:
                    if "captcha" in r.text.lower():
                        raise Captcha(url)
                    return None
            else:
                data = r.text
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh) if want_json else fh.write(data)
            time.sleep(SLEEP)
            return data
        time.sleep(2 * (attempt + 1))
    sys.stderr.write(f"  ⚠ illisible : {url}\n")
    return None


def children(node_uuid):
    data = cached_get(f"node_{node_uuid}",
                      f"{BASE}/api/classificationPlan/v1/children/{node_uuid}_{ROOT}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return (data.get("data") or {}).get("children") or data.get("children") or []
    return []


def kids_of(node):
    d = node.get("data") or {}
    if d.get("isLoaded") and d.get("children"):
        return d["children"]
    return children((node.get("id") or "").split("_")[0])


# --------------------------------------------------------------------------
# Descente de l'arbre
# --------------------------------------------------------------------------
def walk(node, commune, leaves, seen, depth=0):
    nid = node.get("id")
    if not nid or nid in seen or depth > 12:
        return
    seen.add(nid)
    title = (node.get("title") or "").strip()
    if node.get("dataType") == "branch":
        if SKIP_BRANCH_RE.search(title):
            return
        if not GROUP_RE.search(title):
            commune = title                       # le nœud commune
            sys.stderr.write(f"  {commune}\n")
        for k in kids_of(node):
            walk(k, commune, leaves, seen, depth + 1)
    else:
        d = node.get("data") or {}
        ark = ark_of(d.get("url"))
        if ark:
            leaves.append({"commune": commune, "title": title, "ark": ark, "node_id": nid,
                           "url": d.get("url"), "content": d.get("contentUrl")})


def ark_of(url):
    m = re.search(rf"ark:/{NAAN}/([0-9a-z]+)", url or "")
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Image : uuid média + éventuel manifeste IIIF natif
# --------------------------------------------------------------------------
def media_of(leaf):
    """→ (jpg_url | None, manifeste_natif | None, nb_images)."""
    ark = leaf["ark"]
    url = leaf.get("content") or f"{BASE}/record/{NAAN}/{ark}/content"
    txt = cached_get(f"content_{ark}", url, want_json=False)
    if not txt:
        return None, None, 0
    flat = txt.replace("\\/", "/")
    # 1) lien de téléchargement explicite /ark:/NAAN/<ark>/<uuid>
    uuids = re.findall(rf"ark:/{NAAN}/{ark}/({UUID_RE.pattern})", flat, re.I)
    # 2) repli : uuids du document, hors uuids de l'arbre
    if not uuids:
        leaf_uuid = (leaf.get("node_id") or "").split("_")[0]
        uuids = [u for u in UUID_RE.findall(flat)
                 if u.lower() not in (ROOT, START, leaf_uuid.lower())]
    uuids = list(dict.fromkeys(u.lower() for u in uuids))
    m = re.search(r"https?://[^\"'\s<>]+/manifest(?:\.json)?\b", flat)
    manifest = m.group(0) if m else None
    jpg = f"{BASE}/ark:/{NAAN}/{ark}/{uuids[0]}" if uuids else None
    return jpg, manifest, len(uuids)


# --------------------------------------------------------------------------
# Titre → type / section / année
# --------------------------------------------------------------------------
def classify(title):
    t = title.lower()
    if "assemblage" in t:
        return "tableau_assemblage"
    if re.search(r"\bfeuille\b", t):
        return "feuille"
    return "section"


def annee_of(title):
    m = re.search(r"\b(1[78]\d\d)\b", title or "")
    y = int(m.group(1)) if m else None
    return y if y and 1790 <= y <= 1870 else None


# --------------------------------------------------------------------------
# Commune → INSEE (exact uniquement ; cf. harvest/README.md, affaire Ainhoa)
# --------------------------------------------------------------------------
def cle(nom):
    s = "".join(c for c in unicodedata.normalize("NFD", (nom or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-'’\"]+", " ", s).strip()


def load_alias():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "communes_alias.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return {cle(k): v for k, v in json.load(fh).get(DEPT, {}).items()}
    except Exception:
        return {}


ALIAS = load_alias()
_insee = {}


def normalize(commune):
    """« Arsures (les) [Commune détachée …] » → « Les Arsures » ;
    « Aubépin (l") » → « L'Aubépin »."""
    name = re.sub(r"\[.*?\]", "", commune or "").replace("’", "'").strip()
    m = re.match(r"^(.*?),?\s*\((le|la|les|l['\"]?)\)\s*$", name, re.I)
    if m:
        art = m.group(2).rstrip("'\"").capitalize()
        name = f"{art}'{m.group(1).strip()}" if art == "L" else f"{art} {m.group(1).strip()}"
    return re.sub(r"\(.*?\)", "", name).strip(" .,")


def geo_exact(name):
    if not name:
        return None
    k = cle(name)
    if k in ALIAS:
        return ALIAS[k]
    if k in _insee:
        return _insee[k]
    code = None
    try:
        r = session.get(GEO_API, params={"nom": name, "codeDepartement": DEPT,
                                          "fields": "nom,code", "limit": 10}, timeout=15)
        for c in r.json():
            if cle(c["nom"]) == k:
                code = c["code"]
                break
    except Exception:
        pass
    _insee[k] = code
    time.sleep(0.1)
    return code


def insee_of(commune):
    code = geo_exact(normalize(commune))
    if code:
        return code, None
    # « [commune fusionnée à celle de Malange en 1824.] » → Malange
    m = re.search(r"(?:fusionn[ée]e|r[ée]unie|rattach[ée]e)\s+(?:à|a)\s+(?:celle\s+de\s+)?"
                  r"([^\]\.,;]+?)(?:\s+en\s+\d{4}|\]|\.|,|$)", commune or "", re.I)
    if m:
        code = geo_exact(normalize(m.group(1)))
        if code:
            return code, m.group(1).strip()
    return None, None


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------
def q(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


COLS = ("insee", "type", "annee", "archive_url", "image_url", "iiif_manifest",
        "source", "source_url", "licence", "licence_overlay_ok", "statut")


def commune_of(leaf):
    """Nœud commune parent ; à défaut (planche rangée hors d'un nœud commune),
    la commune en tête du titre : « Abergement-La-Ronce, section A, … »."""
    if leaf.get("commune"):
        return leaf["commune"]
    return (leaf.get("title") or "").split(",")[0].strip() or None


def emit(leaves, out_path):
    rows, sans_insee, sans_image, multi, via_fusion = [], [], 0, 0, set()
    for i, l in enumerate(leaves, 1):
        if not l.get("commune"):
            l["commune"] = commune_of(l)
            l["depuis_titre"] = True
        code, cible = insee_of(l["commune"])
        if not code:
            sans_insee.append(l)
            continue
        if cible:
            via_fusion.add(f"{l['commune']} → {cible} ({code})")
        jpg, manifest, n = media_of(l)
        if n > 1:
            multi += 1
        if not jpg and not manifest:
            sans_image += 1
        iiif = manifest or (f"{WORKER}/static-manifest?u={urllib.parse.quote(jpg, safe='')}"
                            if jpg else None)
        rows.append((code, classify(l["title"]), annee_of(l["title"]), l["url"], jpg, iiif,
                     SOURCE, BASE, LICENCE, True, "georef" if iiif else "lien"))
        if i % 100 == 0:
            sys.stderr.write(f"  … {i}/{len(leaves)} planches\n")

    hors = sum(1 for r in rows if not r[0].startswith(DEPT))
    if rows and hors / len(rows) > 0.05:
        raise SystemExit(f"✖ {hors}/{len(rows)} INSEE hors du {DEPT} — seed NON écrit")

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"-- Jura (39) — portail Mnesys archives39.fr — {len(rows)} planches, "
                 f"{len({r[0] for r in rows})} communes\n")
        fh.write(f"-- {len(sans_insee)} planches sans INSEE · {sans_image} sans image · "
                 f"{multi} à plusieurs images (1re retenue)\n\n")
        for r in rows:
            fh.write(f"insert into document ({', '.join(COLS)}) values "
                     f"({', '.join(q(v) for v in r)});\n")

    types = {}
    for r in rows:
        types[r[1]] = types.get(r[1], 0) + 1
    sys.stderr.write(f"\n→ {out_path}\n  {len(rows)} planches · "
                     f"{len({r[0] for r in rows})} communes · {types}\n"
                     f"  sans image : {sans_image} · multi-images : {multi}\n")
    if via_fusion:
        sys.stderr.write("  rattachées via la mention de fusion :\n")
        for s in sorted(via_fusion):
            sys.stderr.write(f"    {s}\n")
    n_titre = sum(1 for l in leaves if l.get("depuis_titre"))
    if n_titre:
        sys.stderr.write(f"  {n_titre} planches hors nœud commune → commune lue dans le titre\n")
    if sans_insee:
        communes = sorted({l["commune"] or "(sans commune)" for l in sans_insee})
        tsv = os.path.splitext(out_path)[0] + "_sans_insee.tsv"
        with open(tsv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("commune\ttitre\tark\n")
            for l in sans_insee:
                fh.write(f"{l['commune'] or ''}\t{l['title']}\t{l['url']}\n")
        sys.stderr.write(f"  ⚠ {len(sans_insee)} planches / {len(communes)} communes sans INSEE "
                         f"(détail : {tsv}) :\n")
        for c in communes:
            sys.stderr.write(f"    {c}\n")


# --------------------------------------------------------------------------
def check():
    """Auto-test : la planche de référence doit donner l'uuid média connu."""
    leaf = {"ark": REF_ARK, "content": f"{BASE}/record/{NAAN}/{REF_ARK}/content"}
    jpg, manifest, n = media_of(leaf)
    sys.stderr.write(f"contentUrl  : {leaf['content']}\n"
                     f"image       : {jpg}  ({n} uuid candidats)\n"
                     f"manifeste   : {manifest}\n")
    attendu = f"{BASE}/ark:/{NAAN}/{REF_ARK}/{REF_MEDIA}"
    if jpg == attendu:
        sys.stderr.write("✔ uuid média retrouvé — extraction calibrée\n")
        return 0
    p = os.path.join(CACHE_DIR, f"jura_content_{REF_ARK}.txt")
    sys.stderr.write(f"✖ attendu {attendu}\n"
                     f"  Réponse brute gardée dans {p} — l'envoyer pour calibrage.\n")
    return 1


def main():
    ap = argparse.ArgumentParser(description="Portail Jura (Mnesys) → seed_jura.sql")
    ap.add_argument("--check", action="store_true", help="auto-test sur la planche de référence")
    ap.add_argument("--limit", type=int, help="n'émettre que N planches (essai)")
    ap.add_argument("--start", default=START, help="uuid du nœud de départ")
    ap.add_argument("--phpsessid", help="cookie PHPSESSID d'un navigateur (si captcha)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()

    try:
        prime(args.phpsessid)
        if args.check:
            sys.exit(check())
        sys.stderr.write(f"Descente depuis {args.start} …\n")
        leaves, seen = [], set()
        for k in children(args.start):
            walk(k, None, leaves, seen)
            if args.limit and len(leaves) >= args.limit:
                break
        sys.stderr.write(f"\n{len(leaves)} planches collectées.\n")
        if args.limit:
            leaves = leaves[:args.limit]
        emit(leaves, args.out)
    except Captcha as e:
        sys.exit(f"✖ captcha servi au lieu du JSON ({e}).\n"
                 f"  Ouvrir {BASE} dans un navigateur, copier le cookie PHPSESSID,\n"
                 f"  puis relancer avec --phpsessid <valeur> (le cache garde l'acquis).")


if __name__ == "__main__":
    main()
