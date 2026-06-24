# Seine-Saint-Denis (93) — FRAD093 · **département pilote**

Service FranceArchives : `service/34393` (Archives départementales de la Seine-Saint-Denis).
Statut : licence **OK** ✅ · IIIF **OK** ✅ · harvester **🟡 en cours**.

## Finding aids du fonds cadastre

| Fichier | Niveau | ID FranceArchives | Titre | Période | Enfants niv.1 | Statut |
|---|---|---|---|---|---|---|
| [`facomponent_plans-cadastraux_8c9077ce….xml`](facomponent_plans-cadastraux_8c9077ce3826a2676417514c55903ae704aff91b.xml) | sous-nœud (`facomponent`) | `8c9077ce3826a2676417514c55903ae704aff91b` | « Plans cadastraux. » | 1799 → 1983 | 40 | déposé, **harvest en cours** |
| _(racine)_ | `findingaid` | `2679af120dcec5557878b634c3701f842b1d806e` | IR « Plans du cadastre » | — | — | racine parente |

## Structure RDF observée (sous-nœud « Plans cadastraux »)

- `rico:title` = « Plans cadastraux. » · `beginningDate` 1799 · `endDate` 1983
- `rico:hasOrHadManager` → `service/34393`
- Rattachement : `isOrWasIncludedIn` → findingaid `2679af1…` (la racine)
- 40 × `rico:includesOrIncluded` → `facomponent/<id>` (communes / plans)
- Licence + manifestes IIIF présents en descendant dans les feuilles (AD93 expose IIIF).

## Commande harvester

```bash
cd harvest
# sous-nœud précis (recommandé pour ce fichier) :
python harvest_francearchives.py 8c9077ce3826a2676417514c55903ae704aff91b facomponent > seed_ssd_cadastre.sql

# ou tout l'IR racine :
python harvest_francearchives.py 2679af120dcec5557878b634c3701f842b1d806e > seed_ssd.sql
```

Période napoléonienne : ajouter `--year-min 1800 --year-max 1860` pour filtrer
les feuilles hors période (l'arbre va jusqu'à 1983).
