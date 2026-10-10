"""Banc d'essai : géoréférencement automatique par contour communal (TA <-> contour IGN).

Vérité terrain = GCP Allmaps (web/annotations/collection.json). Pour chaque plan, la commune
est celle qui contient le centre des GCP (en production : l'INSEE de la table `document`).

Sources du contour « pixel » :
  --source masque       masque Allmaps (contour tracé à la main) : teste l'étape 2 seule, hors réseau.
                        + --rotation-aleatoire : plan tourné au hasard (invariance)
                        + --parasites routes,cartouche,voisine : défauts d'extraction simulés
  --source synthetique  TA fabriqué depuis le contour IGN (cadre, cartouche, routes sortantes,
                        texte, rotation) : teste les étapes 1+2 hors réseau.
  --source image        vraie image IIIF (réseau) : étapes 1+2 de bout en bout. À lancer en local.

    python banc_contour.py --source masque
    python banc_contour.py --source image --out sortie_contour   # images de debug dans sortie_contour/debug
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
from enveloppe import extraire_enveloppe
from recalage_contour import appliquer, recaler, reechantillonner

HERE = Path(__file__).resolve().parent
warnings.filterwarnings("ignore", category=UserWarning)


def iou(poly_a, poly_b, cote=1500):
    """IoU de deux polygones (mêmes coordonnées) par rastérisation."""
    allp = np.vstack([poly_a, poly_b])
    x0, y0 = allp.min(0)
    s = cote / max(np.ptp(allp, axis=0))
    shape = (int(np.ptp(allp[:, 1]) * s) + 2, int(np.ptp(allp[:, 0]) * s) + 2)
    a, b = np.zeros(shape, np.uint8), np.zeros(shape, np.uint8)
    cv2.fillPoly(a, [((poly_a - [x0, y0]) * s).astype(np.int32)], 1)
    cv2.fillPoly(b, [((poly_b - [x0, y0]) * s).astype(np.int32)], 1)
    return (a & b).sum() / max((a | b).sum(), 1)


# ----------------------------------------------------------------- perturbations

def tourner(m, rng):
    th = rng.uniform(0, 2 * np.pi)
    c = np.array([m["full_w"], m["full_h"]]) / 2
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    m = dict(m, px=(m["px"] - c) @ R.T + c, mask=(m["mask"] - c) @ R.T + c)
    return m


def parasiter(mask, types, rng, cote=1500):
    """Ajoute au contour des défauts d'extraction typiques, par rastérisation."""
    x0, y0 = mask.min(0) - np.ptp(mask, axis=0) * 0.6
    s = cote / (max(np.ptp(mask, axis=0)) * 2.2)
    img = np.zeros((cote, cote), np.uint8)
    pm = ((mask - [x0, y0]) * s).astype(np.int32)
    cv2.fillPoly(img, [pm], 1)
    diam = max(np.ptp(pm, axis=0))
    cen = pm.mean(0)
    pts = reechantillonner(pm, 200)
    if "routes" in types:  # deux routes sortantes
        for p in pts[rng.choice(len(pts), 2, replace=False)]:
            d = (p - cen) / np.linalg.norm(p - cen)
            q = p + d * 0.25 * diam
            cv2.line(img, tuple(p.astype(int)), tuple(q.astype(int)), 1, max(int(0.015 * diam), 2))
    if "cartouche" in types:  # rectangle collé au point le plus à droite
        p = pts[np.argmax(pts[:, 0])]
        w, h = 0.25 * diam, 0.15 * diam
        cv2.rectangle(img, (int(p[0] - 5), int(p[1] - h / 2)), (int(p[0] + w), int(p[1] + h / 2)), 1, -1)
    if "voisine" in types:  # morceau de commune voisine accolé
        p = pts[rng.integers(len(pts))]
        d = (p - cen) / np.linalg.norm(p - cen)
        q = p + d * 0.1 * diam
        cv2.ellipse(img, tuple(q.astype(int)), (int(0.18 * diam), int(0.1 * diam)),
                    float(np.degrees(np.arctan2(d[1], d[0]))), 0, 360, 1, -1)
    cnts, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)[:, 0, :].astype(float)
    return c / s + [x0, y0]


# ------------------------------------------------------------------- TA synthétique

MOTS = ["COMMUNE", "Section A", "Section B", "dite du Bois", "Chemin", "TABLEAU D'ASSEMBLAGE",
        "Echelle", "Moulin", "le Village", "Bois communal", "Pres", "Combe"]


def ta_synthetique(rings, rot_deg, rng, W=2400, H=1700):
    """Image façon tableau d'assemblage + transformation vraie pixel -> L93 (3x3)."""
    ring = max(rings, key=len)
    c = ring.mean(0)
    th = np.radians(rot_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    loc = (ring - c) @ R  # repère image tourné
    s = 0.62 * min(W / np.ptp(loc[:, 0]), H / np.ptp(loc[:, 1]))  # px par m
    off = np.array([W / 2, H / 2]) + rng.uniform(-0.08, 0.08, 2) * [W, H]

    def geo2px(g):
        q = ((g - c) @ R) * s
        return np.c_[q[:, 0] + off[0], -q[:, 1] + off[1]]

    # transformation vraie pixel -> L93 (inverse de geo2px)
    A = np.linalg.inv(np.array([[1, 0], [0, -1]]) @ R.T * s)
    Mtrue = np.eye(3)
    Mtrue[:2, :2] = A
    Mtrue[:2, 2] = c - A @ off

    img = np.full((H, W, 3), (205, 228, 238), np.uint8)
    tache = cv2.GaussianBlur(rng.normal(0, 1, (H // 20, W // 20)).astype(np.float32), (0, 0), 3)
    img = np.clip(img + cv2.resize(tache, (W, H))[..., None] * 12, 0, 255).astype(np.uint8)
    poly = geo2px(ring).astype(np.int32)
    dedans = np.zeros((H, W), np.uint8)
    cv2.fillPoly(dedans, [poly], 1)
    calque = np.zeros_like(img)
    # sections (traits fins), cours d'eau, bâti : uniquement dans la commune
    pts = reechantillonner(poly, 300)
    for _ in range(9):
        a, b = pts[rng.choice(len(pts), 2, replace=False)].astype(int)
        cv2.line(calque, tuple(a), tuple(b), (60, 60, 60), 2)
    for _ in range(3):
        a, b = pts[rng.choice(len(pts), 2, replace=False)].astype(int)
        m = (a + b) / 2 + rng.normal(0, 60, 2)
        cv2.polylines(calque, [np.array([a, m, b], np.int32)], False, (190, 130, 60), 4)
    for _ in range(25):
        p = poly.mean(0) + rng.normal(0, np.ptp(poly, axis=0) / 6)
        cv2.rectangle(calque, tuple(p.astype(int)), tuple((p + rng.integers(4, 14, 2)).astype(int)), (70, 70, 190), -1)
    img[(dedans > 0) & (calque.sum(2) > 0)] = calque[(dedans > 0) & (calque.sum(2) > 0)]
    # liseré rose + limite communale tiretée
    cv2.polylines(img, [poly], True, (170, 150, 225), 12)
    seg = reechantillonner(poly, 160).astype(np.int32)
    for i in range(0, len(seg), 2):
        cv2.line(img, tuple(seg[i]), tuple(seg[(i + 1) % len(seg)]), (40, 40, 50), 3)
    # routes sortantes (débordent hors commune), noms des voisines, titre, cartouche, nord, cadre
    cen = poly.mean(0)
    for p in pts[rng.choice(len(pts), 3, replace=False)]:
        d = (p - cen) / np.linalg.norm(p - cen)
        a, b = p - d * 120, p + d * 180
        for e in (-4, 4):
            n = np.array([-d[1], d[0]]) * e
            cv2.line(img, tuple((a + n).astype(int)), tuple((b + n).astype(int)), (70, 90, 120), 2)
    for p in pts[rng.choice(len(pts), 4, replace=False)]:
        d = (p - cen) / np.linalg.norm(p - cen)
        cv2.putText(img, str(rng.choice(MOTS)), tuple((p + d * 70).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (50, 50, 50), 2)
    cv2.putText(img, "COMMUNE DE X - TABLEAU D'ASSEMBLAGE", (W // 2 - 420, 110), cv2.FONT_HERSHEY_TRIPLEX, 1.4, (40, 40, 40), 3)
    cv2.rectangle(img, (W - 520, H - 300), (W - 90, H - 90), (40, 40, 40), 3)
    for k in range(4):
        cv2.putText(img, str(rng.choice(MOTS)), (W - 500, H - 250 + 45 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2)
    cv2.arrowedLine(img, (150, 380), (150 + int(-np.sin(th) * 120), 380 - int(np.cos(th) * 120)), (40, 40, 40), 4, tipLength=0.3)
    cv2.rectangle(img, (40, 40), (W - 40, H - 40), (40, 40, 40), 6)
    cv2.rectangle(img, (55, 55), (W - 55, H - 55), (40, 40, 40), 2)
    return img, Mtrue, poly.astype(float)


# ------------------------------------------------------------------------- banc

def georeferencer_ta(img, rings, methode="auto", modele="similitude", debug_prefix=None):
    """Étapes 1+2 sur une image. methode "auto" : essaie "contour" puis "densite" et garde
    le recalage au meilleur taux d'inliers. Renvoie (contour_px, resultat) ou (None, None)."""
    meilleur = (None, None)
    for meth in (("contour", "densite") if methode == "auto" else (methode,)):
        dbg = None if debug_prefix is None else f"{debug_prefix}_{meth}.jpg"
        contour = extraire_enveloppe(img, meth, debug=dbg)
        if contour is None or len(contour) < 10:
            continue
        r = recaler(contour, rings, modele=modele)
        r["methode"] = meth
        if meilleur[1] is None or r["part_inliers"] > meilleur[1]["part_inliers"]:
            meilleur = (contour, r)
        if methode == "auto" and r["statut"] == "calé":
            break
    return meilleur


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["masque", "image", "synthetique"], default="masque")
    ap.add_argument("--contours", default="france-geojson", help="france-geojson | wfs | fichier.geojson")
    ap.add_argument("--collection", default=str(HERE.parent / "web/annotations/collection.json"))
    ap.add_argument("--out", default="sortie_contour")
    ap.add_argument("--only", default="", help="ids Allmaps séparés par des virgules")
    ap.add_argument("--methode", choices=["auto", "contour", "densite"], default="auto", help="étape 1")
    ap.add_argument("--modele", choices=["similitude", "affine"], default="similitude")
    ap.add_argument("--rotation-aleatoire", action="store_true")
    ap.add_argument("--parasites", default="", help="routes,cartouche,voisine")
    ap.add_argument("--width", type=int, default=2000, help="largeur de téléchargement (source image)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if args.source == "image" and (args.rotation_aleatoire or args.parasites):
        ap.error("--rotation-aleatoire / --parasites : sources masque et synthetique seulement")

    out = Path(args.out)
    (out / "debug").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    ref = Contours("france-geojson", out / "cache_contours")       # recherche de la commune
    src = ref if args.contours == "france-geojson" else Contours(args.contours, out / "cache_contours")
    parasites = {p for p in args.parasites.split(",") if p}

    rows = []
    for m in load_maps(args.collection, only):
        row = dict(id=m["id"], carte=m["name"], n_gcp=len(m["px"]))
        t0 = time.time()
        try:
            insee, nom = ref.commune_au_point(*m["xy"].mean(0))
            row.update(insee=insee, commune=nom)
            rings = src.contour(insee)
            lo = loo_affine_rmse(m["px"], m["xy"])
            row["plancher_affine_m"] = round(lo, 1) if lo is not None else ""
            if args.source == "synthetique":
                rot = rng.uniform(-180, 180) if args.rotation_aleatoire else rotation_deg(m["px"], m["xy"])
                img, Mtrue, poly_vrai = ta_synthetique(rings, rot, rng)
                cv2.imwrite(str(out / "debug" / f"{m['id']}_ta.jpg"), img)
                contour, r = georeferencer_ta(img, rings, args.methode, args.modele, out / "debug" / m["id"])
                gx = rng.uniform(poly_vrai.min(0), poly_vrai.max(0), (400, 2))
                gx = gx[[cv2.pointPolygonTest(poly_vrai.astype(np.float32), tuple(p), False) > 0 for p in gx]][:30]
                px, xy, vrai = gx, appliquer(Mtrue, gx), poly_vrai
            else:
                if args.rotation_aleatoire:
                    m = tourner(m, rng)
                px, xy, vrai = m["px"], m["xy"], m["mask"]
                if args.source == "masque":
                    contour = parasiter(m["mask"], parasites, rng) if parasites else m["mask"]
                    r = recaler(contour, rings, modele=args.modele)
                else:
                    path, w = fetch_image(m, args.width, out / "images")
                    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                    contour, r = georeferencer_ta(img, rings, args.methode, args.modele, out / "debug" / m["id"])
                    if contour is not None:  # pixels de l'image téléchargée -> pleine résolution (GCP)
                        k = m["full_w"] / w
                        contour = contour * k
                        r["M"] = r["M"] @ np.diag([1 / k, 1 / k, 1])
            row["rotation_vraie"] = round(rotation_deg(px, xy), 1)
            if contour is None:
                row["statut"] = "échec étape 1 (aucune enveloppe)"
            else:
                if vrai is not None:
                    row["iou_enveloppe"] = round(iou(contour, vrai), 2)
                e = np.linalg.norm(appliquer(r["M"], px) - xy, axis=1)
                row.update(methode=r.get("methode", ""), angle_estime=round(r["angle_deg"], 1), part_inliers=round(r["part_inliers"], 2),
                           statut=r["statut"], erreur_mediane_m=round(float(np.median(e)), 1),
                           rmse_m=round(float(np.sqrt(np.mean(e ** 2))), 1), erreur_max_m=round(float(e.max()), 1))
        except Exception as ex:  # noqa: BLE001 — bilan complet même si un plan plante
            row["statut"] = f"erreur : {type(ex).__name__}: {ex}"[:160]
        row["duree_s"] = round(time.time() - t0, 1)
        rows.append(row)
        print({k: v for k, v in row.items() if k not in ("id",)}, flush=True)

    cols = ["id", "carte", "insee", "commune", "n_gcp", "rotation_vraie", "angle_estime", "methode", "iou_enveloppe",
            "part_inliers", "statut", "erreur_mediane_m", "rmse_m", "erreur_max_m", "plancher_affine_m", "duree_s"]
    with open(out / "resultats_contour.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, cols)
        wr.writeheader()
        wr.writerows(rows)
    show = cols[1:-1]
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
