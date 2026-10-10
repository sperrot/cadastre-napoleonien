"""Fonctions partagées des bancs de géoréférencement automatique (georef_auto/).

Vérité terrain = annotations Allmaps de web/annotations/collection.json :
GCP (pixel -> Lambert-93) et masque (polygone tracé sur l'image).
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote

import numpy as np

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
        sel = re.search(r'points="([^"]+)"', it["target"].get("selector", {}).get("value", ""))
        mask = np.array([[float(a) for a in p.split(",")] for p in sel.group(1).split()]) if sel else None
        name = unquote(re.sub(r"^https://iiif-allmaps\.sperrot\.workers\.dev/static-iiif/", "", src["id"])).rsplit("/", 1)[-1]
        maps.append(dict(id=mid, name=name, service=src["id"], service_type=src.get("type", ""),
                         full_w=src["width"], full_h=src["height"], px=px, xy=xy, mask=mask))
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


# ------------------------------------------------------------------------ images

def fetch_image(m, width, cache_dir):
    import cv2
    import requests
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{m['id']}.jpg"
    if not path.exists():
        base = m["service"].rstrip("/")
        hdr = {"User-Agent": "Mozilla/5.0 (cadastre-napoleonien georef_auto)"}
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
