"""Banc de test de MaRE (github.com/luftj/MaRE) sur nos plans déjà géoréférencés.

Vérité terrain = les GCP saisis à la main dans Allmaps (web/annotations/collection.json).
Pour chaque plan :
  1. télécharge l'image IIIF (réduite à --width px) ;
  2. construit la « feuille » attendue par MaRE (bbox en Lambert-93) :
       --prior commune : emprise des GCP + marge, mise au format de l'image
                         (= ce qu'on saurait en production : la commune) ;
       --prior oracle  : emprise exacte de l'image déduite des GCP (meilleur cas) ;
     plus --decoys feuilles leurres voisines pour tester aussi la recherche ;
  3. indexe les références OSM (hydrographie, via Overpass) puis lance MaRE ;
  4. mesure l'erreur (m) aux GCP Allmaps et la compare au plancher affine.

À lancer EN LOCAL (accès réseau aux serveurs IIIF des AD + Overpass) :

    git clone https://github.com/luftj/MaRE.git ../../MaRE
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements-mare.txt
    python test_mare.py --mare ../../MaRE --out sortie_mare

Sorties : sortie_mare/resultats_mare.csv (+ tableau Markdown à l'écran),
sortie_mare/debug/maskimg_<id>.png (masque « eau » extrait : à regarder !),
sortie_mare/aligned_<id>_*.jpg + .wld (plan recalé, Lambert-93).
"""
import argparse
import csv
import importlib
import json
import re
import sys
import time
import types
from pathlib import Path
from urllib.parse import unquote

import numpy as np

HERE = Path(__file__).resolve().parent
L93 = "EPSG:2154"


# --------------------------------------------------------------------------- GCP

def load_maps(collection_path, only=None):
    from pyproj import Transformer
    to_l93 = Transformer.from_crs("EPSG:4326", L93, always_xy=True)
    data = json.loads(Path(collection_path).read_text(encoding="utf-8"))
    maps = []
    for it in data["items"]:
        mid = it["id"].rsplit("/", 1)[-1]
        if only and mid not in only:
            continue
        src = it["target"]["source"]
        feats = it["body"]["features"]
        px = np.array([f["properties"]["resourceCoords"] for f in feats], float)
        ll = np.array([f["geometry"]["coordinates"] for f in feats], float)
        xy = np.c_[to_l93.transform(ll[:, 0], ll[:, 1])]
        name = unquote(re.sub(r"^https://iiif-allmaps\.sperrot\.workers\.dev/static-iiif/", "", src["id"])).rsplit("/", 1)[-1]
        maps.append(dict(id=mid, name=name, service=src["id"], service_type=src.get("type", ""),
                         full_w=src["width"], full_h=src["height"], px=px, xy=xy))
    return maps


def affine_fit(px, xy):
    A = np.c_[px, np.ones(len(px))]
    sol, *_ = np.linalg.lstsq(A, xy, rcond=None)
    return sol  # (3,2) : [u v 1] @ sol = [x y]


def rotation_deg(px, xy):
    sol = affine_fit(px, xy)
    a, c = sol[0, 0], sol[0, 1]  # dérivées de x,y selon u (axe horizontal image)
    return float(np.degrees(np.arctan2(c, a)))


def loo_affine_rmse(px, xy):
    if len(px) < 5:
        return None
    errs = []
    for i in range(len(px)):
        m = np.ones(len(px), bool); m[i] = False
        pred = np.r_[px[i], 1] @ affine_fit(px[m], xy[m])
        errs.append(np.linalg.norm(pred - xy[i]))
    return float(np.sqrt(np.mean(np.square(errs))))


def sheet_bbox(m, prior, margin):
    if prior == "oracle":
        sol = affine_fit(m["px"], m["xy"])
        corners = np.array([[0, 0, 1], [m["full_w"], 0, 1], [0, m["full_h"], 1], [m["full_w"], m["full_h"], 1]]) @ sol
        x0, y0 = corners.min(axis=0)
        x1, y1 = corners.max(axis=0)
        return [x0, y0, x1, y1]
    # « commune » : emprise des GCP (≈ territoire communal) + marge, au format de l'image (nord en haut supposé)
    x0, y0 = m["xy"].min(axis=0)
    x1, y1 = m["xy"].max(axis=0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = (x1 - x0) * (1 + 2 * margin), (y1 - y0) * (1 + 2 * margin)
    aspect = m["full_w"] / m["full_h"]
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def write_sheets(maps, prior, margin, decoys, path):
    feats = []
    for m in maps:
        b = sheet_bbox(m, prior, margin)
        m["bbox"] = b
        boxes = [(m["id"], b)]
        w, h = b[2] - b[0], b[3] - b[1]
        ring = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
        for k, (dx, dy) in enumerate(ring[:decoys]):
            boxes.append((f"{m['id']}_leurre{k}", [b[0] + dx * w, b[1] + dy * h, b[2] + dx * w, b[3] + dy * h]))
        for name, (x0, y0, x1, y1) in boxes:
            feats.append({"type": "Feature", "properties": {"blatt_100": name},
                          "geometry": {"type": "Polygon",
                                       "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    Path(path).write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")


# ------------------------------------------------------------------------ images

def fetch_image(m, width, cache_dir):
    import cv2
    import requests
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{m['id']}.jpg"
    if not path.exists():
        base = m["service"].rstrip("/")
        hdr = {"User-Agent": "Mozilla/5.0 (cadastre-napoleonien test MaRE)"}
        last = None
        for region_size in (f"full/{width},", "full/full", "full/max"):
            url = f"{base}/{region_size}/0/default.jpg"
            try:
                r = requests.get(url, headers=hdr, timeout=180)
                if r.ok and r.headers.get("content-type", "").startswith("image"):
                    path.write_bytes(r.content)
                    break
                last = f"HTTP {r.status_code} {url}"
            except requests.RequestException as e:
                last = f"{e} {url}"
        else:
            raise RuntimeError(f"image IIIF introuvable : {last}")
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img.shape[1] > width * 1.05:  # serveur qui a ignoré la taille demandée
        img = cv2.resize(img, (width, int(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(path), img)
    return path, img.shape[1]


# ------------------------------------------------------------------------- MaRE

def setup_mare(mare_dir, out_dir, osm_url, osm_query_file, registration="both"):
    """Prépare un config.py MaRE propre au test (MaRE fait reload(config) : pas de surcharge en mémoire)."""
    src = (Path(mare_dir) / "config.py").read_text(encoding="utf-8")
    base = out_dir.resolve().as_posix() + "/"
    new, n = re.subn(r'^base_path = "output/"', f"base_path = {base!r}", src, count=1, flags=re.M)
    if n != 1:
        raise RuntimeError("config.py de MaRE inattendu (ligne base_path introuvable)")
    new += f"""

# ---- surcharges cadastre-napoleonien/georef_auto/test_mare.py ----
proj_map = {L93!r}      # rendu OSM en Lambert-93 (conforme), pas en lon/lat
proj_sheets = {L93!r}
proj_out = {L93!r}      # .wld en mètres Lambert-93
sheet_name_field = "blatt_100"
osm_image_size = [1000, 500]  # neutralise le ratio 2:1 codé en dur pour la KDR100 (osm.paint_features)
save_transform = True
registration_mode = {registration!r}
"""
    if osm_url:
        new += f"osm_url = {osm_url!r}\n"
    if osm_query_file:
        new += f"osm_query = {Path(osm_query_file).read_text(encoding='utf-8')!r}\n"
    cfg_dir = out_dir / "_mare_config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.py").write_text(new, encoding="utf-8")

    sys.path[:0] = [str(cfg_dir), str(Path(mare_dir).resolve())]
    # MaRE importe `imp`, retiré en Python 3.12
    if "imp" not in sys.modules:
        shim = types.ModuleType("imp")
        shim.reload = importlib.reload
        sys.modules["imp"] = shim
    # scikit-image récent : ransac(random_state=) devenu ransac(rng=), et un échec
    # d'estimation renvoie un objet FailedEstimation au lieu de None (MaRE plante dessus)
    import inspect
    import skimage.measure
    orig_ransac = skimage.measure.ransac
    rng_kw = "random_state" not in inspect.signature(orig_ransac).parameters

    def ransac(*a, random_state=None, **kw):
        kw["rng" if rng_kw else "random_state"] = random_state
        model, inliers = orig_ransac(*a, **kw)
        if model is None or not hasattr(model, "params"):
            return None, None
        return model, inliers
    skimage.measure.ransac = ransac
    import config
    for d in (config.path_output, config.path_osm, config.reference_descriptors_folder,
              config.reference_keypoints_folder):
        Path(d).mkdir(parents=True, exist_ok=True)
    return config


def read_wld(path):
    A, D, B, E, C, F = (float(x) for x in Path(path).read_text().split())
    return np.array([[A, B, C], [D, E, F]])


def evaluate(m, out_dir, scale):
    """Erreur aux GCP : pixel image -> pixel recalé (inverse de la matrice ECC) -> Lambert-93 (.wld)."""
    tfile = out_dir / f"transform_{m['id']}.npy"
    wlds = sorted(out_dir.glob(f"aligned_{m['id']}_*.wld"))
    if not tfile.exists() or not wlds:
        return None
    M = np.load(tfile)
    M3 = np.vstack([M, [0, 0, 1]]) if M.shape == (2, 3) else M
    p = np.c_[m["px"] * scale, np.ones(len(m["px"]))]
    q = (np.linalg.inv(M3) @ p.T).T
    q = q[:, :2] / q[:, 2:3]
    geo = (read_wld(wlds[-1]) @ np.c_[q, np.ones(len(q))].T).T
    return np.linalg.norm(geo - m["xy"], axis=1)


def evaluate_ransac(m, res, img_w, scale, config):
    """Erreur aux GCP de la seule transformation RANSAC de la recherche, géoréférencée correctement.

    En mode `ransac`, MaRE écrit un .wld dont le cadre est calculé dans le repère de
    l'image source et non de l'image recalée (registration.align_map_image_model) :
    exact seulement pour une transformation proche de l'identité (feuilles nord en
    haut, bien cadrées). Ici on recompose : pixel requête -> pixel référence -> L93.
    """
    bbox, _, _, T = res
    if T is None or bbox is None:
        return None
    k = config.process_image_width / img_w           # image téléchargée -> taille de traitement
    p = np.c_[m["px"] * scale * k, np.ones(len(m["px"]))]
    r = (np.linalg.inv(np.asarray(T, float)) @ p.T).T  # T : référence -> requête
    r = r[:, :2] / r[:, 2:3]
    x0, y0, x1, y1 = bbox
    mpp = (x1 - x0) / config.index_img_width_train   # m par pixel de la référence indexée
    geo = np.c_[x0 + r[:, 0] * mpp, y1 - r[:, 1] * mpp]
    return np.linalg.norm(geo - m["xy"], axis=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mare", required=True, help="clone local de github.com/luftj/MaRE")
    ap.add_argument("--collection", default=str(HERE.parent / "web/annotations/collection.json"))
    ap.add_argument("--out", default="sortie_mare")
    ap.add_argument("--only", default="", help="ids Allmaps séparés par des virgules")
    ap.add_argument("--width", type=int, default=3000, help="largeur de téléchargement des images (px)")
    ap.add_argument("--prior", choices=["commune", "oracle"], default="commune")
    ap.add_argument("--margin", type=float, default=0.3, help="marge autour de l'emprise des GCP (prior commune)")
    ap.add_argument("--decoys", type=int, default=8, help="feuilles leurres voisines par plan (0-8)")
    ap.add_argument("-r", type=int, default=30, help="hypothèses vérifiées par MaRE (son -r)")
    ap.add_argument("--osm-url", default=None, help="instance Overpass (défaut : celle de MaRE)")
    ap.add_argument("--osm-query", default=None, help="fichier contenant une requête Overpass de remplacement")
    ap.add_argument("--registration", choices=["both", "ransac", "ecc"], default="both",
                    help="mode de recalage MaRE (both = ECC initialisé par RANSAC, son défaut)")
    ap.add_argument("--rebuild-index", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    maps = load_maps(args.collection, only)
    print(f"{len(maps)} plans géoréférencés Allmaps chargés")

    config = setup_mare(args.mare, out_dir, args.osm_url, args.osm_query, args.registration)
    sheets_path = out_dir / "feuilles_l93.geojson"
    write_sheets(maps, args.prior, args.margin, args.decoys, sheets_path)

    import indexing
    if args.rebuild_index or not Path(config.reference_index_path).exists():
        print("Construction de l'index OSM (Overpass, peut être long)…")
        indexing.build_index(str(sheets_path))

    import main as mare_main
    captured = {}
    orig_retrieve = mare_main.retrieve_best_match_index

    def retrieve_spy(*a, **kw):
        res = orig_retrieve(*a, **kw)
        captured["res"] = res
        return res
    mare_main.retrieve_best_match_index = retrieve_spy

    rows = []
    for m in maps:
        row = dict(id=m["id"], carte=m["name"], n_gcp=len(m["px"]),
                   rotation_deg=round(rotation_deg(m["px"], m["xy"]), 1))
        loo = loo_affine_rmse(m["px"], m["xy"])
        row["plancher_affine_m"] = round(loo, 1) if loo is not None else ""
        captured.clear()
        for old in [*out_dir.glob(f"aligned_{m['id']}_*"), *out_dir.glob(f"*_{m['id']}.npy")]:
            old.unlink()  # pas de relecture d'un résultat d'une exécution précédente
        t0 = time.time()
        try:
            img_path, w = fetch_image(m, args.width, out_dir / "images")
            scale = w / m["full_w"]
            mare_main.process_sheet(str(img_path), str(sheets_path), img=True, ground_truth_name=m["id"],
                                    restrict=args.r, debug=True)
            res = captured.get("res")
            if res and res[2]:
                ranking = [s[-1] for s in res[2]]
                row["rang_recherche"] = ranking.index(m["id"]) + 1 if m["id"] in ranking else "absent"
                row["inliers"] = int(res[1])
                errs_r = evaluate_ransac(m, res, w, scale, config)
                if errs_r is not None:
                    row["ransac_corrige_mediane_m"] = round(float(np.median(errs_r)), 1)
            else:
                row["rang_recherche"] = "non vérifié"
            errs = evaluate(m, out_dir, scale)
            if errs is None:
                row["statut"] = "échec (recherche ou recalage)"
            else:
                row["statut"] = "recalé"
                row["erreur_mediane_m"] = round(float(np.median(errs)), 1)
                row["rmse_m"] = round(float(np.sqrt(np.mean(errs ** 2))), 1)
                row["erreur_max_m"] = round(float(errs.max()), 1)
        except Exception as e:  # noqa: BLE001 — on veut un bilan complet même si un plan plante
            row["statut"] = f"erreur : {type(e).__name__}: {e}"[:200]
        row["duree_s"] = round(time.time() - t0, 1)
        rows.append(row)
        print(row)

    cols = ["id", "carte", "n_gcp", "rotation_deg", "rang_recherche", "inliers", "statut",
            "erreur_mediane_m", "rmse_m", "erreur_max_m", "ransac_corrige_mediane_m", "plancher_affine_m",
            "duree_s"]
    with open(out_dir / "resultats_mare.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, cols)
        wr.writeheader()
        wr.writerows(rows)
    print("\n| " + " | ".join(cols[1:]) + " |\n|" + "---|" * (len(cols) - 1))
    for r in rows:
        print("| " + " | ".join(str(r.get(c, "")) for c in cols[1:]) + " |")
    ok = [r for r in rows if r.get("statut") == "recalé" and r.get("erreur_mediane_m", 1e9) < 50]
    print(f"\nRecalés à < 50 m (médiane) : {len(ok)}/{len(rows)}")


if __name__ == "__main__":
    main()
