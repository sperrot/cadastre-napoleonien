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
