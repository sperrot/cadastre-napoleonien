# Géoréférencement automatique — évaluation de MaRE

Question : le dépôt [luftj/MaRE](https://github.com/luftj/MaRE) (thèse HCU Hamburg,
2023) peut-il géoréférencer automatiquement les plans du cadastre napoléonien de
notre collecte ?

**Réponse courte : non, pas en l'état.** MaRE est pensé pour un autre type de
carte, et deux de ses limites touchent directement nos plans. On peut en
reprendre l'idée (recaler l'hydrographie du plan sur OSM), mais pas l'utiliser
tel quel. Le détail ci-dessous, puis le banc de test pour le vérifier sur nos
vrais plans.

## Ce que fait MaRE

1. Segmente le **bleu** du plan (cours d'eau, étangs).
2. Cherche la bonne feuille dans un **tableau d'assemblage connu d'avance**
   (grille de feuilles d'une série topographique, ex. Karte des Deutschen
   Reiches 1:100 000). Il compare des descripteurs KAZE du plan avec ceux des
   rendus OSM de chaque feuille, puis vérifie par RANSAC (similitude).
3. Affine le recalage par ECC (affine) et écrit l'image recalée + un `.wld`.

## Pourquoi ça ne colle pas à nos plans

| # | Point | Constat |
|---|---|---|
| 1 | **Rotation** | MaRE utilise des descripteurs KAZE *upright*, non invariants en rotation. Sur nos 15 plans géoréférencés dans Allmaps, **5 sont tournés de plus de 20°** (23°, −31°, 60°, 91°, 91°) et 1 de 14° (tableau ci-dessous). Test synthétique : la mise en correspondance tient jusqu'à ~15°, l'erreur est de 72 m à 1,1 km à 20°, et ça échoue au-delà de 30°. |
| 2 | **Sortie fausse dès que le plan n'est pas « droit et plein cadre »** | En mode `ransac`, le cadre écrit dans le `.wld` est calculé dans le repère de l'image *source* et non de l'image *recalée* (`registration.align_map_image_model`). C'est sans effet sur des feuilles nord en haut bien cadrées (le cas de la thèse), mais l'erreur atteint 400 m à 5° et 1,1 km à 15°, alors que la transformation RANSAC elle-même est bonne à 8–24 m. Le mode par défaut (`both`, ECC initialisé par RANSAC) a un cadre correct, mais l'ECC **dérive** dans tous nos essais synthétiques : 400 m à 1,8 km d'erreur, là où RANSAC seul est meilleur. |
| 3 | **Pas de grille de feuilles** | Le cadastre n'est pas une série à carroyage. On connaît en revanche **la commune** de chaque plan, ce qui rend l'étape de recherche presque inutile. La difficulté est le recalage, et c'est justement la partie fragile (points 1-2). |
| 4 | **Peu de signal** | Seul le bleu sert. Nos tableaux d'assemblage n'occupent que 10 à 50 % de l'image (médiane ≈ 0,3, le reste est marge, cartouche et légende). Beaucoup de communes ont peu d'eau, et les feuilles de section (1/1 250 – 1/2 500) n'en montrent presque pas. |
| 5 | **Licence et maintenance** | Pas de licence (« get in touch » : on ne peut pas intégrer le code sans accord de l'auteur). `simple_cb.py` est un code tiers non licencié. Dernier commit en août 2023. Incompatible avec Python ≥ 3.12 (`imp`), OpenCV 5 (`KAZE_create`) et scikit-image récent (`ransac`) : contourné dans notre banc sans toucher à MaRE. |

## Ce qui a été testé ici

### 1. Nos 15 géoréférencements Allmaps (données réelles)

`analyse_gcp_allmaps.py` lit `web/annotations/collection.json` et ajuste les GCP
(pixel → Lambert-93). Résultat complet : [`gcp_allmaps_analyse.csv`](gcp_allmaps_analyse.csv).

| plan | GCP | m/px | rotation | affine LOO (m) | part image utile |
|---|---|---|---|---|---|
| FRAD025_3P178_01 | 21 | 0,85 | 0° | 12 | 0,16 |
| FRAD088_…88116_3P5056_1 | 60 | 1,67 | 1° | 22 | 0,14 |
| FRAD025_3P122_01 | 49 | 1,70 | 2° | 25 | 0,28 |
| FRAD025_3P623_01 | 5 | 0,22 | **23°** | (42) | 0,51 |
| AD071_0362_3PA_07976_D | 21 | 0,85 | **−31°** | 14 | 0,48 |
| FRAD025_3P80_01 | 42 | 1,70 | 0° | 24 | 0,10 |
| FRAD025_3P630_01 | 17 | 0,85 | **60°** | 32 | 0,32 |
| FRAD025_3P27_01 | 8 | 0,86 | 0° | (44) | 0,16 |
| FRAD088_…88500_3P5440_1 | 41 | 0,83 | −1° | 15 | 0,34 |
| FRAD095_3P_3290 | 42 | 1,28 | −14° | 15 | 0,21 |
| AD093CA_2047W_0049_C | 3 | 1,30 | −2° | — | 0,27 |
| AD093CA_2047W_0121_C | 6 | 0,68 | 0° | (19) | 0,50 |
| FRAD088_…88451_3P5391_1 | 9 | 0,83 | **91°** | (96) | 1,00 |
| AD093CA_2047W_0563_C | 4 | 1,12 | −1° | — | 0,13 |
| AD093CA_2047W_0012_C | 11 | 1,28 | **91°** | 101 | 0,34 |

- **Rotation** : 5/15 plans au-delà de ce que MaRE tolère.
- **Affine LOO** : erreur en validation croisée (on retire un point) d'un modèle
  affine global, c'est-à-dire le modèle de sortie de MaRE. Il vaut **12 à 32 m**
  sur les plans bien saisis. C'est le plancher que MaRE ne peut pas battre ;
  au-delà, Allmaps en TPS / polynôme fait mieux. Valeurs entre parenthèses :
  moins de 10 GCP, peu fiables.
- **Part image utile** : surface du masque Allmaps / surface de l'image.

### 2. MaRE sur un plan synthétique (hors réseau)

`test_synthetique.py` fabrique un plan dont la vérité est connue (rivières bleues,
bâti rouge, traits noirs, 3 m/px), avec une rotation choisie, puis lance MaRE
avec un OSM synthétique. **Ce sont des chiffres synthétiques, pas des résultats
sur nos plans.** Ils mesurent le comportement de la méthode dans un cas
favorable.

Emprise « oracle » (feuille = emprise exacte de l'image), `--registration ransac` :

| rotation | inliers | erreur sortie MaRE | erreur RANSAC recomposée |
|---|---|---|---|
| 0° | 62 | 37 m | 21 m |
| 5° | 52 | 415 m | 8 m |
| 10° | 38 | 776 m | 11 m |
| 15° | 17 | 1,1 km | 24 m |
| 20° | 5 | 3,1 km | 1,1 km |
| 30° | 8 | 13,8 km | 6,5 km |
| 45° / 60° / 90° | — | échec | échec |

Emprise « commune » (emprise des GCP + 30 %, cas réaliste) : 132 m (sortie
MaRE) contre 4,5 m (RANSAC recomposé) à 0°, et 337 m contre 1,5 m à 10°. Le mode
par défaut `both` (ECC) donne 584 m et 1,8 km.

### 3. MaRE sur nos vrais plans : **pas exécuté ici**

L'environnement d'exécution n'a pas accès aux serveurs IIIF des AD ni à
Overpass (politique réseau). Le banc `test_mare.py` est prêt et validé de bout
en bout sur le cas synthétique. **À lancer en local** :

```bash
git clone https://github.com/luftj/MaRE.git ../../MaRE
python -m venv .venv && . .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements-mare.txt

# les 15 plans, mode par défaut de MaRE, 8 feuilles leurres par plan
python test_mare.py --mare ../../MaRE --out sortie_mare

# le cas le plus favorable : plans nord en haut, bien saisis (≥ 20 GCP), sortie RANSAC
python test_mare.py --mare ../../MaRE --out sortie_mare_ransac --registration ransac \
    --only 258f6ed109ae27b5,c26b2cc241446bda,d5b9f30c24c0baeb,3b55c34b8af7d73a,61f192b21527751a
```

Pour chaque plan, le banc télécharge l'image IIIF, construit la « feuille »
(emprise de la commune ≈ GCP + marge, ou `--prior oracle`) et des feuilles
leurres voisines, indexe OSM, lance MaRE, puis mesure l'erreur aux GCP Allmaps.
Colonnes de `sortie_mare/resultats_mare.csv` :

- `rang_recherche` : rang de la bonne feuille parmi les candidates.
- `erreur_mediane_m`, `rmse_m` : erreur de la **sortie MaRE** (image + `.wld`).
- `ransac_corrige_mediane_m` : erreur de la transformation RANSAC de MaRE,
  géoréférencée sans le défaut du point 2. C'est ce que vaudrait la méthode une
  fois ce défaut corrigé.
- `plancher_affine_m` : meilleur résultat possible avec un affine (voir § 1).

À regarder aussi : `sortie_mare/debug/maskimg_<id>.png`. Si le masque bleu est
vide ou bruité, la segmentation (`segmentation_steps` dans le `config.py` de
MaRE) n'est pas adaptée aux lavis du cadastre.

## Recommandation

- **Ne pas adopter MaRE** comme outil de géoréférencement du projet, pour les
  raisons ci-dessus, et parce que sans licence on ne peut pas l'intégrer.
- **Allmaps reste la voie de production.**
- Piste plus prometteuse pour pré-placer les plans automatiquement : partir de ce
  qu'on sait déjà, **la commune**. Le tableau d'assemblage trace la limite
  communale, souvent proche de la limite actuelle (geo.api.gouv.fr). Un
  recalage de forme invariant en rotation (contour du TA contre contour actuel)
  donnerait une position initiale, à affiner ensuite dans Allmaps. Le banc
  ci-dessus (vérité terrain + métriques) peut servir à évaluer cette piste de
  la même façon.
