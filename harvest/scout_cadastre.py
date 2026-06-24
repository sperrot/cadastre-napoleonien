#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scout cadastre — étage AMONT du pipeline (avant `harvest_francearchives.py`).

Rôle :
    1. Descend l'arbre RDF FranceArchives d'un fonds (findingaid ou facomponent),
       en réutilisant le **contournement anti-robot** déjà présent dans
       `harvest_francearchives.py` (session + défi JS + cookie).
    2. Isole, pour CHAQUE commune, la branche « Plans du cadastre napoléonien ».
       Son libellé varie selon les départements (« Plans cadastraux »,
       « Plans du cadastre », « Atlas cadastral », « Cadastre napoléonien »…) :
       détection par mots-clés + repli sur la présence de feuilles-plans (IIIF).
    3. Vérifie la **licence** et la **dispo IIIF** sur un échantillon de feuilles
       (la licence est par institution → un échantillon suffit à trancher).
    4. Émet les **bons arguments pour le harvester** : une ligne de commande par
       branche isolée (mode `facomponent`), + un récap markdown pour le tableau
       de synthèse. Avec `--run`, exécute directement le harvester et concatène
       le SQL produit dans un seul fichier seed.

PIPELINE :
    scout_cadastre.py  ──(descend + vérifie licence/IIIF)──▶  arguments
                                                              │
                                          harvest_francearchives.py  ──▶  seed_*.sql

⚠️  À LANCER EN LOCAL (comme le harvester ; FranceArchives bloque les fetchs serveur).

Dépendances :  pip install requests rdflib   (mêmes que le harvester)

Usage :
    # Reconnaissance seule (n'exécute pas le harvester) :
    python scout_cadastre.py d17231b4a0689ac142534b2a6ee4fc0c190338a1 findingaid

    # Limiter le balayage (test rapide) :
    python scout_cadastre.py 8c9077ce3826a2676417514c55903ae704aff91b facomponent --limit 3

    # Reconnaissance + lancement du harvester sur chaque branche isolée :
    python scout_cadastre.py d17231b4a0689ac142534b2a6ee4fc0c190338a1 findingaid \
        --run --out seed_calvados_A-D.sql --year-min 1800 --year-max 1860
"""

import sys
import re
import argparse
import subprocess
from pathlib import Path

from rdflib import URIRef

# ── Réutilisation du harvester (contournement robot + helpers RDF) ───────────
# Import : harvest_francearchives n'exécute rien à l'import (main() est gardé
# par `if __name__ == "__main__"`). On récupère sa session anti-robot.
from harvest_francearchives import (
    BASE, RICO, RDFS,
    fetch_graph, eid_of, leaf_manifest, resolve_licence, classify,
)

HARVESTER = Path(__file__).with_name("harvest_francearchives.py")

# ── Détection de la branche « Plans du cadastre napoléonien » ────────────────
# Libellés rencontrés (variables selon départements) : « Plans cadastraux »,
# « Plans du cadastre », « Atlas cadastral », « Cadastre napoléonien »,
# « Tableau d'assemblage », « Section A »…
PLANS_POS = re.compile(
    r"plan|atlas|cadastr|tableau\s+d['e ]assemblage|assemblage|\bsection\b",
    re.I,
)
# À EXCLURE : documents textuels du cadastre (pas des plans) et cadastre moderne.
PLANS_NEG = re.compile(
    r"matric|mutation|état\s+de\s+section|etat\s+de\s+section|registre|"
    r"répertoire|repertoire|\btable\b|classement|arpentage|proc[èe]s|"
    r"délimitation|delimitation|r[ée]nov|remembr",
    re.I,
)

def is_plans_title(t: str) -> bool:
    t = t or ""
    return bool(PLANS_POS.search(t)) and not PLANS_NEG.search(t)


# ── Helpers RDF locaux ───────────────────────────────────────────────────────
def node(etype: str, eid: str):
    """Retourne (graph, subj, title, children_eids, manifest) d'un nœud."""
    g = fetch_graph(etype, eid)
    subj = URIRef(f"{BASE}/{etype}/{eid}")
    title = next((str(o) for o in g.objects(subj, RICO.title)), None) \
        or next((str(o) for o in g.objects(subj, RDFS.label)), None)
    children = [eid_of(str(o)) for o in g.objects(subj, RICO.includesOrIncluded)]
    manifest = leaf_manifest(g, subj)
    return g, subj, (title or ""), children, manifest


def root_service(etype: str, eid: str):
    """Institution gestionnaire (URI service/NNNN) à la racine de l'arbre."""
    g, subj, *_ = node(etype, eid)
    for o in g.objects(subj, RICO.hasOrHadManager):
        return str(o)
    for o in g.objects(subj, RICO.hasOrHadHolder):
        return str(o)
    return None


def peek_manifest(etype: str, eid: str, budget: list):
    """DFS court : 1er manifeste IIIF rencontré sous ce nœud (pour licence/IIIF)."""
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        _, _, _, children, manifest = node(etype, eid)
    except RuntimeError:
        return None
    if manifest and not children:
        return manifest
    if manifest:                 # certains nœuds portent déjà le manifeste
        return manifest
    for c in children:
        m = peek_manifest("facomponent", c, budget)
        if m:
            return m
    return None


# ── Descente : isole les branches « plans cadastre » par commune ─────────────
def scout(etype: str, eid: str, limit: int = 0, max_depth: int = 8):
    """
    Renvoie une liste de branches isolées :
        {commune, branch_title, branch_eid, branch_etype, licence,
         overlay_ok, iiif, manifest_sample}
    """
    service = root_service(etype, eid)
    targets, seen = [], set()
    _licence_done = {"v": None}     # cache licence (1 lecture suffit / institution)

    def record(branch_etype, branch_eid, branch_title, commune):
        if any(t["branch_eid"] == branch_eid for t in targets):
            return
        # Échantillon licence/IIIF : 1ʳᵉ feuille à manifeste sous la branche.
        manifest = peek_manifest(branch_etype, branch_eid, budget=[60])
        iiif = bool(manifest)
        if manifest and _licence_done["v"] is None:
            _licence_done["v"] = resolve_licence(service, manifest)
        licence, overlay_ok = _licence_done["v"] or ("À vérifier", False)
        targets.append({
            "commune": commune or branch_title,
            "branch_title": branch_title,
            "branch_eid": branch_eid,
            "branch_etype": branch_etype,
            "licence": licence if iiif else "À vérifier",
            "overlay_ok": overlay_ok and iiif,
            "iiif": iiif,
            "manifest_sample": manifest,
        })
        sys.stderr.write(
            f"  ✓ {commune or '?':30.30} | {branch_title[:40]:40.40} "
            f"| IIIF={'oui' if iiif else 'non '} | {licence} | {branch_eid}\n"
        )

    def walk(etype, eid, parent_title, depth):
        if eid in seen or depth > max_depth:
            return
        if limit and len(targets) >= limit:
            return
        seen.add(eid)
        try:
            g, subj, title, children, manifest = node(etype, eid)
        except RuntimeError as e:
            sys.stderr.write(f"  ! {e}\n")
            return

        # (1) Nœud nommé « plans/cadastre » avec des enfants → branche isolée.
        if children and is_plans_title(title):
            record(etype, eid, title, commune=parent_title)
            return                       # on ne descend pas : le harvester le fera

        # (2) Nœud dont les enfants directs sont des feuilles-plans (IIIF) :
        #     le nœud lui-même = branche plans de la commune (libellé absent).
        if children:
            for c in children:
                if limit and len(targets) >= limit:
                    return
                try:
                    _, _, c_title, c_children, c_manifest = node("facomponent", c)
                except RuntimeError:
                    continue
                if c_manifest and not c_children and is_plans_title(c_title):
                    record(etype, eid, title or parent_title or c_title,
                           commune=parent_title or title)
                    return
                if not c_children:        # feuille non-plan → on ignore
                    continue
                # (3) sinon : sous-branche → on continue la descente.
                walk("facomponent", c, parent_title=title or parent_title,
                     depth=depth + 1)
        return

    sys.stderr.write(f"Descente de {etype}/{eid} (service {service}) …\n")
    walk(etype, eid, parent_title=None, depth=0)
    sys.stderr.write(f"\n{len(targets)} branche(s) « plans cadastre » isolée(s).\n")
    return service, targets


# ── Sorties : arguments harvester + récap markdown ───────────────────────────
def harvester_cmd(t, year_min, year_max):
    return (f"python harvest_francearchives.py {t['branch_eid']} "
            f"{t['branch_etype']} --year-min {year_min} --year-max {year_max}")


def emit_plan(service, targets, year_min, year_max):
    print("## Arguments harvester (branches isolées)\n")
    for t in targets:
        print(harvester_cmd(t, year_min, year_max))
    print("\n## Récap (pour le tableau de synthèse)\n")
    print("| Commune | Branche | Licence | IIIF | eid |")
    print("|---|---|---|---|---|")
    for t in targets:
        print(f"| {t['commune']} | {t['branch_title']} | "
              f"{'✅ '+t['licence'] if t['overlay_ok'] else '⚠️ '+t['licence']} | "
              f"{'✅' if t['iiif'] else '❌'} | `{t['branch_eid']}` |")


def run_harvester(targets, out_path, year_min, year_max):
    """Exécute le harvester sur chaque branche et concatène le SQL dans out_path."""
    out = Path(out_path)
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"-- seed cadastre — {len(targets)} branche(s) — "
                 f"période {year_min}-{year_max}\n")
        for i, t in enumerate(targets, 1):
            sys.stderr.write(f"[{i}/{len(targets)}] harvester ← "
                             f"{t['commune']} ({t['branch_eid']}) …\n")
            cmd = [sys.executable, str(HARVESTER), t["branch_eid"],
                   t["branch_etype"], "--year-min", str(year_min),
                   "--year-max", str(year_max)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               cwd=str(HARVESTER.parent))
            fh.write(f"\n-- ── {t['commune']} / {t['branch_title']} "
                     f"({t['branch_eid']}) ──\n")
            fh.write(r.stdout)
            if r.returncode != 0:
                sys.stderr.write(r.stderr)
    sys.stderr.write(f"\nSeed écrit : {out}\n")


def main():
    ap = argparse.ArgumentParser(
        description="Scout cadastre — isole les branches « plans » et arme le harvester")
    ap.add_argument("eid", help="identifiant racine (findingaid ou facomponent)")
    ap.add_argument("etype", nargs="?", default="findingaid",
                    choices=["findingaid", "facomponent"])
    ap.add_argument("--limit", type=int, default=0,
                    help="nb max de branches à isoler (0 = tout ; utile pour tester)")
    ap.add_argument("--year-min", type=int, default=1800)
    ap.add_argument("--year-max", type=int, default=1860)
    ap.add_argument("--run", action="store_true",
                    help="exécuter le harvester sur les branches isolées")
    ap.add_argument("--out", default="seed_cadastre.sql",
                    help="fichier seed SQL produit avec --run")
    args = ap.parse_args()

    service, targets = scout(args.etype, args.eid, limit=args.limit)
    if not targets:
        sys.stderr.write("Aucune branche « plans cadastre » détectée. "
                         "Ajuste PLANS_POS/PLANS_NEG ou vérifie l'eid.\n")
        sys.exit(2)

    emit_plan(service, targets, args.year_min, args.year_max)
    if args.run:
        run_harvester(targets, args.out, args.year_min, args.year_max)


if __name__ == "__main__":
    main()
