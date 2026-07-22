#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génère harvest/seed_charente.sql — fonds 3 P « Plans du cadastre napoléonien »
des Archives départementales de la Charente (La Source, plateforme Ligeo).

Entrées (produites par la moisson du portail, cf. harvest/README.md § Charente) :
  - notices.tsv : une ligne par notice de l'inventaire
        id_notice <TAB> ark <TAB> "3 P 1/2 - Section A dite de Chardat. Feuille 1. | 1825"
  - tree_3p.txt : l'arbre, pour savoir quelles notices sont des communes
        rang~Nom commune~id_notice~id.type.section.feuille;...

Le portail sert des manifestes IIIF ouverts (Etalab 2.0, CORS *) :
    https://lasource.archives.lacharente.fr/ark:/61904/<ark>/manifest
C'est l'URL passée à Allmaps — vérifiée sur l'éditeur.

Usage : python harvest/seed_charente.py --in <dossier contenant les 2 fichiers>
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'seed_charente.sql')

PORTAIL = 'https://lasource.archives.lacharente.fr'
DEPT = '16'
SOURCE = 'Archives départementales de la Charente (La Source)'
# Le manifeste porte : « Document librement réutilisable, conformément à la
# licence ouverte Etalab 2.0 » → overlay/géoréférencement autorisés.
LICENCE = 'Licence Ouverte (Etalab 2.0)'
GEO_API = 'https://geo.api.gouv.fr/communes'


# ---------------------------------------------------------------- parsing ---

def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def parse_h3(h3):
    """« 3 P 1/2 - Section A dite de Chardat. Feuille 1. | 1825 »
       → (cote, titre, annee).  L'année est optionnelle."""
    annee = None
    m = re.search(r'\|\s*(\d{4})', h3)
    if m:
        annee = int(m.group(1))
        h3 = h3[:m.start()]
    h3 = h3.strip()
    # La racine peut porter une lettre (« 3 P 28A/5 ») : elle doit rester dans
    # la cote, sinon la planche est perdue à l'étape parse_cote.
    m = re.match(r'^(3\s*P\s*\d+[A-Za-z]?(?:/\d+)?)\s*-\s*(.*)$', h3)
    if m:
        return norm(m.group(1)), norm(m.group(2)), annee
    return None, norm(h3), annee


def parse_cote(cote):
    """« 3 P 1/2 » → ('1', 2) ; « 3 P 28A/5 » → ('28A', 5) ; « 3 P 1 » → ('1', None).

    Une quarantaine de communes ont une cote suffixée d'une lettre (communes
    scindées en plusieurs plans : 19A/19B, 73A..73D).
    """
    if not cote:
        return None, None
    m = re.match(r'^3\s*P\s*(\d+[A-Z]?)(?:/(\d+))?$', norm(cote), re.I)
    if not m:
        return None, None
    return m.group(1).upper(), (int(m.group(2)) if m.group(2) else None)


def tri_cote(racine):
    """Clé de tri naturelle : '9' < '28A' < '28B' < '102'."""
    m = re.match(r'^(\d+)([A-Z]?)$', racine)
    return (int(m.group(1)), m.group(2)) if m else (10 ** 9, racine)


def dossier_iiif(racine):
    """Racine de cote → dossier du serveur d'images : '28A' → '3P_028A'.

    Le numéro est zéro-comblé sur 3 chiffres, la lettre conservée telle quelle
    (vérifié : 3P_028A existe, 3P_28A non).
    """
    m = re.match(r'^(\d+)([A-Z]?)$', racine)
    return f'3P_{int(m.group(1)):03d}{m.group(2)}' if m else f'3P_{racine}'


def classify(titre):
    """Titre de notice → (type, section_lettre, feuille_num).

    Le portail préfixe le type de document : « Section A dite de Chardat.
    Feuille 1. ». Quelques dizaines de libellés sortent du moule
    (« Plan général. », « Sections A et B. Feuille 2. ») : on retombe sur
    le type le plus prudent plutôt que d'inventer une section.
    """
    t = norm(titre)
    feuille = None
    m = re.search(r'Feuille\s+(\d+)', t, re.I)
    if m:
        feuille = int(m.group(1))

    lettre = None
    m = re.search(r'(?:^|\s)Section\s+([A-Z]{1,2})(?=[\s.,]|$)', t)
    if m:
        lettre = m.group(1)
    else:
        m = re.match(r'^Sections?\s+([A-Z])(?=[\s.,]|$)', t)
        if m:
            lettre = m.group(1)

    est_ta = bool(re.search(r"tableau|plan\s+g[ée]n[ée]ral", t, re.I))
    if est_ta:
        return 'tableau_assemblage', lettre, None
    if feuille is not None:
        return 'feuille', lettre, feuille
    if lettre:
        return 'section', lettre, None
    return 'feuille', None, None


# ------------------------------------------------------------------ INSEE ---

def load_alias():
    """Réutilise harvest/communes_alias.json (clé = département)."""
    chemin = os.path.join(HERE, 'communes_alias.json')
    try:
        with io.open(chemin, encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as e:
        sys.stderr.write(f'communes_alias.json illisible ({e}) — alias ignorés\n')
        return {}
    return {nom: code for nom, code in (data.get(DEPT) or {}).items()}


ALIAS = load_alias()
_cache = {}


def sans_accents(s):
    """Clé de comparaison : les inventaires écrivent « Eraville » pour Éraville."""
    import unicodedata
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r"[^a-z0-9]+", '', s.lower())


ALIAS_NORM = {sans_accents(k): v for k, v in ALIAS.items()}


def nettoie_nom(nom):
    """« Les Adjots. » → « Les Adjots » ; « Baignes et Sainte-Radegonde. » tel quel.

    Le champ « Lieu » des manifestes donne parfois « ancien / actuel »
    (« Aignes / Aignes-et-Puypéroux ») : on garde la forme actuelle, seule
    connue de geo.api.
    """
    n = norm(nom).rstrip('.').strip()
    n = re.sub(r'\s*\(.*?\)\s*$', '', n)
    if '/' in n:
        n = n.split('/')[-1].strip()
    return n


def insee_of(nom):
    """Nom de commune → code INSEE, restreint au département 16.

    Sans codeDepartement, geo.api renvoie l'homonyme le plus peuplé du pays
    (le piège documenté dans harvest_francearchives.py).
    """
    n = nettoie_nom(nom)
    if not n:
        return None
    if n in ALIAS:
        return ALIAS[n]
    cle = sans_accents(n)
    if cle in ALIAS_NORM:
        return ALIAS_NORM[cle]
    if n in _cache:
        return _cache[n]
    code = None
    try:
        params = urllib.parse.urlencode({
            'nom': n, 'fields': 'code', 'boost': 'population',
            'limit': 1, 'codeDepartement': DEPT})
        req = urllib.request.Request(
            f'{GEO_API}?{params}',
            headers={'User-Agent': 'mapping-cadastre-napoleonien'})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        if data:
            code = data[0]['code']
    except Exception as e:
        sys.stderr.write(f'  geo.api KO pour « {n} » : {e}\n')
    _cache[n] = code
    time.sleep(0.15)
    return code


# -------------------------------------------------------------------- SQL ---

def esc(v):
    if v is None or v == '':
        return 'null'
    return "'" + str(v).replace("'", "''") + "'"


def num(v):
    return str(v) if v is not None else 'null'


COLS = ('insee', 'type', 'section_lettre', 'feuille_num', 'annee', 'cote',
        'archive_url', 'iiif_url', 'iiif_manifest', 'image_url',
        'source', 'source_url', 'licence', 'licence_overlay_ok', 'statut')


# --------------------------------------------------------------- manifeste ---
# Le manifeste de chaque planche est lu une fois, pour deux raisons :
#
# 1. « Lieu » donne le nom de commune actuel (« Aignes / Aignes-et-Puypéroux »)
#    alors que l'inventaire garde celui de 1825 : c'est lui qui fait autorité
#    pour le rattachement INSEE.
# 2. L'URL du service Image API ne se déduit PAS de la cote. Elle la suit dans
#    la majorité des cas (3 P 1/2 → 3P_001/FRAD016_3P_001_02.jpg) mais pas
#    toujours : la cote 22 est stockée sous 3P_202, la 18 sous 3P_108, la 41
#    sous 3P_401. Une dérivation mécanique produisait ~7 % de vignettes 404.
#
# Le résultat est mis en cache sur disque (clé = ark) : les reruns sont gratuits.

def lit_manifestes(arks, cache_path):
    """[ark, ...] → {ark: {'lieu':…, 'image':…, 'w':…, 'h':…}}."""
    import ssl
    from concurrent.futures import ThreadPoolExecutor

    cache = {}
    if os.path.exists(cache_path):
        try:
            with io.open(cache_path, encoding='utf-8') as fh:
                cache = dict(json.load(fh))
        except Exception:
            cache = {}

    # Le portail sert une chaîne de certificats incomplète : le magasin système
    # de Windows la complète, pas celui de Python. Vérification désactivée pour
    # ce seul hôte (contenu public, aucun secret transmis).
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    a_lire = [a for a in arks if a not in cache]
    print(f'  manifestes : {len(cache)} en cache, {len(a_lire)} à lire')

    def service_image(doc):
        """@id du service Image API du canvas (et non celui de la recherche)."""
        trouve = []

        def walk(o):
            if isinstance(o, list):
                for x in o:
                    walk(x)
            elif isinstance(o, dict):
                s = o.get('service')
                cands = s if isinstance(s, list) else ([s] if isinstance(s, dict) else [])
                for c in cands:
                    if isinstance(c, dict):
                        sid = str(c.get('@id') or c.get('id') or '')
                        if '/iiif/SERIE_' in sid:
                            trouve.append(sid)
                for v in o.values():
                    walk(v)
        walk(doc)
        return trouve[0] if trouve else None

    def un(ark):
        url = f'{PORTAIL}/ark:/61904/{ark}/manifest'
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                                        'Chrome/124.0 Safari/537.36'})
        for essai in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
                    d = json.loads(r.read().decode('utf-8', 'replace'))
                lieu = None
                for md in d.get('metadata') or []:
                    if norm(md.get('label')) == 'Lieu':
                        lieu = norm(md.get('value'))
                canvas = (((d.get('sequences') or [{}])[0]).get('canvases') or [{}])[0]
                return ark, {'lieu': lieu, 'image': service_image(d),
                             'w': canvas.get('width'), 'h': canvas.get('height')}
            except Exception:
                time.sleep(1.0 * (essai + 1))
        return ark, None

    if a_lire:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for k, (ark, info) in enumerate(ex.map(un, a_lire), 1):
                cache[ark] = info
                if k % 500 == 0:
                    print(f'    {k}/{len(a_lire)}', flush=True)
                    with io.open(cache_path, 'w', encoding='utf-8') as fh:
                        json.dump(cache, fh, ensure_ascii=False)
        with io.open(cache_path, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, ensure_ascii=False)
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='dossier', required=True,
                    help='dossier contenant notices.tsv et tree_3p.txt')
    args = ap.parse_args()

    f_notices = os.path.join(args.dossier, 'notices.tsv')
    f_tree = os.path.join(args.dossier, 'tree_3p.txt')

    # 1) l'arbre : quels id de notice sont des communes, et leur nom
    communes = {}          # id_notice -> nom
    ordre = []             # ids de commune, dans l'ordre de l'inventaire
    for l in io.open(f_tree, encoding='utf-8'):
        l = l.rstrip('\n')
        if not l.strip():
            continue
        rang, nom, cid, _leaves = l.split('~', 3)
        communes[cid] = nom
        ordre.append(cid)
    print(f'arbre : {len(communes)} communes')

    # 2) les notices, dédoublonnées par id (une notice = une ligne)
    vues = {}
    for l in io.open(f_notices, encoding='utf-8'):
        l = l.rstrip('\n')
        if not l.strip():
            continue
        parts = l.split('\t')
        if len(parts) < 3:
            continue
        nid, ark, h3 = parts[0], parts[1], parts[2]
        if nid and ark:
            vues[nid] = (ark, h3)
    print(f'notices : {len(vues)} uniques')

    # 3) les planches, regroupées par numéro de cote (3 P N/M) : N = la commune.
    planches = {}              # N -> [(M, nid, ark, titre, annee), ...]
    sans_cote = nb_communes_notice = 0
    for nid, (ark, h3) in vues.items():
        if nid in communes:          # notice de regroupement, pas un plan
            nb_communes_notice += 1
            continue
        cote, titre, annee = parse_h3(h3)
        n, m = parse_cote(cote)
        if n is None or m is None:
            sans_cote += 1
            continue
        planches.setdefault(n, []).append((m, nid, ark, cote, titre, annee))
    for n in planches:
        planches[n].sort()
    cotes = sorted(planches, key=tri_cote)
    print(f'planches : {sum(len(v) for v in planches.values())} '
          f'réparties sur {len(cotes)} cotes')

    # 4) lecture des manifestes (1 par planche) : lieu + URL réelle de l'image
    print('lecture des manifestes (1 par planche)...')
    tous_arks = [p[2] for n in cotes for p in planches[n]]
    infos = lit_manifestes(tous_arks,
                           os.path.join(args.dossier, 'manifestes.json'))
    manquants = [a for a in tous_arks if not infos.get(a)]
    if manquants:
        print(f'  {len(manquants)} manifeste(s) illisible(s)')

    # Lieu de la commune = celui de sa première planche lisible
    lieux = {}
    for n in cotes:
        for (_m, _nid, ark, _c, _t, _a) in planches[n]:
            info = infos.get(ark)
            if info and info.get('lieu'):
                lieux[n] = info['lieu']
                break

    # Nom de l'arbre, dans l'ordre de l'inventaire : repli quand le manifeste
    # ne porte pas de champ « Lieu ».
    nom_arbre = {}
    for i, cid in enumerate(cotes):
        if i < len(ordre):
            nom_arbre[cid] = communes[ordre[i]]

    # 5) INSEE par cote
    print(f'résolution INSEE (geo.api + alias COG, département {DEPT})...')
    insee_de_cote, inconnues = {}, []
    for n in cotes:
        nom = lieux.get(n) or nom_arbre.get(n)
        code = insee_of(nom) if nom else None
        insee_de_cote[n] = code
        if not code:
            inconnues.append(f'3 P {n} « {nettoie_nom(nom) if nom else "?"} »')
    print(f'  {sum(1 for v in insee_de_cote.values() if v)}/{len(cotes)} résolues')
    if inconnues:
        print(f'  NON RÉSOLUES ({len(inconnues)}) :')
        for x in inconnues:
            print(f'    {x}')

    # 6) lignes SQL
    lignes, sans_insee, sans_image = [], 0, 0
    for n in cotes:
        insee = insee_de_cote.get(n)
        for (m, nid, ark, cote, titre, annee) in planches[n]:
            if not insee:
                sans_insee += 1
                continue

            typ, lettre, feuille = classify(titre)

            # URL du service Image API telle que déclarée par le manifeste.
            # À défaut (manifeste illisible), on retombe sur la dérivation par
            # la cote, exacte pour ~93 % des planches.
            info = infos.get(ark) or {}
            base_img = info.get('image')
            if not base_img:
                sans_image += 1
                dossier = dossier_iiif(n)
                base_img = (f'{PORTAIL}/iiif/SERIE_P/3P/{dossier}/'
                            f'FRAD016_{dossier}_{m:02d}.jpg')
            archive_url = f'{PORTAIL}/ark:/61904/{ark}'
            manifest = f'{archive_url}/manifest'
            vignette = f'{base_img}/full/400,/0/default.jpg'

            vals = [
                esc(insee), esc(typ), esc(lettre), num(feuille), num(annee),
                esc(cote), esc(archive_url), esc(base_img), esc(manifest),
                esc(vignette), esc(SOURCE), esc(PORTAIL), esc(LICENCE),
                'true', esc('georef'),
            ]
            lignes.append('insert into document (' + ', '.join(COLS) +
                          ') values (' + ', '.join(vals) + ');')

    with io.open(OUT, 'w', encoding='utf-8') as f:
        f.write(f'-- Charente (16) — fonds 3 P, {SOURCE}\n')
        f.write(f'-- {len(lignes)} plans, {len(ordre)} communes de l\'inventaire\n')
        f.write(f'-- Licence : {LICENCE} — overlay/géoréférencement autorisés\n\n')
        f.write('\n'.join(lignes))
        f.write('\n')

    print(f'\nOK {len(lignes)} inserts -> {OUT}')
    print(f'   ignorés : {nb_communes_notice} notices de commune, '
          f'{sans_cote} sans cote exploitable, {sans_insee} sans INSEE')
    if sans_image:
        print(f'   {sans_image} planche(s) sans image au manifeste : URL dérivée de la cote')


if __name__ == '__main__':
    main()
