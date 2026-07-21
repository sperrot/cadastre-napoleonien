#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Haute-Garonne (31) — chargement direct dans Supabase.

Source : data.haute-garonne.fr (Opendatasoft), jeu `cadastre-napoleonien`.
Couverture partielle assumée : **communes de plus de 10 000 habitants**
(173 planches, 14 communes).

Reprend la logique de `harvest/seed_hte_garonne.py` (type déduit du champ
`analyse`, cote, année) mais charge directement via PostgREST et utilise
`urllib` plutôt que `requests`, dont la vérification TLS échoue sur ce poste.

Les images sont servies par l'API de fichiers ODS, **sans extension** dans
l'URL : le worker sait désormais les servir telles quelles (route
`/static-iiif`), ce qui rend le géoréférencement Allmaps possible.

Usage : python harvest/load_hautegaronne_direct.py [--dry-run]
"""
import os, re, sys, json, time, argparse
import urllib.request, urllib.parse, urllib.error

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, '..', 'download', 'cadastre-napoleonien_hte_garonne.json')
GEO = 'https://geo.api.gouv.fr/communes'
DEPT = '31'
WORKER = 'https://iiif-allmaps.sperrot.workers.dev'
UA = {'User-Agent': 'mapping-cadastre-napoleonien/0.6'}
BATCH = 500


def load_env():
    env = {}
    with open(os.path.join(HERE, '.env'), encoding='utf-8') as f:
        for l in f:
            l = l.strip()
            if '=' in l and not l.startswith('#'):
                k, v = l.split('=', 1); env[k] = v
    return env


_cache = {}
def resolve_insee(commune):
    """INSEE depuis le nom, restreint au département 31 (anti-homonyme)."""
    key = commune.lower().strip()
    if key in _cache:
        return _cache[key]
    q = urllib.parse.urlencode({'nom': commune, 'codeDepartement': DEPT,
                                'fields': 'code', 'limit': 1})
    try:
        with urllib.request.urlopen(urllib.request.Request(f'{GEO}?{q}', headers=UA), timeout=20) as r:
            data = json.loads(r.read())
        code = data[0]['code'] if data else None
    except Exception as e:
        print(f'  ! {commune!r}: {e}', file=sys.stderr)
        code = None
    _cache[key] = code
    time.sleep(0.1)
    return code


def parse_annee(s):
    m = re.search(r'(1[6-9]\d{2})', s or '')
    return int(m.group(1)) if m else None


def parse_cote(analyse):
    m = re.search(r'(\d+\s*[WP]\s*[\d\s/]+)', analyse or '')
    return m.group(1).strip() if m else None


def parse_type(analyse):
    a = (analyse or '').lower()
    if 'assemblage' in a:
        return 'tableau_assemblage'
    if 'section' in a:
        return 'section'
    return 'feuille'


def iiif_manifest(jpg_url):
    return f'{WORKER}/static-manifest?u=' + urllib.parse.quote(jpg_url, safe='')


def post_batch(env, rows):
    data = json.dumps(rows, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f"{env['SUPABASE_URL']}/rest/v1/document",
                                 data=data, method='POST', headers={
        'apikey': env['SUPABASE_SERVICE_ROLE_KEY'],
        'Authorization': 'Bearer ' + env['SUPABASE_SERVICE_ROLE_KEY'],
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates,return=minimal',
    })
    try:
        r = urllib.request.urlopen(req, timeout=180)
        return r.status, ''
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    env = load_env()

    with open(SRC, encoding='utf-8') as f:
        records = json.load(f)
    print(f'{len(records)} planches dans le JSON open data')

    rows, skip = [], 0
    for rec in records:
        commune = (rec.get('commune') or '').strip()
        img = (rec.get('image') or {}).get('url') or ''
        if not commune or not img:
            skip += 1
            continue
        insee = resolve_insee(commune)
        if not insee:
            skip += 1
            continue
        analyse = rec.get('analyse') or ''
        rows.append({
            'insee': insee,
            'type': parse_type(analyse),
            'annee': parse_annee(rec.get('date', '')),
            'cote': parse_cote(analyse),
            'archive_url': img,
            'image_url': img,
            'iiif_manifest': iiif_manifest(img),
            'source': 'Archives de la Haute-Garonne (AD31)',
            'source_url': 'https://data.haute-garonne.fr',
            'licence': 'Licence Ouverte 2.0',
            'licence_overlay_ok': True,
            'statut': 'georef',
        })

    par_type = {}
    for r in rows:
        par_type[r['type']] = par_type.get(r['type'], 0) + 1
    print(f"a charger : {len(rows)} planches sur {len({r['insee'] for r in rows})} communes "
          f"({skip} ignorees) · {par_type}")
    if args.dry_run:
        for r in rows[:3]:
            print('  ex.', json.dumps(r, ensure_ascii=False)[:180])
        return

    ok = err = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        code, msg = post_batch(env, chunk)
        if code < 300:
            ok += len(chunk); print(f'  batch {i//BATCH+1} : HTTP {code} · +{len(chunk)}')
        else:
            err += len(chunk); print(f'  batch {i//BATCH+1} : HTTP {code} · ERR {msg}')
    print(f'termine : {ok} charges, {err} erreurs')


if __name__ == '__main__':
    main()
