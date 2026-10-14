"""Test hors réseau de MaRE via test_mare.py : plan et OSM synthétiques, rotation contrôlée.

Sert à (1) vérifier l'installation sans Overpass ni serveur IIIF, (2) mesurer la
tolérance de MaRE à la rotation du plan. Résultat synthétique : ne remplace pas
le test sur nos vrais plans.

    python test_synthetique.py --mare ../../MaRE --rot 10 --out synth_rot10 [options de test_mare.py]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer

HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--mare", required=True)
ap.add_argument("--rot", type=float, default=0.0, help="rotation du plan (degrés)")
ap.add_argument("--out", default="synth")
args, passthrough = ap.parse_known_args()

OUT = Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(0)
to_ll = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)

# « commune » de 6 x 4 km (Lambert-93), rivières sinueuses sur 3 x 3 communes
X0, Y0, CW, CH = 930000.0, 6680000.0, 6000.0, 4000.0
lines = []
for _ in range(14):
    x, y = X0 - CW + rng.uniform(0, 3 * CW), Y0 - CH
    ang = np.pi / 2 + rng.normal(0, 0.4)
    pts = []
    for _ in range(120):
        pts.append((x, y))
        ang += rng.normal(0, 0.25)
        x += 120 * np.cos(ang)
        y += 120 * np.sin(ang)
    lines.append(np.array(pts))
lakes = [np.array([(X0 + 2000 + 300 * np.cos(t), Y0 + 1500 + 200 * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 30)])]


def to_lonlat(a):
    lon, lat = to_ll.transform(a[:, 0], a[:, 1])
    return np.c_[lon, lat].tolist()


GJ = {"type": "FeatureCollection", "features":
      [{"type": "Feature", "properties": {"waterway": "river", "@id": f"w{i}"},
        "geometry": {"type": "LineString", "coordinates": to_lonlat(l)}} for i, l in enumerate(lines)]
      + [{"type": "Feature", "properties": {"natural": "water", "@id": "lake"},
          "geometry": {"type": "Polygon", "coordinates": [to_lonlat(l)]}} for l in lakes]}

# plan : 3000 x 2000 px, 3 m/px, tourné de --rot degrés ; papier, bâti rouge, traits noirs, eau bleue
W, H, S = 3000, 2000, 3.0
th = np.radians(args.rot)
cx, cy = X0 + CW / 2, Y0 + CH / 2


def l93_to_px(a):
    d = a - [cx, cy]
    u = (np.cos(th) * d[:, 0] + np.sin(th) * d[:, 1]) / S
    v = (np.sin(th) * d[:, 0] - np.cos(th) * d[:, 1]) / S
    return np.c_[u + W / 2, v + H / 2]


img = np.full((H, W, 3), (200, 225, 240), np.uint8)
for _ in range(400):
    p = rng.uniform([0, 0], [W, H]).astype(int)
    cv2.rectangle(img, tuple(p), tuple(p + rng.integers(5, 25, 2)), (90, 90, 200), -1)
for _ in range(150):
    p = rng.uniform([0, 0], [W, H]).astype(int)
    cv2.line(img, tuple(p), tuple(p + rng.integers(-200, 200, 2)), (40, 40, 40), 2)
for l in lines:
    cv2.polylines(img, [l93_to_px(l).astype(np.int32)], False, (210, 140, 60), 9)
for l in lakes:
    cv2.fillPoly(img, [l93_to_px(l).astype(np.int32)], (210, 140, 60))
cv2.rectangle(img, (0, 0), (W - 1, H - 1), (40, 40, 40), 20)

# 20 GCP « Allmaps » exacts dans la commune
gl93 = rng.uniform([X0, Y0], [X0 + CW, Y0 + CH], (20, 2))
gll = np.c_[to_ll.transform(gl93[:, 0], gl93[:, 1])]
mid = "synthetique0001"
coll = {"type": "AnnotationPage", "items": [{
    "id": f"https://annotations.allmaps.org/maps/{mid}",
    "target": {"source": {"id": "https://example.invalid/iiif/synthetique.jpg", "type": "ImageService2",
                          "width": W, "height": H}},
    "body": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"resourceCoords": p.tolist()},
         "geometry": {"type": "Point", "coordinates": g.tolist()}} for p, g in zip(l93_to_px(gl93), gll)]}}]}
(OUT / "collection.json").write_text(json.dumps(coll), encoding="utf-8")
(OUT / "images").mkdir(exist_ok=True)
cv2.imwrite(str(OUT / "images" / f"{mid}.jpg"), img)  # déjà en cache : pas de téléchargement

sys.path.insert(0, str(HERE))
import test_mare  # noqa: E402

orig_setup = test_mare.setup_mare


def setup_offline(*a, **kw):
    cfg = orig_setup(*a, **kw)
    import osm
    osm.get_from_osm = lambda bbox, url=None: json.loads(json.dumps(GJ))  # pas d'Overpass
    return cfg


test_mare.setup_mare = setup_offline
sys.argv = ["test_mare.py", "--mare", args.mare, "--collection", str(OUT / "collection.json"),
            "--out", str(OUT), "--width", str(W)] + passthrough
test_mare.main()
