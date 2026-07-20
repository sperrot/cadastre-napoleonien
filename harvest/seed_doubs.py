#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère harvest/seed_doubs.sql depuis download/cadastre-napoleonien_doubs.json.

Remplace l'ancienne approche (portail scrapé → seed_doubs.sql 548 liens ARK +
update_doubs.sql) : on part du JSON open data (5700 feuilles JPEG directes) et
on branche le chemin JPEG → IIIF → Allmaps via le worker (route /static-manifest).

Le JSON ne porte pas l'INSEE : résolution via geo.api.gouv.fr **restreinte au
département 25** (codeDepartement) pour éviter les homonymes hors département.
À lancer en local (réseau requis).

Champs source : unitdate (année), unittitle (commune), scopecontent (note),
                file_path (URL JPEG download.doubs.fr).

Usage : python harvest/seed_doubs.py
"""

import json
import os
import re
import time
import urllib.parse
import argparse
import requests

SRC  = os.path.join(os.path.dirname(__file__), '..', 'download', 'cadastre-napoleonien_doubs.json')
GEO  = 'https://geo.api.gouv.fr/communes'
DEPT = '25'
SLEEP = 0.2

# Route worker JPEG → manifeste IIIF (identique à Saône-et-Loire ; cf. worker.js).
WORKER = 'https://iiif-allmaps.sperrot.workers.dev'

_cache = {}


def esc(s):
    return (s or '').replace("'", "''")


def iiif_manifest(jpg_url):
    return f"{WORKER}/static-manifest?u={urllib.parse.quote(jpg_url, safe='')}"


def resolve_insee(commune_name: str):
    """INSEE depuis le nom, RESTREINT au département 25 (anti-homonyme)."""
    key = commune_name.lower().strip()
    if key in _cache:
        return _cache[key]
    try:
        r = requests.get(GEO, params={
            'nom': commune_name,
            'codeDepartement': DEPT,   # ← ne cherche que dans le Doubs
            'fields': 'code',
            'limit': 1,
        }, timeout=10)
        r.raise_for_status()
        data = r.json()
        code = data[0]['code'] if data else None
    except Exception as e:
        print(f'  ! {commune_name!r}: {e}')
        code = None
    _cache[key] = code
    time.sleep(SLEEP)
    return code


def parse_annee(s: str):
    m = re.search(r'(\d{4})', s or '')
    return int(m.group(1)) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'seed_doubs.sql'))
    args = parser.parse_args()

    with open(SRC, encoding='utf-8') as f:
        records = json.load(f)

    print(f'{len(records)} enregistrements a traiter...')

    seen = {}
    lines = []
    ok = skip = 0

    for rec in records:
        commune = (rec.get('unittitle') or '').strip()
        img_url = (rec.get('file_path') or '').strip()
        if not commune or not img_url:
            skip += 1
            continue

        if commune not in seen:
            code = resolve_insee(commune)
            seen[commune] = code
            print(('  ok ' if code else '  -- ') + f'{commune} -> {code or "non trouve"}')
        else:
            code = seen[commune]

        if not code:
            skip += 1
            continue

        annee = parse_annee(rec.get('unitdate', ''))
        annee_sql = str(annee) if annee else 'null'
        manifest  = iiif_manifest(img_url)

        # archive_url = recherche par commune sur le portail (pas d'ARK par image
        # dans le JSON), cohérent avec l'ancien update_doubs.sql.
        commune_enc = urllib.parse.quote(commune)
        archive_url = (
            f'https://archives.doubs.fr/search/results'
            f'?target=controlledAccessGeographicName&keyword={commune_enc}'
        )

        lines.append(
            f"insert into document "
            f"(insee, type, annee, archive_url, image_url, iiif_manifest, "
            f"source, source_url, licence, licence_overlay_ok, statut) values "
            f"('{code}', 'feuille', {annee_sql}, '{esc(archive_url)}', '{esc(img_url)}', "
            f"'{esc(manifest)}', "
            f"'Archives départementales du Doubs', 'https://archives.doubs.fr', "
            f"'Licence Ouverte', true, 'georef');"
        )
        ok += 1

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(f'-- Doubs (25) — {ok} feuilles JPEG open data -> IIIF (worker) -> Allmaps\n')
        f.write(f'-- Genere depuis download/cadastre-napoleonien_doubs.json ({skip} ignores)\n')
        f.write('-- Remplace l ancien seed_doubs.sql (ARK) + update_doubs.sql\n\n')
        f.write('\n'.join(lines))
        f.write('\n')

    print(f'\nOK {ok} inserts -> {args.out}  ({skip} ignores)')


if __name__ == '__main__':
    main()
