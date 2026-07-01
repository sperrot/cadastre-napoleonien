#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère harvest/seed_saone_et_loire.sql depuis download/71-cadastre.csv.
INSEE calculé directement : '71' + str(int(col_insee)).zfill(3)
Usage : python harvest/seed_saone_et_loire.py
"""

import csv
import os
import re
import urllib.parse

SRC = os.path.join(os.path.dirname(__file__), '..', 'download', '71-cadastre.csv')
OUT = os.path.join(os.path.dirname(__file__), 'seed_saone_et_loire.sql')

# Route worker JPEG → manifeste IIIF Presentation (générée à la volée).
# Même endpoint pour tous les JPEG open data (71, Bretagne, Doubs…).
WORKER = 'https://iiif-allmaps.sperrot.workers.dev'

def iiif_manifest(jpg_url):
    """URL du manifeste IIIF servi par le worker pour ce JPEG."""
    return f"{WORKER}/static-manifest?u={urllib.parse.quote(jpg_url, safe='')}"

TYPE_MAP = {
    'PARCELLAIRE':              'feuille',
    'GEOMETRIQUE PARCELLAIRE':  'feuille',
    "TABLEAU D'ASSEMBLAGE":     'tableau_assemblage',
    "TABLEAUD'ASSEMBLAGE":      'tableau_assemblage',
    'MASSE DE CULTURE':         'feuille',
}

def esc(s):
    return s.replace("'", "''") if s else ''

def parse_annee(s):
    s = s.strip()
    m = re.search(r'(\d{4})', s)
    return int(m.group(1)) if m else 'null'

def parse_section(s):
    # "A1", "C2", etc. → lettre seule
    s = s.strip()
    if s and s[0].isalpha():
        return s[0].upper()
    return None

def main():
    rows_ok = 0
    rows_skip = 0
    lines = []

    with open(SRC, encoding='latin-1') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            # Nettoyage des clés (espaces parasites dans l'en-tête)
            row = {k.strip(): v.strip() for k, v in row.items()}

            insee_raw = row.get('INSEE', '')
            if not insee_raw.isdigit():
                rows_skip += 1
                continue

            image_url = row.get('Lien vers image Open Data', '')
            if not image_url:
                rows_skip += 1
                continue

            cartes = row.get('Cartes', '').strip()
            doc_type = TYPE_MAP.get(cartes)
            if doc_type is None:
                rows_skip += 1
                continue

            insee = '71' + str(int(insee_raw)).zfill(3)
            annee = parse_annee(row.get('Date', ''))
            cote  = esc(row.get('Cotes', ''))
            section = parse_section(row.get('N section', '') or row.get('N° section', '') or row.get('N\xa0section', ''))

            archive_url = row.get('Lien ark vers Image AD71', '') or image_url
            manifest    = iiif_manifest(image_url)   # JPEG opendata → worker IIIF

            section_sql = f"'{section}'" if section else 'null'
            annee_sql   = str(annee) if annee != 'null' else 'null'

            lines.append(
                f"insert into document "
                f"(insee, type, section_lettre, annee, cote, archive_url, image_url, "
                f"iiif_manifest, source, source_url, licence, licence_overlay_ok, statut) values "
                f"('{insee}', '{doc_type}', {section_sql}, {annee_sql}, "
                f"'{cote}', '{esc(archive_url)}', '{esc(image_url)}', "
                f"'{esc(manifest)}', "
                f"'Archives de Saône-et-Loire (AD71)', 'https://www.archives71.fr', "
                f"'Licence Ouverte', true, 'georef');"
            )
            rows_ok += 1

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(f'-- Saône-et-Loire (71) — {rows_ok} feuilles, {rows_skip} lignes ignorées\n\n')
        f.write('\n'.join(lines))
        f.write('\n')

    print(f'OK {rows_ok} inserts -> {OUT}  ({rows_skip} ignores)')

if __name__ == '__main__':
    main()
