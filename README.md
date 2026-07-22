# Cadastre napoléonien — annuaire cartographique

Visualiseur web léger pour retrouver, par commune, les plans du **cadastre
napoléonien** numérisés par les archives départementales (tableaux
d'assemblage, sections, feuilles).

> **État : V0.x — « annuaire cartographique ».**
> Carte + recherche de commune + liens vers les plans d'archives.
> Aucune image hébergée, aucun géoréférencement (paliers suivants).

## Principe : le plus léger possible

| Composant | Choix | 
|-----------|-------|
| Front | Statique (MapLibre GL JS, CDN) | 
| Fond de carte | OSM raster (sans clé) |
| Communes (recherche + contours) | [geo.api.gouv.fr](https://geo.api.gouv.fr) côté client | 
| Liens d'archives | table `document` dans Supabase |
| Images des plans | **restent chez les archives** (lien sortant) | 

L'app n'héberge donc **aucune image** : elle indexe et cartographie des liens.


## Arborescence

```
.
├── web/
│   ├── index.html          # page unique
│   ├── style.css
│   ├── app.js              # carte + recherche + lecture Supabase
│   ├── config.example.js   # modèle de config (à copier)
│   └── config.js           # config locale (ignorée par git)
└── supabase/
    ├── schema.sql          # tables commune + document, RLS lecture publique
    └── seed.sql            # données de démo (à remplacer)
```

# État des lieux national — cadastre napoléonien par département

Inventaire de l'avancement de la numérisation, du géoréférencement et de la
vectorisation du cadastre napoléonien (tableaux d'assemblage + feuilles de
section) et de sa mise à disposition, pour les **95 départements de métropole
hors Paris** (96 dont 2A/2B, moins le 75).

**Date de l'inventaire : 2026-07-20** · Fichier de données : [`etat_des_lieux_departements.csv`](etat_des_lieux_departements.csv)

## Échelle d'avancement

- **N5** — Vectorisé — contours SHP/GPKG disponibles
- **N4** — Géoréférencé disponible et/ou moissonnable FranceArchives + IIIF
- **N3** — Numérisé + téléchargeable en open data (JPG/CSV)
- **N2** — Numérisé, visualiseur AD uniquement
- **N1** — Partiel / incertain / non identifié clairement
- **N0** — Rien d'identifié en ligne

Cas mixtes classés au niveau le plus haut atteint, précisé en commentaire
(ex. Haute-Garonne : open data villes >10 000 hab, reste via AD).

## Statistiques

| Indicateur | Nombre | Part |
|---|---|---|
| N5 — Vectorisé — contours SHP/GPKG disponibles | 7 / 95 | 7 % |
| N4 — Géoréférencé disponible et/ou moissonnable FranceArchives + IIIF | 7 / 95 | 7 % |
| N3 — Numérisé + téléchargeable en open data (JPG/CSV) | 3 / 95 | 3 % |
| N2 — Numérisé, visualiseur AD uniquement | 75 / 95 | 79 % |
| N1 — Partiel / incertain / non identifié clairement | 3 / 95 | 3 % |
| N0 — Rien d'identifié en ligne | 0 / 95 | 0 % |
| **Géoréférencé ou vectorisé disponible (≥ N4)** | **14 / 95** | **15 %** |
| **Diffusion exploitable hors visualiseur (≥ N3)** | **17 / 95** | **18 %** |
| IIIF disponible ou générable identifié | 14 / 95 | 15 % |
| Licence ouverte (LO/ODbL/équiv.) sur au moins une source | 13 / 95 | 14 % |
| Lignes vérifiées en réel (✅) | 18 / 95 | 19 % |

Familles de visualiseurs AD identifiées (candidates aux pipelines du repo) : **Ligeo** 24 · **Mnesys** 16 · **Arkothèque** 13 · **Archinoë** 6 · **Bach** 5 · **THOT** 3 · **Pleade** 1.

## Tableau par département

| N° | Département | Source (lien) | Formats dispo | État | Licence | Commentaire |
|---|---|---|---|---|---|---|
| 01 | Ain | [FranceArchives + AD (Ligeo)](https://www.archives.ain.fr/n/archives-cadastrales/n:397) | ARK, IIIF | N4 ✅ | Réutilisation OK (CGU AD01) | Cadastre complet 463 communes (findingaid FA) ; manifeste IIIF direct dans Allmaps confirmé ; seed repo en cours |
| 02 | Aisne | [AD (Ligeo)](https://archives.aisne.fr/archive/recherche/cadastres/n:12) | JPG (visionneuse) | N4 ✅ | À vérifier | Cadastre en ligne ; IIIF ok (licence ouverte etalab 2.0) |
| 03 | Allier | [AD (Arkothèque)](https://archives.allier.fr/archives-en-ligne/cartes-plans-documents-figures/cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 04 | Alpes-de-Haute-Provence | [AD (portail)](https://www.archives04.fr/s/15/cadastre/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 05 | Hautes-Alpes | [AD (Ligeo)](https://archives.hautes-alpes.fr/archive/resultats/cadastrenumerise/n:199?type=cadastrenumerise) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ~1 800 docs cadastre numérisés référencés FranceArchives |
| 06 | Alpes-Maritimes | [AD (Ligeo)](https://archives06.fr/archive/resultats/cadastre2/n:104?type=cadastre2) | JPG, IIIF partiel | N2 ⚠️ | À vérifier | ~100 docs IIIF référencés FranceArchives (partiel) |
| 07 | Ardèche | [AD (Ligeo)](https://archives.ardeche.fr/archive/recherche/planscadastraux/n:102) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 08 | Ardennes | [AD (Arkothèque)](https://archives.cd08.fr/arkotheque/consult_fonds/index.php?ref_fonds=2) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 09 | Ariège | [AD (portail)](https://archives.ariege.fr/rechercher-et-consulter/archives-en-ligne/) | — | N1 ⚠️ | À vérifier | Compoix numérisés en ligne ; plans du cadastre napoléonien (3P) non identifiés en ligne |
| 10 | Aube | [AD (Arkothèque)](https://www.archives-aube.fr/recherches/documents-numerises/cadastre-cartes-et-plans/cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 11 | Aude | [AD (portail)](https://archivesdepartementales.aude.fr/les-archives-en-ligne) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Cadastre parmi les 3,7 M pages numérisées ; page dédiée à confirmer |
| 12 | Aveyron | [AD (Ligeo)](https://archives.aveyron.fr/archive/recherche/cadastre/n:23) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 13 | Bouches-du-Rhône | [AD (Ligeo)](https://www.archives13.fr/archive/recherche/cadastre/n:36) | JPG (visionneuse) | N2 ⚠️ | IIIF présent |  |
| 14 | Calvados | [FranceArchives + AD (Mnesys)](https://archives.calvados.fr/search/form/dfc4e27b-4f7e-431e-b413-655e793be3b7) | ARK (sans IIIF) | N2 ✅ | Réutilisation OK (CGU AD14) | Moissonnable FA mais pas de manifeste IIIF (visionneuse ARK) ; harvester repo à adapter |
| 15 | Cantal | [AD (portail)](https://archives.cantal.fr/rechercher/cadastre-et-archives-foncieres) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 16 | Charente | [FranceArchives + AD (Ligeo)](https://lasource.archives.lacharente.fr/archive/resultats/cadastre/n:125?type=cadastre) | IIIF | N4 ✅ | ok | Numérisation intégrale confirmée (portail La Source testé) ; ≈11 000 docs cadastre en IIIF |
| 17 | Charente-Maritime | [AD (Archinoë)](http://www.archinoe.net/v2/ad17/cadastre.html) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Pipeline Archinoë→IIIF du repo (AD21) applicable |
| 18 | Cher | [AD (Arkothèque)](https://www.archives18.fr/archives-numerisees/plans-du-cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 19 | Corrèze | [AD (Archinoë)](http://www.archinoe.fr/cg19/cadastre.php) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈4 600 docs numérisés référencés FranceArchives ; pipeline Archinoë applicable |
| 21 | Côte-d'Or | [AD (Archinoë)](https://archives.cotedor.fr/v2/site/AD21/Rechercher/Recherche_thematique/Cartes_et_plans) | JPG, IIIF (généré repo) | N2 ✅ | Réutilisation soumise aux CGU AD21 | 7 976 manifestes IIIF statiques générés par le repo (pipeline Archinoë→worker) ; overlay public non autorisé |
| 22 | Côtes-d'Armor | [Open data Région Bretagne + AD (Ligeo)](https://www.data.gouv.fr/datasets/assemblage-des-feuilles-du-cadastre-napoleonien-en-bretagne-2) | SHP, WMS, WFS + JPG | N5 ✅ | Licence Ouverte 2.0 | Contours des feuilles + tableau d'assemblage vectorisés (région) ; feuilles image via AD |
| 23 | Creuse | [AD (Arkothèque)](https://archives.creuse.fr/rechercher/archives-numerisees/cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 24 | Dordogne | [AD (Arkothèque)](https://archives.dordogne.fr/archives-numerisees/cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 25 | Doubs | [data.gouv + AD (Mnesys)](https://www.data.gouv.fr/datasets/planches-du-cadastre-napoleonien) | JPG téléchargeable, CSV/JSON, IIIF (worker repo) | N3 ✅ | ODbL | ~5 700 planches JPEG en open data ; 633 feuilles seedées (worker JPEG→IIIF) ; visionneuse Mnesys sans manifeste accessible |
| 26 | Drôme | [AD (Mnesys)](https://archives.ladrome.fr/search/form/47e6db60-8648-42ca-8415-539025d51807) | ARK (visionneuse) | N2 ⚠️ | À vérifier |  |
| 27 | Eure | [AD (portail)](https://archives.eure.fr/search?preset=106&view=list) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 28 | Eure-et-Loir | [AD (Arkothèque)](https://archives28.fr/archives-et-inventaires-en-ligne/fonds-iconographiques/plans-du-cadastre-napoleonien-3-p) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 29 | Finistère | [Open data Région Bretagne + AD](https://archives.finistere.fr/espace-de-recherche-dans-le-cadastre) | SHP, WMS, WFS + JPG | N5 ✅ | Licence Ouverte 2.0 | Contours vectorisés (région) ; espace cadastre AD ; Brest métropole diffuse aussi un WMS |
| 30 | Gard | [AD (Ligeo)](https://earchives.gard.fr/document/FRAD030_3_PFi) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈19 600 docs numérisés référencés FA ; Nîmes 1825 vectorisée en accès libre (GPKG Nakala, ANR PARCEDES) |
| 31 | Haute-Garonne | [data.gouv + AD (Ligeo)](https://www.data.gouv.fr/datasets/cadastre-napoleonien-des-communes-de-la-haute-garonne) | JPG téléchargeable (villes >10 000 hab), CSV/JSON + IIIF (AD) | N3 ✅ | Licence Ouverte 2.0 (open data) / CGU AD31 | Cas mixte : open data grandes villes, reste via AD ; manifeste IIIF AD direct dans Allmaps confirmé ; seed repo |
| 32 | Gers | [AD (portail)](http://www.archives32.fr/FondsNumerises/index.php?type=2) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 33 | Gironde | [AD (Ligeo)](https://archives.gironde.fr/archive/recherche/cadastre/n:91) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈7 700 docs numérisés référencés FranceArchives |
| 34 | Hérault | [AD (Pierresvives)](http://archives-pierresvives.herault.fr/archives/recherche/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈15 000 docs numérisés référencés FranceArchives |
| 35 | Ille-et-Vilaine | [Open data Région Bretagne + AD (THOT)](http://archives-en-ligne.ille-et-vilaine.fr/thot_internet/FrmSommaireFrame.asp) | SHP, WMS, WFS + JPG | N5 ✅ | Licence Ouverte 2.0 | Contours vectorisés (région) ; visualiseur THOT côté AD |
| 36 | Indre | [AD (Bach)](http://www.archives36.fr/f/Cadastre/mosaique/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 37 | Indre-et-Loire | [AD (Mnesys)](https://archives.touraine.fr/search/form/0883f4b0-8c3d-427b-8618-d9e67239068b) | ARK (visionneuse) | N2 ⚠️ | À vérifier | ≈12 700 docs numérisés référencés FA (beaucoup d'E-dépôts communaux) |
| 38 | Isère | [AD (Arkothèque)](https://archivesenligne1.archives-isere.fr/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 39 | Jura | [AD (Mnesys)](https://archives39.fr/search/form/0a4fae72-ee28-4663-ac8f-e4a4e89ebc68) | ARK (visionneuse) | N2 ✅ | Restrictive : rediffusion/modification interdites | ≈8 800 docs numérisés référencés FA ; manifeste IIIF caché derrière la SPA ; licence bloquante pour overlay |
| 40 | Landes | [AD (Arkothèque)](http://www.archives.landes.fr/arkotheque/consult_fonds/index.php?ref_fonds=1) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 41 | Loir-et-Cher | [AD (portail)](http://archives.culture41.fr/archives/recherche/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 42 | Loire | [AD (Ligeo)](https://archives.loire.fr/archive/recherche/cadastre/n:133) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 43 | Haute-Loire | [AD (portail)](https://www.archives43.fr/archives-en-ligne/territoires-altiligeriens) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 44 | Loire-Atlantique | [AD (Archinoë)](https://archives-numerisees.loire-atlantique.fr/v2/ad44/cadastre.html) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Pipeline Archinoë applicable ; vérifier le « Cadastre Napoléonien Régional » du catalogue GéoPAL (Pays de la Loire) |
| 45 | Loiret | [AD (Arkothèque) + data.gouv](https://www.archives-loiret.fr/faire-vos-recherches/archives-numerisees/cadastre-napoleonien) | JPG (visionneuse) + ZIP toponymes | N2 ⚠️ | Licence Ouverte 2.0 (toponymes) | Toponymes du cadastre vectorisés en open data → géoréférencement sous-jacent probable, plans non publiés en géoréf |
| 46 | Lot | [AD (Bach)](http://archives.lot.fr/f/CadastreNapoleonien/mosaique/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 47 | Lot-et-Garonne | [AD (Archinoë)](http://www.archinoe.fr/v2/ad47/cadastre.html) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Pipeline Archinoë applicable |
| 48 | Lozère | [AD (Ligeo)](http://archives.lozere.fr/archive/recherche/cadastre/n:14) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 49 | Maine-et-Loire | [AD (portail)](http://www.archives49.fr/acces-directs/archives-en-ligne/plans-cadastraux-napoleoniens/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 50 | Manche | [AD (portail)](https://www.archives-manche.fr/e/RechercheTransversale?from=0&f_92%5B0%5D=cadastre&f_87%5B0%5D=Cadastre+napol%E9onien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 51 | Marne | [AD (Mnesys)](https://archives.marne.fr/search/form/f3530583-c23e-4b18-9497-6fd477446b28) | ARK (visionneuse) | N2 ✅ | À vérifier | ≈23 500 docs numérisés référencés FA (plus gros volume) ; cible pipeline Mnesys V0.6 du repo |
| 52 | Haute-Marne | [AD (portail)](http://archives.haute-marne.fr/archives/search/default/%252A%253A%252A?filter_field=dyndescr_cSubject_liste-sousDomaine&filter_value=Cartes+et+plans) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 53 | Mayenne | [AD (Ligeo)](https://chercher-archives.lamayenne.fr/archives-en-ligne/cadastre-search-form.html) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 54 | Meurthe-et-Moselle | [AD (portail)](http://archives.meurthe-et-moselle.fr/archives-en-ligne/plans-cadastraux-napol%C3%A9oniens-de-meurthe-et-moselle) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 55 | Meuse | [AD (portail)](http://archives.meuse.fr/search?preset=28&view=list) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 56 | Morbihan | [Open data Région Bretagne + AD (Ligeo)](https://recherche.archives.morbihan.fr/archive/recherche/cadastre/n:7) | SHP, WMS, WFS + JPG, IIIF partiel | N5 ✅ | Licence Ouverte 2.0 | Contours vectorisés (région) ; ~240 docs IIIF référencés FA |
| 57 | Moselle | [AD (portail)](http://www.archives57.com/index.php/recherches/archives-en-ligne/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 58 | Nièvre | [AD (Mnesys)](https://archives.nievre.fr/search/form/5dea445a-5b66-4d4d-a1ea-6cffb70ec9cf) | ARK (visionneuse) | N2 ⚠️ | À vérifier | ≈4 600 docs numérisés référencés FranceArchives |
| 59 | Nord | [AD (Mnesys)](https://archivesdepartementales.lenord.fr/editorial/page/7dcf6e86-7a43-46de-be0e-d37b28d6731b) | ARK (visionneuse) | N2 ⚠️ | À vérifier | Plans du cadastre du Consulat et napoléonien |
| 60 | Oise | [AD (portail)](https://archives.oise.fr/rechercher/archives-en-ligne/cartes-et-plans) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Plans napoléoniens + plans par masses de cultures en ligne |
| 61 | Orne | [AD (portail)](https://archives.orne.fr/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 62 | Pas-de-Calais | [AD (Archinoë)](https://archivesenligne.pasdecalais.fr/console/ir_seriel.php?id=56&p=formulaire_cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Pipeline Archinoë applicable |
| 63 | Puy-de-Dôme | [AD (Ligeo)](http://www.archivesdepartementales.puydedome.fr/archive/recherche/cadastre/n:109) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈5 100 docs numérisés référencés FranceArchives |
| 64 | Pyrénées-Atlantiques | [AD (Pleade)](https://earchives.le64.fr/archives-en-ligne/cadastre-search-form.html) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Numérisation complète des plans 1810-1846 |
| 65 | Hautes-Pyrénées | [AD (Arkothèque)](http://www.archivesenligne65.fr/article.php?laref=476&titre=les-plans-cadastraux) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 66 | Pyrénées-Orientales | [AD (portail)](http://archives.cd66.fr) | JPG (visionneuse) | N2 ✅ | Réutilisation libre affichée (mention provenance) | Plans cadastraux napoléoniens en ligne (confirmé) ; réutilisation libre et gratuite avec mention ; ⚠️ accès bloqué depuis l'étranger |
| 67 | Bas-Rhin | [AD Alsace (portail)](https://archives.bas-rhin.fr/rechercher/aide-a-recherche/un-lieu-ou-un-monument-/mener-une-recherche-dans-documents-cadastraux/) | JPG (visionneuse) | N2 ⚠️ | À vérifier | 6 948 plans numérisés (1807-1868), couverture complète |
| 68 | Haut-Rhin | [AD Alsace (Mnesys)](https://archives68.alsace.eu/search/form/d58ae5e0-4a93-4114-9097-ea2a854dba55) | ARK (visionneuse) | N2 ⚠️ | À vérifier | Partiel : plan « village » + tableau d'assemblage numérisés |
| 69 | Rhône | [AD (Mnesys)](http://archives.rhone.fr/#recherche_cadastre) | ARK (visionneuse) | N2 ⚠️ | À vérifier |  |
| 70 | Haute-Saône | [AD (Ligeo)](http://archives.haute-saone.fr/archive/recherche/cadastre/n:135) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 71 | Saône-et-Loire | [Open data AD71 (Arkothèque)](https://www.archives71.fr/arkotheque/consult_fonds/index.php?ref_fonds=38) | JPG téléchargeable, CSV, IIIF (worker repo) | N3 ✅ | Licence Ouverte | 9 707 feuilles seedées dans le repo depuis le CSV open data (worker JPEG→IIIF) |
| 72 | Sarthe | [AD (Bach)](http://archives.sarthe.fr/f/cadastrenapoleonien/tableau/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 73 | Savoie | [AD (Mnesys)](http://enligne.savoie-archives.fr/?id=recherche_guidee_cadastre_web) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Voir aussi la mappe sarde (cadastre savoyard antérieur) |
| 74 | Haute-Savoie | [AD (Mnesys)](http://archives.hautesavoie.fr/?id=388) | JPG (visionneuse) | N2 ⚠️ | À vérifier | ≈22 200 docs numérisés référencés FA (2e volume national) → candidat pipeline Mnesys |
| 76 | Seine-Maritime | [AD (Mnesys)](http://recherche.archivesdepartementales76.net/?id=recherche_guidee_cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 77 | Seine-et-Marne | [AD (portail)](https://archives.seine-et-marne.fr/fr/plans-du-cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 78 | Yvelines | [AD (portail)](http://www.archives.yvelines.fr/article.php?larub=28&titre=cadastre-napoleonien) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 79 | Deux-Sèvres | [FranceArchives + AD (Ligeo, portail mutualisé 79/86)](https://archives-deux-sevres-vienne.fr/archive/resultats/autrecadastre/n:99?type=autrecadastre) | IIIF (partiel) | N4 ⚠️ | À vérifier | ≈1 100 docs cadastre en IIIF via FranceArchives → moissonnable |
| 80 | Somme | [AD (Mnesys)](https://archives.somme.fr/search/form/e49b14d1-178f-4fe9-bdb1-30d705a42c01) | ARK (visionneuse) | N2 ⚠️ | À vérifier | ≈13 300 docs numérisés référencés FA (dont plans par masses de cultures) |
| 81 | Tarn | [AD (portail)](https://archives.tarn.fr/rechercher/archives-et-images-en-ligne/documents-numerises/cadastre-napoleonien-plans-parcellaires-communaux) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 82 | Tarn-et-Garonne | [AD + SIG départemental (SIGD)](http://www.archives82.fr/rechercher-et-consulter/archives-en-ligne/cadastres.html) | WebGIS (consultation seule) | N4 ⚠️ | Fermée (pas d'export identifié) | 2 696 plans géoréférencés, vectorisés et mosaïqués (2012) via « Web Cadastre Napoléonien » (carto.ledepartement82.fr), superposables au cadastre actuel ; pas de téléchargement libre identifié |
| 83 | Var | [AD (Arkothèque)](http://www.archives.var.fr/arkotheque/consult_fonds/index.php?ref_fonds=6) | JPG (visionneuse) | N2 ⚠️ | À vérifier | Plans + matrices |
| 84 | Vaucluse | [data.gouv + SIG dép. (Lizmap) + AD (Ligeo)](https://www.data.gouv.fr/datasets/cadastre-napoleonien-geo-reference-vaucluse-et-sections-cadastrales-associees-1-2) | GeoTIFF, WMS, SHP (sections) + JPG | N5 ✅ | Licence Ouverte 2.0 | Raster géoréférencé + sections vectorisées en open data ; visualiseur maps.vaucluse.fr |
| 85 | Vendée | [Recherche (Nakala/Huma-Num) + SIG ArcGIS + AD](https://www.nakala.fr/10.34847/nkl.1f590t6u) | GPKG (vecteur), WebGIS ArcGIS + JPG | N5 ⚠️ | Ouverte (Nakala) / ArcGIS à vérifier | Partiel : CadNap85 sud-Vendée (29 communes) vectorisé en GPKG libre (ANR PARCEDES) ; plateforme collaborative ArcGIS départementale (86 669 parcelles) non librement exportable |
| 86 | Vienne | [AD (Ligeo, portail mutualisé 79/86)](https://archives-deux-sevres-vienne.fr/archive/resultats/autrecadastre/n:99?type=autrecadastre) | JPG, IIIF (traces) | N2 ⚠️ | À vérifier | Quelques docs IIIF référencés FA ; même serveur que 79 → potentiel identique à confirmer |
| 87 | Haute-Vienne | [AD (Bach)](http://archives.haute-vienne.fr/f/cadastre/tableau/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 88 | Vosges | [FranceArchives + AD (Ligeo)](http://www.archives-recherche.vosges.fr/recherche-en-ligne/base-de-donnees-et-images-numerisees9) | IIIF | N4 ✅ | Licence Ouverte 2.0 | Moissonné par le repo : 5 691 docs / 453 communes, 100 % overlay_ok |
| 89 | Yonne | [AD (portail)](http://archivesenligne.yonne-archives.fr/archives/recherche/cadastre) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 90 | Territoire de Belfort | [AD (Mnesys)](https://archives.territoiredebelfort.fr/search/form/a4ac06cb-f05c-4c27-9a8e-6ce15ce29a32) | ARK (visionneuse) | N2 ⚠️ | À vérifier |  |
| 91 | Essonne | [AD (Mnesys)](https://archives.essonne.fr/search/form/a94f4fea-30c7-4d17-aaf9-d5e5924e934d) | ARK (visionneuse) | N2 ⚠️ | À vérifier | ≈4 800 docs numérisés référencés FranceArchives |
| 92 | Hauts-de-Seine | [data.gouv + AD (Ligeo)](https://www.data.gouv.fr/datasets/cadastre-napoleonien-assemblage-departemental) | SHP (assemblage), JPG+JGW géoréférencés téléchargeables, CSV/JSON | N5 ✅ | Licence Ouverte (Etalab) | Assemblage départemental vectorisé + toutes les feuilles géoréférencées (RGF93-CC49) téléchargeables |
| 93 | Seine-Saint-Denis | [Open data CG93 + FranceArchives + AD](https://opendata.seine-saint-denis.fr) | Dalles géoréférencées (bbox), IIIF | N4 ✅ | Licence Ouverte | Pilote du repo : 252 dalles géoréf seedées + 550 docs IIIF moissonnables FA ; vectorisation évoquée mais non trouvée publiée ; 2 communes à re-moissonner |
| 94 | Val-de-Marne | [AD (Bach)](http://archives.valdemarne.fr/f/Cadastre/tableau/) | JPG (visionneuse) | N2 ⚠️ | À vérifier |  |
| 95 | Val-d'Oise | [FranceArchives + AD (Ligeo)](https://archives.valdoise.fr/archive/recherche/cadastre/n:681) | ARK, IIIF | N4 ✅ | Réutilisation OK (CGU AD95) | Moissonné par le repo : 1 477 feuilles, 187 communes ; manifeste IIIF direct Allmaps (profil famille FOND.TIF) |
| 2A | Corse-du-Sud | [AD (THOT) + data.corsica](https://www.data.corsica/explore/dataset/le-plan-terrier-de-la-corse-archive-de-corse-et-de-vincennes/) | JPG (plan terrier) | N1 ⚠️ | À vérifier | Plan terrier (1771-1796) en open data ; cadastre napoléonien en cours de mise en ligne |
| 2B | Haute-Corse | [AD (THOT)](https://archives.isula.corsica/internet_thot/frmsommaireframe.asp) | — | N1 ⚠️ | À vérifier | Portail Collectivité de Corse ; cadastre napoléonien non clairement en ligne |

### Paris (75) — hors périmètre statistique

Paris est exclu du décompte des 95, mais ses plans anciens sont en ligne aux Archives de Paris :

- Le cadastre de Paris par îlot, dit **Atlas Vasserot** (1810-1836) et sa mise à jour rive droite, dite **Atlas Vasserot et Bellanger** (1830-1850) : [plans de Paris dans ses limites avant 1860](https://archives.paris.fr/archives-numerisees/documents-iconographiques/plans-parcellaires/accedez-aux-plans-de-paris-dans-ses-limites-avant-1860).
- Le **cadastre napoléonien des communes annexées** (1808-1825) et sa révision (1830-1850) : [plans des communes avant leur annexion à Paris en 1860](https://archives.paris.fr/archives-numerisees/documents-iconographiques/plans-parcellaires/le-cadastre-napoleonien-des-communes-annexees-1808-1825-et-sa-revision-1830-1850).

### Légende

- **État** : niveau N0–N5 (échelle ci-dessus) · ✅ vérifié en réel (repo ou test manuel) · ⚠️ passe rapide, lien/licence non testés individuellement.
- **Formats** : « JPG (visionneuse) » = images vues dans le viewer sans téléchargement structuré ; « JPG téléchargeable » = open data ; « ARK » = lien pérenne visionneuse ; « IIIF » = manifeste exploitable (Allmaps).
- **Licence** : « À vérifier » = CGU du site AD non dépouillées lors de cette passe.



## Utilisation

- **Rechercher** une commune par son nom (autocomplete).
- **Cliquer** sur la carte : sélectionne la commune sous le pointeur.
- Le panneau liste les plans disponibles, groupés en *tableau d'assemblage →
  sections → feuilles*, chaque entrée ouvrant le viewer de l'archive.

## État des lieux national

Inventaire par département (95, métropole hors Paris) de l'avancement
numérisation / géoréférencement / vectorisation et de la mise à disposition :
voir [`ETAT_DES_LIEUX.md`](ETAT_DES_LIEUX.md) (données :
[`etat_des_lieux_departements.csv`](etat_des_lieux_departements.csv)).

## Feuille de route

- **V0.0** ✅ Annuaire cartographique (lecture).
- **V0.3** ✅ Géoréférencement réel via [Allmaps](https://allmaps.org) (annotations
  JSON, rendu déformé côté navigateur, sans serveur de tuiles) + sections au
  zoom fort. Département Seine Saint Denis disponible (Rechercher Sevran,  Aulnay , Drancy, Villepinte ...)
- **V1** Workflow de validation, couverture multi-départements, exports.
