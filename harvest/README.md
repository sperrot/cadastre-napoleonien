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
