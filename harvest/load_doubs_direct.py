#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Charge le Doubs (25) DIRECTEMENT dans Supabase depuis le JSON open data,
sans passer par un seed SQL intermédiaire.

Contourne le bug SSL/certifi Windows du seed_doubs.py qui utilise `requests` :
tout passe par urllib (qui utilise le CA store système).

- Source : download/cadastre-napoleonien_doubs.json
- INSEE  : geo.api.gouv.fr (restreint dept 25, anti-homonyme)
- IIIF   : worker /static-manifest (jpg → manifeste v3)
- Cible  : /rest/v1/document (Supabase PostgREST, service_role)

Usage : python harvest/load_doubs_direct.py
"""
import os, re, json, sys, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(__file__)
SRC  = os.path.join(HERE, '..', 'download', 'cadastre-napoleonien_doubs.json')
GEO  = 'https://geo.api.gouv.fr/communes'
DEPT = '25'
WORKER = 'https://iiif-allmaps.sperrot.workers.dev'
UA = 'mapping-cadastre-napoleonien/0.5 (load_doubs_direct)'
BATCH = 500


def load_env():
    env = {}
    with open(os.path.join(HERE, '.env'), encoding='utf-8') as f:
        for l in f:
            l = l.strip()
            if '=' in l and not l.startswith('#'):
                k, v = l.split('=', 1); env[k] = v
    return env


def http_get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


_cache = {}
def resolve_insee(commune):
    key = commune.lower().strip()
    if key in _cache: return _cache[key]
    q = urllib.parse.urlencode({'nom': commune, 'codeDepartement': DEPT, 'fields': 'code', 'limit': 1})
    try:
        data = http_get_json(f'{GEO}?{q}')
        code = data[0]['code'] if data else None
    except Exception as e:
        code = None
        print(f'  ! {commune!r}: {e}', file=sys.stderr)
    _cache[key] = code
    time.sleep(0.1)
    return code


def iiif_manifest(jpg_url):
    return f'{WORKER}/static-manifest?u=' + urllib.parse.quote(jpg_url, safe='')


def parse_annee(s):
    m = re.search(r'(\d{4})', s or '')
    return int(m.group(1)) if m else None


def post_batch(env, batch):
    url = f'{env["SUPABASE_URL"]}/rest/v1/document'
    data = json.dumps(batch, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'apikey': env['SUPABASE_SERVICE_ROLE_KEY'],
        'Authorization': 'Bearer ' + env['SUPABASE_SERVICE_ROLE_KEY'],
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates,return=minimal',
    })
    try:
        r = urllib.request.urlopen(req, timeout=180)
        return r.status, ''
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:400]


def main():
    env = load_env()
    with open(SRC, encoding='utf-8') as f:
        records = json.load(f)
    print(f'{len(records)} enregistrements du JSON open data Doubs')

    rows = []
    seen_url = set()
    skip = 0
    for i, rec in enumerate(records):
        commune = (rec.get('unittitle') or '').strip()
        img_url = (rec.get('file_path') or '').strip()
        if not commune or not img_url:
            skip += 1; continue
        if img_url in seen_url:
            skip += 1; continue  # doublon d'archive_url
        seen_url.add(img_url)

        code = resolve_insee(commune)
        if not code:
            skip += 1; continue

        rows.append({
            'insee': code,
            'type':  'feuille',
            'annee': parse_annee(rec.get('unitdate', '')),
            'archive_url':  img_url,     # cf. discussion : archive_url = JPEG direct (unique)
            'image_url':    img_url,
            'iiif_manifest': iiif_manifest(img_url),
            'source':       'Archives départementales du Doubs',
            'source_url':   'https://archives.doubs.fr',
            'licence':      'Licence Ouverte',
            'licence_overlay_ok': True,
            'statut':       'georef',
        })
        if (i+1) % 500 == 0:
            print(f'  … résolus {len(rows)} / traités {i+1}')

    print(f'\nprêt à charger {len(rows)} lignes ({skip} ignorées)')

    ok = err = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i+BATCH]
        code, msg = post_batch(env, batch)
        if code < 300:
            ok += len(batch)
            print(f'  batch {i//BATCH+1:>3} : HTTP {code} · +{len(batch)} · cumul {ok}')
        else:
            err += len(batch)
            print(f'  batch {i//BATCH+1:>3} : HTTP {code} · ERR {msg}')
            if err > 100: raise SystemExit('trop d\'erreurs, arrêt')
    print(f'\n→ Doubs : {ok} chargés, {err} erreurs, {skip} ignorés')


if __name__ == '__main__':
    main()
