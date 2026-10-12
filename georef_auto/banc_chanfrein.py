"""Banc : recalage du contour IGN sur l'encre du TA (recalage_chanfrein.py), sans extraction
d'enveloppe. Vérité terrain = GCP Allmaps, comme banc_contour.py ; images IIIF en cache.

Hypothèses d'échelle (--echelle) :
  oracle    m/px vrai (GCP) x {0,97 ; 1 ; 1,03} : teste la recherche seule.
  standard  numérisation à --dpi, échelles --denominateurs (défaut 1/2 500, 1/5 000, 1/10 000,
            1/20 000) x {0,97 ; 1 ; 1,03}. Les deux sont propres au fonds (Doubs : 300 dpi,
            1/10 000 et 1/20 000 ; Jura archives39 : 137,5 dpi, 1/5 000 et 1/10 000).
  libre     grille géométrique de 0,15 à 3 m/px (pleine résolution), pas de 6 %.

    python banc_chanfrein.py --echelle oracle
    python banc_chanfrein.py --echelle standard --out sortie_chanfrein
"""
import argparse
import csv
import time
import warnings
from pathlib import Path

import cv2
import numpy as np

from communs import fetch_image, load_maps, loo_affine_rmse, rotation_deg
from contours_ign import Contours
from recalage_chanfrein import recaler_image
from recalage_contour import appliquer

HERE = Path(__file__).resolve().parent
warnings.filterwarnings("ignore", category=UserWarning)
DENOMINATEURS = (2500, 5000, 10000, 20000)
JEU = (0.97, 1.0, 1.03)


def m_par_px_vrai(px, xy):
    A = np.c_[px, np.ones(len(px))]
    sol, *_ = np.linalg.lstsq(A, xy, rcond=None)
    return float(np.sqrt(abs(np.linalg.det(sol[:2].T))))


def echelles_candidates(mode, m, dpi, denominateurs=DENOMINATEURS):
    """m/px en pleine résolution."""
    if mode == "oracle":
        return [m_par_px_vrai(m["px"], m["xy"]) * j for j in JEU]
    if mode == "standard":
        return [d * 0.0254 / dpi * j for d in denominateurs for j in JEU]
    return list(np.geomspace(0.15, 3.0, int(np.log(20) / np.log(1.06)) + 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--echelle", choices=["oracle", "standard", "libre"], default="standard")
    ap.add_argument("--dpi", type=float, default=300)
    ap.add_argument("--denominateurs", default="2500,5000,10000,20000",
                    help="échelles en usage dans le fonds (mode standard), ex. Jura : 5000,10000")
    ap.add_argument("--contours", default="france-geojson", help="france-geojson | wfs | fichier.geojson")
    ap.add_argument("--collection", default=str(HERE.parent / "web/annotations/collection.json"))
    ap.add_argument("--images", default="sortie_contour/images", help="cache des images IIIF")
    ap.add_argument("--out", default="sortie_chanfrein")
    ap.add_argument("--only", default="")
    ap.add_argument("--width", type=int, default=2000)
    ap.add_argument("--pas-angle", type=float, default=2.0)
    ap.add_argument("--insee", default="", help="forçage id=insee,... quand le centre des GCP tombe dans une "
                    "voisine (en production, l'INSEE vient de la table document)")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "debug").mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    forces = dict(x.split("=") for x in args.insee.split(",") if "=" in x)
    ref = Contours("france-geojson", Path("sortie_contour/cache_contours"))
    src = ref if args.contours == "france-geojson" else Contours(args.contours, out / "cache_contours")

    rows = []
    for m in load_maps(args.collection, only):
        row = dict(id=m["id"], carte=m["name"], n_gcp=len(m["px"]))
        t0 = time.time()
        try:
            insee, nom = (forces[m["id"]], "(forcé)") if m["id"] in forces else ref.commune_au_point(*m["xy"].mean(0))
            row.update(insee=insee, commune=nom)
            rings = src.contour(insee)
            lo = loo_affine_rmse(m["px"], m["xy"])
            row["plancher_affine_m"] = round(lo, 1) if lo is not None else ""
            row["rotation_vraie"] = round(rotation_deg(m["px"], m["xy"]), 1)
            row["m_par_px_vrai"] = round(m_par_px_vrai(m["px"], m["xy"]), 3)
            path, w = fetch_image(m, args.width, Path(args.images))
            img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            k = m["full_w"] / w
            denoms = [int(d) for d in args.denominateurs.split(",")]
            ech = [e * k for e in echelles_candidates(args.echelle, m, args.dpi, denoms)]
            r = recaler_image(img, rings, ech, pas_angle=args.pas_angle, debug=out / "debug" / f"{m['id']}.jpg")
            if r is None:
                row["statut"] = "aucune pose"
            else:
                M = r["M"] @ np.diag([1 / k, 1 / k, 1])  # pixels pleine résolution -> L93
                e = np.linalg.norm(appliquer(M, m["px"]) - m["xy"], axis=1)
                row.update(angle_estime=round(r["angle_deg"], 1), m_par_px_estime=round(r["m_par_px"] / k, 3),
                           couverture=round(r["couverture"], 2), contraste=round(r["contraste"], 2), couverture_hasard=round(r["couverture_hasard"], 2),
                           z=round(r["z"], 1), ecart_2e=round(r["ecart_2e"], 2), statut=r["statut"],
                           erreur_mediane_m=round(float(np.median(e)), 1),
                           rmse_m=round(float(np.sqrt(np.mean(e ** 2))), 1), erreur_max_m=round(float(e.max()), 1))
        except Exception as ex:  # noqa: BLE001
            row["statut"] = f"erreur : {type(ex).__name__}: {ex}"[:160]
        row["duree_s"] = round(time.time() - t0, 1)
        rows.append(row)
        print({k_: v for k_, v in row.items() if k_ != "id"}, flush=True)

    cols = ["id", "carte", "insee", "commune", "n_gcp", "rotation_vraie", "angle_estime", "m_par_px_vrai",
            "m_par_px_estime", "couverture", "contraste", "couverture_hasard", "z", "ecart_2e", "statut", "erreur_mediane_m",
            "rmse_m", "erreur_max_m", "plancher_affine_m", "duree_s"]
    with open(out / f"resultats_chanfrein_{args.echelle}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, cols)
        wr.writeheader()
        wr.writerows(rows)
    show = ["carte", "commune", "rotation_vraie", "angle_estime", "m_par_px_vrai", "m_par_px_estime",
            "couverture", "contraste", "ecart_2e", "statut", "erreur_mediane_m", "plancher_affine_m"]
    print("\n| " + " | ".join(show) + " |\n|" + "---|" * len(show))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in show) + " |")
    for statut in ("calé", "probable", "à vérifier"):
        sel = [r for r in rows if r.get("statut") == statut]
        bons = sum(r.get("erreur_mediane_m", 1e9) < 50 for r in sel)
        faux = sum(r.get("erreur_mediane_m", 0) >= 100 for r in sel)
        print(f"{statut:>10} : {len(sel):2d}/{len(rows)}  (< 50 m : {bons}, > 100 m : {faux})")


if __name__ == "__main__":
    main()
