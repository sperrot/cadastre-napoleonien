#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère harvest/seed_hte_garonne.sql depuis download/cadastre-napoleonien_hte_garonne.json.

L'INSEE n'est pas dans le JSON : résolution via geo.api.gouv.fr (appel réseau requis).
À lancer en local.

Champs source :
  date    : année
  analyse : description libre (contient section/cote parfois)
  commune : nom de la commune
  image   : {url, filename, width, height, ...}

Usage : python harvest/seed_hte_garonne.py [--out harvest/seed_hte_garonne.sql]
"""

import json
import os
import re
import time
import argparse
import requests

SRC  = os.path.join(os.path.dirname(__file__), '..', 'download', 'cadastre-napoleonien_hte_garonne.json')
GEO  = 'https://geo.api.gouv.fr/communes'
DEPT = '31'
SLEEP = 0.2

_cache = {}

def esc(s):
    return (s or '').replace("'", "''")

def resolve_insee(commune_name: str) -> str | None:
    """Résout le code INSEE depuis le nom de commune via geo.api.gouv.fr."""
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
        print(f'  ⚠ INSEE lookup failed for {commune_name!r}: {e}')
        code = None
    _cache[key] = code
    time.sleep(SLEEP)
    return code

def parse_annee(s: str) -> int | None:
    m = re.search(r'(\d{4})', s or '')
    return int(m.group(1)) if m else None

def parse_cote(analyse: str) -> str:
    """Extrait la cote (ex. '3 P 4425') depuis le champ analyse."""
    m = re.search(r'(\d+\s*[WP]\s*[\d\s/]+)', analyse or '')
    return m.group(1).strip() if m else ''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'seed_hte_garonne.sql'))
    args = parser.parse_args()

    with open(SRC, encoding='utf-8') as f:
        records = json.load(f)

    lines   = []
    ok = skip = 0
    seen_communes = {}

    for rec in records:
        commune = (rec.get('commune') or '').strip()
        if not commune:
            skip += 1
            continue

        if commune not in seen_communes:
            code = resolve_insee(commune)
            seen_communes[commune] = code
            if code:
                print(f'  ✓ {commune} → {code}')
            else:
                print(f'  ✗ {commune} → non trouvé')
        else:
            code = seen_communes[commune]

        if not code:
            skip += 1
            continue

        image   = rec.get('image') or {}
        img_url = image.get('url', '')
        if not img_url:
            skip += 1
            continue

        annee   = parse_annee(rec.get('date', ''))
        analyse = rec.get('analyse', '')
        cote    = esc(parse_cote(analyse))
        annee_sql = str(annee) if annee else 'null'

        lines.append(
            f"insert into document "
            f"(insee, type, annee, cote, archive_url, image_url, "
            f"source, source_url, licence, licence_overlay_ok, statut) values "
            f"('{code}', 'feuille', {annee_sql}, '{cote}', "
            f"'https://archives.haute-garonne.fr', '{esc(img_url)}', "
            f"'Archives de la Haute-Garonne (AD31)', 'https://archives.haute-garonne.fr', "
            f"'Réutilisation à vérifier (CD31)', false, 'lien');"
        )
        ok += 1

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(f'-- Haute-Garonne (31) — {ok} feuilles, {skip} ignorées\n\n')
        f.write('\n'.join(lines))
        f.write('\n')

    print(f'\n✓ {ok} inserts → {args.out}  ({skip} ignorés)')

if __name__ == '__main__':
    main()
