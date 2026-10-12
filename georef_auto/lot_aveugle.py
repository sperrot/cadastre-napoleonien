"""Lot à l'aveugle : recalage_chanfrein sur des tableaux d'assemblage SANS vérité terrain, puis
page de validation visuelle (ok / faux / illisible) pour construire la vérité terrain du fonds.

Sources (catalogue local, pas de base) :
  25  download/cadastre-napoleonien_doubs.json — la page _01 de chaque cote est le TA ;
      INSEE par le nom de commune (contours IGN du département, homonymes exclus).
  39  harvest/seed_jura.sql — lignes type 'tableau_assemblage' avec INSEE.

Images : JPEG open data servi en IIIF par le worker (/static-iiif), 2000 px, en cache.

    python lot_aveugle.py --dept 25 --n 30 --dpi 300 --denominateurs 5000,10000,20000
    python lot_aveugle.py --dept 39 --n 30 --dpi 137.5 --denominateurs 5000,10000
    python lot_aveugle.py --page          # régénère seulement validation.html (tous les lots)

Sorties dans --out (défaut sortie_lot/) : lot_<dept>.csv (statut, échelle déduite, pose pixel
pleine résolution -> L93), apercus/<dept>_<insee>.jpg, validation.html. La page garde les
réponses dans le navigateur et les exporte en CSV (bouton) : à déposer dans georef_auto/.
"""
import argparse
import csv
import html
import json
import re
import time
import unicodedata
import warnings
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from communs import fetch_image
from contours_ign import Contours
from recalage_chanfrein import recaler_image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKER = "https://iiif-allmaps.sperrot.workers.dev/static-iiif/"
warnings.filterwarnings("ignore", category=UserWarning)


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s.replace("saint", "st").replace("sainte", "ste")).strip()


def catalogue(dept, contours):
    """Liste de dict(insee, commune, cote, image_url) des TA du département."""
    feats = contours._communes_dep(dept, next(n for c, n, _ in contours._departements() if c == dept))
    noms = {}
    for f in feats:
        noms.setdefault(_norm(f["properties"]["nom"]), []).append((f["properties"]["code"], f["properties"]["nom"]))
    out = []
    if dept == "25":
        for it in json.loads((ROOT / "download/cadastre-napoleonien_doubs.json").read_text(encoding="utf-8")):
            url = it.get("file_path") or ""
            m = re.search(r"/(FRAD025_(3P\d+)_01)\.jpg$", url)
            hits = noms.get(_norm(it.get("unittitle") or ""), [])
            if m and len(hits) == 1:
                out.append(dict(insee=hits[0][0], commune=hits[0][1], cote=m.group(2), image_url=url))
    elif dept == "39":
        pat = re.compile(r"values \('(\d{5})', 'tableau_assemblage', [^,]+, '([^']*)', '[^']*', '([^']+\.jpg)'")
        nom = {c: n for v in noms.values() for c, n in v}
        for line in (ROOT / "harvest/seed_jura.sql").read_text(encoding="utf-8").splitlines():
            m = pat.search(line)
            if m and m.group(1) in nom:
                out.append(dict(insee=m.group(1), commune=nom[m.group(1)], cote=m.group(2), image_url=m.group(3)))
    else:
        raise SystemExit(f"département {dept} non câblé")
    # un TA par commune (le premier)
    vus, uniq = set(), []
    for d in out:
        if d["insee"] not in vus:
            vus.add(d["insee"])
            uniq.append(d)
    return uniq


def apercu(img, M_px_l93, rings, statut, texte, chemin, largeur=1400):
    """Image réduite + contour IGN posé (pose pixel 2000 px -> L93 inversée)."""
    f = largeur / img.shape[1]
    vis = cv2.resize(img, (largeur, int(img.shape[0] * f)), interpolation=cv2.INTER_AREA)
    Minv = np.linalg.inv(M_px_l93)
    coul = {"calé": (40, 170, 40), "probable": (0, 150, 230)}.get(statut, (40, 40, 220))
    for r in rings:
        q = (np.c_[r, np.ones(len(r))] @ Minv.T)[:, :2] * f
        cv2.polylines(vis, [np.round(q).astype(np.int32)], True, (255, 255, 255), 6)
        cv2.polylines(vis, [np.round(q).astype(np.int32)], True, (200, 60, 0), 3)
    cv2.rectangle(vis, (0, 0), (largeur, 40), (255, 255, 255), -1)
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()  # OpenCV : pas d'accents
    cv2.putText(vis, texte, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, coul, 2)
    cv2.imwrite(str(chemin), vis, [cv2.IMWRITE_JPEG_QUALITY, 82])


COLS = ["dept", "insee", "commune", "cote", "statut", "contraste", "ecart_2e", "couverture", "angle_deg",
        "m_par_px_plein", "echelle_deduite", "largeur_px", "duree_s", "pose_plein_l93", "image_url", "apercu"]


def reglages(args):
    """Paramètres de recaler_image passés en ligne de commande."""
    return dict(pas_angle=args.pas_angle, diam_min=args.diam_min, saturation=args.saturation, debord=args.debord)


def traiter_un(d, args, out):
    """Recale un TA (dict du catalogue) et renvoie la ligne du CSV."""
    src = Contours(args.contours, HERE / "sortie_chanfrein/cache_contours")      # contour à poser
    denoms = [int(x) for x in args.denominateurs.split(",")]
    row = dict(dept=args.dept, **d)
    t0 = time.time()
    try:
        m = dict(id=f"{args.dept}_{d['insee']}", service=WORKER + quote(d["image_url"], safe=""))
        path, w = fetch_image(m, 2000, out / "images")
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        rings = src.contour(d["insee"])
        # échelles candidates en m/px de l'image 2000 px : la pleine résolution est inconnue
        # ici (pas de manifeste lu) -> on la lit dans info.json
        full_w = largeur_pleine(m["service"]) or w
        k = full_w / w
        ech = [dd * 0.0254 / args.dpi * j * k for dd in denoms for j in (0.97, 1.0, 1.03)]
        r = recaler_image(img, rings, ech, **reglages(args))
        if r is None:
            row["statut"] = "aucune pose"
        else:
            mpx = r["m_par_px"] / k
            M = r["M"] @ np.diag([1 / k, 1 / k, 1])
            row.update(statut=r["statut"], contraste=round(r["contraste"], 2), ecart_2e=round(r["ecart_2e"], 2),
                       couverture=round(r["couverture"], 2), angle_deg=round(r["angle_deg"], 1),
                       m_par_px_plein=round(mpx, 3), echelle_deduite=int(round(mpx / 0.0254 * args.dpi, -2)),
                       largeur_px=full_w, pose_plein_l93=json.dumps(np.round(M[:2], 6).tolist()))
            ap = f"apercus/{args.dept}_{d['insee']}.jpg"
            apercu(img, r["M"], rings, r["statut"],
                   f"{d['commune']} ({d['insee']})  {r['statut']}  ecart {r['ecart_2e']:.2f}  1/{row['echelle_deduite']}",
                   out / ap)
            row["apercu"] = ap
    except Exception as ex:  # noqa: BLE001
        row["statut"] = f"erreur : {type(ex).__name__}: {ex}"[:160]
    row["duree_s"] = round(time.time() - t0, 1)
    print({k_: row.get(k_) for k_ in ("insee", "commune", "statut", "ecart_2e", "echelle_deduite", "duree_s")}, flush=True)
    return row


def traiter(args):
    out = Path(args.out)
    (out / "apercus").mkdir(parents=True, exist_ok=True)
    cont = Contours("france-geojson", HERE / "sortie_contour/cache_contours")   # noms -> INSEE
    cat = catalogue(args.dept, cont)
    exclus = set(args.exclure.split(",")) if args.exclure else set()
    cat = [c for c in cat if c["insee"] not in exclus]
    rng = np.random.default_rng(args.seed)
    choix = [cat[i] for i in rng.permutation(len(cat))[:args.n]]
    if args.insee:
        voulus = args.insee.split(",")
        choix = [c for c in cat if c["insee"] in voulus]
    print(f"{args.dept} : {len(cat)} TA au catalogue, {len(choix)} tirés", flush=True)
    fichier = out / f"lot_{args.dept}.csv"
    deja = {}
    if fichier.exists():
        deja = {r["insee"]: r for r in csv.DictReader(open(fichier, encoding="utf-8"))}
    a_faire = [d for d in choix if not (d["insee"] in deja and deja[d["insee"]].get("statut"))]
    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(args.jobs) as ex:
            faits = dict(zip([d["insee"] for d in a_faire], ex.map(traiter_un, a_faire, [args] * len(a_faire), [out] * len(a_faire))))
    else:
        faits = {d["insee"]: traiter_un(d, args, out) for d in a_faire}
    rows = [faits.get(d["insee"]) or deja[d["insee"]] for d in choix]
    with open(fichier, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, COLS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    for s in ("calé", "probable", "à vérifier"):
        print(f"{s:>10} : {sum(r.get('statut') == s for r in rows)}/{len(rows)}")


_info = {}


def largeur_pleine(service):
    import requests
    if service not in _info:
        try:
            r = requests.get(service.rstrip("/") + "/info.json", timeout=60,
                             headers={"User-Agent": "Mozilla/5.0 (cadastre-napoleonien georef_auto)"})
            _info[service] = int(r.json()["width"])
        except Exception:  # noqa: BLE001
            _info[service] = None
    return _info[service]


def reapercus(out, contours="pci"):
    """Redessine les aperçus depuis les poses du CSV (images et contours en cache)."""
    src = Contours(contours, HERE / "sortie_chanfrein/cache_contours")
    for f in sorted(Path(out).glob("lot_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if not r.get("apercu"):
                continue
            img = cv2.imdecode(np.fromfile(str(Path(out) / "images" / f"{r['dept']}_{r['insee']}.jpg"), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            k = int(r["largeur_px"]) / img.shape[1]
            M = np.vstack([np.array(json.loads(r["pose_plein_l93"])), [0, 0, 1]]) @ np.diag([k, k, 1])
            apercu(img, M, src.contour(r["insee"]), r["statut"],
                   f"{r['commune']} ({r['insee']})  {r['statut']}  ecart {r['ecart_2e']}  1/{r['echelle_deduite']}",
                   Path(out) / r["apercu"])


def page(out):
    rows = []
    for f in sorted(Path(out).glob("lot_*.csv")):
        rows += [r for r in csv.DictReader(open(f, encoding="utf-8")) if r.get("apercu")]
    ordre = {"calé": 0, "probable": 1, "à vérifier": 2}
    rows.sort(key=lambda r: (r["dept"], ordre.get(r["statut"], 3), -float(r["ecart_2e"] or 0)))
    cartes = []
    for r in rows:
        cle = f"{r['dept']}_{r['insee']}"
        cartes.append(f"""
<article class="carte s{ordre.get(r['statut'], 3)}" data-cle="{cle}">
  <header><b>{html.escape(r['commune'])}</b> <span>{r['insee']} · {html.escape(r['cote'])}</span>
  <em>{r['statut']} · écart {r['ecart_2e']} · contraste {r['contraste']} · 1/{r['echelle_deduite']} · {r['angle_deg']}°</em></header>
  <a href="{r['apercu']}" target="_blank"><img loading="lazy" src="{r['apercu']}" alt="{html.escape(r['commune'])}"></a>
  <div class="choix">
    <label><input type="radio" name="{cle}" value="ok"> juste</label>
    <label><input type="radio" name="{cle}" value="approx"> à peu près (décalé)</label>
    <label><input type="radio" name="{cle}" value="faux"> faux</label>
    <label><input type="radio" name="{cle}" value="hs"> pas un TA / illisible</label>
  </div>
</article>""")
    donnees = json.dumps({f"{r['dept']}_{r['insee']}": {k: r[k] for k in ("dept", "insee", "commune", "cote", "statut", "ecart_2e", "contraste", "echelle_deduite")} for r in rows}, ensure_ascii=False)
    Path(out, "validation.html").write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Validation géoréf auto</title>
<style>
:root{{--fond:#f6f4ef;--carte:#fff;--texte:#222;--doux:#666;--ok:#2a8a2a;--prob:#d98a00;--ko:#c33}}
@media (prefers-color-scheme:dark){{:root{{--fond:#1b1b1b;--carte:#262626;--texte:#eee;--doux:#aaa}}}}
body{{margin:0;background:var(--fond);color:var(--texte);font:15px/1.4 system-ui,sans-serif}}
.bar{{position:sticky;top:0;z-index:2;background:var(--carte);padding:10px 16px;border-bottom:1px solid #8884;display:flex;gap:16px;flex-wrap:wrap;align-items:center}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,560px),1fr));gap:16px;padding:16px}}
.carte{{background:var(--carte);border-radius:8px;padding:10px;border-left:6px solid var(--ko)}}
.carte.s0{{border-left-color:var(--ok)}} .carte.s1{{border-left-color:var(--prob)}}
.carte.fait{{opacity:.55}}
header span,header em{{color:var(--doux);font-size:13px;margin-left:6px}} header em{{display:block;margin:0}}
img{{width:100%;height:auto;margin-top:6px;border-radius:4px}}
.choix{{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px}}
button{{font:inherit;padding:6px 12px}}
</style></head><body>
<div class="bar"><b>Contour IGN posé automatiquement</b><span id="compte"></span>
<span>Cliquer l'image pour l'agrandir.</span><button id="export">Exporter le CSV</button></div>
<main>{''.join(cartes)}</main>
<script>
const D={donnees};
const K='validation_georef_auto';
let rep={{}}; try{{rep=JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{}}
function maj(){{let n=0;document.querySelectorAll('.carte').forEach(c=>{{const v=rep[c.dataset.cle];c.classList.toggle('fait',!!v);if(v){{n++;const i=c.querySelector('input[value="'+v+'"]');if(i)i.checked=true}}}});
document.getElementById('compte').textContent=n+' / '+Object.keys(D).length+' validés'}}
document.addEventListener('change',e=>{{if(e.target.type!=='radio')return;rep[e.target.name]=e.target.value;try{{localStorage.setItem(K,JSON.stringify(rep))}}catch(_){{}};maj()}});
document.getElementById('export').onclick=()=>{{const cols=['dept','insee','commune','cote','statut','ecart_2e','contraste','echelle_deduite','verdict'];
const l=[cols.join(',')].concat(Object.entries(D).map(([k,r])=>cols.map(c=>c==='verdict'?(rep[k]||''):'"'+String(r[c]).replace(/"/g,'""')+'"').join(',')));
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([l.join('\\n')],{{type:'text/csv'}}));a.download='validation_lot.csv';a.click()}};
maj();
</script></body></html>""", encoding="utf-8")
    print(f"{out}/validation.html : {len(rows)} plans")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dept", choices=["25", "39"])
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dpi", type=float, default=300)
    ap.add_argument("--denominateurs", default="5000,10000,20000")
    ap.add_argument("--pas-angle", type=float, default=2.0)
    ap.add_argument("--diam-min", type=float, default=0.10, help="lot initial : 0.25")
    ap.add_argument("--saturation", type=float, default=0.3, help="0 = carte de traits brute (lot initial)")
    ap.add_argument("--debord", type=float, default=0.1, help="lot initial : 0")
    ap.add_argument("--insee", default="", help="ne traiter que ces INSEE (liste, pris dans tout le catalogue)")
    ap.add_argument("--jobs", type=int, default=1, help="plans traités en parallèle")
    ap.add_argument("--exclure", default="", help="INSEE à écarter (déjà en vérité terrain)")
    ap.add_argument("--out", default="sortie_lot")
    ap.add_argument("--contours", default="pci", help="pci (Parcellaire Express) | wfs | france-geojson")
    ap.add_argument("--page", action="store_true", help="régénère seulement validation.html")
    args = ap.parse_args()
    if not args.page:
        if not args.dept:
            ap.error("--dept requis")
        traiter(args)
    else:
        reapercus(args.out, args.contours)
    page(args.out)


if __name__ == "__main__":
    main()
