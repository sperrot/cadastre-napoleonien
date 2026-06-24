#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Harvester FranceArchives → table `document` (cadastre napoléonien).

Descend récursivement un instrument de recherche FranceArchives via ses
exports RDF, isole les feuilles « Tableau d'assemblage » numérisées, en
extrait commune (→ INSEE) / année / cote / source / manifeste IIIF / image,
vérifie la LICENCE par institution (lue dans le manifeste IIIF), puis génère
des INSERT SQL prêts pour Supabase.

⚠️  À LANCER EN LOCAL.
    FranceArchives ne répond pas aux fetchs serveur (ex. WebFetch), mais
    répond normalement depuis une machine classique. Les manifestes/images
    IIIF des AD (ex. Seine-Saint-Denis) sont, eux, accessibles partout.

Dépendances :
    pip install requests rdflib

Usage :
    python harvest_francearchives.py 2679af120dcec5557878b634c3701f842b1d806e \
        > seed_ssd.sql

    # 2679af1… = instrument de recherche « Plans du cadastre » (Seine-Saint-Denis)
"""

import sys
import time
import re
import argparse
import requests
from rdflib import Graph, URIRef, Namespace
from rdflib.namespace import RDF, RDFS

BASE = "https://francearchives.gouv.fr"
RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")
DCTERMS = Namespace("http://purl.org/dc/terms/")

HEADERS = {
    # FranceArchives sert une page de défi JS aux UA non-navigateur :
    # un UA réaliste est nécessaire pour obtenir le contenu.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/rdf+xml, application/xml, text/xml, */*",
}
SLEEP = 0.7          # politesse : ~1 req/s
GEO_API = "https://geo.api.gouv.fr/communes"

# Période retenue (cadastre napoléonien). Surchargée par les arguments CLI.
YEAR_MIN, YEAR_MAX = 1800, 1860

session = requests.Session()
session.headers.update(HEADERS)

# Défi anti-bot FranceArchives : <script>window.location.href='/redirect_…'</script>
REDIRECT_RE = re.compile(r"window\.location\.href='(/redirect_[^']+)'")

# Caches pour éviter les requêtes répétées
_rdf_cache, _insee_cache, _licence_cache = {}, {}, {}


def get(url: str, accept: str = None) -> requests.Response:
    """GET qui franchit le défi JS de FranceArchives (redirection + cookie)."""
    h = {"Accept": accept} if accept else {}
    r = session.get(url, headers=h, timeout=30, allow_redirects=True)
    head = r.text[:600]
    if "window.location.href='/redirect_" in head:
        m = REDIRECT_RE.search(head)
        if m:
            # suivre une fois : pose le cookie de session, renvoie le vrai contenu
            r = session.get(BASE + m.group(1), headers=h, timeout=30, allow_redirects=True)
            time.sleep(SLEEP)
    return r


# ----------------------------------------------------------------------
# Récupération RDF (on essaie plusieurs motifs d'URL d'export)
# ----------------------------------------------------------------------
def fetch_graph(etype: str, eid: str) -> Graph:
    key = (etype, eid)
    if key in _rdf_cache:
        return _rdf_cache[key]
    candidates = [
        f"{BASE}/{etype}/{eid}.rdf",
        f"{BASE}/{etype}/{eid}/rdf.xml",
        f"{BASE}/{etype}/{eid}/rdf",
        f"{BASE}/{etype}/{eid}",          # content-negotiation via Accept
    ]
    for url in candidates:
        try:
            r = get(url, accept="application/rdf+xml")
        except requests.RequestException:
            continue
        if r.status_code == 200 and "rdf:RDF" in r.text[:4000]:
            g = Graph()
            g.parse(data=r.content, format="xml")
            _rdf_cache[key] = g
            time.sleep(SLEEP)
            return g
    raise RuntimeError(
        f"Aucun export RDF n'a répondu pour {etype}/{eid}. "
        f"Vérifie le motif d'URL (copie le lien du bouton « RDF/XML » d'une notice)."
    )


def eid_of(uri: str) -> str:
    return uri.rstrip("/").split("/")[-1]


# Titres de branches à exclure d'office (hors cadastre napoléonien)
EXCLUDE_RE = re.compile(r"rénov|renov|intendance", re.IGNORECASE)


def first_str(g: Graph, subj, pred):
    for o in g.objects(subj, pred):
        return str(o)
    return None


def year_of(g: Graph, subj, pred):
    s = first_str(g, subj, pred)
    if s and s[:4].isdigit():
        return int(s[:4])
    return None


def period_overlaps(begin, end) -> bool:
    """L'intervalle [begin, end] du nœud recoupe-t-il [YEAR_MIN, YEAR_MAX] ?
    Dates manquantes traitées comme bornes ouvertes (on descend dans le doute)."""
    b = begin if begin is not None else -10**9
    e = end if end is not None else 10**9
    return b <= YEAR_MAX and e >= YEAR_MIN


# ----------------------------------------------------------------------
# Descente récursive : on collecte les feuilles (avec manifeste IIIF)
# ----------------------------------------------------------------------
def walk(etype: str, eid: str, leaves: list, seen: set, parent_title: str = None):
    if eid in seen:
        return
    seen.add(eid)
    g = fetch_graph(etype, eid)
    subj = URIRef(f"{BASE}/{etype}/{eid}")

    title = first_str(g, subj, RICO.title) or ""
    begin = year_of(g, subj, RICO.beginningDate)
    end = year_of(g, subj, RICO.endDate)
    children = list(g.objects(subj, RICO.includesOrIncluded))
    manifest = leaf_manifest(g, subj)

    # ---- Feuille (notice avec manifeste IIIF) ----
    if manifest and not children:
        if begin is not None and not (YEAR_MIN <= begin <= YEAR_MAX):
            sys.stderr.write(f"  (hors période {begin}) {parent_title or ''} — {title}\n")
            return
        # begin None ([s.d.]) : on garde, car la BRANCHE a déjà été validée napoléonienne
        leaves.append(extract_leaf(g, subj, manifest, commune_hint=parent_title))
        sys.stderr.write(f"  feuille : {parent_title or '?'} — {title} ({eid})\n")
        return

    # ---- Nœud : ÉLAGAGE avant de descendre (l'index, c'est titre + dates) ----
    if EXCLUDE_RE.search(title):
        sys.stderr.write(f"  ✂ branche écartée (titre) : {title}\n")
        return
    if not period_overlaps(begin, end):
        sys.stderr.write(f"  ✂ branche écartée ({begin}-{end}) : {title}\n")
        return
    for child in children:
        walk("facomponent", eid_of(str(child)), leaves, seen, parent_title=title)


def leaf_manifest(g: Graph, subj: URIRef):
    """URL du manifeste IIIF si la notice en porte un, sinon None."""
    # Le manifeste est une Instantiation dont l'@id (sur le domaine AD) finit
    # par /manifest(#…). On reconstruit l'URL en coupant le fragment.
    for inst in g.objects(subj, RICO.isOrWasDescribedBy):
        for m in g.objects(inst, RICO.hasInstantiation):
            s = str(m)
            if "/manifest" in s:
                return re.sub(r"//+", "/", s.split("#")[0]).replace("https:/", "https://")
    # Repli : n'importe quel triplet contenant /manifest
    for s in g.subjects():
        if "/manifest" in str(s):
            return re.sub(r"//+", "/", str(s).split("#")[0]).replace("https:/", "https://")
    return None


def extract_leaf(g: Graph, subj: URIRef, manifest: str, commune_hint: str = None) -> dict:
    def first(pred):
        for o in g.objects(subj, pred):
            return str(o)
        return None

    title = first(RICO.title) or first(RDFS.label) or ""
    year = first(RICO.beginningDate)
    cote = first(RICO.identifier)
    service = first(RICO.hasOrHadManager) or first(RICO.hasOrHadHolder)

    # commune : selon la structure, soit dans le titre de la feuille
    # ("Aulnay-sous-Bois, 1782."), soit dans celui du parent ("Sevran").
    commune_name = commune_from_titles(title, commune_hint)
    if not (commune_name and insee_of(commune_name)):
        for s in g.objects(subj, RICO.hasOrHadSubject):
            if "/location/" in str(s):
                loc = resolve_location(eid_of(str(s)))
                if loc:
                    commune_name = loc
                break

    # image (dao) : source d'une instantiation, hors vignette
    image = None
    for inst in g.objects(subj, RICO.hasInstantiation):
        for src in g.objects(inst, DCTERMS.source):
            u = str(src)
            if "daoloc" in u and "vignette" not in u:
                image = re.sub(r"//+", "/", u).replace("https:/", "https://")

    licence, overlay_ok = resolve_licence(service, manifest)

    return {
        "title": title,
        "type": classify(title),
        "annee": int(year) if year and year.isdigit() else None,
        "cote": cote,
        "commune": commune_name,
        "insee": insee_of(commune_name) if commune_name else None,
        "facomponent": str(subj).replace(f"{BASE}/", f"{BASE}/fr/"),
        "iiif_manifest": manifest,
        "image_url": image,
        "source_service": service,
        "licence": licence,
        "licence_overlay_ok": overlay_ok,
    }


GENERIC_TITLES = ("tableau", "section", "plan", "feuille", "matrice",
                  "état", "etat", "atlas", "registre", "cadastre")

def commune_from_titles(leaf_title: str, parent_title: str):
    """Commune = titre feuille s'il est nominatif ("Aulnay-sous-Bois, 1782."),
    sinon titre parent ("Sevran") pour les feuilles génériques (tableau, section…)."""
    t = (leaf_title or "").strip()
    low = t.lower()
    if t and not any(low.startswith(w) for w in GENERIC_TITLES):
        return re.sub(r"[\s,]+\d{3,4}.*$", "", t).strip(" .,")   # retire l'année finale
    return parent_title


def classify(title: str) -> str:
    t = title.lower()
    if "assemblage" in t:
        return "tableau_assemblage"
    if "section" in t:
        return "section"
    return "feuille"


# ----------------------------------------------------------------------
# Résolutions (commune→INSEE, licence via manifeste)
# ----------------------------------------------------------------------
def resolve_location(loc_id: str):
    if loc_id in _insee_cache:
        return _insee_cache[loc_id]
    try:
        g = fetch_graph("location", loc_id)
        label = None
        for _, _, o in g.triples((None, RDFS.label, None)):
            label = str(o)
            break
        _insee_cache[loc_id] = label
        return label
    except RuntimeError:
        return None


def insee_of(commune_name: str):
    # nettoie « SEVRAN [commune] » → « SEVRAN »
    name = re.sub(r"\[.*?\]", "", commune_name or "").strip()
    if not name:
        return None
    if name in _insee_cache:
        return _insee_cache[name]
    try:
        r = session.get(GEO_API, params={"nom": name, "fields": "code",
                                          "boost": "population", "limit": 1}, timeout=15)
        data = r.json()
        code = data[0]["code"] if data else None
    except Exception:
        code = None
    _insee_cache[name] = code
    time.sleep(0.2)
    return code


def resolve_licence(service: str, manifest: str):
    """Lit le manifeste IIIF (accessible) pour déterminer la licence."""
    if service in _licence_cache:
        return _licence_cache[service]
    licence, overlay_ok = None, False
    try:
        r = session.get(manifest, timeout=30)
        txt = r.text.lower()
        if "licence ouverte" in txt or "etalab" in txt or "open licence" in txt:
            licence, overlay_ok = "Licence Ouverte", True
        elif "creativecommons.org/licenses/by" in txt or "cc-by" in txt:
            licence, overlay_ok = "CC-BY", True
        elif "publicdomain" in txt or "domaine public" in txt:
            licence, overlay_ok = "Domaine public", True
        else:
            licence, overlay_ok = "À vérifier", False
    except Exception:
        licence, overlay_ok = "À vérifier", False
    _licence_cache[service] = (licence, overlay_ok)
    return licence, overlay_ok


# ----------------------------------------------------------------------
# Sortie SQL
# ----------------------------------------------------------------------
def sql_escape(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def emit_sql(leaves):
    cols = ("insee", "type", "annee", "cote", "archive_url", "iiif_manifest",
            "image_url", "source", "source_url", "licence", "licence_overlay_ok", "statut")
    print("-- Généré par harvest_francearchives.py")
    print(f"-- {len([l for l in leaves if l['insee']])} notices avec INSEE / {len(leaves)} feuilles\n")
    for l in leaves:
        if not l["insee"]:
            sys.stderr.write(f"  ⚠ INSEE introuvable pour : {l['commune']} ({l['title']})\n")
            continue
        statut = "georef" if l["licence_overlay_ok"] else "lien"
        # source lisible : on garde l'URI service ; à enrichir si besoin
        vals = [
            l["insee"], l["type"], l["annee"], l["cote"], l["facomponent"],
            l["iiif_manifest"], l["image_url"], l["source_service"], None,
            l["licence"], l["licence_overlay_ok"], statut,
        ]
        print(f"insert into document ({', '.join(cols)}) values "
              f"({', '.join(sql_escape(v) for v in vals)});")


def main():
    global YEAR_MIN, YEAR_MAX
    ap = argparse.ArgumentParser(description="Harvester FranceArchives → SQL Supabase")
    ap.add_argument("eid", help="identifiant de l'instrument de recherche (ou facomponent)")
    ap.add_argument("etype", nargs="?", default="findingaid",
                    choices=["findingaid", "facomponent"])
    ap.add_argument("--year-min", type=int, default=YEAR_MIN)
    ap.add_argument("--year-max", type=int, default=YEAR_MAX)
    args = ap.parse_args()
    YEAR_MIN, YEAR_MAX = args.year_min, args.year_max

    leaves, seen = [], set()
    sys.stderr.write(f"Descente de {args.etype}/{args.eid} "
                     f"(période {YEAR_MIN}-{YEAR_MAX}) …\n")
    walk(args.etype, args.eid, leaves, seen)
    sys.stderr.write(f"\n{len(leaves)} feuilles collectées.\n")
    emit_sql(leaves)


if __name__ == "__main__":
    main()
