#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hauts-de-Seine (92) — catalogue des feuilles de section géoréférencées.

Source : opendata.hauts-de-seine.fr (Opendatasoft), jeu
`fr-229200506-cadastre-napoleonien-feuilles-de-sections` — 896 feuilles,
35 communes. Particularités vérifiées le 2026-07-21 :

- le jeu porte **directement `code_insee`** → aucune résolution geo.api ;
- chaque feuille a deux fichiers : le JPG source et la version géoréférencée
  suffixée `_cale`, **servie en ZIP** (JPEG + JGW) donc non affichable ;
- le champ `..._telecharge` pointe vers un FTP qui renvoie 404 : la bonne URL
  est celle de l'objet fichier ODS (`fichier.url`), vérifiée en HTTP 200.

Choix d'ingestion (décidé avec l'utilisateur) : on ne retient que les feuilles
disposant d'une version `_cale`. `archive_url` pointe sur cette version
géoréférencée (ce que l'utilisateur télécharge), `image_url` sur le JPG source
(vignette). **Pas de `iiif_manifest`** → aucun bouton « Géoréférencer », les
plans étant déjà calés à la source.

Usage : python harvest/load_hautsdeseine_direct.py [--dry-run]
"""
import os, re, sys, json, argparse, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(__file__)
ODS = ("https://opendata.hauts-de-seine.fr/api/explore/v2.1/catalog/datasets/"
       "fr-229200506-cadastre-napoleonien-feuilles-de-sections/records")
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


def fetch_records():
    """Pagine l'API ODS (limite 100 par appel)."""
    out, offset = [], 0
    while True:
        u = f"{ODS}?limit=100&offset={offset}"
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            d = json.loads(r.read())
        res = d.get('results', [])
        out += res
        total = d.get('total_count', 0)
        offset += len(res)
        if not res or offset >= total:
            break
    return out


def annee(date_str):
    """« 1843-1859 » ou « 1808-1809 » → 1843 / 1808 ; « s.d » → None."""
    m = re.search(r'(1[6-9]\d{2})', date_str or '')
    return int(m.group(1)) if m else None


def fichier_url(champ):
    """L'objet fichier ODS porte une URL directe et exploitable."""
    return champ.get('url') if isinstance(champ, dict) else None


def post_batch(env, rows):
    url = f"{env['SUPABASE_URL']}/rest/v1/document"
    data = json.dumps(rows, ensure_ascii=False).encode('utf-8')
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
        return e.code, e.read().decode('utf-8', 'replace')[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    env = load_env()

    recs = fetch_records()
    print(f"{len(recs)} feuilles recuperees depuis Opendatasoft")

    rows, sans_cale, sans_insee = [], 0, 0
    for rec in recs:
        cale = fichier_url(rec.get('nom_fichier_georef_homogeneise'))
        if not cale:
            sans_cale += 1
            continue                      # on ne retient que les georeferencees
        insee = (rec.get('code_insee') or '').strip()
        if not re.fullmatch(r'\d{5}', insee):
            sans_insee += 1
            continue
        src = fichier_url(rec.get('nom_fichier_source_homogeneise'))
        num = rec.get('num_feuille')
        rows.append({
            'insee': insee,
            'type': 'section',
            'section_lettre': (rec.get('code_section') or None),
            'feuille_num': int(num) if str(num or '').isdigit() else None,
            'annee': annee(rec.get('date')),
            'cote': rec.get('cote') or None,
            'archive_url': cale,          # version georeferencee (ZIP JPEG+JGW)
            'image_url': src,             # JPG source, sert de vignette
            'source': 'Archives des Hauts-de-Seine (AD92)',
            'source_url': 'https://opendata.hauts-de-seine.fr',
            'licence': 'Licence Ouverte',
            'licence_overlay_ok': True,
            'statut': 'georef',           # deja cale a la source
        })

    communes = sorted({r['insee'] for r in rows})
    print(f"a charger : {len(rows)} feuilles sur {len(communes)} communes "
          f"({sans_cale} sans version _cale, {sans_insee} sans INSEE valide)")
    if args.dry_run:
        for r in rows[:3]:
            print('  ex.', json.dumps(r, ensure_ascii=False)[:190])
        return

    ok = err = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        code, msg = post_batch(env, chunk)
        if code < 300:
            ok += len(chunk)
            print(f"  batch {i // BATCH + 1} : HTTP {code} · +{len(chunk)} · cumul {ok}")
        else:
            err += len(chunk)
            print(f"  batch {i // BATCH + 1} : HTTP {code} · ERR {msg}")
    print(f"termine : {ok} charges, {err} erreurs")


if __name__ == '__main__':
    main()
