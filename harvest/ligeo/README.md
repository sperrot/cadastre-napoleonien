# Moisson des portails Ligeo — ce qu'il me faut, département par département

24 départements servent leur cadastre sur **Ligeo**. Deux sont faits (Charente,
Aisne) et la recette est stable, mais **elle ne se généralise pas toute seule** :
à chaque portail, ce qui coûte n'est pas le code, c'est la vérification. Voir
« Pourquoi une pré-vérification » plus bas.

## Ce que je demande, par département

Trois informations, et un fichier. Rien de plus — tout le reste (commune, année,
type de planche, URL d'image, dimensions) est lu dans les manifestes.

| # | Quoi | Pourquoi |
|---|---|---|
| 1 | **URL de la page de résultats** (page 1) | point de départ du collecteur |
| 2 | **URL de la page 2**, copiée depuis le navigateur | la grammaire de pagination Ligeo **n'est pas devinable** — sur l'Aisne elle insère un segment `/archive/` qui n'existe pas en page 1. Prouvé : quatre motifs plausibles testés, aucun ne marchait |
| 3 | **Nombre de résultats annoncé** | seul moyen de savoir si la collecte est complète |
| 4 | **`arks.tsv`** produit par le collecteur | la liste des arks |

Renseigner les colonnes correspondantes dans [`portails.csv`](portails.csv), et
déposer le TSV dans `depot/<code>-<nom>/arks.tsv`.

### Produire `arks.tsv`

1. Ouvrir la page de résultats dans un navigateur (les pages HTML sont sous
   **Anubis** — preuve de travail — et `robots.txt` interdit
   `/archive/resultats/*?*` : la collecte se fait donc **une fois**, depuis une
   session de navigateur légitime, et tout le reste passe par les endpoints
   IIIF ouverts).
2. Coller [`../aisne_collecte_arks.js`](../aisne_collecte_arks.js) dans la
   console. Il calibre la pagination, respecte le `Crawl-delay: 5`, reprend
   après coupure et télécharge le TSV.
3. Vérifier le compte affiché à la fin.

## Pourquoi une pré-vérification, et pas juste « lancer le script »

Sur l'Aisne, le premier run a résolu 625 communes sur 659 et produit un seed
d'apparence correcte. Creuser cet écart a révélé **quatre défauts**, dont trois
auraient corrompu les données en silence :

| Trouvé à la main | Effet si non vu |
|---|---|
| Le champ commune a **3 formes** ; dans l'une, le nom actuel est *dans* la parenthèse | 255 planches rattachées au nom de 1825 |
| 745 planches d'un **autre fonds** (E-Dépôt, sous-série 1 G) au motif de cote différent | 745 planches perdues |
| Le fonds mêle napoléonien et **cadastre rénové** (10 planches de 1929) | du cadastre de 1929 présenté comme napoléonien |
| geo.api mettait ses **échecs réseau en cache** | 7 planches disparues sur une coupure passagère |

D'où `seed_ligeo.py --check` (à venir) : il lit ~50 manifestes et imprime le
profil du fonds — formes du champ commune, familles d'identifiants, min/max des
années, CORS avec et sans `Origin`, tuilage de l'`info.json`, taux de résolution
INSEE. Une page à lire au lieu de plusieurs heures d'archéologie.

## Pièges déjà établis, valables pour tous les portails Ligeo

- **CORS invisible sans `Origin`.** L'en-tête `Access-Control-Allow-Origin: *`
  n'apparaît que si la requête en porte un. Tester sans → conclure à tort que le
  portail est inutilisable par Allmaps.
- **Le manifeste ne dit pas la licence.** L'Aisne renvoie « conditions fixées par
  le conseil départemental » alors que le service confirme Etalab 2.0. Ne jamais
  déduire `overlay_ok` du seul manifeste.
- **Ne pas dériver le chemin de l'image depuis la cote.** En Charente, la
  dérivation semblait exacte sur 28 échantillons et se trompait sur ~7 % du
  fonds. Toujours lire le service Image API dans le manifeste.
- **Le fonds peut être lacunaire.** Aisne : rien sur une partie de
  l'arrondissement de Château-Thierry. Ce n'est pas un bug de moisson.

## Cas particuliers de cette vague

- **79 Deux-Sèvres + 86 Vienne** partagent un portail. Une seule collecte, mais
  la résolution INSEE devra essayer les deux départements au lieu d'un —
  adaptation nécessaire avant de lancer.
- **56 Morbihan** est aussi couvert par l'open data de la Région Bretagne
  (contours vectorisés, N5). Le chantier Bretagne est suspendu : à trancher,
  moisson Ligeo maintenant ou attente de la solution régionale.
- **63 Puy-de-Dôme** et **07 Ardèche** : Ligeo **sans IIIF**. Pipeline différent
  (worker JPEG→IIIF, comme le Doubs). Mis de côté dans `depot/_sans_iiif/`.
  L'Ardèche n'a pas de licence confirmée.

## Après la moisson

```bash
python harvest/build_alias_insee.py --dept NN     # alias COG, une fois
python harvest/seed_ligeo.py --dept NN --check    # profil du fonds
python harvest/seed_ligeo.py --dept NN            # seed complet
python harvest/load_seed_to_supabase.py harvest/seed_NN.sql
python harvest/refresh_georef_status.py           # sans --dept : régénère le calque
```
