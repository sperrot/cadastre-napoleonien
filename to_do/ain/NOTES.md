# Ain (01) — FRAD001

Service FranceArchives : `service/33359` (Archives départementales de l'Ain).

## Finding aid

| Fichier | ID | Titre | Cotes | Période | Enfants niv.1 |
|---|---|---|---|---|---|
| [`findingaid_eefe9797….xml`](findingaid_eefe9797a37dd7e91a65765a7fa44eb3141bec46_rdf.xml) | `eefe9797a37dd7e91a65765a7fa44eb3141bec46` | « Répertoire méthodique du Cadastre napoléonien » | `3 P 1-10188 ; 1777 W 2-498` · `FRAD001_CADASTRE_NAPO` | 1802 → 1978 | 463 (communes) |

## ⚠️ Périmètre : cadastre COMPLET → on ne garde que les PLANS

Contrairement à Vosges/Val-d'Oise (finding aids « Plans du cadastre napoléonien »,
plans seuls), l'arbre Ain est le **répertoire complet**. Chaque commune a, en
sous-nœuds : `Limites de communes`, `État de la section…`, **`Plans parcellaires`**
(← les plans), `Matrices anciennes`, `Propriétés foncières…`. 

**Décision (2026-06-29) : plans uniquement.** Moissonné via `scout_cadastre.py`
qui isole la branche **« Plans parcellaires »** par commune et **élague** les
branches-registres (état/matrice/propriété).

## Licence / IIIF

- **Licence** : overlay_ok **true** (confirmé Sylvain, CGU AD01). Le manifeste ne
  porte qu'un `attribution` → ajouté en dur dans `SERVICE_LICENCE["33359"]` du
  harvester. Voir [`../licences_par_service.md`](../licences_par_service.md).
- **IIIF** : ✅ serveur famille « FOND.TIF » (comme Vosges) → **marche en direct
  dans Allmaps** avec l'URL `…/manifest` (cf. [`../diagnostic_iiif_allmaps.md`](../diagnostic_iiif_allmaps.md)).

## Correctif scout appliqué pour cet arbre

Le run a révélé deux trous du scout, corrigés et validés sur 12 communes :
1. `PLANS_NEG` durci : `\b[ée]tats?\b` capte « État **de la** section A » (le « de la »
   cassait l'ancien motif) + `limites de commune`, `propriété`, `folio`, `sommier`.
2. **Élagage des branches-registres** dès leur titre (`depth>0` + `PLANS_NEG`) :
   évite que « État de section » (dont les enfants « Section A » passent le filtre)
   soit capté comme branche plans.

## Commande

```bash
cd harvest
python scout_cadastre.py eefe9797a37dd7e91a65765a7fa44eb3141bec46 findingaid \
    --run --out seed_ain.sql        # TLS via truststore (auto)
```
