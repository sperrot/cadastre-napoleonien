#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renseigne en base l'état de géoréférencement réel (Allmaps) des plans.

Allmaps ne propose pas de requête groupée : l'état d'un plan se lit à
`https://annotations.allmaps.org/manifests/<id>`, où `<id>` est l'identifiant
Allmaps du manifeste — les 16 premiers caractères du SHA-1 hexadécimal de son
URL (équivalent de `@allmaps/id`, vérifié contre la lib JS).

Le résultat est stocké dans la colonne `document.georef` (jsonb, déjà présente
au schéma et jusque-là inutilisée) :
    {"url": "https://annotations.allmaps.org/manifests/<id>", "checked_at": "…"}
ou `null` si le plan n'est pas encore calé. Le front s'en sert pour le
compteur « % géoréférencé » des cartes département et la facette
« Géoréférencé ».

Idempotent : seules les lignes dont l'état change sont écrites. À relancer
périodiquement (le géoréférencement est collaboratif, il évolue).

Usage : python harvest/refresh_georef_status.py [--dry-run] [--dept 25]
"""
import os, sys, json, time, hashlib, argparse
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(__file__)
ANNOT = 'https://annotations.allmaps.org/manifests/'
WORKERS = 8


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


def allmaps_id(manifest_url: str) -> str:
    """Identifiant Allmaps = 16 premiers caractères du SHA-1 hex de l'URL."""
    return hashlib.sha1(manifest_url.encode('utf-8')).hexdigest()[:16]


def is_georeferenced(manifest_url: str):
    """→ URL d'annotation si le plan est calé dans Allmaps, sinon None."""
    url = ANNOT + allmaps_id(manifest_url)
    req = urllib.request.Request(url, headers={'User-Agent': 'mapping-cadastre-napoleonien'})
    for essai in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
                return url if (data.get('items') or []) else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None            # jamais géoréférencé
            if e.code in (429, 502, 503):
                time.sleep(1.5 * (essai + 1))
                continue
            return None
        except Exception:
            time.sleep(1.0 * (essai + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--dept', help='limiter à un département (ex. 25)')
    args = ap.parse_args()
    env = load_env()

    filtre = f'&insee=like.{args.dept}*' if args.dept else ''
    rows, off = [], 0
    while True:
        st, page = api(env, 'GET',
                       f'document?select=id,insee,iiif_manifest,georef'
                       f'&type=eq.tableau_assemblage&iiif_manifest=not.is.null{filtre}'
                       f'&order=id&limit=1000&offset={off}')
        if st >= 300:
            raise SystemExit(f'lecture: HTTP {st} {page}')
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    print(f'{len(rows)} tableaux d\'assemblage avec manifeste IIIF')
    if not rows:
        return

    # Interrogation Allmaps en parallèle (I/O bound)
    print(f'interrogation Allmaps ({WORKERS} en parallele)...')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        annots = list(ex.map(lambda r: is_georeferenced(r['iiif_manifest']), rows))
    cales = sum(1 for a in annots if a)
    print(f'  termine en {time.time()-t0:.0f}s : {cales} plan(s) cale(s) sur {len(rows)}')

    # Diff : n'écrire que ce qui change
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    updates = []
    for r, annot in zip(rows, annots):
        actuel = (r.get('georef') or {}).get('url') if isinstance(r.get('georef'), dict) else None
        if annot and actuel != annot:
            updates.append((r['id'], {'url': annot, 'checked_at': now}))
        elif not annot and r.get('georef') is not None:
            updates.append((r['id'], None))
    print(f'{len(updates)} ligne(s) a mettre a jour')
    if args.dry_run or not updates:
        for i, u in updates[:5]:
            print('  ex.', i, u)
        return

    ok = err = 0
    for doc_id, val in updates:
        st, msg = api(env, 'PATCH', f'document?id=eq.{doc_id}',
                      body={'georef': val}, prefer='return=minimal')
        if st < 300:
            ok += 1
        else:
            err += 1
            if err <= 3:
                print(f'  ERR {st}: {msg}')
    print(f'termine : {ok} mises a jour, {err} erreurs')

    # Récapitulatif par département
    st, res = api(env, 'GET',
                  'document?select=insee&type=eq.tableau_assemblage&georef=not.is.null&limit=10000')
    if st < 300:
        par_dept = {}
        for d in res:
            k = (d['insee'] or '??')[:2]
            par_dept[k] = par_dept.get(k, 0) + 1
        print('assemblages geo-references par departement :', par_dept or '(aucun)')


if __name__ == '__main__':
    main()
