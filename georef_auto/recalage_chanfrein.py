"""Recalage du contour IGN directement sur l'encre du tableau d'assemblage, sans extraire d'enveloppe.

Principe (chanfrein dirigé IGN -> image) : on dessine le contour IGN de la commune à une échelle
supposée, on le fait tourner et glisser sur une carte « proximité de l'encre » de l'image, et on
garde la pose où le contour tombe le plus sur des traits. Seul ce sens est mesuré : l'encre en
trop (sections, chemins, lettrage, cartouche, carroyage) ne pénalise pas, et un trait pâle ou
tireté suffit s'il est au bon endroit.

1. Carte de traits continue : écart Lab au papier local (assombrissement + couleur, ce qui
   capte le liseré rose pâle et les traits gris clairs), moins sa version lissée (l'estompe du
   relief et les aplats ne sont pas des traits). Réduite par maximum, adoucie (σ), moins sa
   moyenne locale (une zone uniformément encrée — texte, bord du scanner — ne vaut rien).
2. Recherche exhaustive, image réduite : échelles candidates x rotations (pas 2°), translation
   par corrélation (cv2.matchTemplate, FFT). Score = moyenne de la carte le long du contour.
   La carte est saturée (un trait pâle pèse autant que le cartouche ou le lettrage noirs) et
   le contour peut déborder de l'image (commune actuelle plus grande que celle du TA).
3. Affinage des meilleures poses distinctes, image pleine : ICP modèle -> scène (point IGN ->
   pixel d'encre le plus proche) + RANSAC similitude, tolérance décroissante.
4. Confiance : couverture (part du contour IGN à moins de τ d'un trait) de la meilleure pose,
   moins celle de la 2e pose distincte après affinage (ecart_2e). calé ≥ 0,15, probable ≥ 0,10.
"""
import inspect

import cv2
import numpy as np
from skimage.measure import ransac
from skimage.transform import SimilarityTransform

from recalage_contour import reechantillonner

_RANSAC_RNG = "rng" if "rng" in inspect.signature(ransac).parameters else "random_state"
FLIP = np.diag([1.0, -1.0])


def _pose(s, th, t):
    """L93 centré -> pixel : p = s R(th) diag(1,-1) g + t. Renvoie la matrice 3x3."""
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    M = np.eye(3)
    M[:2, :2] = s * R @ FLIP
    M[:2, 2] = t
    return M


def _app(M, pts):
    return pts @ M[:2, :2].T + M[:2, 2]


def carte_traits(img, larg_trait=15):
    """Force de trait dans [0, 1] (float32, même taille que img, réglée pour ~2000 px de large)."""
    lab8 = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    k = (img.shape[1] // 40) | 1
    fond = np.dstack([cv2.medianBlur(lab8[:, :, i], k) for i in range(3)]).astype(np.float32)
    d = lab8.astype(np.float32) - fond
    # l'assombrissement compte, pas l'éclaircissement ; la couleur pèse double (liserés)
    de = np.sqrt(np.minimum(d[:, :, 0], 0) ** 2 + 2.0 * (d[:, :, 1] ** 2 + d[:, :, 2] ** 2))
    t = np.clip(de - cv2.blur(de, (larg_trait | 1,) * 2), 0, None)
    ref = np.percentile(t[t > 0], 99) if (t > 0).any() else 1.0
    t = np.clip(t / ref, 0, 1).astype(np.float32)
    # cadres, filets et méridienne : longs traits droits horizontaux / verticaux, effacés
    H, W = t.shape
    b = (t > 0.15).astype(np.uint8)
    h = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((1, W // 6), np.uint8))
    v = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((H // 6, 1), np.uint8))
    t[cv2.dilate(h | v, np.ones((7, 7), np.uint8)) > 0] = 0
    return t


def reduire_max(t, largeur):
    """Réduction qui conserve les traits fins (maximum local puis moyenne)."""
    f = largeur / t.shape[1]
    n = max(int(round(1 / f)), 1)
    t = cv2.dilate(t, np.ones((n, n), np.uint8))
    return cv2.resize(t, (largeur, int(t.shape[0] * f)), interpolation=cv2.INTER_AREA)


def carte_proximite(traits, sigma, fenetre):
    """Traits adoucis, centrés localement (float32)."""
    f = cv2.GaussianBlur(traits, (0, 0), sigma)
    k = int(fenetre) | 1
    return f - cv2.blur(f, (k, k))


def _distincts(cands, n, d_ang, d_pos):
    out = []
    for c in cands:
        if all(abs((c[1] - o[1] + 180) % 360 - 180) > d_ang or np.hypot(*(c[3] - o[3])) > d_pos for o in out):
            out.append(c)
        if len(out) == n:
            break
    return out


def recherche_grossiere(F, rings_c, echelles_px, pas_angle=2.0, diam_min=0.25, debord=0.0):
    """F : carte de proximité (image réduite). rings_c : anneaux L93 centrés.
    echelles_px : px (image réduite) par mètre. debord : part de la taille de l'image dont le
    contour peut dépasser de chaque côté (limite actuelle plus grande que celle du TA, feuille
    rognée). Renvoie les candidats triés (score, angle_deg, echelle, t(2,))."""
    pad = int(round(debord * max(F.shape)))
    if pad:
        F = cv2.copyMakeBorder(F, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    H, W = F.shape
    pts = np.vstack(rings_c)
    cands = []
    for s in echelles_px:
        for a in np.arange(0, 360, pas_angle):
            M = _pose(s, np.radians(a), (0, 0))
            q = [_app(M, r) for r in rings_c]
            allq = np.vstack(q)
            lo, hi = allq.min(0), allq.max(0)
            tw, th_ = int(np.ceil(hi[0] - lo[0])) + 3, int(np.ceil(hi[1] - lo[1])) + 3
            if tw >= W or th_ >= H or max(tw, th_) < diam_min * min(W - 2 * pad, H - 2 * pad):
                continue
            T = np.zeros((th_, tw), np.float32)
            cv2.polylines(T, [np.round(r - lo + 1).astype(np.int32) for r in q], True, 1.0, 1)
            n = T.sum()
            res = cv2.matchTemplate(F, T, cv2.TM_CCORR)
            _, mx, _, loc = cv2.minMaxLoc(res)
            t = np.array(loc, float) - lo + 1 - pad
            cands.append((mx / n, a, s, t))
    del pts
    cands.sort(key=lambda c: -c[0])
    return cands


def _ransac(src, dst, tol, rng):
    model, inl = ransac((src, dst), SimilarityTransform, min_samples=3, residual_threshold=tol,
                        max_trials=200, **{_RANSAC_RNG: rng})
    if model is None or inl is None:
        return None
    return model.params


def affiner(M, G, encre, taus, rng, iters=10):
    """ICP modèle -> scène : M (L93 centré -> pixel), G points IGN centrés (denses)."""
    d, lab = cv2.distanceTransformWithLabels((1 - encre).astype(np.uint8), cv2.DIST_L2, 5,
                                             labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(encre)
    # label -> coordonnées du pixel d'encre (labels numérotés dans l'ordre de balayage des zéros)
    zero_lab = lab[ys, xs]
    coord = np.zeros((lab.max() + 1, 2), np.float64)
    coord[zero_lab] = np.c_[xs, ys]
    H, W = encre.shape
    for tau in taus:
        for _ in range(iters):
            Q = _app(M, G)
            ok = (Q[:, 0] >= 0) & (Q[:, 1] >= 0) & (Q[:, 0] < W - 1) & (Q[:, 1] < H - 1)
            if ok.sum() < 10:
                return M
            qi = np.round(Q[ok]).astype(int)
            near = coord[lab[qi[:, 1], qi[:, 0]]]
            close = d[qi[:, 1], qi[:, 0]] < 2.5 * tau
            if close.sum() < 10:
                break
            # la similitude ne sait pas représenter la symétrie L93 (y vers le haut) -> pixel
            Mn = _ransac(G[ok][close] @ FLIP, near[close], tau, rng)
            if Mn is None:
                break
            Mn = Mn @ np.diag([1.0, -1.0, 1.0])
            bouge = np.abs(_app(Mn, G) - Q).max()
            M = Mn
            if bouge < 0.2:
                break
    return M


def couverture(M, G, dist, tau, decalage=0.0):
    """Part des points du contour (décalés de `decalage` px selon la normale) à moins de tau d'un trait."""
    H, W = dist.shape
    Q = _app(M, G)
    if decalage:
        t = np.roll(Q, -1, axis=0) - np.roll(Q, 1, axis=0)
        n = np.c_[-t[:, 1], t[:, 0]] / np.maximum(np.hypot(t[:, 0], t[:, 1]), 1e-9)[:, None]
        Q = Q + decalage * n
    Q = np.round(Q).astype(int)
    ok = (Q[:, 0] >= 0) & (Q[:, 1] >= 0) & (Q[:, 0] < W) & (Q[:, 1] < H)
    v = np.zeros(len(G), bool)
    v[ok] = dist[Q[ok, 1], Q[ok, 0]] < tau
    return v.mean()


def contraste(M, G, dist, tau, decalage):
    """Couverture sur le contour moins celle du contour décalé des deux côtés : une limite est
    encrée sur la ligne et pas à côté ; une zone de fouillis (texte, hachures) l'est partout."""
    cov = couverture(M, G, dist, tau)
    return cov - 0.5 * (couverture(M, G, dist, tau, decalage) + couverture(M, G, dist, tau, -decalage)), cov


def recaler_image(img, anneaux_l93, m_par_px, pas_angle=2.0, largeur_grossiere=800,
                  n_hyp=12, sigma=1.5, diam_min=0.10, seuil_trait=0.15, seuils=(0.15, 0.10),
                  saturation=0.3, debord=0.1, paliers=(8, 5, 3), debug=None):
    """img : BGR. anneaux_l93 : contour IGN. m_par_px : échelles candidates (mètres par pixel de
    img). diam_min : plus grande dimension minimale du contour posé (part du petit côté de
    l'image). saturation : force de trait au-delà de laquelle un trait compte plein dans la
    recherche grossière (0 = carte brute). debord : voir recherche_grossiere.
    Renvoie dict(M pixel->L93 3x3, couverture, z, ecart_2e, angle_deg, m_par_px, statut)."""
    rings = [np.asarray(r, float) for r in anneaux_l93]
    c = np.vstack(rings).mean(0)
    rings_c = [r - c for r in rings]
    H0, W0 = img.shape[:2]
    perim = sum(np.hypot(*np.diff(np.vstack([r, r[:1]]), axis=0).T).sum() for r in rings_c)

    # 1-2. recherche grossière
    f = largeur_grossiere / W0
    traits = carte_traits(img)
    # un trait pâle (liseré rose) au bon endroit doit peser autant que le cartouche ou le
    # lettrage noirs : sans saturation, ceux-ci attirent toutes les poses
    tg = np.minimum(traits / saturation, 1).astype(np.float32) if saturation else traits
    F = carte_proximite(reduire_max(tg, largeur_grossiere), sigma=sigma, fenetre=largeur_grossiere / 20)
    ech_s = [f / m for m in m_par_px]             # px réduits par mètre
    cands = recherche_grossiere(F, rings_c, ech_s, pas_angle, diam_min, debord)
    if not cands:
        return None
    diam = np.ptp(np.vstack(rings_c), axis=0).max()
    retenus = _distincts(cands, n_hyp, 15, 0.1 * largeur_grossiere)

    # 3. affinage, image pleine
    enc = (traits > seuil_trait).astype(np.uint8)
    dist = cv2.distanceTransform((1 - enc).astype(np.uint8), cv2.DIST_L2, 3)
    G = np.vstack([reechantillonner(r, pas=perim / 3000) for r in rings_c])
    rng = np.random.default_rng(0)
    k = W0 / 2000
    taus = [t * k for t in paliers]
    tau_f = taus[-1]
    resultats = []
    for sc, a, s, t in retenus:
        M = _pose(s / f, np.radians(a), t / f)
        M = affiner(M, G, enc, taus, rng)
        ctr, cv = contraste(M, G, dist, tau_f, 5 * tau_f)
        resultats.append((ctr, sc, M, cv))
    resultats.sort(key=lambda r: -r[0])
    ctr, sc, M, cov = resultats[0]

    # 4. confiance : même contour posé au hasard (rotation, translation) sur l'image
    s_fin = np.sqrt(abs(np.linalg.det(M[:2, :2])))
    hasard = []
    for _ in range(200):
        th = rng.uniform(0, 2 * np.pi)
        Mr = _pose(s_fin, th, (0, 0))
        q = _app(Mr, G)
        lo, hi = q.min(0), q.max(0)
        if hi[0] - lo[0] >= W0 or hi[1] - lo[1] >= H0:
            continue
        t = rng.uniform(-lo, [W0, H0] - hi)
        hasard.append(couverture(_pose(s_fin, th, t), G, dist, tau_f))
    hasard = np.array(hasard) if hasard else np.array([0.0, 0.01])
    z = (cov - hasard.mean()) / max(hasard.std(), 0.01)
    def _ang(M_):
        return np.degrees(np.arctan2(M_[1, 0], M_[0, 0]))

    autres = [r[0] for r in resultats[1:]
              if abs((_ang(r[2]) - _ang(M) + 180) % 360 - 180) > 10 or np.hypot(*(r[2][:2, 2] - M[:2, 2])) > 0.05 * W0]
    ecart = ctr - max(autres) if autres else ctr
    # une seule pose nettement meilleure que toutes les autres = calage fiable ; le z-score
    # (contour posé au hasard) ne discrimine pas sur nos plans, gardé pour information
    statut = "calé" if ecart >= seuils[0] else "probable" if ecart >= seuils[1] else "à vérifier"

    # pixel -> L93
    Minv = np.linalg.inv(M)
    T = np.eye(3)
    T[:2, 2] = c
    Mpx = T @ Minv
    if debug is not None:
        vis = img.copy()
        vis[enc > 0] = (vis[enc > 0] * 0.5 + np.array([0, 0, 255]) * 0.5).astype(np.uint8)
        for r in rings_c:
            cv2.polylines(vis, [np.round(_app(M, r)).astype(np.int32)], True, (255, 0, 0), max(int(2 * k), 2))
        cv2.putText(vis, f"cov {cov:.2f} z {z:.1f} ecart {ecart:.2f}", (20, int(50 * k)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2 * k, (0, 120, 0), max(int(3 * k), 2))
        cv2.imwrite(str(debug), vis)
    return dict(
        M=Mpx,
        couverture=float(cov),
        contraste=float(ctr),
        couverture_hasard=float(hasard.mean()),
        z=float(z),
        ecart_2e=float(ecart),
        score_grossier=float(sc),
        angle_deg=float(np.degrees(np.arctan2(Mpx[1, 0], Mpx[0, 0]))),
        m_par_px=float(np.sqrt(abs(np.linalg.det(Mpx[:2, :2])))),
        statut=statut,
    )
