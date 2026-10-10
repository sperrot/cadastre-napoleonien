# Géoréférencement automatique

Deux approches évaluées sur nos plans déjà calés dans Allmaps :

1. [MaRE](#évaluation-de-mare) (recalage de l'hydrographie sur OSM) : **non retenu**.
2. [Recalage par contour communal](#recalage-par-contour-communal) (contour du tableau
   d'assemblage ↔ contour IGN de la commune) : **prometteur**, 10 plans sur 15 calés
   automatiquement à moins de 50 m à partir du contour, sans aucun faux positif.

## Évaluation de MaRE

Question : le dépôt [luftj/MaRE](https://github.com/luftj/MaRE) (thèse HCU Hamburg,
2023) peut-il géoréférencer automatiquement les plans du cadastre napoléonien de
notre collecte ?

**Réponse courte : non, pas en l'état.** MaRE est pensé pour un autre type de
carte, et deux de ses limites touchent directement nos plans. On peut en
reprendre l'idée (recaler l'hydrographie du plan sur OSM), mais pas l'utiliser
tel quel. Le détail ci-dessous, puis le banc de test pour le vérifier sur nos
vrais plans.

### Ce que fait MaRE

1. Segmente le **bleu** du plan (cours d'eau, étangs).
2. Cherche la bonne feuille dans un **tableau d'assemblage connu d'avance**
   (grille de feuilles d'une série topographique, ex. Karte des Deutschen
   Reiches 1:100 000). Il compare des descripteurs KAZE du plan avec ceux des
   rendus OSM de chaque feuille, puis vérifie par RANSAC (similitude).
3. Affine le recalage par ECC (affine) et écrit l'image recalée + un `.wld`.

### Pourquoi ça ne colle pas à nos plans

| # | Point | Constat |
|---|---|---|
| 1 | **Rotation** | MaRE utilise des descripteurs KAZE *upright*, non invariants en rotation. Sur nos 15 plans géoréférencés dans Allmaps, **5 sont tournés de plus de 20°** (23°, −31°, 60°, 91°, 91°) et 1 de 14° (tableau ci-dessous). Test synthétique : la mise en correspondance tient jusqu'à ~15°, l'erreur est de 72 m à 1,1 km à 20°, et ça échoue au-delà de 30°. |
| 2 | **Sortie fausse dès que le plan n'est pas « droit et plein cadre »** | En mode `ransac`, le cadre écrit dans le `.wld` est calculé dans le repère de l'image *source* et non de l'image *recalée* (`registration.align_map_image_model`). C'est sans effet sur des feuilles nord en haut bien cadrées (le cas de la thèse), mais l'erreur atteint 400 m à 5° et 1,1 km à 15°, alors que la transformation RANSAC elle-même est bonne à 8–24 m. Le mode par défaut (`both`, ECC initialisé par RANSAC) a un cadre correct, mais l'ECC **dérive** dans tous nos essais synthétiques : 400 m à 1,8 km d'erreur, là où RANSAC seul est meilleur. |
| 3 | **Pas de grille de feuilles** | Le cadastre n'est pas une série à carroyage. On connaît en revanche **la commune** de chaque plan, ce qui rend l'étape de recherche presque inutile. La difficulté est le recalage, et c'est justement la partie fragile (points 1-2). |
| 4 | **Peu de signal** | Seul le bleu sert. Nos tableaux d'assemblage n'occupent que 10 à 50 % de l'image (médiane ≈ 0,3, le reste est marge, cartouche et légende). Beaucoup de communes ont peu d'eau, et les feuilles de section (1/1 250 – 1/2 500) n'en montrent presque pas. |
| 5 | **Licence et maintenance** | Pas de licence (« get in touch » : on ne peut pas intégrer le code sans accord de l'auteur). `simple_cb.py` est un code tiers non licencié. Dernier commit en août 2023. Incompatible avec Python ≥ 3.12 (`imp`), OpenCV 5 (`KAZE_create`) et scikit-image récent (`ransac`) : contourné dans notre banc sans toucher à MaRE. |

### Ce qui a été testé ici

#### 1. Nos 15 géoréférencements Allmaps (données réelles)

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

#### 2. MaRE sur un plan synthétique (hors réseau)

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

#### 3. MaRE sur nos vrais plans : **pas exécuté ici**

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

### Recommandation

- **Ne pas adopter MaRE** comme outil de géoréférencement du projet, pour les
  raisons ci-dessus, et parce que sans licence on ne peut pas l'intégrer.
- **Allmaps reste la voie de production.**
- Piste retenue : le recalage par contour communal, ci-dessous.

---

## Recalage par contour communal

On connaît la commune de chaque plan. Le tableau d'assemblage (TA) trace sa limite, souvent
inchangée depuis 1830. On recale donc **l'enveloppe de la commune extraite du TA** sur le
**contour IGN actuel** de la même commune (ADMIN EXPRESS), sans OSM.

### Méthode

| Étape | Module | Principe |
|---|---|---|
| 1. Enveloppe | [`enveloppe.py`](enveloppe.py) | Masque « encre » (plus sombre ou plus saturé que le papier local). Effacement du cadre (longs traits droits), des marges et des encadrés rectangulaires (cartouche). Région de la commune par remplissage des zones fermées (`contour`) ou par densité d'encre (`densite`). Ouverture morphologique contre les routes sortantes, puis plus grande composante. Mode `auto` : essaie les deux et garde le meilleur recalage. |
| 2. Recalage | [`recalage_contour.py`](recalage_contour.py) | Initialisation invariante (centroïdes, rapport des aires, balayage de la rotation sur 360°). Puis ICP + **RANSAC** (similitude) avec tolérance décroissante : les morceaux qui ne collent pas (route, cartouche, limite modifiée) sortent comme aberrants. |
| 3. Confiance | idem | Part du contour à moins de la tolérance du contour IGN : **calé** ≥ 0,6, **probable** ≥ 0,45, sinon **à vérifier**. |
| Contours IGN | [`contours_ign.py`](contours_ign.py) | Géoplateforme WFS ADMIN EXPRESS COG (production, `--contours wfs`, couche à confirmer au premier appel réel) ou [france-geojson](https://github.com/gregoiredavid/france-geojson) (ADMIN EXPRESS COG 2018 simplifié, utilisé pour les essais ci-dessous). |

### Vérification préalable : contour de 1830 ≈ contour IGN ?

Masque Allmaps (limite tracée sur le TA, géoréférencée par les GCP) comparé au contour
IGN : **IoU de 0,94 à 0,98 pour 10 plans sur 15** (Doubs, Vosges, Saône-et-Loire,
Val-d'Oise), et 0,81–0,87 en Seine-Saint-Denis (urbanisation, limites retouchées).
Les autres plans n'ont pas de contour communal exploitable dans leur masque :
plan partiel (3P623), pas de masque (Senones), calage à 3 GCP douteux (Drancy 0049).

### Résultats

**Étape 2 sur données réelles** (`--source masque` : contour = masque Allmaps, erreur
mesurée aux GCP Allmaps). Détail : [`resultats_contour_masques.csv`](resultats_contour_masques.csv).

| plan | commune | rotation vraie | rotation estimée | inliers | statut | erreur médiane (m) | plancher affine (m) |
|---|---|---|---|---|---|---|---|
| FRAD025_3P178_01 | Courvières | 0° | 0° | 0,66 | calé | 14 | 12 |
| FRAD088_…88116_3P5056_1 | Cornimont | 1° | 1° | 1,00 | calé | 21 | 22 |
| FRAD025_3P122_01 | Chapelle-des-Bois | 2° | 3° | 0,94 | calé | 29 | 25 |
| FRAD025_3P623_01 | Villeneuve-d'Amont | 23° | 22° | 0,40 | à vérifier | 1 878 | 42 |
| AD071_0362_3PA_07976_D | Pruzilly | −31° | −30° | 0,69 | calé | 28 | 14 |
| FRAD025_3P80_01 | Boujailles | 1° | 0° | 0,88 | calé | 26 | 24 |
| FRAD025_3P630_01 | Villers-sous-Chalamont | 60° | 60° | 0,82 | calé | 42 | 32 |
| FRAD025_3P27_01 | Arc-sous-Montenot | 0° | 0° | 0,78 | calé | 48 | 44 |
| FRAD088_…88500_3P5440_1 | Ventron | −1° | −1° | 1,00 | calé | 23 | 15 |
| FRAD095_3P_3290 | Villiers-le-Bel | −15° | −14° | 0,84 | calé | 21 | 15 |
| AD093CA_2047W_0049_C | Drancy | 0° | −103° | 0,30 | à vérifier | 3 015 | — |
| AD093CA_2047W_0121_C | Drancy | 1° | 1° | 0,73 | calé | 17 | 19 |
| FRAD088_…88451_3P5391_1 | Senones | 91° | −60° | 0,28 | à vérifier | 4 862 | 96 |
| AD093CA_2047W_0563_C | Sevran | −2° | 4° | 0,40 | à vérifier | 136 | — |
| AD093CA_2047W_0012_C | Aulnay-sous-Bois | 89° | 91° | 0,66 | calé | 91 | 101 |

- **11 calés, dont 10 à moins de 50 m**, à une erreur comparable au plancher affine
  (la précision de la saisie Allmaps elle-même). Rotations de 60° et 90° retrouvées.
- Les 4 « à vérifier » sont exactement les plans sans contour communal utilisable : **le
  statut de confiance repère les échecs**.

**Robustesse (étape 3 simulée sur les contours réels)** :

| essai | calé | probable | à vérifier | faux positifs (calé > 100 m) |
|---|---|---|---|---|
| masques bruts | 11 | 0 | 4 | 0 |
| plan tourné au hasard (`--rotation-aleatoire`) | 11 | 0 | 4 | 0 |
| + 2 routes sortantes (`--parasites routes`) | 9 | 2 | 4 | 0 |
| + cartouche collé (`--parasites cartouche`) | 9 | 2 | 4 | 0 |
| + morceau de commune voisine (`--parasites voisine`) | 9 | 2 | 4 | 0 |
| les trois à la fois (IoU contour ≈ 0,8) | 5 | 5 | 5 | 0 |

Avec les trois défauts cumulés, les plans calés restent à 22–33 m. Le RANSAC écarte les
parasites, mais la confiance baisse et des plans passent en « probable » ou « à vérifier ».

**Étapes 1+2 sur TA synthétiques** (`--source synthetique` : TA dessiné depuis le
contour IGN, avec liseré, limite tiretée, sections, routes qui traversent le cadre,
noms de communes voisines, titre, cartouche, flèche du nord, double cadre) :
**15/15 calés, erreur médiane 18 m (max 38 m), IoU enveloppe médiane 0,97**, aussi bien
avec la rotation réelle de chaque plan qu'avec une rotation aléatoire. Ce sont des
images idéalisées : elles valident la chaîne, pas le comportement sur de vrais TA.

### Limites connues

- **Limites administratives modifiées** (fusion, commune nouvelle, échange de
  territoire) : on recale sur un contour qui n'est pas celui de 1830. Le RANSAC tolère un
  morceau différent ; au-delà, le plan passe en « à vérifier ». Communes nouvelles à
  traiter avec les communes déléguées (pas encore fait).
- **Feuilles de section** : elles ne montrent qu'une partie de la commune, la méthode
  ne s'applique qu'aux tableaux d'assemblage (cas de 3P623).
- **Précision** : modèle similitude (l'option `--modele affine` n'apporte rien sur nos
  plans). Le résultat est un pré-calage à 15–50 m, à affiner dans Allmaps.
- **Vrais TA non testés ici** (pas d'accès aux serveurs d'archives depuis
  l'environnement de travail). C'est l'étape 1 qui reste à valider.

### À lancer en local : étape 1 sur les vraies images

```bash
pip install -r requirements-mare.txt   # numpy, opencv, pyproj, scikit-image, requests suffisent
python banc_contour.py --source image --out sortie_contour
```

Le banc télécharge chaque TA en IIIF (2000 px), extrait l'enveloppe, recale et mesure
l'erreur aux GCP Allmaps. À regarder :

- `sortie_contour/resultats_contour.csv` : colonnes `iou_enveloppe` (enveloppe extraite
  contre masque Allmaps), `statut`, `erreur_mediane_m`, `methode` (contour/densite) ;
- `sortie_contour/debug/<id>_contour.jpg` et `<id>_densite.jpg` : encre détectée
  (rouge) et enveloppe retenue (bleu). Si l'enveloppe attrape le cadre, un cartouche ou
  rate la limite, c'est là qu'on le voit, pour ajuster `enveloppe.py`.

Autres options : `--contours wfs` (contours IGN à jour), `--methode contour|densite`,
`--only <ids Allmaps>`. Hors réseau : `--source masque` (étape 2) et
`--source synthetique` (étapes 1+2), avec `--rotation-aleatoire` et
`--parasites routes,cartouche,voisine`.
