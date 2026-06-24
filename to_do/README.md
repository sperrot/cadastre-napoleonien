# to_do — finding aids cadastre napoléonien (par département)

Suivi de la moisson FranceArchives → Supabase. Objectif : pour chaque
département, descendre l'arbre XML (RDF) du/des instrument(s) de recherche
jusqu'à **tous les documents de cadastre napoléonien** (tableaux d'assemblage,
sections, feuilles) numérisés.

## Organisation du dossier

- Un **sous-dossier par département** (`calvados/`, …).
- Tu y déposes le(s) fichier(s) finding aid RDF/XML ; je les range et les renomme
  `findingaid_<plage>_<id>.xml` (`<plage>` = tranche alpha des communes couvertes).
- Chaque sous-dossier a un `NOTES.md` détaillant ses finding aids et leur statut.
- Ce `README.md` porte le **tableau de synthèse maître** (mis à jour à ta demande).

## Comment lire l'arbre (rappel)

Le RDF d'un finding aid (racine) ne contient **ni IIIF ni licence** : seulement
le titre, le service (institution) et la liste des `facomponent` enfants
(`rico:includesOrIncluded`). IIIF + licence n'apparaissent qu'**en descendant
dans les facomponents** jusqu'aux feuilles — c'est ce que fait le harvester
(`harvest/harvest_francearchives.py`), à lancer **en local** (FranceArchives
bloque les fetchs serveur).

→ Les colonnes **licence** et **iiif dispo** ne peuvent donc être renseignées
qu'**au 1er run local** du harvester sur un échantillon de feuilles.

---

## Tableau de synthèse — amont du harvester

| Département | Lien XML arbre | Licence | IIIF dispo | Harvester |
|---|---|---|---|---|
| **Seine-Saint-Denis (93)** — FRAD093 · *pilote* | [findingaid `2679af1…`](https://francearchives.gouv.fr/findingaid/2679af120dcec5557878b634c3701f842b1d806e) · sous-nœud [facomponent « Plans cadastraux » `8c9077ce…`](https://francearchives.gouv.fr/facomponent/8c9077ce3826a2676417514c55903ae704aff91b) | ✅ OK | ✅ OK | 🟡 **en cours** — `python harvest_francearchives.py 8c9077ce3826a2676417514c55903ae704aff91b facomponent` |
| **Calvados (14)** — FRAD014 | A→D : [findingaid `d17231b4…`](https://francearchives.gouv.fr/findingaid/d17231b4a0689ac142534b2a6ee4fc0c190338a1)<br>E→Le Me : [findingaid `c89ef2c4…`](https://francearchives.gouv.fr/findingaid/c89ef2c4dfe0d59b57752e97961d4f0b9d067601) | ⏳ à déterminer (local) | ⏳ à déterminer (local) | `python harvest_francearchives.py d17231b4a0689ac142534b2a6ee4fc0c190338a1`<br>`python harvest_francearchives.py c89ef2c4dfe0d59b57752e97961d4f0b9d067601` — **à lancer** |

### Légende statuts
- **Lien XML arbre** : URL du finding aid FranceArchives (le `.rdf` est l'export téléchargé).
- **Licence** : ⏳ à déterminer · ✅ Licence Ouverte/Etalab/CC-BY/Domaine public (`overlay_ok`) · ⚠️ à vérifier.
- **IIIF dispo** : ⏳ à déterminer · ✅ manifeste(s) présent(s) · ❌ pas de IIIF (lien simple).
- **Harvester** : commande à lancer · 🟡 en cours · ✅ moissonné (→ `seed_*.sql`).

---

## ⚠️ Points d'attention par département

### Seine-Saint-Denis (93) — département pilote
- Fonds testé en premier (cf. `harvest/README.md`). Licence **OK** + **IIIF OK**.
- Le fichier déposé est un **sous-nœud** (`facomponent` « Plans cadastraux »,
  `8c9077ce…`), pas la racine : le lancer en mode `facomponent`.
- Arbre : 1799-1983 (filtrer la période napoléonienne via `--year-min/--year-max`).
- Détail : voir [`seine-saint-denis/NOTES.md`](seine-saint-denis/NOTES.md).

### Calvados (14)
- Fonds découpé alphabétiquement en plusieurs finding aids (FRAD014). Déposés :
  - **A → D** (`d17231b4…`, Ablon → Ducy-Sainte-Marguerite) — 198 sous-nœuds.
  - **E → Le Me** (`c89ef2c4…`, Écrammeville → Le-Mesnil-Villement) — 153 sous-nœuds.
- **Manque encore** la/les tranche(s) **Le Me → Z** : à récupérer et déposer dans `a_traiter/`.

Détail : voir [`calvados/NOTES.md`](calvados/NOTES.md).
