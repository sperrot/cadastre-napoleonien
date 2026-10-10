"""Contours communaux IGN (ADMIN EXPRESS), en Lambert-93, avec cache disque.

Sources :
- "wfs" : Géoplateforme IGN, ADMIN EXPRESS COG à jour (production). Couche et champ
  configurables (WFS_TYPENAME, WFS_CHAMP_INSEE) : à confirmer à la première exécution réelle.
- "france-geojson" : github.com/gregoiredavid/france-geojson = ADMIN EXPRESS COG 2018
  simplifié (visvalingam 25 %). Sert au banc et au développement hors Géoplateforme.
- chemin d'un fichier GeoJSON local (propriété "code" ou "insee_com" + géométrie WGS84).

Un contour est renvoyé comme liste d'anneaux extérieurs (np.ndarray Nx2, mètres L93).
"""
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

WFS_URL = "https://data.geopf.fr/wfs/ows"
WFS_TYPENAME = "ADMINEXPRESS-COG.LATEST:commune"
WFS_CHAMP_INSEE = "insee_com"
FG_RAW = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master"
UA = {"User-Agent": "Mozilla/5.0 (cadastre-napoleonien georef_auto)"}

_to_l93 = None


def _l93(coords):
    global _to_l93
    if _to_l93 is None:
        from pyproj import Transformer
        _to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    a = np.asarray(coords, float)
    return np.c_[_to_l93.transform(a[:, 0], a[:, 1])]


def anneaux(geometry, projeter=True):
    """Anneaux extérieurs d'un Polygon/MultiPolygon GeoJSON (trous ignorés)."""
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [_l93(p[0]) if projeter else np.asarray(p[0], float) for p in polys]


def _get_json(url, cache, params=None):
    import requests
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = requests.get(url, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text, encoding="utf-8")
    return r.json()


def _slug(code, nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return f"{code}-" + re.sub(r"[^a-z0-9]+", "-", s).strip("-")


class Contours:
    def __init__(self, source="france-geojson", cache_dir="cache_contours"):
        self.source = source
        self.cache = Path(cache_dir)
        self._deps = None
        self._communes = {}  # code département -> features (france-geojson)

    # ---------------------------------------------------------------- france-geojson
    def _departements(self):
        if self._deps is None:
            gj = _get_json(f"{FG_RAW}/departements.geojson", self.cache / "fg_departements.geojson")
            self._deps = [(f["properties"]["code"], f["properties"]["nom"], anneaux(f["geometry"]))
                          for f in gj["features"]]
        return self._deps

    def _communes_dep(self, code, nom):
        if code not in self._communes:
            slug = _slug(code, nom)
            gj = _get_json(f"{FG_RAW}/departements/{slug}/communes-{slug}.geojson",
                           self.cache / f"fg_communes_{code}.geojson")
            self._communes[code] = gj["features"]
        return self._communes[code]

    def commune_au_point(self, x, y):
        """(insee, nom) de la commune contenant le point L93 (france-geojson, COG 2018)."""
        for code, nom, rings in self._departements():
            if any(_dedans(r, x, y) for r in rings):
                for f in self._communes_dep(code, nom):
                    if any(_dedans(r, x, y) for r in anneaux(f["geometry"])):
                        return f["properties"]["code"], f["properties"]["nom"]
        return None, None

    # ---------------------------------------------------------------------- public
    def contour(self, insee):
        if self.source == "wfs":
            params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                      "typeNames": WFS_TYPENAME, "outputFormat": "application/json",
                      "srsName": "EPSG:2154",  # évite l'ambiguïté d'ordre lat/lon du WFS 2.0
                      "cql_filter": f"{WFS_CHAMP_INSEE}='{insee}'"}
            gj = _get_json(WFS_URL, self.cache / f"wfs_{insee}.geojson", params)
            feats = gj.get("features", [])
            if feats:
                return [r for f in feats for r in anneaux(f["geometry"], projeter=False)]
        elif self.source == "france-geojson":
            dep = insee[:3] if insee.startswith("97") else insee[:2]
            nom = next(n for c, n, _ in self._departements() if c == dep)
            feats = [f for f in self._communes_dep(dep, nom) if f["properties"]["code"] == insee]
        else:
            gj = json.loads(Path(self.source).read_text(encoding="utf-8"))
            feats = [f for f in gj["features"]
                     if insee in (f["properties"].get("code"), f["properties"].get(WFS_CHAMP_INSEE))]
        if not feats:
            raise LookupError(f"commune {insee} absente de la source {self.source}")
        return [r for f in feats for r in anneaux(f["geometry"])]


def _dedans(ring, x, y):
    """Point dans polygone (parité des croisements)."""
    xs, ys = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = ((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / (yj - ys + 1e-12) + xs)
    return bool(np.count_nonzero(cross) % 2)
