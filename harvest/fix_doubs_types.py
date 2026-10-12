#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doubs (25) : reclasse la page 01 en tableau d'assemblage + numérote les feuilles.

Le fonds Doubs a été chargé avec `type='feuille'` pour toutes les planches. Or
le motif de nommage open data est `…/FRAD025_<cote>_<NN>.jpg` où **la page 01
est le tableau d'assemblage** de la commune et les suivantes les feuilles de
section.

⚠️ La règle « page 01 = TA » est fausse pour ~1 cote sur 3 (validation visuelle
du 2026-10-12) : le TA peut être en _02…_11. `georef_auto/trouver_ta_doubs.py`
retrouve la vraie page en y recalant le contour communal ; son CSV corrige la
règle (`--ta-csv`, par défaut georef_auto/sortie_ta_doubs/ta_doubs.csv s'il existe).

Ce script, idempotent, applique via PostgREST (service_role) :
  - `type='tableau_assemblage'` pour les `_01.jpg`
  - `type='feuille'` pour les autres
  - puis, pour chaque cote dont le TA trouvé n'est pas la _01 : la _01 repasse en
    `feuille` et la page trouvée en `tableau_assemblage`
  - `feuille_num` = entier extrait du suffixe `_NN` (tri correct, libellés
    « Feuille N » au lieu de « Planche » dans la GED)

Usage : python harvest/fix_doubs_types.py [--dry-run] [--ta-csv chemin.csv]
"""
import os, re, sys, csv, json, argparse, urllib.request, urllib.error

# Console Windows en cp1252 par défaut → les flèches/accents cassent les print()
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(__file__)
BATCH = 100


def load_env():
    env = {}
    with open(os.path.join(HERE, '.env'), encoding='utf-8') as f:
        for l in f:
            l = l.strip()
            if '=' in l and not l.startswith('#'):
                k, v = l.split('=', 1); env[k] = v
    return env


def api(env, method, path, body=None, prefer=None):
    h = {
        'apikey': env['SUPABASE_SERVICE_ROLE_KEY'],
        'Authorization': 'Bearer ' + env['SUPABASE_SERVICE_ROLE_KEY'],
    }
    if prefer:
        h['Prefer'] = prefer
    data = None
    if body is not None:
        h['Content-Type'] = 'application/json'
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        f"{env['SUPABASE_URL']}/rest/v1/{path}", data=data, method=method, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=120)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:300]


PAGE_RE = re.compile(r'_(\d{1,3})\.jpe?g$', re.I)
COTE_RE = re.compile(r'/FRAD025_(3P\d+)_(\d{1,3})\.jpe?g$', re.I)
TA_CSV = os.path.join(HERE, '..', 'georef_auto', 'sortie_ta_doubs', 'ta_doubs.csv')


def pages_ta(chemin):
    """{cote: numéro de page du TA} pour les cotes où trouver_ta_doubs a calé une page."""
    if not chemin or not os.path.exists(chemin):
        return {}
    with open(chemin, encoding='utf-8') as f:
        return {r['cote']: int(r['page_ta']) for r in csv.DictReader(f)
                if r.get('statut') == 'calé' and r.get('page_ta')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--ta-csv', default=TA_CSV, help='sortie de georef_auto/trouver_ta_doubs.py')
    args = ap.parse_args()
    ta = pages_ta(args.ta_csv)
    print(f'{len(ta)} cotes au TA vérifié, dont {sum(n != 1 for n in ta.values())} hors page 01')
    env = load_env()

    # 1) Récupérer toutes les lignes du 25
    rows, off = [], 0
    while True:
        st, page = api(env, 'GET',
                       f'document?select=id,image_url,type,feuille_num&insee=like.25*'
                       f'&order=image_url&limit=1000&offset={off}')
        if st >= 300:
            raise SystemExit(f'lecture: HTTP {st} {page}')
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    print(f'{len(rows)} lignes Doubs')

    # 2) Calculer l'état cible
    updates = []
    sans_motif = 0
    for r in rows:
        m = PAGE_RE.search(r.get('image_url') or '')
        if not m:
            sans_motif += 1
            continue
        num = int(m.group(1))
        mc = COTE_RE.search(r.get('image_url') or '')
        page_ta = ta.get(mc.group(1), 1) if mc else 1
        want_type = 'tableau_assemblage' if num == page_ta else 'feuille'
        if r.get('type') != want_type or r.get('feuille_num') != num:
            updates.append({'id': r['id'], 'type': want_type, 'feuille_num': num})

    nb_assemblages = sum(1 for u in updates if u['type'] == 'tableau_assemblage')
    print(f'{len(updates)} lignes à mettre à jour '
          f'({nb_assemblages} en tableau d\'assemblage) · {sans_motif} sans motif _NN')
    if args.dry_run:
        for u in updates[:5]:
            print('  ex.', u)
        return

    # 3) Appliquer — un PATCH par numéro de page (≈30 requêtes au lieu de 5 000).
    # PostgREST ne sait pas faire UPDATE … FROM : on groupe par suffixe de page,
    # chaque groupe partageant le même couple (type, feuille_num).
    par_page = {}
    for r in rows:
        m = PAGE_RE.search(r.get('image_url') or '')
        if m:
            par_page.setdefault(m.group(1), int(m.group(1)))

    ok = err = 0
    for suffixe, num in sorted(par_page.items(), key=lambda kv: kv[1]):
        want_type = 'tableau_assemblage' if num == 1 else 'feuille'
        # filtre : département 25 + URL se terminant par _<suffixe>.jpg
        path = (f'document?insee=like.25*&image_url=like.*_{suffixe}.jpg')
        st, msg = api(env, 'PATCH', path,
                      body={'type': want_type, 'feuille_num': num},
                      prefer='return=minimal')
        if st < 300:
            ok += 1
            print(f'  page {suffixe} → {want_type} (feuille_num={num}) : HTTP {st}')
        else:
            err += 1
            print(f'  page {suffixe} : ERR {st} {msg}')
    # 4) Exceptions : cotes dont le TA n'est pas la page 01 (une requête par page)
    for cote, num in sorted(ta.items()):
        if num == 1:
            continue
        for page, want_type in ((1, 'feuille'), (num, 'tableau_assemblage')):
            path = f'document?insee=like.25*&image_url=like.*/FRAD025_{cote}_{page:02d}.jpg'
            st, msg = api(env, 'PATCH', path, body={'type': want_type}, prefer='return=minimal')
            ok, err = (ok + 1, err) if st < 300 else (ok, err + 1)
            if st >= 300:
                print(f'  {cote}_{page:02d} : ERR {st} {msg}')
    print(f'termine : {ok} mises a jour, {err} erreurs')


if __name__ == '__main__':
    main()
