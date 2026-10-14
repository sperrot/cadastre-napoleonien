"""Doubs : trouver la page qui est vraiment le tableau d'assemblage (TA) de chaque cote 3P.

`fix_doubs_types.py` suppose que la page _01 est le TA. Le lot à l'aveugle (validation du
2026-10-12) montre que c'est faux pour ~1 cote sur 3 : le TA peut être en _04, _05, _06…, et
la _01 est alors une feuille de section.

Pour chaque cote :
1. vignettes de toutes les pages (IIIF 800 px) ; la densité de traits sert à les classer : un TA
   montre la commune entière, petite, sur une feuille peu chargée, une feuille de section est
   couverte de parcelles ;
2. recalage_chanfrein page par page, de la moins chargée à la plus chargée ; la première page
   « calée » est le TA (arrêt) ; si aucune ne l'est, la cote est « TA non trouvé ».

    python trouver_ta_doubs.py --cotes 3P587,3P493,3P561
    python trouver_ta_doubs.py --n 20 --seed 2          # tirage au hasard
    python trouver_ta_doubs.py --toutes                  # tout le fonds (long : plusieurs heures)

Sortie : sortie_ta_doubs/ta_doubs.csv (une ligne par cote, reprise possible) + aperçus du TA.
"""
import argparse
import collections
import csv
import json
import re
import time
import warnings
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from communs import fetch_image
from contours_ign import Contours
from lot_aveugle import WORKER, _norm, apercu, largeur_pleine
from recalage_chanfrein import carte_traits, recaler_image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DPI, DENOMS = 300, (5000, 10000, 20000)
warnings.filterwarnings("ignore", category=UserWarning)


def _cle(nom):
    """Clé de nom de commune sans article : « Fontenelles (Les) », « Les Fontenelles » -> « fontenelles »."""
    k = _norm(re.sub(r"\s*\((les|le|la|l')\)\s*$", "", nom or "", flags=re.I))
    return re.sub(r"^(les|le|la|l) ", "", k)


def _nom_actuel(it):
    """Nom actuel si le catalogue l'indique (« Actuelle commune de Les Alliés. »), sinon le titre."""
    m = re.search(r"[Aa]ctuelle commune d[e']\s*(.+?)\.?$", it.get("scopecontent") or "")
    return m.group(1) if m else it.get("unittitle")


def cotes_doubs(contours):
    """{cote: dict(insee, commune, pages=[(num, url)])} — INSEE par le nom (homonymes exclus)."""
    feats = contours._communes_dep("25", next(n for c, n, _ in contours._departements() if c == "25"))
    noms = collections.defaultdict(list)
    for f in feats:
        noms[_cle(f["properties"]["nom"])].append((f["properties"]["code"], f["properties"]["nom"]))
    out = {}
    for it in json.loads((ROOT / "download/cadastre-napoleonien_doubs.json").read_text(encoding="utf-8")):
        m = re.search(r"/FRAD025_(3P\d+)_(\w+)\.jpg$", it.get("file_path") or "")
        if not m:
            continue
        hits = noms.get(_cle(_nom_actuel(it)), [])
        d = out.setdefault(m.group(1), dict(cote=m.group(1), titre=it.get("unittitle"), pages=[],
                                            insee=hits[0][0] if len(hits) == 1 else None,
                                            commune=hits[0][1] if len(hits) == 1 else None))
        d["pages"].append((m.group(2), it["file_path"]))
    for d in out.values():
        d["pages"].sort()
    return out


def densite(url, cache):
    """Part de pixels « trait » sur une vignette 800 px (TA : faible)."""
    m = dict(id=Path(url).stem, service=WORKER + quote(url, safe=""))
    path, _ = fetch_image(m, 800, cache)
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    return float((carte_traits(img) > 0.15).mean())


def chercher(d, src, out, diam_min):
    pages = d["pages"]
    rings = src.contour(d["insee"])
    essais = []

    def ordre():
        """La _01 d'abord (TA dans ~70 % des cotes) ; les densités ne sont calculées qu'ensuite."""
        yield from (p for p in pages if p[0] == "01")
        dens = {}
        for num, url in pages:
            if num != "01":
                try:
                    dens[num] = densite(url, out / "vignettes")
                except Exception:  # noqa: BLE001
                    dens[num] = 1.0
        yield from sorted((p for p in pages if p[0] != "01"), key=lambda p: dens[p[0]])

    for num, url in ordre():
        m = dict(id=Path(url).stem, service=WORKER + quote(url, safe=""))
        path, w = fetch_image(m, 2000, out / "images")
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        full_w = largeur_pleine(m["service"]) or w
        k = full_w / w
        ech = [dd * 0.0254 / DPI * j * k for dd in DENOMS for j in (0.97, 1.0, 1.03)]
        r = recaler_image(img, rings, ech, diam_min=diam_min)
        essais.append(f"{num}:{r['statut'] if r else 'aucune'}:{r['ecart_2e']:.2f}" if r else f"{num}:aucune")
        if r and r["statut"] == "calé":
            mpx = r["m_par_px"] / k
            M = r["M"] @ np.diag([1 / k, 1 / k, 1])
            ap = f"apercus/{d['cote']}_{num}.jpg"
            apercu(img, r["M"], rings, r["statut"],
                   f"{d['commune']} ({d['insee']}) {d['cote']}_{num}  ecart {r['ecart_2e']:.2f}  1/{int(round(mpx / 0.0254 * DPI, -2))}",
                   out / ap)
            return dict(page_ta=num, statut="calé", ecart_2e=round(r["ecart_2e"], 2), angle_deg=round(r["angle_deg"], 1),
                        echelle_deduite=int(round(mpx / 0.0254 * DPI, -2)), largeur_px=full_w,
                        pose_plein_l93=json.dumps(np.round(M[:2], 6).tolist()), image_url=url, apercu=ap,
                        rang_densite=len(essais), essais=" ".join(essais))
    return dict(page_ta="", statut="TA non trouvé", essais=" ".join(essais), rang_densite=len(essais))


_src = None


def traiter_cote(d, out, diam_min):
    global _src
    if _src is None:
        _src = Contours("pci", HERE / "sortie_chanfrein/cache_contours")
    row = dict(dept="25", cote=d["cote"], insee=d["insee"], commune=d["commune"], titre=d["titre"], n_pages=len(d["pages"]))
    t0 = time.time()
    if not d["insee"]:
        row["statut"] = "INSEE non résolu (commune fusionnée ?)"
    else:
        try:
            row.update(chercher(d, _src, out, diam_min))
        except Exception as ex:  # noqa: BLE001
            row["statut"] = f"erreur : {type(ex).__name__}: {ex}"[:160]
    row["duree_s"] = round(time.time() - t0, 1)
    return row


COLS = ["dept", "cote", "insee", "commune", "titre", "n_pages", "page_ta", "statut", "ecart_2e", "angle_deg", "echelle_deduite",
        "rang_densite", "essais", "duree_s", "largeur_px", "pose_plein_l93", "image_url", "apercu"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cotes", default="")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--toutes", action="store_true")
    ap.add_argument("--diam-min", type=float, default=0.12, help="taille mini de la commune / petit côté de l'image")
    ap.add_argument("--out", default="sortie_ta_doubs")
    ap.add_argument("--workers", type=int, default=1, help="cotes traitées en parallèle")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "apercus").mkdir(parents=True, exist_ok=True)
    ref = Contours("france-geojson", HERE / "sortie_contour/cache_contours")
    toutes = cotes_doubs(ref)
    if args.toutes:
        choix = sorted(toutes)
    elif args.cotes:
        choix = [c.strip() for c in args.cotes.split(",") if c.strip()]
    else:
        cand = sorted(toutes)
        choix = [cand[i] for i in np.random.default_rng(args.seed).permutation(len(cand))[:args.n]]
    fichier = out / "ta_doubs.csv"
    rows = {r["cote"]: r for r in csv.DictReader(open(fichier, encoding="utf-8"))} if fichier.exists() else {}
    a_faire = [toutes[c] for c in choix if not (c in rows and rows[c].get("statut")
                                               and not rows[c]["statut"].startswith(("erreur", "INSEE")))]
    travail = partial(traiter_cote, out=out, diam_min=args.diam_min)
    if args.workers > 1:
        pool = Pool(args.workers, initializer=cv2.setNumThreads, initargs=(2,))
        flux = pool.imap_unordered(travail, a_faire)
    else:
        flux = map(travail, a_faire)
    for row in flux:
        c = row["cote"]
        rows[c] = row
        print({k: row.get(k) for k in ("cote", "commune", "n_pages", "page_ta", "statut", "ecart_2e", "rang_densite", "essais", "duree_s")}, flush=True)
        with open(fichier, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, COLS, extrasaction="ignore")
            wr.writeheader()
            wr.writerows(rows.values())
    sel = [rows[c] for c in choix if c in rows]
    print(collections.Counter(r["statut"] for r in sel))
    print("page du TA :", collections.Counter(r.get("page_ta") for r in sel if r.get("page_ta")).most_common())


if __name__ == "__main__":
    main()
