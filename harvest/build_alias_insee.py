#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complète harvest/communes_alias.json pour un département, depuis le COG INSEE.

Les inventaires d'archives nomment les communes telles qu'elles étaient au
XIXe siècle (« Aignes-et-Puypéroux », « Gourville »). geo.api.gouv.fr ne connaît
que les communes actuelles : ces libellés n'y résolvent pas. On reconstitue donc
la chaîne  libellé historique → code d'époque → ... → commune actuelle  à partir
des deux fichiers publics du COG :

  v_commune_depuis_1943.csv : tous les libellés de communes depuis 1943
  v_mvt_commune_<millesime>.csv : les mouvements (fusions, rétablissements)

Le suivi est transitif : une commune fusionnée dans une commune elle-même
fusionnée ensuite est rattachée au bout de la chaîne.

Usage : python harvest/build_alias_insee.py --dept 16 [--dry-run]
"""

import argparse
import csv
import io
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ALIAS_PATH = os.path.join(HERE, 'communes_alias.json')

BASE = 'https://www.insee.fr/fr/statistiques/fichier/8377162'
F_COMMUNES = f'{BASE}/v_commune_depuis_1943.csv'
F_MVT = f'{BASE}/v_mvt_commune_2025.csv'
# Communes actuelles (pour savoir où s'arrête la chaîne de succession)
F_ACTUELLES = 'https://unpkg.com/@etalab/decoupage-administratif/data/communes.json'


def telecharge(url, cache_dir):
    nom = url.rstrip('/').split('/')[-1]
    if not nom.endswith(('.csv', '.json')):
        nom += '.json'
    chemin = os.path.join(cache_dir, nom)
    if os.path.exists(chemin) and os.path.getsize(chemin) > 1000:
        return chemin
    print(f'  téléchargement {nom}...')
    req = urllib.request.Request(url, headers={'User-Agent': 'mapping-cadastre-napoleonien'})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    with open(chemin, 'wb') as f:
        f.write(data)
    return chemin


def lit_csv(chemin):
    with io.open(chemin, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dept', required=True, help='code département, ex. 16')
    ap.add_argument('--cache', default=os.path.join(HERE, '_cog'),
                    help='dossier de cache des fichiers COG')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    dept = args.dept
    os.makedirs(args.cache, exist_ok=True)

    print('COG INSEE :')
    communes = lit_csv(telecharge(F_COMMUNES, args.cache))
    mvts = lit_csv(telecharge(F_MVT, args.cache))
    with io.open(telecharge(F_ACTUELLES, args.cache), encoding='utf-8') as f:
        etalab = json.load(f)
    actuelles = {x['code'] for x in etalab if x.get('type') == 'commune-actuelle'}
    noms_actuels = {x['code']: x['nom'] for x in etalab
                    if x.get('type') == 'commune-actuelle'}
    print(f'  {len(communes)} enregistrements de communes, {len(mvts)} mouvements, '
          f'{len(actuelles)} communes actuelles')

    # 1) successeurs : code avant -> {codes après}. Un ENSEMBLE, pas un scalaire :
    #    71 communes du COG ont été SCINDÉES entre plusieurs communes (25015 est
    #    partagée entre Amondans, Cléron, Fertans et Malans). Écraser succ[av]
    #    reviendrait à en désigner une au hasard, silencieusement.
    succ = {}
    for m in mvts:
        av, ap = m.get('COM_AV'), m.get('COM_AP')
        if not av or not ap or av == ap:
            continue
        if m.get('TYPECOM_AV') != 'COM' or m.get('TYPECOM_AP') != 'COM':
            continue
        succ.setdefault(av, set()).add(ap)

    def resout(code):
        """Suit la chaîne de succession jusqu'à une commune actuelle.

        Renvoie None dès qu'un maillon est scindé : mieux vaut un libellé non
        rattaché, visible dans le rapport, qu'un rattachement arbitraire.
        """
        vus = set()
        while code and code not in actuelles and code not in vus:
            vus.add(code)
            cibles = succ.get(code)
            if not cibles or len(cibles) > 1:
                return None
            code = next(iter(cibles))
        return code if code in actuelles else None

    # 2) libellés historiques du département -> code d'époque
    #    (on garde aussi les libellés de communes actuelles : sans effet, mais
    #     ils rendent la table auto-portante)
    par_nom = {}
    for c in communes:
        if c.get('TYPECOM') != 'COM':
            continue
        code = c.get('COM') or ''
        if not code.startswith(dept):
            continue
        for cle in ('LIBELLE', 'NCCENR'):
            nom = (c.get(cle) or '').strip()
            if nom:
                par_nom.setdefault(nom, set()).add(code)

    # 3) résolution
    table, ambigus, perdus = {}, [], []
    for nom, codes in sorted(par_nom.items()):
        cibles = {resout(c) for c in codes}
        cibles.discard(None)
        if len(cibles) == 1:
            cible = cibles.pop()
            # inutile de lister une commune actuelle sous son propre nom :
            # geo.api la résout déjà.
            if noms_actuels.get(cible) != nom:
                table[nom] = cible
        elif len(cibles) > 1:
            ambigus.append((nom, sorted(cibles)))
        else:
            perdus.append(nom)

    print(f'\ndépartement {dept} :')
    print(f'  {len(table)} libellés historiques rattachés à une commune actuelle')
    if ambigus:
        print(f'  {len(ambigus)} ambigus (plusieurs cibles) — ignorés :')
        for nom, c in ambigus[:10]:
            print(f'    {nom} -> {c}')
    if perdus:
        print(f'  {len(perdus)} sans successeur actuel — ignorés : '
              + ', '.join(perdus[:10]))

    exemples = [(n, c) for n, c in table.items()][:12]
    print('  exemples :')
    for n, c in exemples:
        print(f'    {n:34s} -> {c} ({noms_actuels.get(c)})')

    if args.dry_run:
        print('\n--dry-run : communes_alias.json non modifié')
        return

    # 4) fusion dans communes_alias.json (les entrées existantes font foi :
    #    elles ont pu être corrigées à la main)
    with io.open(ALIAS_PATH, encoding='utf-8') as f:
        alias = json.load(f)
    avant = dict(alias.get(dept) or {})
    fusion = dict(table)
    fusion.update(avant)                      # priorité au manuel
    alias[dept] = dict(sorted(fusion.items()))
    with io.open(ALIAS_PATH, 'w', encoding='utf-8') as f:
        json.dump(alias, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'\ncommunes_alias.json : département {dept} = {len(alias[dept])} entrées '
          f'({len(avant)} déjà présentes, conservées)')


if __name__ == '__main__':
    main()
