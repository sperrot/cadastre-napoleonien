# Méthodologie — moisson FranceArchives → base cadastre napoléonien

Le harvester doit rester **agile** : chaque département a sa structure d'arbre,
sa plateforme d'images et sa licence. Ce document fige la méthode et les pièges.

Voir aussi le suivi par département : [`to_do/README.md`](to_do/README.md).

---

## 1. Vérifier la licence — département par département

**La licence n'est PAS uniforme.** Elle conditionne le droit d'**overlay/géoréférencement**
(= modifier + rediffuser l'image). On l'a vérifié : Seine-Saint-Denis = ouvert,
Jura = restrictif. Donc **un contrôle par institution est obligatoire**.

**Source faisant foi : le manifeste IIIF.** La licence opérante est déclarée
dans le manifeste (`license` / `rights` / `attribution`, ou un profil maison
comme `ligeoReUseProfil`), pas dans l'instrument de recherche (qui ne porte
qu'un `conditionsOfAccess` générique renvoyant au CRPA).

Procédure (1 fois par institution = par `service/NNNN`) :
1. Récupérer **un** manifeste d'une feuille du département.
2. Y chercher : `Licence Ouverte` / `Etalab` / `CC-BY` / `domaine public`
   → **`licence_overlay_ok = true`**, `statut = 'georef'`.
3. Sinon (mention restrictive, « ne pas diffuser/modifier », ou rien)
   → **`À vérifier`**, `licence_overlay_ok = false`, `statut = 'lien'`.
4. En cas de doute ou de mention restrictive : **demande écrite de réutilisation
   à l'AD** avant tout overlay public (le harvester ne tranche pas le droit).

Le harvester fait ce test automatiquement (`resolve_licence`) et **met en cache
par service** pour ne lire qu'un manifeste par institution.

Repères connus :
| Institution | Licence | overlay |
|---|---|---|
| AD Seine-Saint-Denis (`service/34393`) | Licence Ouverte (Etalab) | ✅ |
| AD du Jura | « ne pas diffuser/modifier sans accord écrit » | ❌ |

---

## 2. Quel finding aid récupérer sur FranceArchives ?

On cherche **le finding aid en tête d'arborescence** : le **fonds cadastre** du
département (souvent série **3P**, ou intitulé « Plans du cadastre »), qui
contient la branche « cadastre napoléonien ».

- **Exemple Seine-Saint-Denis** : finding aid `2679af120dcec…` « Plans du
  cadastre » (cotes 2045W-2047W, 2074W), `service/34393`. Sa branche
  « Plans cadastraux » → ~40 communes → feuilles (tableaux d'assemblage…).
- **Exemple Calvados** : `d17231b4…` « Cadastre (communes A→D) », `service/33495`.

Comment le trouver :
1. Sur FranceArchives, filtrer par **service d'archives** (le département) +
   recherche « cadastre » / « plans du cadastre ».
2. Ouvrir le finding aid, noter l'**id** dans l'URL `…/findingaid/<id>`.
3. (Optionnel) télécharger son **RDF** : `…/findingaid/<id>/rdf.xml`.

⚠️ **Piège fréquent : un fonds éclaté en plusieurs finding aids** (par tranches
de communes). Calvados n'a que **A→D** déposé ; il manque E→Z. Toujours vérifier
la **couverture alphabétique** des communes et récupérer les **finding aids
frères**.

**V0.1 — on ne garde que les données IIIF.** Une feuille n'est retenue que si
elle porte un **manifeste IIIF** (condition d'Allmaps). Les notices sans IIIF
sont ignorées en V0.1 (elles pourront devenir de simples « liens » plus tard).

---

## 3. Le harvester — exclusions, dates, franchissement du robot

Script : [`harvest/harvest_francearchives.py`](harvest/harvest_francearchives.py).
À lancer **en local** (FranceArchives bloque les fetchs serveur).

### a) Franchir la barrière anti-robot (méthode « token »)
FranceArchives répond aux requêtes non-navigateur par une **page de défi JS** :
```html
<script>window.location.href='/redirect_<TOKEN>====/<chemin>';</script>
```
Le harvester :
1. envoie un **User-Agent navigateur** ;
2. détecte la page de défi, **extrait le token** et **suit une fois** l'URL
   `/redirect_<TOKEN>====/<chemin>` → cela **pose un cookie de session** ;
3. les requêtes suivantes passent directement (cookie présent).

URL d'export qui renvoie le RDF : **`/{type}/{id}/rdf.xml`** (le `.csv` existe
mais est *superficiel* : il ne contient pas l'arbre).

### b) Élagage de branches (l'« index sur l'arbre »)
On **ne descend pas** une branche inutile. À chaque nœud, on lit son **titre**
et son **intervalle de dates** (`beginningDate`/`endDate`) et on **coupe avant
de télécharger** ses enfants si :
- le titre matche `EXCLUDE_RE` = `rénov|renov|intendance` ; ou
- l'intervalle **ne recoupe pas** la période cible (`period_overlaps`).

Effet : « Plans du cadastre rénové » (1906-1983) et « Plans d'intendance »
(1781-1792) sont coupés **à la racine** → bien moins de requêtes, et plus aucune
fuite de feuilles `[s.d.]` du rénové.

### c) Filtre de période (feuilles)
Par défaut **1800-1860** (`--year-min` / `--year-max`). Une feuille hors période
est écartée. Une feuille **sans date (`[s.d.]`)** n'est gardée **que** si elle
est dans une branche **déjà validée napoléonienne** (grâce à l'élagage).

### d) Extraction par feuille
Pour chaque feuille (= notice avec manifeste IIIF, sans enfant) :
`titre`, `type` (assemblage/section/feuille), `année`, `cote`, `commune`
(titre du nœud parent **ou** titre de la feuille selon la structure → INSEE via
`geo.api.gouv.fr`), `manifeste IIIF`, `image (dao)`, `service` (source),
`licence` (via 1 manifeste/institution). Sortie : `INSERT` SQL.

```bash
python harvest_francearchives.py <findingaid_id> > seed_<dept>.sql
# options : --year-min 1799 --year-max 1855
```

---

## 4. Note pour plus tard — actualisation incrémentale (sans re-crawler tout l'arbre)

À terme il faudra **retrouver les manquants** (INSEE non résolus, feuilles sans
IIIF, nouvelles numérisations) **sans re-télécharger tout l'arbre** :

- **Persister un index local** des nœuds déjà visités (id, liste d'enfants,
  date de visite, ETag/Last-Modified) → un re-run ne fetch que les nœuds changés.
- **IIIF Change Discovery API** : FranceArchives/Biblissima exposent cette API
  précisément pour repérer les ressources **nouvelles ou actualisées** → idéal
  pour rafraîchir sans crawl complet.
- **INSEE manquants** : rejouer la résolution **uniquement** sur les lignes
  `insee IS NULL` (en base), contre un référentiel communes **enrichi**
  (communes anciennes/fusionnées, Insee historique) — sans toucher FranceArchives.
- **IIIF manquants** : ne re-vérifier que les feuilles précédemment sans
  manifeste (liste persistée), pas tout le fonds.

---

## 5. Suite

- **Mapper `service/NNNN` → libellé lisible** (« Archives départementales de … »)
  pour la mention « Source » exigée par le CRPA (actuellement l'URI brute).
- **Front** : afficher un badge « overlay/georef dispo » piloté par
  `licence_overlay_ok`, puis intégrer **Allmaps** pour ces communes.
- **Compléter les fonds éclatés** (ex. Calvados E→Z) via `to_do/`.
- **Demandes de réutilisation** aux AD dont la licence est « À vérifier ».
- **Passage à l'échelle nationale** : dump open-data FranceArchives + filtrage
  local, avec contrôle de licence par institution.

---

## Pour le commit — paragraphe « Notice »

> **Notice** — Pipeline de moisson FranceArchives → Supabase pour le cadastre
> napoléonien. Ajout du harvester local `harvest/harvest_francearchives.py`
> (franchissement du défi JS par token+cookie, export RDF `/{type}/{id}/rdf.xml`,
> élagage de branches par titre+dates `EXCLUDE_RE`/`period_overlaps`, filtre de
> période 1800-1860, extraction commune→INSEE / manifeste IIIF / image / licence).
> Schéma étendu (`migration_0002` : `cote`, `iiif_manifest`, `image_url`,
> `licence`, `licence_overlay_ok`) : la **licence par institution** pilote
> l'autorisation d'overlay/georef (SSD = Licence Ouverte ✅, Jura = restrictif ❌).
> Pilote Seine-Saint-Denis amorcé (`seed_ssd_pilot.sql`, Sevran). Méthodologie et
> suivi par département dans `METHODOLOGIE.md` et `to_do/`.
