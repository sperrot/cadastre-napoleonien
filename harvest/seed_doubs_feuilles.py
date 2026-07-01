#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère harvest/seed_doubs_feuilles.sql depuis download/cadastre-napoleonien_doubs.json.
Ajoute les feuilles individuelles (JPG direct) au-delà des 548 ARK déjà dans seed_doubs.sql.

L'INSEE n'est pas dans le JSON : résolution via geo.api.gouv.fr.
À lancer en local (TLS et réseau requis).

Usage : python harvest/seed_doubs_feuilles.py
"""

import json
import os
import re
import time
import argparse
import requests

SRC  = os.path.join(os.path.dirname(__file__), '..', 'download', 'cadastre-napoleonien_doubs.json')
GEO  = 'https://geo.api.gouv.fr/communes'
DEPT = '25'
SLEEP = 0.2

_cache = {}

def esc(s):
    return (s or '').replace("'", "''")

def resolve_insee(commune_name: str) -> str | None:
    key = commune_name.lower().strip()
    if key in _cache:
        return _cache[key]
    try:
        r = requests.get(GEO, params={
            'nom': commune_name,
            'codeDepartement': DEPT,
            'fields': 'code',
            'limit': 1,
        }, timeout=10)
        r.raise_for_status()
        data = r.json()
        code = data[0]['code'] if data else None
    except Exception as e:
        print(f'  ⚠ {commune_name!r}: {e}')
        code = None
    _cache[key] = code
    time.sleep(SLEEP)
    return code

def parse_annee(s: str) -> int | None:
    m = re.search(r'(\d{4})', s or '')
    return int(m.group(1)) if m else None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'seed_doubs_feuilles.sql'))
    args = parser.parse_args()

    with open(SRC, encoding='utf-8') as f:
        records = json.load(f)

    print(f'{len(records)} enregistrements à traiter…')

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
            status = '✓' if code else '✗'
            print(f'  {status} {commune} → {code or "non trouvé"}')
        else:
            code = seen[commune]

        if not code:
            skip += 1
            continue

        annee = parse_annee(rec.get('unitdate', ''))
        scope = esc(rec.get('scopecontent') or '')
        annee_sql = str(annee) if annee else 'null'

        # archive_url = portal de recherche par commune (comme dans update_doubs.sql)
        commune_enc = requests.utils.quote(commune)
        archive_url = (
            f'https://archives.doubs.fr/search/results'
            f'?target=controlledAccessGeographicName&keyword={commune_enc}'
        )

        lines.append(
            f"insert into document "
            f"(insee, type, annee, archive_url, image_url, "
            f"source, source_url, licence, licence_overlay_ok, statut) values "
            f"('{code}', 'feuille', {annee_sql}, '{esc(archive_url)}', '{esc(img_url)}', "
            f"'Archives départementales du Doubs', 'https://archives.doubs.fr', "
            f"'Réutilisation OK (open data CD25)', false, 'lien');"
        )
        ok += 1

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(f'-- Doubs (25) feuilles open data — {ok} images JPG, {skip} ignorées\n')
        f.write('-- Complète seed_doubs.sql (ARK liens) avec les images directes\n\n')
        f.write('\n'.join(lines))
        f.write('\n')

    print(f'\n✓ {ok} inserts → {args.out}  ({skip} ignorés)')

if __name__ == '__main__':
    main()
