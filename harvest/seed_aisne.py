#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génère harvest/seed_aisne.sql — cadastre napoléonien des Archives
départementales de l'Aisne (plateforme Ligeo, portail archives.aisne.fr).

Différence avec la Charente : ici le manifeste se suffit à lui-même. Il porte
la cote, la commune ORTHOGRAPHIÉE CORRECTEMENT, l'année, le type de planche et
l'URL réelle du service Image API :

    label    : « 3P0001_01 • Abbecourt : Tableau d'assemblage • 1828 »
    metadata : Contexte              → « Cadastre … > A > Abbecourt »
               Dates                 → « 1828 »
               Commune ou lieu-dit   → « Abbécourt (Aisne, France) »
    service  → https://archives.aisne.fr/iiif/FRAD002_CADASTRE/
                        FRAD002_3P0001/FRAD002_3P0001_01.jpg   (Image API level1)

L'entrée se réduit donc à **la liste des arks**, l'inventaire HTML étant
protégé par Anubis (cf. harvest/README.md § Aisne).

    arks.txt : un ark par ligne (« vta55154026410f9 »), ou n'importe quel
               fichier texte/TSV d'où l'on sait extraire ark:/63271/<ark>.

Usage : python harvest/seed_aisne.py --arks <fichier> [--limite 50]
"""

import argparse
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'seed_aisne.sql')
CACHE = os.path.join(HERE, '_manifestes_aisne.json')

PORTAIL = 'https://archives.aisne.fr'
NAAN = '63271'
DEPT = '02'
SOURCE = "Archives départementales de l'Aisne"
# Licence Ouverte Etalab 2.0 confirmée par le service → overlay et
# géoréférencement Allmaps autorisés.
LICENCE = 'Licence Ouverte (Etalab 2.0)'
OVERLAY_OK = True
GEO_API = 'https://geo.api.gouv.fr/communes'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


# --------------------------------------------------------------- manifestes ---

def lit_manifestes(arks):
    """[ark] → {ark: manifeste}. Cache disque : les reruns sont gratuits."""
    cache = {}
    if os.path.exists(CACHE):
        try:
            with io.open(CACHE, encoding='utf-8') as fh:
                cache = dict(json.load(fh))
        except Exception:
            cache = {}
    a_lire = [a for a in arks if a not in cache]
    print(f'manifestes : {len(cache)} en cache, {len(a_lire)} à lire')

    def un(ark):
        url = f'{PORTAIL}/ark:/{NAAN}/{ark}/manifest'
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        for essai in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    return ark, json.loads(r.read().decode('utf-8', 'replace'))
            except Exception:
                time.sleep(1.0 * (essai + 1))
        return ark, None

    if a_lire:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for k, (ark, doc) in enumerate(ex.map(un, a_lire), 1):
                cache[ark] = doc
                if k % 250 == 0:
                    print(f'  {k}/{len(a_lire)}', flush=True)
                    with io.open(CACHE, 'w', encoding='utf-8') as fh:
                        json.dump(cache, fh, ensure_ascii=False)
        with io.open(CACHE, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, ensure_ascii=False)
    return cache


def meta(doc, label):
    for md in doc.get('metadata') or []:
        if norm(html.unescape(str(md.get('label')))) == label:
            return norm(html.unescape(str(md.get('value'))))
    return None


def service_image(doc):
    """@id du service Image API du premier canvas."""
    try:
        cv = doc['sequences'][0]['canvases'][0]
        svc = cv['images'][0]['resource'].get('service') or {}
        if isinstance(svc, list):
            svc = svc[0] if svc else {}
        sid = svc.get('@id') or svc.get('id')
        return sid if sid and '/iiif/' in sid else None
    except Exception:
        return None


def parse_label(doc):
    """« 3P0001_01 • Abbecourt : Tableau d'assemblage • 1828 »
       → (identifiant, titre, annee). Tolère l'absence de séparateurs."""
    lab = norm(html.unescape(str(doc.get('label') or '')))
    parts = [p.strip() for p in re.split(r'[•·]', lab) if p.strip()]
    ident = titre = None
    annee = None
    if parts and re.match(r'^\d?\s*[A-Z]\s*\d+', parts[0]):
        ident = parts[0]
        parts = parts[1:]
    for p in list(parts):
        if re.fullmatch(r'1[6-9]\d\d', p):
            annee = int(p)
            parts.remove(p)
    if parts:
        titre = parts[0]
        # « Abbecourt : Tableau d'assemblage » → on ne garde que la partie droite
        if ':' in titre:
            titre = titre.split(':', 1)[1].strip()
    if annee is None:
        d = meta(doc, 'Dates') or ''
        m = re.search(r'1[6-9]\d\d', d)
        if m:
            annee = int(m.group(0))
    return ident, titre, annee


def parse_ident(ident):
    """« 3P0001_01 » → ('3 P 1', 1). Le 1er nombre est le dossier de la commune,
    le second la planche. Renvoie (None, None) si le motif n'est pas reconnu :
    on préfère une cote vide à une cote inventée."""
    if not ident:
        return None, None
    m = re.match(r'^(\d?\s*P)\s*(\d+)([A-Za-z]?)[_/-](\d+)$',
                 ident.replace(' ', ''), re.I)
    if not m:
        m2 = re.match(r'^3P(\d+)([A-Za-z]?)$', ident.replace(' ', ''), re.I)
        if m2:
            return f'3 P {int(m2.group(1))}{m2.group(2).upper()}', None
        return None, None
    return f'3 P {int(m.group(2))}{m.group(3).upper()}', int(m.group(4))


def classify(titre):
    """Titre → (type, section_lettre, feuille_num)."""
    t = norm(titre)
    if not t:
        return 'feuille', None, None
    if re.search(r"tableau|plan\s+g[ée]n[ée]ral", t, re.I):
        return 'tableau_assemblage', None, None
    feuille = None
    m = re.search(r'Feuille\s+(\d+)', t, re.I)
    if m:
        feuille = int(m.group(1))
    lettre = None
    m = re.search(r'(?:^|\s)Sections?\s+([A-Z]{1,2})(?=[\s.,]|$)', t)
    if m:
        lettre = m.group(1)
    if feuille is not None:
        return 'feuille', lettre, feuille
    if lettre:
        return 'section', lettre, None
    return 'feuille', None, None


# ------------------------------------------------------------------ INSEE ---

def cle(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '', s.lower())


def load_alias():
    try:
        with io.open(os.path.join(HERE, 'communes_alias.json'), encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception as e:
        sys.stderr.write(f'communes_alias.json illisible ({e})\n')
        return {}, {}
    t = dict((data.get(DEPT) or {}))
    return t, {cle(k): v for k, v in t.items()}


ALIAS, ALIAS_NORM = load_alias()
_cache_insee = {}


def nettoie_nom(nom):
    """« Abbécourt (Aisne, France) » → « Abbécourt »."""
    n = norm(nom).rstrip('.').strip()
    n = re.sub(r'\s*\(.*?\)\s*$', '', n)
    if '/' in n:                      # « ancien / actuel »
        n = n.split('/')[-1].strip()
    return n


def insee_of(nom):
    """Nom de commune → INSEE, RESTREINT au département 02.

    Sans codeDepartement, geo.api renvoie l'homonyme le plus peuplé du pays :
    c'est ce piège qui avait envoyé 5 905 notices de l'Ain sur Ainhoa.
    """
    n = nettoie_nom(nom)
    if not n:
        return None
    if n in ALIAS:
        return ALIAS[n]
    if cle(n) in ALIAS_NORM:
        return ALIAS_NORM[cle(n)]
    if n in _cache_insee:
        return _cache_insee[n]
    code = None
    try:
        p = urllib.parse.urlencode({'nom': n, 'fields': 'code', 'boost': 'population',
                                    'limit': 1, 'codeDepartement': DEPT})
        req = urllib.request.Request(f'{GEO_API}?{p}',
                                     headers={'User-Agent': 'mapping-cadastre-napoleonien'})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        if d:
            code = d[0]['code']
    except Exception as e:
        sys.stderr.write(f'  geo.api KO pour « {n} » : {e}\n')
    _cache_insee[n] = code
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


def lire_arks(chemin):
    """Accepte un ark par ligne, ou n'importe quel texte contenant ark:/63271/x."""
    txt = io.open(chemin, encoding='utf-8').read()
    arks = re.findall(rf'ark:/{NAAN}/([A-Za-z0-9]+)', txt)
    if not arks:
        # Format du collecteur : « ark <TAB> libellé de la notice ».
        # On ne lit que le 1er champ : le libellé, lui, vient du manifeste.
        for l in txt.splitlines():
            premier = l.split('\t')[0].strip()
            if re.fullmatch(r'[A-Za-z0-9]{8,}', premier):
                arks.append(premier)
    vus, out = set(), []
    for a in arks:                       # dédoublonne en gardant l'ordre
        if a not in vus:
            vus.add(a)
            out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arks', required=True, help='fichier des arks')
    ap.add_argument('--limite', type=int, help='ne traiter que les N premiers (test)')
    args = ap.parse_args()

    arks = lire_arks(args.arks)
    if args.limite:
        arks = arks[:args.limite]
    print(f'{len(arks)} ark(s) distincts')
    if not arks:
        raise SystemExit('aucun ark trouvé — vérifie le fichier')

    docs = lit_manifestes(arks)
    illisibles = [a for a in arks if not docs.get(a)]
    if illisibles:
        print(f'  {len(illisibles)} manifeste(s) illisible(s) : {illisibles[:5]}')

    # 1) extraction
    planches, sans_commune, sans_image, sans_cote = [], [], 0, 0
    for a in arks:
        d = docs.get(a)
        if not d:
            continue
        ident, titre, annee = parse_label(d)
        cote, plan = parse_ident(ident)
        if not cote:
            sans_cote += 1
        commune = meta(d, 'Commune ou lieu-dit') or meta(d, 'Lieu')
        if not commune:                       # repli : « … > A > Abbecourt »
            ctx = meta(d, 'Contexte') or ''
            commune = ctx.split('>')[-1].strip() or None
        img = service_image(d)
        if not img:
            sans_image += 1
        planches.append({'ark': a, 'cote': cote, 'plan': plan, 'titre': titre,
                         'annee': annee, 'commune': commune, 'image': img})
    print(f'planches : {len(planches)} | sans cote {sans_cote} | sans image {sans_image}')

    # 2) INSEE — une résolution par commune distincte
    noms = sorted({p['commune'] for p in planches if p['commune']})
    print(f'résolution INSEE de {len(noms)} commune(s) (département {DEPT})...')
    table = {n: insee_of(n) for n in noms}
    inconnues = sorted(n for n, c in table.items() if not c)
    print(f'  {len(noms) - len(inconnues)}/{len(noms)} résolues')
    if inconnues:
        print(f'  NON RÉSOLUES ({len(inconnues)}) :')
        for n in inconnues:
            print(f'    {n}')

    # 3) garde-fou département — le contrôle qui manquait au seed de l'Ain
    codes = [table[p['commune']] for p in planches
             if p['commune'] and table.get(p['commune'])]
    if not codes:
        raise SystemExit('aucune commune résolue — rien à écrire.')
    hors = [c for c in codes if not c.startswith(DEPT)]
    if len(hors) / len(codes) > 0.05:
        raise SystemExit(f'{len(hors)}/{len(codes)} INSEE hors du {DEPT} — '
                         f'écriture refusée.')

    # 4) SQL
    lignes = []
    for p in planches:
        insee = table.get(p['commune'] or '')
        if not insee:
            sans_commune.append(p['ark'])
            continue
        typ, lettre, feuille = classify(p['titre'])
        if feuille is None and typ == 'feuille':
            feuille = p['plan']              # à défaut, le rang de la planche
        archive_url = f'{PORTAIL}/ark:/{NAAN}/{p["ark"]}'
        vals = [
            esc(insee), esc(typ), esc(lettre), num(feuille), num(p['annee']),
            esc(p['cote']), esc(archive_url), esc(p['image']),
            esc(archive_url + '/manifest'),
            esc(p['image'] + '/full/400,/0/default.jpg' if p['image'] else None),
            esc(SOURCE), esc(PORTAIL), esc(LICENCE),
            'true' if OVERLAY_OK else 'false',
            esc('georef' if OVERLAY_OK else 'lien'),
        ]
        lignes.append('insert into document (' + ', '.join(COLS) +
                      ') values (' + ', '.join(vals) + ');')

    with io.open(OUT, 'w', encoding='utf-8') as f:
        f.write(f"-- Aisne (02) — cadastre napoléonien, {SOURCE}\n")
        f.write(f'-- {len(lignes)} planches sur {len(noms) - len(inconnues)} communes\n')
        f.write(f'-- Licence : {LICENCE} — overlay/géoréférencement autorisés\n\n')
        f.write('\n'.join(lignes) + '\n')
    print(f'\nOK {len(lignes)} inserts -> {OUT}')
    if sans_commune:
        print(f'   {len(sans_commune)} planche(s) sans commune résolue, ignorées')


if __name__ == '__main__':
    main()
