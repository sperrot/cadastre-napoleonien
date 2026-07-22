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
import os
import time
import re
import json
import argparse
import collections
import unicodedata
import requests
from rdflib import Graph, URIRef, Namespace
from rdflib.namespace import RDF, RDFS

BASE = "https://francearchives.gouv.fr"
RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
GEO1 = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

HEADERS = {
    # FranceArchives sert une page de défi JS aux UA non-navigateur :
    # un UA réaliste est nécessaire pour obtenir le contenu.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/rdf+xml, application/xml, text/xml, */*",
}
SLEEP = 0.4          # politesse entre requêtes réseau (cache disque = 0 sleep)
GEO_API = "https://geo.api.gouv.fr/communes"

# Cache disque des RDF : un re-run (ou une reprise après plantage) réutilise les
# nœuds déjà récupérés → quasi instantané. Les échecs ne sont PAS cachés : ils
# seront réessayés au prochain run (récupère les communes sautées). --no-cache désactive.
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
USE_CACHE = True

# Période retenue (cadastre napoléonien). Surchargée par les arguments CLI.
YEAR_MIN, YEAR_MAX = 1790, 1860

session = requests.Session()
session.headers.update(HEADERS)

# Défi anti-bot FranceArchives : <script>window.location.href='/redirect_…'</script>
REDIRECT_RE = re.compile(r"window\.location\.href='(/redirect_[^']+)'")

# Caches pour éviter les requêtes répétées
_rdf_cache, _insee_cache, _licence_cache, _service_cache = {}, {}, {}, {}


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
    # 1. Cache disque (lecture) : 0 réseau, 0 sleep
    cache_path = os.path.join(CACHE_DIR, f"{etype}_{eid}.xml")
    if USE_CACHE and os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            content = fh.read()
        if b"rdf:RDF" in content[:4000]:
            g = Graph()
            g.parse(data=content, format="xml")
            _rdf_cache[key] = g
            return g
    # 2. Réseau (plusieurs motifs d'URL d'export)
    candidates = [
        f"{BASE}/{etype}/{eid}.rdf",
        f"{BASE}/{etype}/{eid}/rdf.xml",
        f"{BASE}/{etype}/{eid}/rdf",
        f"{BASE}/{etype}/{eid}",          # content-negotiation via Accept
    ]
    for attempt in range(5):                 # retries (transitoire : cookie/débit)
        for url in candidates:
            try:
                r = get(url, accept="application/rdf+xml")
            except requests.RequestException:
                continue
            if r.status_code == 200 and "rdf:RDF" in r.text[:4000]:
                g = Graph()
                g.parse(data=r.content, format="xml")
                _rdf_cache[key] = g
                if USE_CACHE:                 # n'écrit QUE les succès
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(cache_path, "wb") as fh:
                        fh.write(r.content)
                time.sleep(SLEEP)
                return g
        time.sleep(3 * (attempt + 1))         # backoff croissant (3,6,9,12s)
    # Échec persistant : on n'interrompt pas la descente, on saute le nœud.
    sys.stderr.write(f"  ⚠ pas de RDF pour {etype}/{eid} — nœud ignoré\n")
    _rdf_cache[key] = None
    return None


def eid_of(uri: str) -> str:
    return uri.rstrip("/").split("/")[-1]


# Titres de branches à exclure d'office (hors cadastre napoléonien) :
# cadastre rénové, plans d'intendance, plans par masse de culture.
EXCLUDE_RE = re.compile(r"rénov|renov|intendance|masse de culture", re.IGNORECASE)


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
def walk(etype: str, eid: str, leaves: list, seen: set, parent_title: str = None,
         commune: str = None, commune_loc: str = None, depth: int = 0):
    if eid in seen:
        return
    seen.add(eid)
    g = fetch_graph(etype, eid)
    if g is None:                 # nœud injoignable : on saute (déjà loggé)
        return
    subj = URIRef(f"{BASE}/{etype}/{eid}")

    title = first_str(g, subj, RICO.title) or ""
    begin = year_of(g, subj, RICO.beginningDate)
    end = year_of(g, subj, RICO.endDate)
    children = list(g.objects(subj, RICO.includesOrIncluded))
    manifest = leaf_manifest(g, subj)

    # ---- Niveau 1 = la commune : on retient son titre ET son lieu indexé ----
    # Le parent IMMÉDIAT d'une feuille n'est pas toujours la commune : dans
    # l'Ain l'arbre est commune → « Plans Napoléoniens » → feuilles, et se fier
    # au parent immédiat fait passer « Plans Napoléoniens » pour un nom de
    # commune. On propage donc la branche communale jusqu'aux feuilles.
    if depth == 1:
        commune = title or commune
        commune_loc = commune_location(g, subj) or commune_loc

    # ---- Feuille (notice avec manifeste IIIF) ----
    if manifest and not children:
        if begin is not None and not (YEAR_MIN <= begin <= YEAR_MAX):
            sys.stderr.write(f"  (hors période {begin}) {parent_title or ''} — {title}\n")
            return
        # begin None ([s.d.]) : on garde, car la BRANCHE a déjà été validée napoléonienne
        leaves.append(extract_leaf(g, subj, manifest, commune_hint=parent_title,
                                   commune_branche=commune, commune_loc=commune_loc))
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
        walk("facomponent", eid_of(str(child)), leaves, seen, parent_title=title,
             commune=commune, commune_loc=commune_loc, depth=depth + 1)


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


def extract_leaf(g: Graph, subj: URIRef, manifest: str, commune_hint: str = None,
                 commune_branche: str = None, commune_loc: str = None) -> dict:
    def first(pred):
        for o in g.objects(subj, pred):
            return str(o)
        return None

    title = first(RICO.title) or first(RDFS.label) or ""
    year = first(RICO.beginningDate)
    cote = first(RICO.identifier)
    service = first(RICO.hasOrHadManager) or first(RICO.hasOrHadHolder)
    dept = dept_of_service(service)   # restreint la résolution INSEE au département

    # Résolution de la commune, du plus fiable au plus indirect :
    #   1. titre de la feuille ("Aulnay-sous-Bois, 1782.") ou du parent ("Sevran")
    #   2. titre de la branche communale (niveau 1 de l'instrument de recherche)
    #   3. coordonnées du lieu indexé sur cette branche → commune ACTUELLE
    #      (rattrape les communes fusionnées : Amareins → Francheleins)
    commune_name = commune_from_titles(title, commune_hint)
    insee = insee_of(commune_name, dept) if commune_name else None
    if not insee and commune_branche:
        insee = insee_of(commune_branche, dept)
        if insee:
            commune_name = commune_branche
    if not insee and commune_loc:
        insee, nom_actuel = insee_of_location(commune_loc)
        if insee:
            commune_name = commune_branche or nom_actuel

    # image (dao) : source d'une instantiation, hors vignette.
    # Motifs rencontrés : daoloc (SSD), daogrp (Val-d'Oise) → on accepte les deux.
    image = None
    for inst in g.objects(subj, RICO.hasInstantiation):
        for src in g.objects(inst, DCTERMS.source):
            u = str(src)
            if ("daoloc" in u or "daogrp" in u) and "vignette" not in u:
                image = re.sub(r"//+", "/", u).replace("https:/", "https://")

    licence, overlay_ok = resolve_licence(service, manifest)
    source_name, source_url = resolve_service(service)

    return {
        "title": title,
        "type": classify(title),
        "annee": int(year) if year and year.isdigit() else None,
        "cote": cote,
        "commune": commune_name,
        "insee": insee,          # résolu ci-dessus (titre → branche → lieu)
        "facomponent": str(subj).replace(f"{BASE}/", f"{BASE}/fr/"),
        "iiif_manifest": manifest,
        "image_url": image,
        "source": source_name,
        "source_url": source_url,
        "licence": licence,
        "licence_overlay_ok": overlay_ok,
    }


def resolve_service(uri: str):
    """service/NNNN → (libellé lisible, URL de la fiche service)."""
    if not uri:
        return (None, None)
    if uri in _service_cache:
        return _service_cache[uri]
    name = None
    g = fetch_graph("service", eid_of(uri))
    if g is not None:
        s = URIRef(uri)
        name = first_str(g, s, RICO.name) or first_str(g, s, RDFS.label)
    res = (name, uri.replace(f"{BASE}/", f"{BASE}/fr/"))
    _service_cache[uri] = res
    return res


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
    # Règle métier : "tableau" → tableau d'assemblage ; "section" → section.
    t = title.lower()
    if "tableau" in t:
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
    g = fetch_graph("location", loc_id)
    label = None
    if g is not None:
        for _, _, o in g.triples((None, RDFS.label, None)):
            label = str(o)
            break
    _insee_cache[loc_id] = label
    return label


# Lieux qui ne sont PAS des communes : « Ain (France ; département) », régions,
# cantons… Les retenir comme nom de commune est ce qui avait envoyé 5 905
# notices de l'Ain sur Ainhoa (64014) : geo.api résout « Ain » en flou.
LOC_NON_COMMUNE = re.compile(
    r";\s*(d[ée]partement|r[ée]gion|pays|canton|arrondissement|province)\s*\)", re.I)


def commune_location(g: Graph, subj: URIRef):
    """Identifiant du lieu COMMUNAL indexé sur une branche, sinon None."""
    for s in g.objects(subj, RICO.hasOrHadSubject):
        if "/location/" not in str(s):
            continue
        loc_id = eid_of(str(s))
        label = resolve_location(loc_id)
        if label and not LOC_NON_COMMUNE.search(label):
            return loc_id
    return None


def insee_of_location(loc_id: str):
    """Lieu FranceArchives → (INSEE de la commune ACTUELLE, son nom).

    Passe par les coordonnées, pas par le nom : c'est ce qui rattrape les
    communes disparues, dont le libellé n'existe plus dans geo.api
    (Amareins 46.08097/4.78352 → 01165 Francheleins).
    """
    key = ("loc", loc_id)
    if key in _insee_cache:
        return _insee_cache[key]
    res = (None, None)
    g = fetch_graph("location", loc_id)
    if g is not None:
        s = URIRef(f"{BASE}/location/{loc_id}")
        lat, lon = first_str(g, s, GEO1.lat), first_str(g, s, GEO1.long)
        if lat and lon:
            try:
                r = session.get(GEO_API, timeout=15,
                                params={"lat": lat, "lon": lon, "fields": "code,nom"})
                d = r.json()
                if d:
                    res = (d[0]["code"], d[0]["nom"])
            except Exception:
                pass
            time.sleep(0.2)
    _insee_cache[key] = res
    return res


# Communes que ni geo.api (libellé) ni les coordonnées FranceArchives ne
# résolvent : communes disparues avant l'indexation FA, variantes d'orthographe
# des AD (« Saint-Martin-du-Fresne » pour Saint-Martin-du-Frêne). Table par
# département, tenue dans communes_alias.json (source : COG INSEE).
def cle_commune(nom: str) -> str:
    """Clé de comparaison d'un libellé de commune : casse, accents et
    séparateurs neutralisés. Les inventaires d'archives écrivent « Etrez » là où
    le COG écrit « Étrez ». On ne va PAS plus loin (pas d'approximation) : c'est
    la recherche floue qui avait envoyé l'Ain sur Ainhoa."""
    s = "".join(c for c in unicodedata.normalize("NFD", (nom or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s\-']+", " ", s).strip()


def load_alias():
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "communes_alias.json")
    try:
        with open(chemin, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        sys.stderr.write(f"⚠ communes_alias.json illisible ({e}) — alias ignorés\n")
        return {}
    table, ambigus = {}, set()
    for d, entrees in data.items():
        if d.startswith("_"):
            continue
        for nom, code in entrees.items():
            k = (d, cle_commune(nom))
            if k in table and table[k] != code:
                ambigus.add(k)          # deux communes que la clé confond
            table[k] = code
    for k in ambigus:                   # on préfère ne rien répondre qu'au hasard
        table.pop(k, None)
        sys.stderr.write(f"⚠ alias ambigu ignoré : {k[0]} / {k[1]}\n")
    return table


COMMUNE_ALIAS = load_alias()


# Département par service (institution) : restreint la résolution INSEE au bon
# département. SANS filtre, geo.api renvoie l'homonyme le plus peuplé — ex.
# « Chatenois » (Vosges 88) → Châtenois (Bas-Rhin 67). eid service -> dept.
# À enrichir en parallèle de SERVICE_LICENCE quand un département est validé.
SERVICE_DEPT = {
    "34471": "95",   # Val-d'Oise
    "33495": "14",   # Calvados
    "34393": "93",   # Seine-Saint-Denis
    "34309": "88",   # Vosges
    "33359": "01",   # Ain
}


def dept_of_service(service: str):
    """service/NNNN → code département (2 chiffres) ou None si inconnu."""
    return SERVICE_DEPT.get(eid_of(service)) if service else None


# Libellés qui ne peuvent pas être un nom de commune : titres de rubrique de
# l'instrument de recherche. Les interroger coûte un aller-retour geo.api par
# titre distinct — sur l'Ain, quelques milliers de « Section B dite "du Tiret" ».
# « Plan » n'est filtré que suivi d'une espace, pour épargner Plan-d'Orgon,
# Le Plan-de-la-Tour…
PAS_UNE_COMMUNE = re.compile(
    r"^(sections?|feuilles?|tableaux?|matrices?|registres?|listes?|folios?|cases\s|"
    r"renvois|proc[èe]s|limites|[ée]tats?|atlas|cadastres?|plans?\s)", re.I)


def insee_of(commune_name: str, dept: str = None):
    # normalise : « Aubervilliers (Seine-Saint-Denis, France) » → « Aubervilliers »,
    # « SEVRAN [commune] » → « SEVRAN », « Bobigny, Bondy, … » → « Bobigny »
    name = re.sub(r"\(.*?\)", "", commune_name or "")   # parenthèses (dept, pays)
    name = re.sub(r"\[.*?\]", "", name)                  # crochets ([commune], [date])
    name = name.split(",")[0]                            # 1re commune si liste
    name = name.strip(" . ")
    if not name:
        return None
    if (dept, cle_commune(name)) in COMMUNE_ALIAS:
        return COMMUNE_ALIAS[(dept, cle_commune(name))]
    if PAS_UNE_COMMUNE.match(name):        # titre de rubrique : pas de requête
        return None
    # Clé de cache par (nom, dept) : deux « Chatenois » de départements
    # différents ne doivent pas se télescoper dans le cache.
    key = (name, dept)
    if key in _insee_cache:
        return _insee_cache[key]
    try:
        params = {"nom": name, "fields": "code", "boost": "population", "limit": 1}
        if dept:
            params["codeDepartement"] = dept   # ← recherche restreinte au département
        r = session.get(GEO_API, params=params, timeout=15)
        data = r.json()
        code = data[0]["code"] if data else None
    except Exception:
        code = None
    _insee_cache[key] = code
    time.sleep(0.2)
    return code


# Licence par service (institution) — table manuelle qui FAIT FOI quand le
# manifeste ne porte pas de licence machine-lisible (cf. to_do/licences_par_service.md).
# id service -> (libellé, overlay_ok). À enrichir au fil des départements validés.
SERVICE_LICENCE = {
    "34471": ("Réutilisation OK (CGU AD95)", True),   # Val-d'Oise
    "33495": ("Réutilisation OK (CGU AD14)", True),   # Calvados
    "34393": ("Licence Ouverte", True),               # Seine-Saint-Denis
    "34309": ("Licence Ouverte", True),               # Vosges (déclarée dans le manifeste)
    "33359": ("Réutilisation OK (CGU AD01)", True),   # Ain (manifeste sans champ license, overlay confirmé)
}


def resolve_licence(service: str, manifest: str):
    """Licence par institution. La table manuelle SERVICE_LICENCE fait foi
    (manifestes souvent sans champ `license`) ; sinon, détection dans le manifeste."""
    if service in _licence_cache:
        return _licence_cache[service]
    sid = eid_of(service) if service else None
    if sid in SERVICE_LICENCE:                 # surcharge manuelle (prioritaire)
        _licence_cache[service] = SERVICE_LICENCE[sid]
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


def controle_dept(leaves, attendu: str):
    """Garde-fou : refuse d'écrire si les INSEE ne tombent pas dans le département.

    C'est le contrôle qui manquait quand seed_ain.sql a été produit : 5 905 des
    6 229 notices portaient un INSEE du 64 (geo.api résolvant « Ain », le lieu
    DÉPARTEMENTAL indexé par FranceArchives, en « Ainhoa »). Personne ne l'a vu
    avant le chargement en base.
    """
    codes = [l["insee"] for l in leaves if l["insee"]]
    if not codes:
        raise SystemExit("✖ aucune notice résolue — rien à écrire.")
    par_dept = collections.Counter(c[:2] for c in codes)
    hors = len(codes) - par_dept.get(attendu, 0)
    part = hors / len(codes)
    sys.stderr.write(f"\nContrôle département (attendu {attendu}) : "
                     f"{dict(par_dept.most_common())}\n")
    if part > 0.05:
        raise SystemExit(
            f"✖ {hors}/{len(codes)} notices ({part:.0%}) hors du département "
            f"{attendu} — écriture refusée. Vérifie la résolution des communes."
        )
    if hors:
        sys.stderr.write(f"  ⚠ {hors} notice(s) hors {attendu}, conservée(s) — "
                         f"à vérifier une par une.\n")


def emit_sql(leaves, out=None):
    out = out or sys.stdout          # liaison tardive (sûr sous redirect_stdout)
    cols = ("insee", "type", "annee", "cote", "archive_url", "iiif_manifest",
            "image_url", "source", "source_url", "licence", "licence_overlay_ok", "statut")
    print("-- Généré par harvest_francearchives.py", file=out)
    print(f"-- {len([l for l in leaves if l['insee']])} notices avec INSEE / {len(leaves)} feuilles\n", file=out)
    for l in leaves:
        if not l["insee"]:
            sys.stderr.write(f"  ⚠ INSEE introuvable pour : {l['commune']} ({l['title']})\n")
            continue
        statut = "georef" if l["licence_overlay_ok"] else "lien"
        vals = [
            l["insee"], l["type"], l["annee"], l["cote"], l["facomponent"],
            l["iiif_manifest"], l["image_url"], l["source"], l["source_url"],
            l["licence"], l["licence_overlay_ok"], statut,
        ]
        print(f"insert into document ({', '.join(cols)}) values "
              f"({', '.join(sql_escape(v) for v in vals)});", file=out)


def main():
    global YEAR_MIN, YEAR_MAX, USE_CACHE
    ap = argparse.ArgumentParser(description="Harvester FranceArchives → SQL Supabase")
    ap.add_argument("eid", help="identifiant de l'instrument de recherche (ou facomponent)")
    ap.add_argument("etype", nargs="?", default="findingaid",
                    choices=["findingaid", "facomponent"])
    ap.add_argument("--year-min", type=int, default=YEAR_MIN)
    ap.add_argument("--year-max", type=int, default=YEAR_MAX)
    ap.add_argument("--out", help="fichier SQL de sortie (UTF-8). Défaut : stdout.")
    ap.add_argument("--no-cache", action="store_true",
                    help="ignore le cache disque .cache/ (re-télécharge tout)")
    ap.add_argument("--expect-dept", metavar="NN",
                    help="code département attendu : refuse d'écrire si plus de "
                         "5 %% des INSEE tombent ailleurs (garde-fou homonymes)")
    args = ap.parse_args()
    YEAR_MIN, YEAR_MAX = args.year_min, args.year_max
    if args.no_cache:
        USE_CACHE = False

    leaves, seen = [], set()
    sys.stderr.write(f"Descente de {args.etype}/{args.eid} "
                     f"(période {YEAR_MIN}-{YEAR_MAX}) …\n")
    walk(args.etype, args.eid, leaves, seen)
    sys.stderr.write(f"\n{len(leaves)} feuilles collectées.\n")

    if args.expect_dept:
        controle_dept(leaves, args.expect_dept)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            emit_sql(leaves, out=fh)
        sys.stderr.write(f"→ SQL écrit dans {args.out}\n")
    else:
        emit_sql(leaves)


if __name__ == "__main__":
    main()
