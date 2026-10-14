"""Étape 2 : recaler un contour communal en pixels (tableau d'assemblage) sur le contour IGN (L93).

Modèle : similitude (échelle, rotation, translation), option affine en fin de course.
1. Initialisation invariante : centroïdes + rapport des aires (échelle), balayage de la
   rotation sur 360° et de quelques échelles ; score = chanfrein tronqué symétrique.
2. Affinage ICP + RANSAC : à chaque itération, appariement au plus proche dans les deux
   sens, similitude estimée par RANSAC (les morceaux qui ne collent pas — route sortante,
   cartouche, limite modifiée depuis 1830 — sortent comme aberrants), tolérance décroissante.
"""
import inspect

import numpy as np
from scipy.spatial import cKDTree
from skimage.measure import ransac
from skimage.transform import SimilarityTransform

FLIP = np.diag([1.0, -1.0, 1.0])  # image (y vers le bas) -> repère direct
_RANSAC_RNG = "rng" if "rng" in inspect.signature(ransac).parameters else "random_state"


def reechantillonner(ring, n=None, pas=None):
    """Points régulièrement espacés le long d'un anneau fermé (n points ou un pas donné)."""
    r = np.asarray(ring, float)
    if not np.allclose(r[0], r[-1]):
        r = np.vstack([r, r[:1]])
    seg = np.hypot(*np.diff(r, axis=0).T)
    cum = np.r_[0, np.cumsum(seg)]
    if n is None:
        n = max(int(cum[-1] / pas), 8)
    t = np.linspace(0, cum[-1], n, endpoint=False)
    return np.c_[np.interp(t, cum, r[:, 0]), np.interp(t, cum, r[:, 1])]


def aire_centroide(rings):
    A, C = 0.0, np.zeros(2)
    for r in rings:
        x, y = r[:, 0], r[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        cr = x * y1 - x1 * y
        a = cr.sum() / 2
        if abs(a) < 1e-9:
            continue
        c = np.array([((x + x1) * cr).sum(), ((y + y1) * cr).sum()]) / (6 * a)
        A += abs(a)
        C += abs(a) * c
    return A, C / A


def perimetre(rings):
    return sum(np.hypot(*np.diff(np.vstack([r, r[:1]]), axis=0).T).sum() for r in rings)


def appliquer(M, pts):
    q = np.c_[pts, np.ones(len(pts))] @ M.T
    return q[:, :2] / q[:, 2:3]


def _similitude(s, th, t):
    c, si = s * np.cos(th), s * np.sin(th)
    return np.array([[c, -si, t[0]], [si, c, t[1]], [0, 0, 1.0]])


def _ransac(src, dst, modele, tol, rng):
    kw = {_RANSAC_RNG: rng}
    model, inl = ransac((src, dst), modele, min_samples=3, residual_threshold=tol, max_trials=300, **kw)
    if model is None or not hasattr(model, "params") or inl is None:
        return None, None
    return model.params, inl


def recaler(contour_px, anneaux_l93, n=400, modele="similitude", pas_angle=2.0,
            echelles=(0.75, 0.87, 1.0, 1.15, 1.33), n_init=3, seuils=(0.6, 0.45)):
    """Renvoie un dict : M (3x3, pixel -> L93), part_inliers, residu_median_m, angle_deg,
    m_par_px, statut : 'calé' (part d'inliers >= seuils[0]), 'probable' (>= seuils[1]), 'à vérifier'."""
    P = reechantillonner(contour_px, n) * [1, -1]
    rings = [np.asarray(r, float) for r in anneaux_l93]
    aG, cG = aire_centroide(rings)
    aP, cP = aire_centroide([np.asarray(contour_px, float) * [1, -1]])
    D = np.sqrt(aG)                                   # taille caractéristique de la commune (m)
    perim = perimetre(rings)
    G_dense = np.vstack([reechantillonner(r, pas=perim / 4000) for r in rings])
    G_sub = np.vstack([reechantillonner(r, pas=perim / n) for r in rings])
    treeG = cKDTree(G_dense)

    def score(M, tau):
        Q = appliquer(M, P)
        d1, _ = treeG.query(Q)
        d2, _ = cKDTree(Q).query(G_sub)
        return 0.5 * (np.minimum(d1, tau).mean() + np.minimum(d2, tau).mean()) / tau

    # 1. initialisation : rotation x échelle, translation par les centroïdes
    s0 = np.sqrt(aG / aP)
    hyps = []
    for th in np.radians(np.arange(0, 360, pas_angle)):
        for k in echelles:
            R = _similitude(s0 * k, th, (0, 0))
            M = _similitude(s0 * k, th, cG - R[:2, :2] @ cP)
            hyps.append((score(M, 0.1 * D), M))
    hyps.sort(key=lambda h: h[0])
    # garde des hypothèses d'angles distincts
    retenues = []
    for sc, M in hyps:
        ang = np.arctan2(M[1, 0], M[0, 0])
        if all(abs((ang - a + np.pi) % (2 * np.pi) - np.pi) > np.radians(15) for _, _, a in retenues):
            retenues.append((sc, M, ang))
        if len(retenues) == n_init:
            break

    # 2. ICP + RANSAC, tolérance décroissante
    taus = [max(f * D, 10.0) for f in (0.1, 0.05, 0.025, 0.012)]
    rng = np.random.default_rng(0)
    meilleur = None
    for _, M, _ in retenues:
        for tau in taus:
            for _ in range(15):
                Q = appliquer(M, P)
                _, i1 = treeG.query(Q)
                _, i2 = cKDTree(Q).query(G_sub)
                src = np.vstack([P, P[i2]])
                dst = np.vstack([G_dense[i1], G_sub])
                Mn, inl = _ransac(src, dst, SimilarityTransform, tau, rng)
                if Mn is None:
                    break
                bouge = np.abs(appliquer(Mn, P) - Q).max()
                M = Mn
                if bouge < 0.05 * tau:
                    break
        tau = taus[-1]
        sc = score(M, tau)
        if meilleur is None or sc < meilleur[0]:
            meilleur = (sc, M, src, dst, inl)

    sc, M, src, dst, inl = meilleur
    if modele == "affine" and inl is not None and inl.sum() >= 6:
        sol, *_ = np.linalg.lstsq(np.c_[src[inl], np.ones(inl.sum())], dst[inl], rcond=None)
        M = np.vstack([sol.T, [0, 0, 1]])
    tau = taus[-1]
    Q = appliquer(M, P)
    d1, _ = treeG.query(Q)
    d2, _ = cKDTree(Q).query(G_sub)
    part = 0.5 * ((d1 < tau).mean() + (d2 < tau).mean())
    Mpx = M @ FLIP
    return dict(
        M=Mpx,
        part_inliers=float(part),
        residu_median_m=float(np.median(np.r_[d1, d2])),
        angle_deg=float(np.degrees(np.arctan2(Mpx[1, 0], Mpx[0, 0]))),
        m_par_px=float(np.sqrt(abs(np.linalg.det(Mpx[:2, :2])))),
        tolerance_m=float(tau),
        statut="calé" if part >= seuils[0] else "probable" if part >= seuils[1] else "à vérifier",
    )
