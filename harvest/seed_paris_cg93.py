#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère harvest/seed_paris_cg93.sql depuis le SHP assembage CG93 (ouest Paris).

Source :  fr-229200506-cadastre-napoleonien-assemblage-departemental (data.gouv.fr?)
Géométries : rectangles WGS84 = emprises des tuiles 1km x 1km
Fichiers    : ZIPs contenant JPG géoréférencés (avec worldfile)

Colonnes remplies :
  bbox        : Polygon WGS84 (emprise directe du scan)
  archive_url : URL de téléchargement du ZIP via portail open data
  statut      : 'bbox' (l'emprise = géoréférencement réel, pas approx.)
  type        : 'feuille' (dalle = 1 scan)
  insee       : à remplir manuellement ou via jointure spatiale avec les
                communes (le SHP couvre Seine-Saint-Denis + Hauts-de-Seine)
  licence_overlay_ok : true (open data CG93)

Usage : python harvest/seed_paris_cg93.py
"""

import struct
import re
import os

SHP_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'download',
    'fr-229200506-cadastre-napoleonien-assemblage-departemental',
)
BASE = os.path.join(SHP_DIR, 'fr-229200506-cadastre-napoleonien-assemblage-departemental')
OUT  = os.path.join(os.path.dirname(__file__), 'seed_paris_cg93.sql')

# Portail OpenDataSoft de l'éditeur — à confirmer avec l'URL réelle
# Hypothèse : les ZIPs sont accessibles via une URL de type ODS
ODS_PORTAL = 'https://opendata.seine-saint-denis.fr/api/explore/v2.1/catalog/datasets/cadastre-napoleonien/files'


def read_dbf():
    path = BASE + '.dbf'
    with open(path, 'rb') as f:
        raw = f.read()

    num_records = struct.unpack('<I', raw[4:8])[0]
    header_size = struct.unpack('<H', raw[8:10])[0]

    fields = []
    offset = 32
    while raw[offset] != 0x0D:
        fh = raw[offset:offset+32]
        name = fh[:11].split(b'\x00')[0].decode('latin-1')
        ftype = chr(fh[11])
        flen = fh[16]
        fields.append((name, ftype, flen))
        offset += 32
    rec_size = sum(f[2] for f in fields) + 1

    records = []
    ptr = header_size
    for _ in range(num_records):
        rec = raw[ptr:ptr+rec_size]
        ptr += rec_size
        off = 1
        d = {}
        for name, _, flen in fields:
            d[name] = rec[off:off+flen].decode('latin-1').strip()
            off += flen
        records.append(d)
    return records


def read_shp_bboxes():
    path = BASE + '.shp'
    with open(path, 'rb') as f:
        raw = f.read()
    bboxes = []
    ptr = 100  # skip file header
    while ptr < len(raw):
        if ptr + 8 > len(raw):
            break
        content_len = struct.unpack('>I', raw[ptr+4:ptr+8])[0] * 2
        ptr += 8
        if ptr + content_len > len(raw):
            break
        shape_type = struct.unpack('<I', raw[ptr:ptr+4])[0]
        if shape_type == 5:  # Polygon
            xmin, ymin, xmax, ymax = struct.unpack('<4d', raw[ptr+4:ptr+36])
            bboxes.append((xmin, ymin, xmax, ymax))
        elif shape_type == 0:  # Null shape
            bboxes.append(None)
        ptr += content_len
    return bboxes


def wgs84_rect_wkt(xmin, ymin, xmax, ymax):
    return (
        f"ST_GeomFromText('POLYGON(("
        f"{xmin} {ymin},{xmax} {ymin},{xmax} {ymax},{xmin} {ymax},{xmin} {ymin}"
        f"))', 4326)"
    )


def main():
    records = read_dbf()
    bboxes  = read_shp_bboxes()

    assert len(records) == len(bboxes), f"{len(records)} records vs {len(bboxes)} shapes"

    lines = []
    ok = skip = 0

    for rec, bbox in zip(records, bboxes):
        if bbox is None:
            skip += 1
            continue

        dalle    = rec.get('dalle', '')
        fichier  = rec.get('fichier', '')
        m        = re.search(r"'id':\s*'([a-f0-9]+)'", fichier)
        file_id  = m.group(1) if m else None

        archive_url = f'{ODS_PORTAL}/{file_id}' if file_id else f'https://[PORTAIL]/files/{dalle}'
        bbox_sql    = wgs84_rect_wkt(*bbox)

        lines.append(
            f"insert into document "
            f"(insee, type, archive_url, bbox, "
            f"source, source_url, licence, licence_overlay_ok, statut) values "
            f"(NULL, 'feuille', '{archive_url}', {bbox_sql}, "
            f"'Conseil Général 93 (CG93)', 'https://opendata.seine-saint-denis.fr', "
            f"'Licence Ouverte', true, 'bbox');  -- {dalle}"
        )
        ok += 1

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(f'-- Paris CG93 — {ok} dalles georef (emprises WGS84 exactes), {skip} ignorees\n')
        f.write('-- INSEE = NULL : a remplir via jointure spatiale ST_Within(centroid, commune.geom)\n')
        f.write('-- archive_url = URL ZIP open data (contient JPG + worldfile)\n\n')
        f.write('\n'.join(lines))
        f.write('\n')

    print(f'OK {ok} inserts -> {OUT}')


if __name__ == '__main__':
    main()
