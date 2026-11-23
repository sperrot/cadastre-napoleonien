#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Connecteur PORTAIL DRÔME (archives.ladrome.fr, Mnesys) → harvest/seed_drome.sql

Objectif : le cadastre napoléonien de la RIVIÈRE DRÔME. Par défaut, seules les
38 communes riveraines (harvest/corridor_drome.json, produit par
corridor_riviere.py) sont descendues. `--tout` lève ce filtre.

⚠️  CGU des AD26 (archives.ladrome.fr/page/conditions-generales-d-utilisation) :
    « Aucune extraction intégrale ou substantielle […] du Site et de son
    contenu ne pourra en être faite sans l'accord préalable et écrit de
    l'éditeur. » → `--tout` n'est à lancer qu'avec cet accord (cf.
    to_do/drome/NOTES.md, modèle de demande). Le mode corridor (≈ 10 % des
    communes) reste une collecte ciblée, au rythme d'un humain (1 req/s).

Même logiciel (Mnesys, Naoned) que le Jura → même API du plan de classement :

    GET /api/classificationPlan/v1/children/{nodeUuid}_{rootUuid}
        → [{id, title, dataType: "branch"|"leaf",
            data:{children, isLoaded, url (ark), contentUrl}}]

Fonds relevé dans un HAR (2026-11-23) : « Plans du cadastre napoléonien. »
(an XI-1974), uuid f9796c5b…, ark:/24626/69437fsmbktg. C'est aussi la racine
des identifiants de l'API ({nœud}_{f9796c5b…}). Arbre :

    Plans du cadastre napoléonien.                  ← ROOT = START
      Allex                                          ← commune (forme ancienne :
        Cadastre parcellaire.                           Livron, Loriol, Aouste…)
          « Tableau d'assemblage. »                  (leaf)
          « Section A, Bayles (les). »               (leaf)
      Cheylard (le)                                  ← parfois une feuille directe

Planche (fragment /record/24626/<ark>/content, notice-0) : cote « 3 P 3256/1 »,
date « 10 septembre 1811 », échelle « 1:20 000 » ; média
/ark:/24626/<ark>/<uuid> (visionneuse), vignette /images/<uuid>_img-notice.jpg,
image pleine supposée en /images/<uuid>.jpg (comme au Jura) → `--check`.
Référence : Allex, TA — ark pd4386zn9s7j, média df229011-dc18-4b0f-bb17-0b894fe42ab0.

Licence : les AD26 autorisent la réutilisation NON commerciale avec mention
« Arch. dép. Drôme, <cote> » ; commerciale = licence avec redevance. Ce n'est
pas une Licence Ouverte → par défaut `licence_overlay_ok = false`,
`statut = 'lien'`, pas de manifeste (le worker ne rediffuse rien).
`--licence-ouverte` bascule en overlay UNIQUEMENT après accord écrit (comme
l'AD39), et il faut alors ajouter archives.ladrome.fr au worker.

TLS : le serveur n'envoie pas son certificat intermédiaire (Gandi RSA DV
Secure Server CA 4) — les navigateurs le récupèrent seuls, pas `requests`.
Il est fourni dans harvest/certs/ et ajouté au magasin certifi : la
vérification TLS reste COMPLÈTE (jamais verify=False).

Dépendances : pip install requests certifi
Usage :
    python harvest/harvest_drome.py --check                # 1. auto-test (Allex, TA)
    python harvest/harvest_drome.py --limit 20             # 2. essai
    python harvest/harvest_drome.py                        # 3. corridor → seed_drome.sql
    python harvest/load_seed_to_supabase.py --replace-dept 26 harvest/seed_drome.sql

Si le portail renvoie un captcha au lieu du JSON : copier le cookie PHPSESSID
d'un navigateur ayant ouvert archives.ladrome.fr, relancer avec
--phpsessid <valeur>. Tout est mis en cache (harvest/.cache/drome_*).
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

BASE = "https://archives.ladrome.fr"
HOST = "archives.ladrome.fr"
NAAN = "24626"
GEO_API = "https://geo.api.gouv.fr/communes"
DEPT = "26"
WORKER = "https://iiif-allmaps.sperrot.workers.dev"

# « Plans du cadastre napoléonien. » (HAR du 2026-11-23) : fonds ET racine des ids
ROOT = "f9796c5b-2f92-448b-bae9-3227f36ca1b1"
START = ROOT

REF_ARK = "pd4386zn9s7j"                          # Allex, tableau d'assemblage
REF_MEDIA = "df229011-dc18-4b0f-bb17-0b894fe42ab0"
REF_COTE, REF_ANNEE = "3 P 3256/1", 1811

SOURCE = "Archives départementales de la Drôme"
LICENCE_AD26 = ("Réutilisation non commerciale, mention « Arch. dép. Drôme, cote » "
                "(commerciale : licence avec redevance) — overlay soumis à accord écrit")
LICENCE_OUVERTE = "Licence Ouverte Etalab (accord écrit AD26)"

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
OUT_DEFAULT = os.path.join(HERE, "seed_drome.sql")
CORRIDOR = os.path.join(HERE, "corridor_drome.json")
GANDI_CA = os.path.join(HERE, "certs", "gandi_rsa_dv_ca4.pem")

# Branches à ne pas descendre (on ne veut que les plans napoléoniens)
# (pas de filtre d'années ici : un nœud « Plans 1808-2002 » contient aussi le
# napoléonien ; la période est filtrée planche par planche, cf. ANNEE_MAX)
SKIP_BRANCH_RE = re.compile(r"matrice|[ée]tats?\s+de\s+section|r[ée]nov|remani|"
                            r"mise\s+[àa]\s+jour", re.I)
ANNEE_MAX = 1870      # au-delà : plan rénové / mis à jour, hors cadastre napoléonien

# Rattachements non confirmés (ajoutés au rapport « à confirmer »). Les formes
# anciennes vues dans l'arbre (Livron, Loriol, Aouste, Lesches, Montlaur,
# Montmaur, Recoubeau, Jansac, Piégros, Molières, Ponet-Saint-Auban,
# Bâtie-des-Fonts) sont dans communes_alias.json["26"].
CANDIDATS_HISTORIQUES = {}

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SLEEP = 1.0           # 1 requête/s : rythme de consultation, pas d'aspiration
TIMEOUT = 60

try:                       # console Windows en cp1252
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# --------------------------------------------------------------------------
# HTTP : magasin certifi + intermédiaire Gandi, cookie CGU, cache disque
# --------------------------------------------------------------------------
def ca_bundle():
    """certifi + intermédiaire Gandi → harvest/.cache/ca_drome.pem."""
    import certifi
    path = os.path.join(CACHE_DIR, "ca_drome.pem")
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as out:
        for src in (certifi.where(), GANDI_CA):
            with open(src, encoding="utf-8") as fh:
                out.write(fh.read().rstrip() + "\n")
    return path


session = requests.Session()
session.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                   "Gecko/20100101 Firefox/128.0"),
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
})


class Captcha(Exception):
    pass


def prime(phpsessid=None):
    """Pose license=true (bandeau CGU des médias) + PHPSESSID (fourni ou obtenu)."""
    session.verify = ca_bundle()
    session.cookies.set("license", "true", domain=HOST)
    if phpsessid:
        session.cookies.set("PHPSESSID", phpsessid, domain=HOST)
    else:
        session.get(f"{BASE}/ark:/{NAAN}/{REF_ARK}", timeout=30)


def cached_get(key, url, want_json=True):
    """GET avec cache disque (succès seulement) et 4 essais."""
    path = os.path.join(CACHE_DIR, f"drome_{key}.{'json' if want_json else 'txt'}")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) if want_json else fh.read()
    for attempt in range(4):
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.exceptions.SSLError:
            raise
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
    return children(uuid_of(node))


def uuid_of(node):
    return (node.get("id") or "").split("_")[0]


# --------------------------------------------------------------------------
# Communes : noms normalisés → INSEE (exact uniquement)
# --------------------------------------------------------------------------
def cle(nom):
    s = "".join(c for c in unicodedata.normalize("NFD", (nom or "").lower())
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"\bst(e?)\b\.?", r"saint\1", s)
    return re.sub(r"[\s\-'’\".]+", " ", s).strip()


def normalize(commune):
    """« Prés (les) » → « Les Prés » ; « Clastre (la) » → « La Clastre » ;
    « Crest [plans] » → « Crest »."""
    name = re.sub(r"\[.*?\]", "", commune or "").replace("’", "'").strip()
    m = re.match(r"^(.*?),?\s*\((le|la|les|l['\"]?)\)\s*$", name, re.I)
    if m:
        art = m.group(2).rstrip("'\"").capitalize()
        name = f"{art}'{m.group(1).strip()}" if art == "L" else f"{art} {m.group(1).strip()}"
    name = re.sub(r"\(.*?\)", "", name)
    name = re.split(r"\s*[:,–—]\s*|\s+-\s+", name)[0]       # « Crest - plans » → « Crest »
    return name.strip(" .,")


def load_alias():
    try:
        with open(os.path.join(HERE, "communes_alias.json"), encoding="utf-8") as fh:
            return {cle(k): v for k, v in json.load(fh).get(DEPT, {}).items()}
    except Exception:
        return {}


def load_corridor():
    with open(CORRIDOR, encoding="utf-8") as fh:
        meta = json.load(fh)
    insee = {c["insee"] for c in meta["communes"]}
    noms = {cle(c["nom"]): c["insee"] for c in meta["communes"]}
    for c in meta["communes"]:
        for a in c.get("anciennes_communes", []):
            noms[cle(a["nom"])] = c["insee"]
    return meta, insee, noms


def communes_du_departement():
    """Communes actuelles du 26 (geo.api, 1 requête) → {clé nom: INSEE}."""
    data = cached_get("communes_26", f"{GEO_API}?codeDepartement={DEPT}&fields=nom,code")
    return {cle(c["nom"]): c["code"] for c in (data or [])}


class Resolveur:
    def __init__(self, corridor_noms):
        self.alias = load_alias()
        self.dept = communes_du_departement()
        self.corridor = corridor_noms
        self.historiques = {cle(k): v for k, v in CANDIDATS_HISTORIQUES.items()}
        self.a_confirmer = set()

    def insee(self, titre):
        """→ (INSEE | None, source) ; source ∈ alias, actuelle, corridor, historique."""
        k = cle(normalize(titre))
        if not k:
            return None, None
        if k in self.alias:
            return self.alias[k], "alias"
        if k in self.dept:
            return self.dept[k], "actuelle"
        if k in self.corridor:
            return self.corridor[k], "corridor"
        if k in self.historiques:
            self.a_confirmer.add(f"{titre} → {self.historiques[k]}")
            return self.historiques[k], "historique"
        return None, None


# --------------------------------------------------------------------------
# Descente de l'arbre, filtrée sur le corridor
# --------------------------------------------------------------------------
class Descente:
    def __init__(self, resolveur, corridor_insee, tout, limit):
        self.r = resolveur
        self.corridor = corridor_insee
        self.tout = tout
        self.limit = limit
        self.leaves, self.seen = [], set()
        self.sautees, self.inconnues = set(), set()
        self.vues = {}

    def plein(self):
        return bool(self.limit) and len(self.leaves) >= self.limit

    def walk_children(self, kids, commune, depth):
        # Une branche au nom inconnu, sœur de communes reconnues, est une
        # commune (ancienne ou mal orthographiée) : on ne la prend PAS pour
        # un regroupement à descendre (sinon le filtre corridor fuirait).
        branches = [k for k in kids if k.get("dataType") == "branch"]
        niveau_communes = commune is None and any(
            self.r.insee(k.get("title"))[0] for k in branches)
        for k in kids:
            if self.plein():
                return
            self.walk(k, commune, depth + 1, niveau_communes)

    def walk(self, node, commune, depth=0, niveau_communes=False):
        nid = node.get("id")
        if not nid or nid in self.seen or depth > 12:
            return
        self.seen.add(nid)
        title = (node.get("title") or "").strip()
        if node.get("dataType") == "branch":
            if SKIP_BRANCH_RE.search(title):
                return
            if commune is None:
                code, src = self.r.insee(title)
                if code:
                    if not self.tout and code not in self.corridor:
                        self.sautees.add(title)
                        return
                    commune = {"titre": title, "insee": code, "src": src}
                    self.vues.setdefault(code, set()).add(title)
                    sys.stderr.write(f"  {title} → {code} ({src})\n")
                elif niveau_communes:
                    self.inconnues.add(title)
                    if not self.tout:
                        return
                    commune = {"titre": title, "insee": None, "src": None}
            self.walk_children(kids_of(node), commune, depth)
        else:
            d = node.get("data") or {}
            ark = ark_of(d.get("url"))
            if not ark:
                return
            if commune is None:
                # planche hors nœud commune : la commune ouvre le titre
                code, src = self.r.insee(title.split(",")[0])
                if not code or (not self.tout and code not in self.corridor):
                    return
                commune = {"titre": title.split(",")[0], "insee": code, "src": src}
            self.leaves.append({"commune": commune, "title": title, "ark": ark,
                                "node_id": nid, "url": d.get("url"),
                                "content": d.get("contentUrl")})


def ark_of(url):
    m = re.search(rf"ark:/{NAAN}/([0-9a-z]+)", url or "")
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Planche : uuid média, cote, année (fragment /record/<NAAN>/<ark>/content)
# --------------------------------------------------------------------------
def content_of(leaf):
    return cached_get(f"content_{leaf['ark']}",
                      leaf.get("content") or f"{BASE}/record/{NAAN}/{leaf['ark']}/content",
                      want_json=False) or ""


def notice_field(frag, *labels):
    for label in labels:
        m = re.search(r'class="attribut">\s*' + re.escape(label) +
                      r'\s*</p>.*?class="read-more"[^>]*>(.*?)</div>', frag, re.S)
        txt = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split()) if m else ""
        if txt:
            return txt
    return None


def meta_of(leaf):
    """→ (cote, année napoléonienne | None, première année lue | None) :
    champs de la DERNIÈRE notice (notice-0)."""
    txt = content_of(leaf)
    i = txt.rfind("notice-info notice-0")
    frag = txt[i:] if i >= 0 else txt
    cote = notice_field(frag, "Cote/Cotes extrêmes", "Cote", "Cotes extrêmes")
    date = notice_field(frag, "Date", "Dates", "Dates extrêmes") or ""
    m = re.search(r"\b(1[789]\d\d|20\d\d)\b", date)
    brute = int(m.group(1)) if m else None
    annee = brute if brute and 1790 <= brute <= ANNEE_MAX else None
    return cote, annee, brute


def media_of(leaf):
    """→ (jpg_url | None, manifeste_natif | None, nb_uuid)."""
    ark = leaf["ark"]
    flat = content_of(leaf).replace("\\/", "/")
    if not flat:
        return None, None, 0
    uuids = re.findall(rf"ark:/{NAAN}/{ark}/({UUID_RE.pattern})", flat, re.I)
    if not uuids:
        leaf_uuid = (leaf.get("node_id") or "").split("_")[0].lower()
        uuids = [u for u in UUID_RE.findall(flat) if u.lower() not in (ROOT, leaf_uuid)]
    uuids = list(dict.fromkeys(u.lower() for u in uuids))
    m = re.search(r"https?://[^\"'\s<>]+/manifest(?:\.json)?\b", flat)
    manifest = m.group(0) if m else None
    jpg = f"{BASE}/images/{uuids[0]}.jpg" if uuids else None
    return jpg, manifest, len(uuids)


def classify(title):
    t = title.lower()
    if "assemblage" in t:
        return "tableau_assemblage"
    if re.search(r"\bfeuille\b", t):
        return "feuille"
    return "section"


def annee_of(title, brute=False):
    m = re.search(r"\b(1[789]\d\d|20\d\d)\b", title or "")
    y = int(m.group(1)) if m else None
    return y if brute or (y and 1790 <= y <= ANNEE_MAX) else None


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


COLS = ("insee", "type", "annee", "cote", "archive_url", "image_url", "iiif_manifest",
        "source", "source_url", "licence", "licence_overlay_ok", "statut")


def emit(leaves, out_path, licence_ouverte, meta_corridor, desc):
    rows, sans_insee, sans_image, multi, hors_periode = [], [], 0, 0, 0
    for i, l in enumerate(leaves, 1):
        code = l["commune"]["insee"]
        if not code:
            sans_insee.append(l)
            continue
        if (annee_of(l["title"], brute=True) or 0) > ANNEE_MAX:
            hors_periode += 1                       # sans requête : le titre suffit
            continue
        cote, annee, brute = meta_of(l)
        if (brute or 0) > ANNEE_MAX:
            hors_periode += 1
            continue
        jpg, manifest, n = media_of(l)
        multi += n > 1
        sans_image += not jpg and not manifest
        if licence_ouverte:
            iiif = manifest or (f"{WORKER}/static-manifest?u={urllib.parse.quote(jpg, safe='')}"
                                if jpg else None)
            licence, ok, statut = LICENCE_OUVERTE, True, "georef" if iiif else "lien"
        else:
            iiif, licence, ok, statut = None, LICENCE_AD26, False, "lien"
        rows.append((code, classify(l["title"]), annee or annee_of(l["title"]), cote,
                     l["url"], jpg, iiif, SOURCE, BASE, licence, ok, statut))
        if i % 50 == 0:
            sys.stderr.write(f"  … {i}/{len(leaves)} planches\n")

    hors = sum(1 for r in rows if not r[0].startswith(DEPT))
    if rows and hors / len(rows) > 0.05:
        raise SystemExit(f"✖ {hors}/{len(rows)} INSEE hors du {DEPT} — seed NON écrit")

    communes = {r[0] for r in rows}
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"-- Drôme (26) — portail Mnesys archives.ladrome.fr — {desc.portee}\n")
        fh.write(f"-- {len(rows)} planches, {len(communes)} communes · "
                 f"{len(sans_insee)} sans INSEE · {sans_image} sans image · "
                 f"{multi} à plusieurs images (1re retenue)\n")
        fh.write(f"-- licence : {LICENCE_OUVERTE if licence_ouverte else LICENCE_AD26}\n\n")
        for r in rows:
            fh.write(f"insert into document ({', '.join(COLS)}) values "
                     f"({', '.join(q(v) for v in r)});\n")

    types = {}
    for r in rows:
        types[r[1]] = types.get(r[1], 0) + 1
    sys.stderr.write(f"\n→ {out_path}\n  {len(rows)} planches · {len(communes)} communes · {types}\n"
                     f"  année : {sum(1 for r in rows if r[2])}/{len(rows)} · "
                     f"cote : {sum(1 for r in rows if r[3])}/{len(rows)} · "
                     f"sans image : {sans_image} · multi-images : {multi} · "
                     f"hors période (> {ANNEE_MAX}) : {hors_periode}\n")

    if meta_corridor and not desc.tout:
        manquantes = [c for c in meta_corridor["communes"] if c["insee"] not in communes]
        sys.stderr.write(f"\n  Corridor : {len(meta_corridor['communes']) - len(manquantes)}"
                         f"/{len(meta_corridor['communes'])} communes riveraines couvertes\n")
        for c in manquantes:
            sys.stderr.write(f"    ✖ pk {c['pk_km']:5.1f}  {c['insee']}  {c['nom']}\n")
    if desc.inconnues:
        sys.stderr.write("\n  Nœuds-communes au nom inconnu (anciennes communes ? "
                         "→ communes_alias.json[\"26\"]) :\n")
        for t in sorted(desc.inconnues):
            sys.stderr.write(f"    ? {t}\n")
    if desc.r.a_confirmer:
        sys.stderr.write("\n  Rattachements historiques À CONFIRMER (CANDIDATS_HISTORIQUES) :\n")
        for s in sorted(desc.r.a_confirmer):
            sys.stderr.write(f"    ~ {s}\n")
    if sans_insee:
        tsv = os.path.splitext(out_path)[0] + "_sans_insee.tsv"
        with open(tsv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("commune\ttitre\tark\n")
            for l in sans_insee:
                fh.write(f"{l['commune']['titre']}\t{l['title']}\t{l['url']}\n")
        sys.stderr.write(f"  ⚠ {len(sans_insee)} planches sans INSEE → {tsv}\n")


# --------------------------------------------------------------------------
def check(ark=REF_ARK):
    """Calibrage : ce que le connecteur extrait d'UNE planche (défaut : Allex, TA)."""
    leaf = {"ark": ark, "content": f"{BASE}/record/{NAAN}/{ark}/content"}
    jpg, manifest, n = media_of(leaf)
    cote, annee, _ = meta_of(leaf)
    sys.stderr.write(f"contentUrl  : {leaf['content']}\n"
                     f"image       : {jpg}  ({n} uuid candidats)\n"
                     f"manifeste   : {manifest}\n"
                     f"cote/année  : {cote} / {annee}\n")
    est_jpeg = False
    if jpg:
        try:
            r = session.get(jpg, headers={"Range": "bytes=0-3"}, timeout=30)
            est_jpeg = r.content[:3] == b"\xff\xd8\xff"
        except requests.RequestException:
            pass
    sys.stderr.write(f"fichier     : {'JPEG ✔' if est_jpeg else 'PAS un JPEG ✖'}\n")
    attendu = (f"{BASE}/images/{REF_MEDIA}.jpg", REF_COTE, REF_ANNEE)
    if ark != REF_ARK:
        ok = est_jpeg and cote
    else:
        ok = est_jpeg and (jpg, cote, annee) == attendu
    if ok:
        sys.stderr.write("✔ extraction calibrée\n")
        return 0
    p = os.path.join(CACHE_DIR, f"drome_content_{ark}.txt")
    sys.stderr.write(f"✖ à calibrer (attendu {attendu}) : réponse brute dans {p}\n"
                     "  Si seul le JPEG échoue : ouvrir la visionneuse, relever l'URL de\n"
                     "  l'image pleine (onglet Réseau) et adapter media_of().\n")
    return 1


def main():
    ap = argparse.ArgumentParser(description="Portail Drôme (Mnesys) → seed_drome.sql")
    ap.add_argument("--check", nargs="?", const=REF_ARK, metavar="ARK",
                    help="calibrer l'extraction sur une planche (défaut : Allex, TA)")
    ap.add_argument("--start", default=START, help="uuid du nœud de départ")
    ap.add_argument("--tout", action="store_true",
                    help="tout le département (SEULEMENT avec l'accord écrit des AD26)")
    ap.add_argument("--licence-ouverte", action="store_true",
                    help="overlay autorisé (SEULEMENT avec l'accord écrit des AD26)")
    ap.add_argument("--limit", type=int, help="n'émettre que N planches (essai)")
    ap.add_argument("--phpsessid", help="cookie PHPSESSID d'un navigateur (si captcha)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    args = ap.parse_args()

    try:
        prime(args.phpsessid)
        if args.check:
            sys.exit(check(args.check))

        meta, corridor_insee, corridor_noms = load_corridor()
        desc = Descente(Resolveur(corridor_noms), corridor_insee, args.tout, args.limit)
        desc.portee = ("tout le département" if args.tout else
                       f"corridor de {meta['riviere']} ({len(corridor_insee)} communes riveraines)")
        sys.stderr.write(f"Descente depuis {args.start} — {desc.portee} …\n")
        desc.walk_children(children(args.start), None, 0)
        sys.stderr.write(f"\n{len(desc.leaves)} planches collectées · "
                         f"{len(desc.sautees)} communes hors corridor non descendues.\n")
        leaves = desc.leaves[:args.limit] if args.limit else desc.leaves
        emit(leaves, args.out, args.licence_ouverte, meta, desc)
    except Captcha as e:
        sys.exit(f"✖ captcha servi au lieu du JSON ({e}).\n"
                 f"  Ouvrir {BASE} dans un navigateur, copier le cookie PHPSESSID,\n"
                 f"  puis relancer avec --phpsessid <valeur> (le cache garde l'acquis).")
    except requests.exceptions.SSLError as e:
        sys.exit(f"✖ TLS : {e}\n  Vérifier harvest/certs/gandi_rsa_dv_ca4.pem (intermédiaire "
                 f"manquant côté serveur) — ne jamais passer verify=False.")


if __name__ == "__main__":
    main()
