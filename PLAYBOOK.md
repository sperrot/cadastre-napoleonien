# PLAYBOOK — ajouter un département

Séquence à suivre pour chaque département. Détails et justifications dans
[METHODOLOGIE.md](METHODOLOGIE.md) ; suivi par département dans [`to_do/`](to_do/).

## Vue d'ensemble

```
FranceArchives          scout_cadastre.py         harvest_francearchives.py      Supabase
(trouver le fonds)  →   (check IIIF + licence)  →  (crawl local → seed.sql)   →   (delete + insert)  →  carte
   id findingaid            optionnel                 EN LOCAL (PowerShell)         SQL Editor
```

> ⚠️ Le harvester se lance **en local** (PowerShell). Lancé autrement, le TLS vers
> FranceArchives échoue. C'est toi qui le lances ; l'analyse des sorties se fait ensuite.

---

## 1. Trouver l'arbre (finding aid)

- Sur **francearchives.gouv.fr** : filtrer par **service d'archives** (le département)
  + recherche « cadastre » / « plans du cadastre ».
- Prendre le finding aid **en tête du fonds cadastre** (souvent série **3P** ou
  « Plans du cadastre »). L'**id** est dans l'URL : `…/findingaid/<ID>`.
- ⚠️ **Fonds éclatés** : vérifier la couverture alphabétique des communes (ex.
  Calvados = A→D + E→LeMe + …) et récupérer les **finding aids frères**.
- 👉 **Entrée unique du pipeline = `<ID>`.** (Dépose le RDF dans `to_do/<dept>/`.)

## 2. Check IIIF + licence (recommandé)

```powershell
python scout_cadastre.py <ID> findingaid        # reconnaissance, sans moisson
```
- **IIIF ❌** → pas d'Allmaps possible → département en **liens seuls**.
- Licence **« Licence Ouverte »** → overlay autorisé ✅ ; sinon **« À vérifier »**
  → liens seuls (overlay désactivé tant que la licence AD n'est pas confirmée).

## 3. Harvester (en local)

```powershell
cd C:\Users\sperr\Desktop\mapping_cadastre_napoleonien\harvest
python harvest_francearchives.py <ID> --out seed_<dept>.sql
```
Sous le capot : franchit l'anti-bot (token+cookie), descend l'arbre, **élague**
(rénové / intendance / masse de culture + hors période **1790-1860**), extrait
chaque feuille, résout l'INSEE (geo.api + `COMMUNE_ALIAS`).
- Surveiller l'entête : **`-- N notices avec INSEE / M feuilles`** + les **`⚠`**.
- Options : `--year-min 1799 --year-max 1855`.

## 4. Entrées → Sorties

- **Entrée** : 1 `<ID>` (le script tire le reste de FranceArchives + geo.api).
- **Sortie** : `seed_<dept>.sql` = un `INSERT` par feuille. Colonnes :
  `insee · type (tableau_assemblage/section/feuille) · annee · cote ·
  archive_url · iiif_manifest · image_url · source · source_url · licence ·
  licence_overlay_ok · statut (georef|lien)`.

## 5. Charger en base (idempotent par département)

SQL Editor Supabase :
```sql
delete from document where left(insee,2) = '<DD>';   -- ex. '95'
-- puis coller tout seed_<dept>.sql -> Run
```
Vérifier :
```sql
select count(distinct insee) communes, count(*) total,
       count(*) filter (where type='tableau_assemblage') tableaux,
       count(*) filter (where licence_overlay_ok) overlay_ok
from document where left(insee,2)='<DD>';
```

## 6. Consigner les manquants

Ajouter à [`to_do/INSEE_a_reconcilier.md`](to_do/INSEE_a_reconcilier.md) :
- les **`⚠ INSEE introuvable`** (hameaux / anciennes communes — la commune
  actuelle est entre parenthèses dans le libellé) ;
- les **communes absentes** (nœud sauté → à récupérer par re-run).

---

## Les 3 pièges

| Piège | Symptôme | Parade |
|---|---|---|
| **Noms historiques** | `Arthieul (Magny-en-Vexin…)`, `Montreuil-sous-Bois` → INSEE introuvable | `COMMUNE_ALIAS`, ou run d'appariement (parenthèse) |
| **Sauts transitoires** | une commune entière absente | re-run (idempotent : delete + insert) |
| **Licence variable** | `overlay_ok=0` (ex. Val-d'Oise) | normal : liens seuls tant que la licence AD n'est pas confirmée |

## Couverture actuelle

| Dépt | Communes | Tableaux | Overlay |
|---|---|---|---|
| 93 Seine-Saint-Denis | ~35 | ~38 | ✅ Licence Ouverte |
| 95 Val-d'Oise | ~181 | 183 | ⏳ à vérifier (liens seuls) |
