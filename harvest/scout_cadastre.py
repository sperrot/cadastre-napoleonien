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
import warnings
import contextlib
from pathlib import Path

from rdflib import URIRef

# ── Réutilisation du harvester (contournement robot + helpers RDF) ───────────
# Import : harvest_francearchives n'exécute rien à l'import (main() est gardé
# par `if __name__ == "__main__"`). On récupère sa session anti-robot ET ses
# fonctions de moisson (walk/emit_sql) pour rester DANS LE MÊME PROCESS — donc
# la même session HTTP (utile quand on neutralise la vérif TLS, cf. --insecure).
import harvest_francearchives as H
from harvest_francearchives import (
    BASE, RICO, RDFS,
    fetch_graph, eid_of, leaf_manifest, resolve_licence, classify,
)

# ── Détection de la branche « Plans du cadastre napoléonien » ────────────────
# Libellés rencontrés (variables selon départements) : « Plans cadastraux »,
# « Plans du cadastre », « Atlas cadastral », « Cadastre napoléonien »,
# « Tableau d'assemblage », « Section A »…
PLANS_POS = re.compile(
    r"plan|atlas|cadastr|tableau\s+d['e ]assemblage|assemblage|\bsection\b",
    re.I,
)
# À EXCLURE : documents textuels du cadastre (pas des plans) et cadastre moderne.
# `\b[ée]tats?\b` couvre « État de section » ET « État de la section A »
# (le « de la » cassait l'ancien motif et laissait passer ces registres).
PLANS_NEG = re.compile(
    r"matric|mutation|\b[ée]tats?\b|registre|répertoire|repertoire|\btable\b|"
    r"classement|arpentage|proc[èe]s|délimitation|delimitation|"
    r"limites?\s+de\s+commune|propri[ée]t|\bfolios?\b|sommier|"
    r"r[ée]nov|remembr",
    re.I,
)

def is_plans_title(t: str) -> bool:
    t = t or ""
    return bool(PLANS_POS.search(t)) and not PLANS_NEG.search(t)


# ── Helpers RDF locaux ───────────────────────────────────────────────────────
def node(etype: str, eid: str):
    """(graph, subj, title, children_eids, manifest) d'un nœud, ou None.

    `fetch_graph` du harvester renvoie None quand aucun export RDF ne répond
    (et n'écrit qu'un warning) : on propage ce None proprement."""
    g = fetch_graph(etype, eid)
    if g is None:
        return None
    subj = URIRef(f"{BASE}/{etype}/{eid}")
    title = next((str(o) for o in g.objects(subj, RICO.title)), None) \
        or next((str(o) for o in g.objects(subj, RDFS.label)), None)
    children = [eid_of(str(o)) for o in g.objects(subj, RICO.includesOrIncluded)]
    manifest = leaf_manifest(g, subj)
    return g, subj, (title or ""), children, manifest


def root_service(etype: str, eid: str):
    """Institution gestionnaire (URI service/NNNN) à la racine de l'arbre."""
    res = node(etype, eid)
    if not res:
        return None
    g, subj, *_ = res
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
    res = node(etype, eid)
    if not res:
        return None
    _, _, _, children, manifest = res
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
        res = node(etype, eid)
        if not res:
            return
        g, subj, title, children, manifest = res

        # (0) Branche-registre explicite (État de section, Matrices, Propriétés…)
        #     → élaguée : on n'y descend pas. (depth>0 : ne pas élaguer la racine,
        #     dont le titre « Répertoire… » matcherait PLANS_NEG.)
        if depth > 0 and title and PLANS_NEG.search(title):
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
                c_res = node("facomponent", c)
                if not c_res:
                    continue
                _, _, c_title, c_children, c_manifest = c_res
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
    """Moissonne chaque branche EN-PROCESS (réutilise H.walk/H.emit_sql).

    Écriture **incrémentale et reprenable** : chaque branche est écrite puis
    flushée atomiquement (marqueur + SQL d'un bloc). Au redémarrage, les branches
    déjà présentes dans le seed sont sautées → robuste aux coupures (sommeil
    machine, etc.), contrairement à un écrit tout-ou-rien en fin de run."""
    import io
    H.YEAR_MIN, H.YEAR_MAX = year_min, year_max
    out = Path(out_path)

    # Reprise : eids des branches déjà écrites (marqueur « (… <eid>) — »).
    done = set()
    if out.exists():
        prev = out.read_text(encoding="utf-8", errors="ignore")
        done = set(re.findall(r"-- ── .*? \(([0-9a-f]{40})\) —", prev))
    resume = bool(done)
    sys.stderr.write(f"{'Reprise' if resume else 'Démarrage'} : "
                     f"{len(done)}/{len(targets)} branche(s) déjà écrite(s).\n")

    with out.open("a" if resume else "w", encoding="utf-8") as fh:
        if not resume:
            fh.write(f"-- seed cadastre — {len(targets)} branche(s) — "
                     f"période {year_min}-{year_max}\n")
        for i, t in enumerate(targets, 1):
            if t["branch_eid"] in done:
                continue
            sys.stderr.write(f"[{i}/{len(targets)}] harvest ← "
                             f"{t['commune']} ({t['branch_eid']}) …\n")
            leaves, seen = [], set()
            H.walk(t["branch_etype"], t["branch_eid"], leaves, seen)
            # bloc construit en mémoire puis écrit+flushé d'un coup (atomique) :
            # une coupure mid-branche laisse la branche absente → refaite au run suivant.
            buf = io.StringIO()
            buf.write(f"\n-- ── {t['commune']} / {t['branch_title']} "
                      f"({t['branch_eid']}) — {len(leaves)} feuille(s) ──\n")
            H.emit_sql(leaves, out=buf)
            fh.write(buf.getvalue())
            fh.flush()
    sys.stderr.write(f"\nSeed écrit : {out}\n")


def main():
    ap = argparse.ArgumentParser(
        description="Scout cadastre — isole les branches « plans » et arme le harvester")
    ap.add_argument("eid", help="identifiant racine (findingaid ou facomponent)")
    ap.add_argument("etype", nargs="?", default="findingaid",
                    choices=["findingaid", "facomponent"])
    ap.add_argument("--limit", type=int, default=0,
                    help="nb max de branches à isoler (0 = tout ; utile pour tester)")
    ap.add_argument("--year-min", type=int, default=1790)
    ap.add_argument("--year-max", type=int, default=1860)
    ap.add_argument("--run", action="store_true",
                    help="exécuter le harvester sur les branches isolées")
    ap.add_argument("--recon-only", action="store_true",
                    help="reconnaissance seule (défaut) : isole + vérifie licence/IIIF, "
                         "n'exécute pas le harvester ; ignore --run si présent")
    ap.add_argument("--out", default="seed_cadastre.sql",
                    help="fichier seed SQL produit avec --run")
    ap.add_argument("--insecure", action="store_true",
                    help="neutralise la vérif TLS (env derrière proxy/CA manquante)")
    args = ap.parse_args()

    # Console Windows en cp1252 : on force l'UTF-8 pour les emojis du récap.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")

    if args.insecure:
        import urllib3
        warnings.simplefilter("ignore")
        urllib3.disable_warnings()
        H.session.verify = False        # session partagée scout + harvester
        sys.stderr.write("⚠ TLS non vérifié (--insecure).\n")
    else:
        # TLS propre via le magasin de certificats de l'OS (truststore).
        try:
            import truststore
            truststore.inject_into_ssl()
            sys.stderr.write("TLS via truststore (magasin OS).\n")
        except Exception:
            sys.stderr.write("truststore indispo (utilise --insecure si TLS KO).\n")

    service, targets = scout(args.etype, args.eid, limit=args.limit)
    if not targets:
        sys.stderr.write("Aucune branche « plans cadastre » détectée. "
                         "Ajuste PLANS_POS/PLANS_NEG ou vérifie l'eid.\n")
        sys.exit(2)

    emit_plan(service, targets, args.year_min, args.year_max)
    if args.run and not args.recon_only:
        run_harvester(targets, args.out, args.year_min, args.year_max)


if __name__ == "__main__":
    main()
