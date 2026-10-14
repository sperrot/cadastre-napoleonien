"""Contours communaux IGN (ADMIN EXPRESS), en Lambert-93, avec cache disque.

Sources :
- "pci" : Géoplateforme IGN, limite communale du Parcellaire Express (cadastre actuel, la
  même lignée que le napoléonien ; ~800 sommets pour Courvières). Source recommandée.
- "wfs" : Géoplateforme IGN, ADMIN EXPRESS COG à jour (~200 sommets pour Courvières).
- "france-geojson" : github.com/gregoiredavid/france-geojson = ADMIN EXPRESS COG 2018
  simplifié (visvalingam 25 %, ~50 sommets). Sert à trouver la commune d'un point (banc).
- chemin d'un fichier GeoJSON local (propriété "code" ou "insee_com" + géométrie WGS84).

Un contour est renvoyé comme liste d'anneaux extérieurs (np.ndarray Nx2, mètres L93).
Codes : « 39190 » (commune actuelle, source choisie) ; « a39017 » (ancienne commune, telle que
le cadastre actuel la garde : feuilles du Parcellaire Express hors communes absorbées depuis,
champ com_abs — Arlay sans Saint-Germain-lès-Arlay ; ou feuilles com_abs = 023 pour L'Aubépin,
absorbée) ; « a39005+a39190 » (TA commun à plusieurs communes : anneaux de chacune, limites
intérieures comprises).
"""
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

WFS_URL = "https://data.geopf.fr/wfs/ows"
WFS_COUCHES = {"wfs": "ADMINEXPRESS-COG.LATEST:commune", "pci": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:commune"}
WFS_CHAMP_INSEE = "code_insee"   # vérifié sur les deux couches le 2026-10-12
FG_RAW = "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master"
UA = {"User-Agent": "Mozilla/5.0 (cadastre-napoleonien georef_auto)"}
COG_BASE = "https://www.insee.fr/fr/statistiques/fichier/8377162/"
COG_COMMUNES, COG_MVT = "v_commune_depuis_1943.csv", "v_mvt_commune_2025.csv"
HERE = Path(__file__).resolve().parent

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

    # ------------------------------------------------------------ anciennes communes
    def _feuilles(self, cql, cle):
        params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                  "typeNames": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:feuille", "outputFormat": "application/json",
                  "srsName": "EPSG:2154", "count": 5000, "cql_filter": cql}
        return _get_json(WFS_URL, self.cache / f"feuilles_{cle}.geojson", params).get("features", [])

    def ancienne(self, insee):
        """Anneaux de l'ancienne commune (voir docstring du module), ou du contour courant si la
        commune n'a rien absorbé."""
        dep = insee[:3] if insee.startswith("97") else insee[:2]
        feats = self._feuilles(f"{WFS_CHAMP_INSEE}='{insee}'", insee)
        if feats and all(f["properties"]["com_abs"] == "000" for f in feats):
            return self.contour(insee)                       # rien d'absorbé : inchangé
        if feats:
            feats = [f for f in feats if f["properties"]["com_abs"] == "000"]
        else:                                                # commune absorbée depuis
            feats = self._feuilles(f"code_dep='{dep}' AND com_abs='{insee[len(dep):]}'", f"abs_{insee}")
        if not feats:
            raise LookupError(f"ancienne commune {insee} introuvable dans les feuilles du Parcellaire Express")
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
        # 0,5 m de dilatation-érosion : referme les interstices entre feuilles voisines
        u = unary_union([shape(f["geometry"]).buffer(0.5) for f in feats]).buffer(-0.5)
        return anneaux(mapping(u), projeter=False)

    def _cog(self, nom):
        """Fichier du COG INSEE : harvest/_cog/ (build_alias_insee.py) ou téléchargé en cache."""
        chemin = HERE.parent / "harvest/_cog" / nom
        if chemin.exists():
            return chemin.read_text(encoding="utf-8")
        import requests
        cache = self.cache / nom
        if not cache.exists():
            r = requests.get(COG_BASE + nom, headers=UA, timeout=120)
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(r.content)
        return cache.read_text(encoding="utf-8")

    def heritiere(self, code):
        """Commune qui a absorbé `code` (mouvements du COG, suivi transitif), ou None."""
        import csv, io
        if not hasattr(self, "_mvt"):
            self._mvt = {}
            for r in csv.DictReader(io.StringIO(self._cog(COG_MVT))):
                if r["TYPECOM_AV"] == "COM" and r["TYPECOM_AP"] == "COM" and r["COM_AV"] != r["COM_AP"]:
                    self._mvt.setdefault(r["COM_AV"], r["COM_AP"])
        vu = set()
        while code in self._mvt and code not in vu:
            vu.add(code)
            code = self._mvt[code]
        return code if vu else None

    def index_cog(self, dep):
        """Nom normalisé -> [(code, libellé)] de toutes les communes du département depuis 1943
        (COG INSEE), pour résoudre les noms anciens des inventaires."""
        import csv, io
        texte = self._cog(COG_COMMUNES)
        idx = {}
        for r in csv.DictReader(io.StringIO(texte)):
            if r["TYPECOM"] == "COM" and r["COM"].startswith(dep):
                v = idx.setdefault(cle_nom(r["LIBELLE"]), [])
                if r["COM"] not in [c for c, _ in v]:
                    v.append((r["COM"], r["LIBELLE"]))
        return idx

    # ---------------------------------------------------------------------- public
    def contour(self, insee):
        if "+" in insee:
            return [r for code in insee.split("+") for r in self.contour(code)]
        if insee.startswith("a"):
            return self.ancienne(insee[1:])
        if self.source in WFS_COUCHES:
            params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                      "typeNames": WFS_COUCHES[self.source], "outputFormat": "application/json",
                      "srsName": "EPSG:2154",  # évite l'ambiguïté d'ordre lat/lon du WFS 2.0
                      "cql_filter": f"{WFS_CHAMP_INSEE}='{insee}'"}
            gj = _get_json(WFS_URL, self.cache / f"{self.source}_{insee}.geojson", params)
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


def cle_nom(nom):
    """Nom de commune comparable : sans accents ni ponctuation, article entre parenthèses remis
    devant (« Aubépin (L') » -> « l aubepin »), saint/sainte abrégés, lès/lez -> les."""
    s = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\[.*?\]", "", s).strip()
    m = re.match(r"^(.*?),?\s*\((le|la|les|l)['\" ]*\)+\s*$", s)
    if m:
        s = f"{m.group(2)} {m.group(1)}"
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bsainte\b", "ste", re.sub(r"\bsaint\b", "st", s))
    s = re.sub(r"\b(les|lez)\b", "les", s)
    return " ".join(s.split())


def resoudre_nom(nom, index):
    """Nom ancien -> [(code, nom officiel)] dans l'index de Contours.index_cog(), ou [] : exact,
    puis sans article, sans complément « lès … », nom actuel complété, enfin graphie voisine
    (Thézy / Thésy) si unique. Plusieurs résultats = homonymes."""
    import difflib
    k = cle_nom(nom)
    essais = [k, re.sub(r"^(le|la|les|l) ", "", k), re.sub(r" (les|sur|sous) .*$", "", k)]
    for e in essais:
        if e in index:
            return index[e]
    # nom actuel complété : Saint-Hymetière -> Saint-Hymetière-sur-Valouse
    # (plusieurs : Vaux -> Vaux-lès-Saint-Claude, Vaux-sur-Poligny ; à départager par l'appelant)
    long_ = [i for i in index if i.startswith(k + " ")]
    if long_:
        return [h for i in long_ for h in index[i]]
    proches = difflib.get_close_matches(k, list(index), n=2, cutoff=0.88)
    if len(proches) == 1 or (len(proches) == 2 and difflib.SequenceMatcher(None, k, proches[0]).ratio()
                              - difflib.SequenceMatcher(None, k, proches[1]).ratio() > 0.05):
        return index[proches[0]]
    return []


def _dedans(ring, x, y):
    """Point dans polygone (parité des croisements)."""
    xs, ys = ring[:, 0], ring[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = ((ys > y) != (yj > y)) & (x < (xj - xs) * (y - ys) / (yj - ys + 1e-12) + xs)
    return bool(np.count_nonzero(cross) % 2)
