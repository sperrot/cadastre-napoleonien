"""Étape 1 : extraire l'enveloppe de la commune d'un tableau d'assemblage (image couleur).

1. Masque « encre » : pixels nettement plus sombres OU plus saturés que le papier
   environnant (fond estimé par flou médian, ce qui neutralise taches et jaunissement).
2. Nettoyage : effacement des longs traits droits (cadre, filets) et de la marge, suppression
   des aplats sombres au bord (hors papier) et des encadrés rectangulaires (cartouche).
3. Région de la commune, deux méthodes :
   - "contour" : remplissage des zones fermées par le trait (limite communale continue) ;
   - "densite" : la commune est la zone où l'encre est dense (sections, chemins, bâti),
     le dehors est du papier quasi vierge — tolère une limite discontinue.
4. Ouverture morphologique pour couper les excroissances étroites (routes sortantes),
   plus grande composante, contour extérieur.
"""
import cv2
import numpy as np


def _impair(x):
    x = max(int(x), 3)
    return x if x % 2 else x + 1


def masque_encre(img, seuil_sombre=0.8, seuil_sat=40):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    W = img.shape[1]
    k = _impair(W / 40)
    fond = cv2.medianBlur(gray, k)
    norm = cv2.divide(gray, fond, scale=255)
    sombre = norm < 255 * seuil_sombre
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    colore = cv2.subtract(sat, cv2.medianBlur(sat, k)) > seuil_sat
    encre = (sombre | colore).astype(np.uint8)
    return cv2.morphologyEx(encre, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def _remplir(mask):
    """Bouche les trous (zones fermées) d'un masque binaire."""
    h, w = mask.shape
    pad = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy()
    cv2.floodFill(ff, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 1)
    return (pad | (1 - ff))[1:-1, 1:-1]


def nettoyer(encre, rect_max=0.92):
    H, W = encre.shape
    # cadre et filets : longs traits droits horizontaux/verticaux, effacés (sans toucher au reste,
    # une limite communale peut être reliée au cadre par une route)
    h = cv2.morphologyEx(encre, cv2.MORPH_OPEN, np.ones((1, W // 4), np.uint8))
    v = cv2.morphologyEx(encre, cv2.MORPH_OPEN, np.ones((H // 4, 1), np.uint8))
    filets = cv2.dilate(h | v, np.ones((5, 5), np.uint8))
    encre = encre & (1 - filets)
    m = max(int(0.01 * W), 2)
    encre[:m], encre[-m:], encre[:, :m], encre[:, -m:] = 0, 0, 0, 0   # marge de numérisation
    joint = cv2.morphologyEx(encre, cv2.MORPH_CLOSE, np.ones((_impair(W / 400),) * 2, np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joint, connectivity=8)
    garde = np.ones(n, bool)
    garde[0] = False
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if (x <= m or y <= m or x + w >= W - m or y + h >= H - m) and area > 0.3 * w * h:
            garde[i] = False                       # aplat sombre au bord (hors papier)
        elif w > 0.1 * W or h > 0.1 * H:
            comp = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
            plein = _remplir(comp)
            cnts, _ = cv2.findContours(plein, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            c = max(cnts, key=cv2.contourArea)
            (_, _), (rw, rh), _ = cv2.minAreaRect(c)
            if rw * rh > 0 and cv2.contourArea(c) / (rw * rh) > rect_max:
                garde[i] = False                   # cartouche / encadré rectangulaire
    return (garde[lab] & (encre > 0)).astype(np.uint8)


def _plus_grande(mask):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    return (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)


def extraire_enveloppe(img, methode="densite", largeur=1600, debug=None):
    """Contour extérieur (Nx2, pixels de l'image d'entrée) de la commune, ou None."""
    f = largeur / img.shape[1]
    small = cv2.resize(img, (largeur, int(img.shape[0] * f)), interpolation=cv2.INTER_AREA)
    W = largeur
    encre = nettoyer(masque_encre(small))
    if methode == "contour":
        ferme = cv2.morphologyEx(encre, cv2.MORPH_CLOSE, np.ones((_impair(W / 150),) * 2, np.uint8))
        region = _remplir(ferme)
        k_open = _impair(W / 80)
    else:
        dens = cv2.blur(encre.astype(np.float32), (_impair(W / 25),) * 2)
        d8 = cv2.normalize(dens, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, region = cv2.threshold(d8, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        region = _remplir(cv2.morphologyEx(region, cv2.MORPH_CLOSE, np.ones((_impair(W / 30),) * 2, np.uint8)))
        # le flou étale la zone dense d'environ un demi-noyau : on le reprend
        region = cv2.erode(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_impair(W / 25),) * 2))
        k_open = _impair(W / 20)
    region = _plus_grande(region)
    if region is None:
        return None
    region = cv2.morphologyEx(region, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open,) * 2))
    region = _plus_grande(region)
    if region is None:
        return None
    cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)[:, 0, :].astype(float)
    if debug is not None:
        vis = small.copy()
        vis[encre > 0] = (vis[encre > 0] * 0.4 + np.array([0, 0, 255]) * 0.6).astype(np.uint8)
        cv2.polylines(vis, [c.astype(np.int32)], True, (255, 0, 0), 3)
        cv2.imwrite(str(debug), vis)
    return c / f
