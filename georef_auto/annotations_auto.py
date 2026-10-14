"""Annotations de géoréférencement Allmaps des TA calés automatiquement (lot_aveugle.py), pour le
calque « Cadastre napoléonien — Géoréf en cours » du site.

Retenus : tout plan posé sauf le verdict « faux » sur un plan « à vérifier » (vrai échec, géoréf
manuel nécessaire). Verdict « approx » = limite légèrement changée, géoréférencement juste.
Verdict « faux » sur un plan calé ou probable = commune actuelle plus grande qu'à l'époque :
pose juste, masque trop grand (le contour actuel, rogné au cadre de l'image).

Par plan : la pose (similitude pixel pleine résolution -> Lambert-93) donne 9 points de calage
(grille sur le masque) et une transformation polynomiale d'ordre 1, qui la reproduit exactement ;
le masque est le contour posé (ancienne commune, union des communes d'un TA commun), simplifié.

    python annotations_auto.py --lots lot_aveugle_39_v3.csv,lot_aveugle_39_sans_insee.csv \
        --verdict validation_lot_v3.csv --sortie ../web/annotations/ta_auto_jura.json --fusion

--fusion remet dans web/annotations/collection.json (le calque ne lit qu'une AnnotationPage) les
annotations de TOUS les ta_auto_*.json (Jura, Doubs…), sans toucher aux plans calés à la main ; harvest/refresh_georef_status.py les
reprend à chaque régénération.
"""
import argparse
import csv
import json
from pathlib import Path
from urllib.parse import quote

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from contours_ign import Contours
from lot_aveugle import WORKER, code_contour, largeur_pleine

HERE = Path(__file__).resolve().parent
MANIFESTE = "https://iiif-allmaps.sperrot.workers.dev/static-manifest?u="
CTX = ["http://iiif.io/api/extension/georef/1/context.json", "http://iiif.io/api/presentation/3/context.json"]
ID_BASE = "https://sperrot.github.io/cadastre-napoleonien/annotations/auto/"
to_wgs = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def taille_image(service, cache, cache_f=None):
    """(largeur, hauteur) pleine résolution, lues dans info.json (en cache). Le worker peut mettre
    plus d'une minute sur un gros JPEG pas encore vu : 3 essais, 180 s chacun."""
    if service not in cache:
        import requests
        dernier = None
        for _ in range(3):
            try:
                r = requests.get(service.rstrip("/") + "/info.json", timeout=180,
                                 headers={"User-Agent": "Mozilla/5.0 (cadastre-napoleonien georef_auto)"})
                j = r.json()
                cache[service] = [int(j["width"]), int(j["height"])]
                break
            except Exception as ex:  # noqa: BLE001
                dernier = ex
        else:
            raise RuntimeError(f"info.json inaccessible : {dernier}")
        if cache_f is not None:
            cache_f.write_text(json.dumps(cache), encoding="utf-8")
    return cache[service]


def masque_px(rings, M, W, H, simpl_m=5.0):
    """Contour L93 -> polygone pixel (pleine résolution), une seule pièce, rogné à l'image."""
    poly = unary_union([Polygon(r).buffer(0) for r in rings]).buffer(1).buffer(-1)
    poly = poly.simplify(simpl_m)
    if poly.geom_type == "MultiPolygon":
        grand = max(poly.geoms, key=lambda g: g.area)
        poly = grand if grand.area > 0.9 * poly.area else poly.convex_hull
    Minv = np.linalg.inv(M)
    q = (np.c_[np.asarray(poly.exterior.coords), np.ones(len(poly.exterior.coords))] @ Minv.T)[:, :2]
    p = Polygon(q).buffer(0).intersection(box(0, 0, W - 1, H - 1))
    if p.is_empty:
        return None
    if p.geom_type != "Polygon":
        p = max(p.geoms, key=lambda g: g.area)
    return np.asarray(p.exterior.coords)[:-1]


def annotation(r, rings, taille):
    W, H = taille
    M = np.vstack([np.array(json.loads(r["pose_plein_l93"])), [0, 0, 1]])      # pixel -> L93
    pts = masque_px(rings, M, W, H)
    if pts is None or len(pts) < 3:
        pts = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], float)
    # 9 points de calage : grille 3x3 sur l'emprise du masque
    lo, hi = pts.min(0), pts.max(0)
    g = np.array([[x, y] for y in np.linspace(lo[1], hi[1], 3) for x in np.linspace(lo[0], hi[0], 3)])
    xy = (np.c_[g, np.ones(len(g))] @ M.T)[:, :2]
    lon, lat = to_wgs.transform(xy[:, 0], xy[:, 1])
    service = WORKER + quote(r["image_url"], safe="")
    man = MANIFESTE + quote(r["image_url"], safe="")
    ident = f"{r['dept']}_{r['insee']}_{r['cote']}".replace("+", "-")
    svg = " ".join(f"{int(round(x))},{int(round(y))}" for x, y in pts)
    return {
        "id": ID_BASE + ident,
        "type": "Annotation",
        "@context": CTX,
        "motivation": "georeferencing",
        "target": {
            "type": "SpecificResource",
            "source": {"id": service, "type": "ImageService2", "width": W, "height": H,
                       "partOf": [{"id": man + "/canvas/1", "type": "Canvas",
                                   "label": {"none": [r["commune"]]},
                                   "partOf": [{"id": man, "type": "Manifest", "label": {"none": [r["commune"]]}}]}]},
            "selector": {"type": "SvgSelector", "value": f'<svg width="{W}" height="{H}"><polygon points="{svg}" /></svg>'},
        },
        "body": {
            "type": "FeatureCollection",
            "transformation": {"type": "polynomial", "options": {"order": 1}},
            "features": [{"type": "Feature", "properties": {"resourceCoords": [int(round(a)), int(round(b))]},
                          "geometry": {"type": "Point", "coordinates": [round(o, 7), round(t, 7)]}}
                         for (a, b), o, t in zip(g, lon, lat)],
        },
    }


def fusionner(collection):
    """Remet dans la page du calque les annotations de tous les fichiers ta_auto_*.json (un par
    département), sans doubler un plan calé à la main."""
    collection = Path(collection)
    page = json.loads(collection.read_text(encoding="utf-8"))
    garde = [it for it in page["items"] if not str(it.get("id", "")).startswith(ID_BASE)]
    deja = {it["target"]["source"]["id"] for it in garde}
    ajout = []
    for f in sorted(collection.parent.glob("ta_auto_*.json")):
        ajout += [it for it in json.loads(f.read_text(encoding="utf-8"))["items"]
                  if it["target"]["source"]["id"] not in deja]
    page["items"] = garde + ajout
    collection.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    return len(garde), len(ajout)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lots", required=True, help="CSV de lot_aveugle.py, séparés par des virgules")
    ap.add_argument("--verdict", default="", help="CSV exporté de validation.html (facultatif)")
    ap.add_argument("--sortie", default=str(HERE.parent / "web/annotations/ta_auto_jura.json"))
    ap.add_argument("--fusion", action="store_true", help="ajouter aussi à web/annotations/collection.json")
    ap.add_argument("--contours", default="pci")
    args = ap.parse_args()

    verdict = ({(v["insee"], v["cote"]): v["verdict"] for v in csv.DictReader(open(args.verdict, encoding="utf-8"))}
               if args.verdict else {})
    src = Contours(args.contours, HERE / "sortie_chanfrein/cache_contours")
    cache_f = HERE / "sortie_chanfrein/cache_contours/info_json.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    items, ecartes, trop_grand, vus = [], [], [], set()
    for f in args.lots.split(","):
        for r in csv.DictReader(open(HERE / f.strip(), encoding="utf-8")):
            cle = (r["insee"], r["cote"])
            if not r.get("pose_plein_l93") or cle in vus:
                continue
            vus.add(cle)
            v = verdict.get(cle, "")
            if r["statut"] not in ("calé", "probable") and v not in ("ok", "approx"):
                ecartes.append(f"{r['commune']} ({r['statut']}, {v or 'sans verdict'})")
                continue
            service = WORKER + quote(r["image_url"], safe="")
            try:
                taille = taille_image(service, cache, cache_f)
                rings = src.contour(code_contour(r["insee"]))
                items.append(annotation(r, rings, taille))
            except Exception as ex:  # noqa: BLE001 — un plan en échec ne bloque pas le lot
                ecartes.append(f"{r['commune']} (erreur : {type(ex).__name__})")
                continue
            if v == "faux":
                trop_grand.append(r["commune"])
    cache_f.write_text(json.dumps(cache), encoding="utf-8")
    page = {"@context": "http://www.w3.org/ns/anno.jsonld", "type": "AnnotationPage", "items": items}
    Path(args.sortie).write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    print(f"{args.sortie} : {len(items)} TA, dont {len(trop_grand)} au masque trop grand ({', '.join(trop_grand)}) ; "
          f"{len(ecartes)} écartés : {', '.join(ecartes)}")
    if args.fusion:
        n_main, n_auto = fusionner(HERE.parent / "web/annotations/collection.json")
        print(f"collection.json : {n_main} plans calés à la main + {n_auto} TA automatiques")


if __name__ == "__main__":
    main()
