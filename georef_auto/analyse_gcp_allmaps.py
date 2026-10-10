"""Analyse des géoréférencements Allmaps existants (vérité terrain).

Pour chaque carte de web/annotations/collection.json, on ajuste sur les GCP
(pixel -> Lambert-93) trois modèles globaux et on en tire ce qui conditionne
un géoréférencement automatique de type MaRE :

- rotation : angle du nord géographique par rapport au haut de l'image.
  MaRE utilise des descripteurs KAZE « upright » (non invariants en rotation) :
  au-delà de ~15-20° l'appariement s'effondre.
- échelle : mètres par pixel de l'image pleine résolution.
- RMSE affine : plancher d'erreur d'un modèle affine global (le modèle de
  sortie de MaRE). Calculé en validation croisée (leave-one-out) quand il y a
  assez de points, sinon non significatif.
- emprise : part de l'image occupée par le masque Allmaps (le territoire
  communal). MaRE suppose que le contenu cartographique remplit la feuille.

Usage :
    python analyse_gcp_allmaps.py [../web/annotations/collection.json] [--csv sortie.csv]
Dépendances : numpy, pyproj.
"""
import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

TO_L93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)


def fit_similarity(px, xy):
    """xy ≈ s·R(θ)·px + t, image en y vers le bas -> on retourne y pour un repère direct."""
    p = px * np.array([1, -1])
    A = []
    b = []
    for (u, v), (x, y) in zip(p, xy):
        A.append([u, -v, 1, 0]); b.append(x)
        A.append([v, u, 0, 1]); b.append(y)
    sol, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    a, c, tx, ty = sol
    pred = np.c_[a * p[:, 0] - c * p[:, 1] + tx, c * p[:, 0] + a * p[:, 1] + ty]
    scale = math.hypot(a, c)
    # angle de rotation image->terrain ; le nord est à -θ par rapport au haut de l'image
    theta = math.degrees(math.atan2(c, a))
    return scale, theta, pred


def fit_affine(px, xy):
    A = np.c_[px, np.ones(len(px))]
    sol, *_ = np.linalg.lstsq(A, xy, rcond=None)
    return A @ sol


def fit_homography(px, xy):
    rows = []
    for (u, v), (x, y) in zip(px, xy):
        rows.append([-u, -v, -1, 0, 0, 0, u * x, v * x, x])
        rows.append([0, 0, 0, -u, -v, -1, u * y, v * y, y])
    _, _, vt = np.linalg.svd(np.array(rows))
    H = vt[-1].reshape(3, 3)
    q = np.c_[px, np.ones(len(px))] @ H.T
    return q[:, :2] / q[:, 2:3]


def rmse(pred, xy):
    return float(np.sqrt(np.mean(np.sum((pred - xy) ** 2, axis=1))))


def loo_affine(px, xy):
    """Erreur leave-one-out d'un affine global (honnête quand peu de points)."""
    errs = []
    for i in range(len(px)):
        m = np.ones(len(px), bool); m[i] = False
        A = np.c_[px[m], np.ones(m.sum())]
        sol, *_ = np.linalg.lstsq(A, xy[m], rcond=None)
        pred = np.r_[px[i], 1] @ sol
        errs.append(np.linalg.norm(pred - xy[i]))
    return float(np.sqrt(np.mean(np.square(errs))))


def mask_fraction(selector_svg, w, h):
    m = re.search(r'points="([^"]+)"', selector_svg)
    if not m:
        return None
    pts = np.array([[float(a) for a in p.split(",")] for p in m.group(1).split()])
    x, y = pts[:, 0], pts[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
    return area / (w * h)


def label(source_id):
    s = re.sub(r"^https://iiif-allmaps\.sperrot\.workers\.dev/static-iiif/", "", source_id)
    from urllib.parse import unquote
    return unquote(s).rsplit("/", 1)[-1]


def analyse(collection_path):
    data = json.loads(Path(collection_path).read_text(encoding="utf-8"))
    out = []
    for it in data["items"]:
        src = it["target"]["source"]
        w, h = src["width"], src["height"]
        feats = it["body"]["features"]
        px = np.array([f["properties"]["resourceCoords"] for f in feats], float)
        ll = np.array([f["geometry"]["coordinates"] for f in feats], float)
        xy = np.c_[TO_L93.transform(ll[:, 0], ll[:, 1])]
        n = len(px)
        row = {
            "carte": label(src["id"]),
            "allmaps_id": it["id"].rsplit("/", 1)[-1],
            "largeur_px": w, "hauteur_px": h, "n_gcp": n,
            "transformation_allmaps": it["body"].get("transformation", {}).get("type", ""),
        }
        if n >= 2:
            scale, theta, pred = fit_similarity(px, xy)
            row["m_par_px"] = round(scale, 3)
            row["rotation_deg"] = round(theta, 1)
            row["rmse_similitude_m"] = round(rmse(pred, xy), 1)
            spread = np.ptp(xy, axis=0)
            row["etendue_gcp_km"] = f"{spread[0]/1000:.1f}x{spread[1]/1000:.1f}"
        if n >= 3:
            row["rmse_affine_m"] = round(rmse(fit_affine(px, xy), xy), 1)
        if n >= 5:
            row["loo_affine_m"] = round(loo_affine(px, xy), 1)
        if n >= 6:
            row["rmse_homographie_m"] = round(rmse(fit_homography(px, xy), xy), 1)
        sel = it["target"].get("selector", {}).get("value", "")
        frac = mask_fraction(sel, w, h)
        if frac is not None:
            row["part_image_masque"] = round(frac, 2)
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("collection", nargs="?",
                    default=str(Path(__file__).resolve().parent.parent / "web/annotations/collection.json"))
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()
    rows = analyse(args.collection)
    cols = ["carte", "n_gcp", "transformation_allmaps", "m_par_px", "rotation_deg",
            "rmse_similitude_m", "rmse_affine_m", "loo_affine_m", "rmse_homographie_m",
            "etendue_gcp_km", "part_image_masque", "largeur_px", "hauteur_px", "allmaps_id"]
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, cols)
            wr.writeheader()
            wr.writerows(rows)
    print("| " + " | ".join(cols[:11]) + " |")
    print("|" + "---|" * 11)
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols[:11]) + " |")


if __name__ == "__main__":
    sys.exit(main())
