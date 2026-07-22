# Harvester FranceArchives → Supabase

Récupère les **tableaux d'assemblage** (et autres plans) d'un fonds cadastre
sur FranceArchives, et produit des `INSERT` SQL pour la table `document`.

## Pourquoi en local ?

FranceArchives ne répond pas aux fetchs « serveur » (bot protection). Lancé
depuis ta machine, il répond normalement. Les manifestes/images **IIIF** des
AD (ex. Seine-Saint-Denis) sont accessibles partout.

## Installation

```bash
pip install requests rdflib
```

## Utilisation

```bash
# Seine-Saint-Denis — IR « Plans du cadastre »
python harvest_francearchives.py 2679af120dcec5557878b634c3701f842b1d806e > seed_ssd.sql

# Un sous-nœud précis (facomponent) plutôt que tout l'IR :
python harvest_francearchives.py 8c9077ce3826a2676417514c55903ae704aff91b facomponent > seed_ssd_cadastre.sql
```

Les logs de descente vont sur **stderr** (lisibles à l'écran), le SQL sur
**stdout** (redirigé vers le fichier).

Puis dans Supabase : exécuter `migration_0002_iiif_licence.sql` (une fois),
puis le `seed_*.sql` produit.

## Ce que fait le script

1. **Descend** récursivement l'arbre (`includesOrIncluded`) jusqu'aux feuilles.
2. Une feuille = notice portant un **manifeste IIIF**. Il en extrait :
   titre, type (`tableau_assemblage`/`section`/`feuille`), année, cote,
   commune (→ **INSEE** via geo.api.gouv.fr), manifeste, image (dao), service.
3. **Licence par institution** : lit **un** manifeste IIIF et cherche
   « Licence Ouverte / Etalab / CC-BY / domaine public ».
   - trouvé → `licence_overlay_ok = true`, `statut = 'georef'`
   - sinon → `À vérifier`, `statut = 'lien'` (overlay désactivé par prudence)

## À calibrer au 1er run (attendu)

- **Motif d'URL d'export RDF** : le script en essaie 4. Si aucun ne répond,
  copie le lien du bouton « RDF/XML » d'une notice et ajuste `fetch_graph`.
- **Nom de la source** : actuellement l'URI `service/NNNN` ; à mapper vers le
  libellé lisible (« Archives départementales de … ») pour la mention CRPA.
- **Communes anciennes/fusionnées** : INSEE parfois introuvable → listées en
  warning sur stderr, à reprendre à la main.
- **Licence** : toujours **revérifier** un échantillon — `overlay_ok=true`
  conditionne la rediffusion publique des images (georef).

---

# `build_alias_insee.py` — apparier communes anciennes et communes actuelles

Les inventaires d'archives nomment les communes telles qu'elles étaient au
XIXᵉ siècle. `geo.api.gouv.fr` ne connaît que les communes **actuelles** :
« Amareins », « Gourville », « Le Grand-Abergement » n'y résolvent pas. Le
script reconstitue hors ligne la chaîne complète, depuis le Code officiel
géographique de l'INSEE :

> libellé historique → code d'époque → … → **commune actuelle**

```bash
python harvest/build_alias_insee.py --dept 16 [--dry-run]
```

Il fusionne le résultat dans `communes_alias.json`, que `harvest_francearchives.py`
consulte avant d'interroger geo.api. **Les entrées déjà présentes font foi** :
une correction manuelle n'est jamais écrasée par un rerun.

Trois fichiers publics, mis en cache dans `harvest/_cog/` (14 Mo, gitignoré,
régénérable) :

| Fichier | Rôle |
|---|---|
| `v_commune_depuis_1943.csv` | tous les libellés de communes depuis 1943 |
| `v_mvt_commune_2025.csv` | les mouvements (fusions, scissions, rétablissements) |
| `@etalab/decoupage-administratif` | les communes actuelles — où s'arrête la chaîne |

## Ce qu'il refuse de faire, et pourquoi

Le script **préfère ne rien répondre plutôt que deviner**. Trois garde-fous, tous
issus de bugs constatés :

- **Successeurs multiples.** 71 communes du COG ont été *scindées*, pas
  fusionnées : `25015` est partagée entre Amondans, Cléron, Fertans et Malans.
  Écraser le successeur reviendrait à en désigner une au hasard. `resout()`
  renvoie `None` dès qu'un maillon est scindé, et le libellé est listé « sans
  successeur actuel » dans le rapport.
- **Libellés ambigus.** Si un même libellé mène à plusieurs communes actuelles
  (« Saint-Médard » en Charente → Saint-Médard *ou* Val-d'Auge), il est écarté et
  signalé, pas départagé.
- **Aucun rapprochement approché.** L'appariement tolère la casse, les accents et
  les séparateurs (`cle_commune()`, côté harvester) — rien de plus. La recherche
  floue de geo.api avait résolu « Ain » en **Ainhoa (64014)** et envoyé 5 905
  notices dans le Pyrénées-Atlantiques : on ne la réintroduit pas ici.

## Portée réelle

Le COG ne remonte qu'à **1943**. Les communes absorbées avant restent hors
d'atteinte quel que soit l'outil : 7 pour la Charente, 5 pour l'Ain, à saisir à
la main. Quand l'inventaire porte des **coordonnées** (champ `Lieu` d'un
manifeste, `geo:lat`/`geo:long` d'un lieu FranceArchives), le géocodage inverse
`geo.api.gouv.fr?lat=&lon=` les rattrape sans intervention — c'est ce qui a
résolu 45 des 65 cas de l'Ain (Amareins 46.08097/4.78352 → 01165 Francheleins).

Contrôle croisé : sur l'Ain, les deux méthodes — COG et coordonnées — donnent
**12 rattachements identiques, 0 désaccord**.

---

# Aisne (02) — cadastre napoléonien, portail Ligeo `archives.aisne.fr`

`seed_aisne.py` produit `seed_aisne.sql`. **Deuxième portail Ligeo traité**, et
le plus simple des deux : ici le manifeste se suffit à lui-même.

## Ce qui est ouvert

Même partage qu'en Charente — HTML sous **Anubis**, IIIF ouvert — vérifié :

| Endpoint | Accès |
|---|---|
| `/ark:/63271/<ark>/manifest` | ouvert, `Access-Control-Allow-Origin: *` |
| `/iiif/FRAD002_CADASTRE/…/info.json` + tuiles | ouvert, **Image API 3.0 level1** |
| `/archive/resultats/…`, `/oai`, `/sitemap/*`, `iiif/search` | Anubis |

⚠️ Le CORS n'apparaît **que si la requête porte un en-tête `Origin`**. Tester
sans `Origin` fait conclure à tort à l'absence de CORS.

Les images sont **réellement tuilées** (256×256, `scaleFactors` 1→32, ~23 Mpx) :
contrairement au Doubs, elles seront consommables par le serveur de tuiles
Allmaps sans redimensionnement intermédiaire.

## Le manifeste porte tout

```
label    : « 3P0001_01 • Abbecourt : Tableau d'assemblage • 1828 »
metadata : Contexte            → « Cadastre … > A > Abbecourt »
           Dates               → « 1828 » (ou « sans date »)
           Commune ou lieu-dit → « Abbécourt (Aisne, France) »   ← accentué
service  → …/iiif/FRAD002_CADASTRE/FRAD002_3P0001/FRAD002_3P0001_01.jpg
```

D'où la différence avec la Charente : **la seule entrée nécessaire est la liste
des arks**. Ni cote, ni titre, ni arbre des communes à extraire du HTML — et
aucune dérivation de chemin d'image à valider, puisque le manifeste déclare le
service Image API.

## Récupération des arks (étape navigateur, ~3 min)

Une notice = une planche = un ark. Il n'existe **aucune route
image → manifeste** : `ark:/63271/<ark>/img:<IMAGE_ID>` ignore le suffixe et
renvoie toujours le manifeste de l'ark ; un ark inventé échoue. Les arks doivent
donc venir de l'inventaire.

1. Ouvrir la page de résultats dans un navigateur :
   `…/archive/resultats/cadastres/n:12?RECH_plan=1&type=cadastres` (**4 443**
   résultats).
2. Coller `harvest/aisne_collecte_arks.js` dans la console. Il pagine seul en
   réutilisant la session (5 s entre deux pages, le `Crawl-delay` déclaré),
   s'arrête si Anubis reprend la main, et télécharge `arks_aisne.tsv`.
3. **Vérifier le compte** : loin de 4 443 ⇒ la pagination a été interrompue.

**La pagination Ligeo ne se devine pas** — relevée sur le portail :

```
page 1 : /archive/resultats/cadastres/n:12?RECH_plan=1&type=cadastres
page 2 : /archive/resultats/cadastres/archive/n:12/limit:50/page:2?RECH_plan=1&…
```

Un segment `/archive/` **supplémentaire** apparaît, plus `limit:` et `page:`.
Aucune heuristique « lien suivant » ne trouve ça : le portail ne pose pas de
`rel="next"` exploitable, et une première version du collecteur s'arrêtait donc
à la page 1 (50 arks sur 4 443). Le segment `limit:` est en revanche une
aubaine — le script essaie 200 puis 100 et retombe sur 50 si le serveur
plafonne, ce qui divise d'autant le nombre de requêtes.

```bash
python harvest/seed_aisne.py --arks arks_aisne.tsv --limite 50   # essai
python harvest/seed_aisne.py --arks arks_aisne.tsv
python harvest/load_seed_to_supabase.py harvest/seed_aisne.sql
```

Les manifestes sont mis en cache dans `_manifestes_aisne.json` : les reruns sont
gratuits.

## Points de vigilance

- **Licence Ouverte Etalab 2.0** confirmée par le service — `overlay_ok = true`.
  Attention : le champ `ligeoReUseProfil` du manifeste, lui, ne dit *pas* que
  la licence est ouverte (« soumises à la législation en vigueur et aux
  conditions fixées par le conseil départemental »), et la page des CGU est
  derrière Anubis. Ne pas se fier au manifeste seul pour un autre portail Ligeo.
- **Le fonds est lacunaire**, en particulier sur l'arrondissement de
  Château-Thierry : `3P0006` manque déjà parmi les douze premiers dossiers. Le
  script n'invente rien — une commune sans planche n'apparaît pas.
- `parse_ident` renvoie une cote vide plutôt qu'une cote devinée si le motif
  `3P0001_01` n'est pas reconnu ; le compte est affiché en fin de run.
- Garde-fou département intégré : refus d'écrire si plus de 5 % des INSEE
  tombent hors du 02.

---

# Charente (16) — fonds 3 P, portail Ligeo « La Source »

`seed_charente.py` produit `seed_charente.sql` (6 727 planches, 332 communes
actuelles). Le cas est **représentatif des 24 départements Ligeo** : à réutiliser
tel quel en changeant le fonds et le département.

## Ce qui est ouvert et ce qui ne l'est pas

Le portail est protégé par **Anubis** (challenge de preuve de travail) sur les
pages HTML de navigation. En revanche les **endpoints IIIF sont ouverts** et
servis avec `Access-Control-Allow-Origin: *` :

| Endpoint | Accès |
|---|---|
| `/ark:/61904/<ark>/manifest` | ouvert (JSON) |
| `/iiif/SERIE_P/3P/<dossier>/<image>.jpg/info.json` + tuiles | ouvert |
| `/archive/fonds/…`, `/…/view:…` | Anubis (navigateur requis) |

L'inventaire lui-même (cotes + arks) n'est donc lisible que depuis un
navigateur. On le récupère **une fois**, à la main, puis tout le reste passe par
les endpoints IIIF ouverts. `robots.txt` impose `Crawl-delay: 5` et interdit
`/archive/*/view:*` : ne pas parcourir les 6 727 notices une à une.

## Récupération de l'inventaire (étape manuelle, ~10 min)

1. Ouvrir `…/archive/fonds/<FONDS>/view:all` dans un navigateur (48 pages de
   150 notices pour le 3 P). Chaque bloc `div.arc_notice_header` porte le titre
   `3 P 1/2 - Section A dite de Chardat. Feuille 1. | 1825` et le lien ark.
2. Extraire par page `id_notice ⇥ ark ⇥ titre` et les concaténer dans
   `notices.tsv`.
3. Extraire l'arbre (`ul.root`) dans `tree_3p.txt`, au format
   `rang~Nom commune~id_notice~id.type.section.feuille;…` : il sert seulement à
   distinguer les **notices de regroupement** (une par commune) des planches.

## Génération du seed

```bash
python harvest/build_alias_insee.py --dept 16     # alias COG (une fois)
python harvest/seed_charente.py --in <dossier>    # notices.tsv + tree_3p.txt
python harvest/load_seed_to_supabase.py harvest/seed_charente.sql
```

## Deux pièges vérifiés sur ce fonds

- **La cote ne donne pas le chemin de l'image.** `3 P N/M` correspond *presque
  toujours* à `3P_NNN/FRAD016_3P_NNN_MM.jpg`, mais pas toujours : la cote 22 est
  stockée sous `3P_202`, la 18 sous `3P_108`, la 41 sous `3P_401`. Dériver
  mécaniquement produisait **~7 % de vignettes 404**. `seed_charente.py` lit donc
  le service Image API **dans chaque manifeste** (résultat mis en cache dans
  `manifestes.json` : les reruns sont gratuits). Les cotes suffixées d'une lettre
  (`3 P 28A/5`) existent aussi — dossier `3P_028A`, numéro zéro-comblé sur 3.
- **Les noms de l'inventaire sont ceux de 1825.** geo.api ne connaît que les
  communes actuelles. Deux garde-fous : le champ `Lieu` du manifeste donne la
  forme récente (« Aignes / Aignes-et-Puypéroux »), et `build_alias_insee.py`
  reconstitue depuis le COG INSEE la chaîne *libellé historique → commune
  actuelle* (141 libellés pour le 16). Restent 7 communes fusionnées avant 1943,
  saisies à la main dans `communes_alias.json` — repérables au motif de cote
  `NA`/`NB` (deux anciennes communes, une commune actuelle : 47A Blanzaguet +
  47B Saint-Cybard-le-Peyrat → Blanzaguet-Saint-Cybard).
