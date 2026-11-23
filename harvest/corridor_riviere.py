#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Corridor d'une rivière → communes riveraines + GeoJSON pour la carte.

Sert l'objectif « cadastre napoléonien de la rivière Drôme » : plutôt que de
moissonner tout un département, on cible les communes que la rivière traverse
ou longe, de la source à la confluence.

Sources (Géoplateforme IGN, WFS public, sans clé) :
  - BDTOPO_V3:cours_d_eau                      → tracé de la rivière
  - ADMINEXPRESS-COG.LATEST:commune            → communes actuelles
  - ADMINEXPRESS-COG.LATEST:commune_associee_ou_deleguee
                                               → anciennes communes encore
                                                 connues de l'IGN (ex. Aix-en-Diois)

Sorties :
  - harvest/corridor_<slug>.json        liste des communes (INSEE, nom, pk km,
                                        longueur riveraine, anciennes communes)
                                        → filtre de harvest_drome.py
  - web/data/riviere_<slug>.geojson     tracé simplifié + contours simplifiés
                                        des communes → calque de la carte

Usage :
    pip install requests shapely pyproj
    python harvest/corridor_riviere.py                       # la Drôme (défaut)
    python harvest/corridor_riviere.py --toponyme "la Drôme" --dept 26 \\
        --cleabs COURDEAU0000002000803141 --slug drome

Pourquoi --cleabs : BD TOPO porte plusieurs objets « la Drôme » (dont une
rivière homonyme du Calvados, et un tronçon partiel de 56 km). On retient
l'objet continu de 112,7 km, source (La Bâtie-des-Fonds) → Rhône (Livron/Loriol).
"""

import argparse
import json
import os
import sys
import warnings

import requests
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

warnings.filterwarnings("ignore", category=DeprecationWarning)

WFS = "https://data.geopf.fr/wfs/ows"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:                       # console Windows en cp1252
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def wfs(typename, cql):
    r = requests.get(WFS, params={
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": typename, "OUTPUTFORMAT": "application/json",
        "CQL_FILTER": cql}, timeout=180)
    r.raise_for_status()
    return r.json()["features"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--toponyme", default="la Drôme")
    ap.add_argument("--cleabs", default="COURDEAU0000002000803141",
                    help="objet BD TOPO retenu (sinon : le plus long du département)")
    ap.add_argument("--dept", default="26")
    ap.add_argument("--slug", default="drome")
    ap.add_argument("--tampon", type=float, default=100,
                    help="m : une commune à moins de cette distance du lit est retenue")
    ap.add_argument("--simplif", type=float, default=0.0002,
                    help="tolérance de simplification du GeoJSON (degrés, ~20 m)")
    args = ap.parse_args()

    to93 = Transformer.from_crs(4326, 2154, always_xy=True).transform

    cours = wfs("BDTOPO_V3:cours_d_eau", f"toponyme='{args.toponyme}'")
    if args.cleabs:
        cours = [f for f in cours if f["properties"]["cleabs"] == args.cleabs]
    if not cours:
        sys.exit(f"✖ aucun cours d'eau « {args.toponyme} » ({args.cleabs or 'tout'})")
    riv_f = max(cours, key=lambda f: transform(to93, shape(f["geometry"])).length)
    riv_wgs = shape(riv_f["geometry"])
    riv = transform(to93, riv_wgs)
    ligne = max(getattr(riv, "geoms", [riv]), key=lambda g: g.length)
    sys.stderr.write(f"{args.toponyme} : {riv_f['properties']['cleabs']} · "
                     f"{riv.length / 1000:.1f} km\n")

    communes = wfs("ADMINEXPRESS-COG.LATEST:commune",
                   f"code_insee_du_departement='{args.dept}'")
    deleguees = wfs("ADMINEXPRESS-COG.LATEST:commune_associee_ou_deleguee",
                    f"code_insee_de_la_commune_de_rattach LIKE '{args.dept}%'")
    zone = riv.buffer(args.tampon)

    anciennes = {}
    for f in deleguees:
        poly = transform(to93, shape(f["geometry"]))
        if poly.intersects(zone):
            p = f["properties"]
            anciennes.setdefault(p["code_insee_de_la_commune_de_rattach"], []).append(
                {"insee": p["code_insee"], "nom": p["nom_officiel"], "nature": p["nature"]})

    rows, feats = [], []
    for f in communes:
        poly = transform(to93, shape(f["geometry"]))
        if not poly.intersects(zone):
            continue
        p = f["properties"]
        pk = ligne.project(poly.intersection(zone).centroid) / 1000
        riveraine = round(poly.intersection(riv).length)
        row = {"insee": p["code_insee"], "nom": p["nom_officiel"], "pk_km": round(pk, 1),
               "longueur_riveraine_m": riveraine,
               "relation": "traversée" if riveraine else
                           f"bordière ({round(poly.distance(riv))} m)"}
        if p["code_insee"] in anciennes:
            row["anciennes_communes"] = anciennes[p["code_insee"]]
        rows.append(row)
        feats.append({"type": "Feature",
                      "properties": {"kind": "commune", "insee": row["insee"],
                                     "nom": row["nom"], "pk_km": row["pk_km"]},
                      "geometry": mapping(shape(f["geometry"]).simplify(args.simplif))})
    rows.sort(key=lambda r: r["pk_km"])

    feats.insert(0, {"type": "Feature",
                     "properties": {"kind": "riviere", "nom": args.toponyme,
                                    "longueur_km": round(riv.length / 1000, 1),
                                    "cleabs": riv_f["properties"]["cleabs"]},
                     "geometry": mapping(riv_wgs.simplify(args.simplif / 4))})

    meta = {"riviere": args.toponyme, "cleabs": riv_f["properties"]["cleabs"],
            "longueur_km": round(riv.length / 1000, 1), "departement": args.dept,
            "tampon_m": args.tampon,
            "source": "IGN — BD TOPO® (cours_d_eau) + ADMIN EXPRESS COG, Géoplateforme WFS",
            "communes": rows}
    out_json = os.path.join(HERE, f"corridor_{args.slug}.json")
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    out_geo = os.path.join(ROOT, "web", "data", f"riviere_{args.slug}.geojson")
    os.makedirs(os.path.dirname(out_geo), exist_ok=True)
    with open(out_geo, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"type": "FeatureCollection",
                   "attribution": "© IGN — BD TOPO®, ADMIN EXPRESS (Licence Ouverte 2.0)",
                   "features": feats}, fh, ensure_ascii=False, separators=(",", ":"))

    sys.stderr.write(f"→ {out_json}\n→ {out_geo} ({os.path.getsize(out_geo) // 1024} Ko)\n"
                     f"{len(rows)} communes riveraines :\n")
    for r in rows:
        anc = ", ".join(a["nom"] for a in r.get("anciennes_communes", []))
        sys.stderr.write(f"  pk {r['pk_km']:6.1f}  {r['insee']}  {r['nom']}"
                         f"{'  [' + anc + ']' if anc else ''}  — {r['relation']}\n")


if __name__ == "__main__":
    main()
