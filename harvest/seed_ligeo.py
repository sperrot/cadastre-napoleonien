#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moisson générique d'un portail Ligeo → harvest/seed_<code>.sql

Les portails Ligeo partagent une architecture (HTML sous Anubis, IIIF ouvert,
un ark par planche, le manifeste porte les métadonnées) mais divergent dans le
détail : nom du champ « commune », grammaire du label, familles de cotes,
chemin du service Image API. Ce script absorbe ces variantes ; ce qu'il ne
peut pas absorber, il le SIGNALE plutôt que de le deviner.

Configuration : harvest/ligeo/portails.csv (une ligne par département).
Entrée       : harvest/ligeo/depot/<code>-<nom>/arks.tsv (cf. ligeo/README.md).

    # 1. profil du fonds avant tout chargement — À LIRE
    python harvest/seed_ligeo.py --dept 02 --check

    # 2. seed complet
    python harvest/seed_ligeo.py --dept 02

    # portail partagé : essaie les deux départements, refuse les ambiguïtés
    python harvest/seed_ligeo.py --dept 79,86 --check

Pourquoi --check : sur l'Aisne, le premier run a rendu un seed d'apparence
correcte (625 communes sur 659). L'écart cachait quatre défauts, dont trois
auraient corrompu les données en silence — un fonds entier ignoré (745
planches E-Dépôt), 255 communes rattachées à leur nom de 1825, et du cadastre
rénové de 1929 présenté comme napoléonien. --check rend ces trois-là visibles
en lisant 60 manifestes.
"""

import argparse
import csv
import glob
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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, 'ligeo', 'portails.csv')
DEPOT = os.path.join(HERE, 'ligeo', 'depot')
GEO_API = 'https://geo.api.gouv.fr/communes'
ANNEE_MIN, ANNEE_MAX = 1780, 1860      # bornes du cadastre napoléonien
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# Le champ « commune » n'a pas le même libellé d'un portail à l'autre.
CHAMPS_COMMUNE = ('Commune ou lieu-dit', 'Lieu', 'Commune', 'Lieux')


def norm(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def cle(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '', s.lower())


# ----------------------------------------------------------- configuration ---

def lit_conf(codes):
    """Lignes de portails.csv pour les codes demandés (la 1re fait référence)."""
    with io.open(CONF, encoding='utf-8') as fh:
        lignes = {r['code']: r for r in csv.DictReader(fh)}
    manquants = [c for c in codes if c not in lignes]
    if manquants:
        raise SystemExit(f'portails.csv : département(s) inconnu(s) {manquants}')
    conf = lignes[codes[0]]
    for champ in ('portail', 'naan'):
        if not (conf.get(champ) or '').strip():
            raise SystemExit(
                f'portails.csv : colonne « {champ} » vide pour le {codes[0]}. '
                f'Cf. harvest/ligeo/README.md.')
    conf['_depts'] = codes
    conf['_noms_depts'] = [lignes[c]['departement'] for c in codes]
    return conf


def trouve_arks(code, explicite=None):
    if explicite:
        return explicite
    motifs = [os.path.join(DEPOT, f'{code}-*', 'arks*.tsv'),
              os.path.join(DEPOT, f'*{code}*', 'arks*.tsv')]
    for m in motifs:
        trouves = sorted(glob.glob(m))
        if trouves:
            return trouves[0]
    raise SystemExit(f'aucun arks.tsv pour le {code} sous {DEPOT}. '
                     f'Cf. harvest/ligeo/README.md.')


def lire_arks(chemin, naan):
    txt = io.open(chemin, encoding='utf-8').read()
    arks = re.findall(rf'ark:/{naan}/([A-Za-z0-9]+)', txt)
    if not arks:
        # Format du collecteur : « ark <TAB> libellé ». Seul le 1er champ compte,
        # le libellé vient du manifeste.
        for l in txt.splitlines():
            premier = l.split('\t')[0].strip()
            if re.fullmatch(r'[A-Za-z0-9]{8,}', premier):
                arks.append(premier)
    vus, out = set(), []
    for a in arks:
        if a not in vus:
            vus.add(a)
            out.append(a)
    return out


# ------------------------------------------------------------- manifestes ---

def lit_manifestes(arks, portail, naan, cache_path):
    cache = {}
    if os.path.exists(cache_path):
        try:
            with io.open(cache_path, encoding='utf-8') as fh:
                cache = dict(json.load(fh))
        except Exception:
            cache = {}
    a_lire = [a for a in arks if a not in cache]
    print(f'manifestes : {len(cache)} en cache, {len(a_lire)} à lire')

    def un(ark):
        req = urllib.request.Request(f'{portail}/ark:/{naan}/{ark}/manifest',
                                     headers={'User-Agent': UA})
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
                    with io.open(cache_path, 'w', encoding='utf-8') as fh:
                        json.dump(cache, fh, ensure_ascii=False)
        with io.open(cache_path, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, ensure_ascii=False)
    return cache


def meta(doc, labels):
    """1re métadonnée dont le libellé figure dans `labels`."""
    if isinstance(labels, str):
        labels = (labels,)
    for md in doc.get('metadata') or []:
        if norm(html.unescape(str(md.get('label')))) in labels:
            return norm(html.unescape(str(md.get('value'))))
    return None


def service_image(doc):
    try:
        cv = doc['sequences'][0]['canvases'][0]
        svc = cv['images'][0]['resource'].get('service') or {}
        if isinstance(svc, list):
            svc = svc[0] if svc else {}
        sid = svc.get('@id') or svc.get('id')
        return sid if sid and '/iiif/' in sid else None
    except Exception:
        return None


def dimensions(doc):
    try:
        cv = doc['sequences'][0]['canvases'][0]
        return cv.get('width'), cv.get('height')
    except Exception:
        return None, None


def parse_label(doc):
    """« IDENT • Commune : Titre • Date » → (ident, titre, annee).

    L'identifiant est le 1er segment dès qu'il ne contient pas le « : » du
    couple Commune/Titre. Ne PAS le reconnaître à un motif de cote : l'Aisne
    mêle « 3P0001_02 », « 3P0749 bis_02 » et « E_Dépôt_0418_1G1_02 ».
    """
    lab = norm(html.unescape(str(doc.get('label') or '')))
    parts = [p.strip() for p in re.split(r'[•·|]', lab) if p.strip()]
    ident = titre = None
    annee = None
    if len(parts) >= 2 and ':' not in parts[0]:
        ident = parts[0]
        parts = parts[1:]
    for p in list(parts):
        if re.fullmatch(r'1[6-9]\d\d', p):
            annee = int(p)
            parts.remove(p)
    if parts:
        titre = parts[0]
        if ':' in titre:
            titre = titre.split(':', 1)[1].strip()
    if annee is None:
        m = re.search(r'1[6-9]\d\d', meta(doc, ('Dates', 'Date')) or '')
        if m:
            annee = int(m.group(0))
    return ident, titre, annee


def parse_ident(ident):
    """Cote = l'identifiant TEL QUE L'AD L'ÉCRIT ; seul le suffixe « _NN »
    (rang de planche) est extrait. Aucune cote reconstruite."""
    if not ident:
        return None, None
    cote = norm(ident)
    m = re.search(r'_(\d{1,3})$', cote)
    return cote, (int(m.group(1)) if m else None)


def classify(titre):
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

class Resolveur:
    """Nom de commune → INSEE. Alias COG d'abord, puis geo.api restreint aux
    départements attendus. Ne devine JAMAIS : une recherche floue nationale
    avait résolu « Ain » en Ainhoa (64014) et corrompu 5 905 notices."""

    def __init__(self, depts, noms_depts):
        self.depts = depts
        self.noms = {n.lower() for n in noms_depts} | {'france'}
        with io.open(os.path.join(HERE, 'communes_alias.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        self.alias = {}
        for d in depts:
            for nom, code in (data.get(d) or {}).items():
                self.alias[cle(nom)] = code
        self.cache = {}
        self.ambigus = []

    def nettoie(self, nom):
        """Trois formes rencontrées, dénombrées sur 4 443 manifestes de l'Aisne :
            « Abbécourt (Aisne, France) »                         → Abbécourt
            « Agnicourt (Agnicourt-et-Séchelles, Aisne, France) » → la parenthèse
                  porte le nom ACTUEL, la tête de champ celui de 1825
            « Beaulne-et-Chivy »                                  → tel quel
        Jeter la parenthèse laissait 255 planches sur un nom disparu."""
        n = norm(nom).rstrip('.').strip()
        m = re.match(r'^(.*?)\s*\((.*)\)\s*$', n)
        if m:
            dedans = [p.strip() for p in m.group(2).split(',') if p.strip()]
            dedans = [p for p in dedans if p.lower() not in self.noms]
            n = dedans[0] if dedans else m.group(1).strip()
        if '/' in n:                      # « ancien / actuel »
            n = n.split('/')[-1].strip()
        return n

    def _geo(self, nom, dept):
        p = urllib.parse.urlencode({'nom': nom, 'fields': 'code', 'boost': 'population',
                                    'limit': 1, 'codeDepartement': dept})
        req = urllib.request.Request(f'{GEO_API}?{p}',
                                     headers={'User-Agent': 'mapping-cadastre-napoleonien'})
        # Une panne réseau ne doit PAS se confondre avec une commune inconnue :
        # sans réessai, un « connection closed » transitoire mettait None en
        # cache et faisait disparaître les planches de la commune.
        for essai in range(4):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    d = json.loads(r.read())
                return d[0]['code'] if d else None, True
            except Exception as e:
                sys.stderr.write(f'  geo.api essai {essai + 1}/4 « {nom} » : {e}\n')
                time.sleep(1.5 * (essai + 1))
        return None, False

    def __call__(self, nom):
        n = self.nettoie(nom)
        if not n:
            return None
        if cle(n) in self.alias:
            return self.alias[cle(n)]
        if n in self.cache:
            return self.cache[n]
        trouves, complet = {}, True
        for dept in self.depts:
            code, ok = self._geo(n, dept)
            complet &= ok
            if code:
                trouves[dept] = code
            time.sleep(0.15)
        if len(set(trouves.values())) > 1:
            # Portail partagé : le même libellé existe dans les deux
            # départements. On refuse plutôt que d'en élire un.
            self.ambigus.append((n, dict(trouves)))
            return None
        code = next(iter(trouves.values()), None)
        if complet:                       # on ne mémorise que ce qu'on a obtenu
            self.cache[n] = code
        return code


# ------------------------------------------------------------------ CHECK ---

def famille(ident):
    """« 3P0001_02 » → « 3P#### » ; « E_Dépôt_0418_1G1_02 » → « E_Dépôt_… »."""
    if not ident:
        return '(aucun identifiant)'
    return re.sub(r'\d+', '#', ident)


def http_probe(url, origin=None):
    h = {'User-Agent': UA}
    if origin:
        h['Origin'] = origin
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30)
        return r.status, r.headers.get('Access-Control-Allow-Origin'), r.read()
    except Exception as e:
        return None, str(e)[:50], b''


def check(conf, arks, docs, resolveur, taille):
    code = conf['_depts'][0]
    print()
    print('=' * 72)
    print(f"PROFIL DU FONDS — {conf['departement']} ({code}) — {taille} manifestes lus")
    print('=' * 72)

    lus = [d for d in docs.values() if d]
    print(f'\n1. Manifestes      : {len(lus)}/{taille} lus, {taille - len(lus)} en échec')
    if not lus:
        raise SystemExit('aucun manifeste lisible — vérifie portail et naan.')

    # -- champ commune
    print('\n2. Champ commune')
    trouve = None
    for champ in CHAMPS_COMMUNE:
        n = sum(1 for d in lus if meta(d, champ))
        if n:
            print(f'   « {champ} » présent sur {n}/{len(lus)}')
            trouve = trouve or champ
    if not trouve:
        print('   AUCUN des libellés connus. Libellés réellement présents :')
        for k, v in Counter(norm(html.unescape(str(md.get("label"))))
                            for d in lus for md in d.get('metadata') or []).most_common(10):
            print(f'      {k}  x{v}')
        print('   → ajouter le bon libellé à CHAMPS_COMMUNE avant de continuer.')
    else:
        formes = Counter()
        for d in lus:
            v = meta(d, CHAMPS_COMMUNE) or ''
            m = re.match(r'^(.*?)\s*\((.*)\)\s*$', v)
            formes['sans parenthèse' if not m else
                   f'{len([x for x in m.group(2).split(",") if x.strip()])} éléments'] += 1
        print(f'   formes : {dict(formes)}')
        print('   (>2 éléments ⇒ le nom ACTUEL est dans la parenthèse — cf. Aisne)')
        for d in lus:
            v = meta(d, CHAMPS_COMMUNE) or ''
            m = re.match(r'^(.*?)\s*\((.*)\)\s*$', v)
            if m and len([x for x in m.group(2).split(',') if x.strip()]) > 2:
                print(f'   exemple : « {v} » → « {resolveur.nettoie(v)} »')
                break

    # -- familles d'identifiants
    print('\n3. Familles d\'identifiants (une famille inattendue = un fonds ignoré)')
    fam = Counter(famille(parse_label(d)[0]) for d in lus)
    for k, v in fam.most_common(8):
        print(f'   {k:<34} x{v}')

    # -- années
    print('\n4. Années')
    ans = [parse_label(d)[2] for d in lus]
    dates = [a for a in ans if a]
    if dates:
        print(f'   {len(dates)} datées : {min(dates)}–{max(dates)} | '
              f'{len(ans) - len(dates)} sans date')
        print(f'   par décennie : {dict(sorted(Counter((a // 10) * 10 for a in dates).items()))}')
        hors = [a for a in dates if a > ANNEE_MAX or a < ANNEE_MIN]
        if hors:
            print(f'   ⚠ {len(hors)} hors [{ANNEE_MIN}–{ANNEE_MAX}] : {sorted(set(hors))}')
            print('     → cadastre rénové mêlé au fonds ; elles seront écartées.')
    else:
        print('   aucune date lisible')

    # -- types
    print('\n5. Types de planche')
    print(f'   {dict(Counter(classify(parse_label(d)[1])[0] for d in lus))}')

    # -- image + CORS
    print('\n6. Service Image API et CORS')
    imgs = [service_image(d) for d in lus]
    sans = sum(1 for i in imgs if not i)
    print(f'   {len(imgs) - sans}/{len(imgs)} manifestes déclarent un service image'
          + (f' — {sans} SANS' if sans else ''))
    ex = next((i for i in imgs if i), None)
    if ex:
        print(f'   exemple : {ex}')
        man = f"{conf['portail']}/ark:/{conf['naan']}/{next(iter(docs))}/manifest"
        for lib, url in (('manifeste', man), ('info.json', ex + '/info.json')):
            s1, c1, _ = http_probe(url)
            s2, c2, corps = http_probe(url, origin='https://allmaps.org')
            print(f'   {lib:<10} sans Origin : {s1} CORS={c1} | '
                  f'avec Origin : {s2} CORS={c2}')
            if lib == 'info.json' and corps:
                try:
                    j = json.loads(corps)
                    print(f'      {j.get("width")}x{j.get("height")} | '
                          f'profile={j.get("profile")} | tiles={j.get("tiles")}')
                    if not j.get('tiles'):
                        print('      ⚠ pas de tuilage déclaré : le serveur Allmaps '
                              'peine sur les images lourdes (cf. Doubs, 7,6 Mo)')
                except Exception:
                    print('      ⚠ info.json illisible')
        w, h = dimensions(lus[0])
        print(f'   dimensions du 1er canvas : {w}x{h}')

    # -- INSEE
    print('\n7. Résolution INSEE (échantillon)')
    noms = sorted({meta(d, CHAMPS_COMMUNE) for d in lus if meta(d, CHAMPS_COMMUNE)})
    res = {n: resolveur(n) for n in noms}
    ko = [n for n, c in res.items() if not c]
    print(f'   {len(noms) - len(ko)}/{len(noms)} communes résolues')
    hors = [c for c in res.values() if c and c[:2] not in conf['_depts']]
    if hors:
        print(f'   ⚠ {len(hors)} hors département attendu : {sorted(set(hors))}')
        print('     (peut être légitime : une commune ayant changé de département)')
    for n in ko[:10]:
        print(f'   non résolue : {n}')
    if resolveur.ambigus:
        print(f'   ⚠ {len(resolveur.ambigus)} libellé(s) ambigu(s) entre départements :')
        for n, t in resolveur.ambigus[:5]:
            print(f'      {n} → {t}')

    print('\n' + '=' * 72)
    print('Relire les ⚠ ci-dessus AVANT de lancer le seed complet.')
    print('=' * 72)


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


def seed(conf, arks, docs, resolveur, out_path):
    depts = conf['_depts']
    overlay = (conf.get('overlay_ok') or '').strip().lower() in ('oui', 'true', '1')
    licence = conf.get('licence') or 'À vérifier'
    # Libellé d'attribution : celui du portail, pas un libellé fabriqué —
    # il s'affiche tel quel sous chaque planche (mention CRPA).
    source = (conf.get('source') or '').strip() or         f"Archives départementales — {conf['departement']}"
    portail = conf['portail']

    planches, hors_periode, sans_image, sans_cote = [], [], 0, 0
    for a in arks:
        d = docs.get(a)
        if not d:
            continue
        ident, titre, annee = parse_label(d)
        if annee is not None and not (ANNEE_MIN <= annee <= ANNEE_MAX):
            hors_periode.append((ident, annee))
            continue
        cote, plan = parse_ident(ident)
        if not cote:
            sans_cote += 1
        commune = meta(d, CHAMPS_COMMUNE)
        if not commune:
            ctx = meta(d, ('Contexte', 'Context')) or ''
            commune = ctx.split('>')[-1].strip() or None
        img = service_image(d)
        if not img:
            sans_image += 1
        planches.append({'ark': a, 'cote': cote, 'plan': plan, 'titre': titre,
                         'annee': annee, 'commune': commune, 'image': img})
    print(f'planches : {len(planches)} | sans cote {sans_cote} | sans image {sans_image}')
    if hors_periode:
        print(f'  {len(hors_periode)} hors [{ANNEE_MIN}-{ANNEE_MAX}], écartées : '
              f'{sorted({y for _, y in hors_periode})}')

    noms = sorted({p['commune'] for p in planches if p['commune']})
    print(f'résolution INSEE de {len(noms)} commune(s), département(s) {depts}...')
    table = {n: resolveur(n) for n in noms}
    ko = sorted(n for n, c in table.items() if not c)
    print(f'  {len(noms) - len(ko)}/{len(noms)} résolues')
    for n in ko:
        print(f'    NON RÉSOLUE : {n}')

    # Garde-fou : le contrôle qui manquait au premier seed de l'Ain.
    codes = [table[p['commune']] for p in planches
             if p['commune'] and table.get(p['commune'])]
    if not codes:
        raise SystemExit('aucune commune résolue — rien à écrire.')
    hors = [c for c in codes if c[:2] not in depts]
    print(f'contrôle département : {dict(Counter(c[:2] for c in codes))}')
    if len(hors) / len(codes) > 0.05:
        raise SystemExit(f'{len(hors)}/{len(codes)} INSEE hors {depts} — '
                         f'écriture refusée.')

    lignes, ignorees = [], 0
    for p in planches:
        insee = table.get(p['commune'] or '')
        if not insee:
            ignorees += 1
            continue
        typ, lettre, feuille = classify(p['titre'])
        if feuille is None and typ == 'feuille':
            feuille = p['plan']
        archive_url = f"{portail}/ark:/{conf['naan']}/{p['ark']}"
        vals = [
            esc(insee), esc(typ), esc(lettre), num(feuille), num(p['annee']),
            esc(p['cote']), esc(archive_url), esc(p['image']),
            esc(archive_url + '/manifest'),
            esc(p['image'] + '/full/400,/0/default.jpg' if p['image'] else None),
            esc(source), esc(portail), esc(licence),
            'true' if overlay else 'false',
            esc('georef' if overlay else 'lien'),
        ]
        lignes.append('insert into document (' + ', '.join(COLS) +
                      ') values (' + ', '.join(vals) + ');')

    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"-- {conf['departement']} ({depts[0]}) — {source}\n")
        f.write(f'-- {len(lignes)} planches sur {len(noms) - len(ko)} communes\n')
        f.write(f'-- Licence : {licence} — overlay {"autorisé" if overlay else "REFUSÉ"}\n\n')
        f.write('\n'.join(lignes) + '\n')
    print(f'\nOK {len(lignes)} inserts -> {out_path}')
    if ignorees:
        print(f'   {ignorees} planche(s) sans commune résolue, ignorées')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dept', required=True,
                    help='code département, ou liste « 79,86 » pour un portail partagé')
    ap.add_argument('--arks', help='fichier des arks (défaut : ligeo/depot/<code>-*/arks.tsv)')
    ap.add_argument('--check', action='store_true',
                    help='profil du fonds sur un échantillon, sans rien écrire')
    ap.add_argument('--taille-check', type=int, default=60)
    ap.add_argument('--out', help='fichier SQL (défaut : harvest/seed_<code>.sql)')
    args = ap.parse_args()

    codes = [c.strip() for c in args.dept.split(',') if c.strip()]
    conf = lit_conf(codes)
    chemin = trouve_arks(codes[0], args.arks)
    arks = lire_arks(chemin, conf['naan'])
    print(f"{conf['departement']} ({'+'.join(codes)}) — {len(arks)} ark(s) "
          f"distincts depuis {os.path.relpath(chemin, HERE)}")
    if not arks:
        raise SystemExit('aucun ark trouvé — vérifie le fichier.')

    attendu = (conf.get('nb_resultats') or '').strip()
    if attendu.isdigit() and abs(len(arks) - int(attendu)) > 0:
        print(f'  ⚠ {len(arks)} arks pour {attendu} résultats annoncés '
              f'— collecte peut-être incomplète')

    cache = os.path.join(HERE, f'_manifestes_{codes[0]}.json')
    lot = arks[:args.taille_check] if args.check else arks
    docs = lit_manifestes(lot, conf['portail'], conf['naan'], cache)
    docs = {a: docs.get(a) for a in lot}
    resolveur = Resolveur(codes, conf['_noms_depts'])

    if args.check:
        check(conf, lot, docs, resolveur, len(lot))
        return
    out = args.out or os.path.join(HERE, f'seed_{codes[0]}.sql')
    seed(conf, arks, docs, resolveur, out)


if __name__ == '__main__':
    main()
