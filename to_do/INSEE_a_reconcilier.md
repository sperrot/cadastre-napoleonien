# Cas à réconcilier — futur run d'appariement commune → INSEE

Cases non résolues lors des moissons, à reprendre **sans recrawler tout l'arbre**
(cf. METHODOLOGIE.md §4) : un run dédié qui ne rejoue que ces entrées.

Deux familles :
- **Communes absentes** (nœud sauté transitoirement) → à récupérer par re-run.
- **INSEE non résolu** (commune ancienne/hameau, ou nom raté par geo.api) → à
  mapper vers l'INSEE actuel.

---

## Seine-Saint-Denis (93) — communes ABSENTES (saut transitoire)

À récupérer par re-run du harvester (idempotent : `delete … where left(insee,2)='93'`
puis recharge). Vérifier leur présence ensuite.

| Commune | INSEE | Cause |
|---|---|---|
| Aubervilliers | 93001 | nœud sauté pendant le crawl |
| Saint-Denis | 93066 | nœud sauté pendant le crawl |

---

## Val-d'Oise (95) — INSEE non résolu

**Run du 2026-06-29** (findingaid `5570bf08…`) : **1477 feuilles collectées →
`harvest/seed_val-doise.sql`**, dont **15 feuilles non résolues** réparties sur
**5 libellés**. À reprendre par run dédié (sans recrawl), puis `UPDATE` ciblé du seed.

Le libellé `location` porte souvent la **commune actuelle entre parenthèses** :
`Arthieul (Magny-en-Vexin, Val-d'Oise, France)`. Piste : parser le 1er terme
parenthétique → geo.api `nom=<token>&codeDepartement=95`.

| Libellé brut (commune captée) | Commune actuelle | Type | Feuilles | Piste INSEE |
|---|---|---|---|---|
| Arthieul (Magny-en-Vexin, …) | Magny-en-Vexin | ancienne commune / hameau | 3 (assemblage + Section A Le Village 1ʳᵉ/2ᵉ) | rattacher à Magny-en-Vexin |
| Gadancourt (Avernes, …) | Avernes | ancienne commune / hameau | 5 (assemblage + Sect. A La Montagne 1/2 + Sect. B Le Village 1/2) | rattacher à Avernes |
| Gouzangrez (Commeny, …) | Commeny | ancienne commune / hameau | 3 (assemblage + Sect. A feuille unique + dévelop. village) | rattacher à Commeny |
| « Section A, Le Bois de Boissy. » | — indéterminée | **parent = section** : commune jamais captée | 2 (1ʳᵉ/2ᵉ feuille) | retrouver (Boissy-l'Aillerie ?) via l'arbre / la cote |
| « Section B, Le Village. » | — indéterminée | **parent = section** : commune jamais captée | 2 (1ʳᵉ/2ᵉ feuille) | retrouver la commune via l'arbre / la cote |

> Notes du run :
> - **Saint-Gratien** (présent dans la liste précédente) **n'apparaît plus** dans
>   les warnings de ce run → considéré **résolu** (à vérifier dans le seed).
> - Variante typographique : `Gadancourt` porte une **apostrophe courbe**
>   (`Val-d’Oise`) vs droite ailleurs → le parser doit gérer `'` et `’`.
> - Les 3 hameaux (Arthieul, Gadancourt, Gouzangrez) = **8 feuilles** récupérables
>   automatiquement ; les 2 cas « section orpheline » = **4 feuilles** au cas par cas.

---

## Vosges (88) — INSEE non résolu

**Run du 2026-06-29** (findingaid `_id à renseigner_`) : **6410 feuilles collectées
→ `harvest/seed_vosges.sql`**, ~**185 feuilles non résolues**. Quatre familles
(les 3 du Val-d'Oise + une nouvelle : « sections orphelines »).

**Ingéré dans Supabase** (état 2026-06-29) :

| communes | documents | tableaux d'assemblage | overlay_ok |
|---|---|---|---|
| 453 | 5691 | 460 | 5691 (**100 %** — Licence Ouverte) |

→ **719 feuilles** non ingérées (6410 collectées − 5691) = celles sans INSEE
(familles A–D ci-dessous). **Complétion REPORTÉE** (décision 2026-06-29) : la
réconciliation se fera plus tard, sans recrawl.

### A — hameau/ancienne commune AVEC commune actuelle entre () → auto (token parenthèse + geo.api `codeDepartement=88`)

| Libellé capté (commune actuelle) | Commune actuelle | ~feuilles |
|---|---|---|
| Colroy-la-Grande (Provenchères-et-Colroy) | Provenchères-et-Colroy | 11 |
| Granges-de-Plombières (Plombières-les-Bains) | Plombières-les-Bains | 11 |
| Harsault (La Vôge-les-Bains) | La Vôge-les-Bains | 7 |
| Hautmougey (La Vôge-les-Bains) | La Vôge-les-Bains | 4 |
| Moncel-et-Happoncourt (Moncel-sur-Vair) | Moncel-sur-Vair | 6 |
| La Neuveville-lès-Raon (Raon-l'Étape) | Raon-l'Étape | 17 (doublon apparent dans le log) |
| Oncourt (Thaon-les-Vosges) | Thaon-les-Vosges | 3 |
| Provenchères-sur-Fave (Provenchères-et-Colroy) | Provenchères-et-Colroy | 1 |
| Rouceux (Neufchâteau) | Neufchâteau | 5 |
| Ruaux (Plombières-les-Bains) | Plombières-les-Bains | 7 |
| Saint-Jean-du-Marché (La Neuveville-devant-Lépanges) | La Neuveville-devant-Lépanges | 5 |

### B — nom de commune + « (Vosges, France) » seul, raté par geo.api (homonymes hors-dépt) → requête `codeDepartement=88` / alias

| Commune | INSEE actuel probable | ~feuilles |
|---|---|---|
| Rainville | 88375 | 17 |
| Ramecourt | 88369 (homonyme Pas-de-Calais 62) | 6 |
| Rollainville | 88400 | 6 |
| La Neuveville-sous-Châtenois | à vérifier (fusion ?) | 12 |

### C — ancienne commune/hameau SANS parenthèse → COG historique / heuristique nom

| Libellé | Piste |
|---|---|
| Fruze | hameau/ancienne commune → COG ; ses sections tombent en orphelines (famille D) |
| Gouécourt | idem |
| Outrancourt | idem |
| Rémois | idem |
| Uzemain-les-Forges | vraisemblablement **Uzemain** (88488) |

### D — sections orphelines (commune PERDUE) → remonter l'arbre / cote / sujet `location`

Feuilles captées avec, comme « commune », un libellé générique :
`Section unique`, `Section A`, `Section B`, `Tableau d'assemblage`. Le nom de la
commune n'a jamais été propagé. Ce sont **très probablement les sections des
communes de la famille C** (Fruze, Gouécourt, Outrancourt, Rémois, Uzemain-les-Forges)
dont **seul le Tableau d'assemblage** a capté le nom.

> ⚠️ **Bug structurel du harvester révélé ici** : pour certaines formes d'arbre,
> le nom de commune n'est propagé qu'au **Tableau d'assemblage**, pas aux feuilles
> de section (qui sont des **frères** de l'assemblage, pas des enfants) → elles
> tombent en « Section X » orphelin. À corriger : propager `commune_hint` depuis
> le nœud commune vers TOUS ses descendants, ou résoudre la commune via le sujet
> `location` de chaque feuille. Cela supprimerait la famille D **et** une partie de C.

> Le détail par feuille (sections A1, B2…) fait foi dans `harvest/seed_vosges.sql`.

---

## Doubs (25) — INSEE non résolu

**Run du 2026-06-29** : **633 feuilles « Atlas parcellaire » → `harvest/seed_doubs.sql`**,
~**88 feuilles non résolues**. Cas plus homogène que Vosges : la commune EST captée
(libellé `Nom (Atlas parcellaire)`), mais geo.api échoue → presque tout est de la
**commune ancienne/fusionnée** (famille C) ou une commune actuelle ratée (famille B).

> Le Doubs apporte un 3ᵉ nom de branche « plans » : **« Atlas parcellaire »**
> (après « Plans cadastraux », « Plans du cadastre napoléonien », « Plans parcellaires »,
> « Plans Napoléoniens »). Bien couvert par `PLANS_POS` du scout (`atlas`).

### Traitement (3 sous-cas)

1. **Article inversé `Nom (Le/La/Les)`** → reformer `Le/La/Les Nom` avant geo.api :
   Allemands (Les), Châtelet (Le), Chaux-de-Gilley (La), Friolais (Le),
   Gratteris (Le), Longevilles-Mont-d'Or (Les).
2. **Orphelin (famille D)** : `Atlas parcellaire (Plan général de Besançon et de son
   territoire ; section A)` → commune = **Besançon (25056)**.
3. **Communes anciennes/fusionnées + actuelles ratées** (le gros) → geo.api
   `codeDepartement=25`, puis COG historique pour les fusionnées. Liste brute :

   Alaise, Antorpe, Arcier, Arguel, Athose, Auxon-Dessous, Auxon-Dessus,
   Bians-les-Usiers, Bois-la-Ville, Boismurie, Bonnevaux-le-Prieuré,
   Brey-et-Maisons-du-Bois, Cernay-l'Église, Champvans-lès-Baume, Chapelle-d'Huin,
   Charbonnières-les-Sapins, Chasnans, Châtillon-sur-Lison, Châtillon-sous-Maîche,
   Chaux-lès-Châtillon, Chaux-lès-Clerval, Chazelot, Chazoy, Chevigney-sur-l'Ognon,
   Colombier-Châtelot, Cordiron, Cottier, Coulans-sur-Lison, Courcelles-lès-Châtillon,
   Courcelles-lès-Quingey, Cour-lès-Baume, Cussey-sur-l'Ognon, Doulaize, Droitfontaine,
   Glainans, Goux-les-Usiers, Grand-Combe-Châteleu, Grand-Combe-des-Bois,
   Grandfontaine-Fournets, Granges-Maillot, Granges-Sainte-Marie, Granges-Vienney,
   Hautepierre-le-Châtelet, Hauterive-la-Fresse, Labergement-du-Navois,
   Longevelle-sur-le-Doubs, Maisières-Notre-Dame, Mambouhans, Montancy-Brémoncourt,
   Montferney, Montflovin, Montfort, Montursin, Morchamps, Mouillevillers,
   Mouthier-Hautepierre, Neuvier, Nods, Pointvillers, Pompierre-sur-le-Doubs,
   Rantechaux, Refranche, Saint-Maurice-Échelotte, Sancey-le-Grand, Sancey-le-Long,
   Santoche, Saraz, Scey-en-Varais, Sombacour, Tournedoz, Vaire-le-Grand,
   Vaire-le-Petit, Vanclans, Vauchamps, Vaux-les-Prés, Vernois-le-Fol,
   Verrières-du-Grosbois, Ville-du-Pont, Villeneuve-d'Amont, Villerschief,
   Villers-sous-Montrond.

> Détail par feuille : `harvest/seed_doubs.sql`. **Complétion reportée.**

---

## Stratégie d'appariement (run futur)

1. **Hameaux / anciennes communes** : extraire la commune actuelle = 1er token
   entre parenthèses du libellé `location` → geo.api `nom=<token>&codeDepartement=95`.
   (NB : le plan reste rattaché à la commune actuelle ; on pourra garder le nom
   historique en métadonnée.)
2. **Communes (nom + dépt) ratées par geo.api** (homonymes hors-dépt : Rainville,
   Ramecourt, Rollainville, Saint-Gratien, Pierrefitte-sur-Seine…) → requêter avec
   `codeDepartement` ou enrichir `COMMUNE_ALIAS`. Gain le plus simple, à faire en 1er.
3. **Cas « parent = section » / sections orphelines** (Le Bois de Boissy ; Vosges
   famille D) : commune non captée → **corriger le harvester** pour propager la
   commune à TOUTES les feuilles (pas seulement l'assemblage) ou la dériver du
   sujet `location` de chaque feuille. Supprime la famille D et une partie de C.
4. **Anciennes communes/hameaux sans parenthèse** (Fruze, Gouécourt, Outrancourt…)
   → brancher un **référentiel des communes historiques** (COG INSEE / fusions)
   plutôt que le seul geo.api.
5. **Article inversé `Nom (Le/La/Les)`** (Doubs : Châtelet (Le), Allemands (Les)…)
   → reformer `Le/La/Les Nom` avant la requête geo.api.

> Le correctif #3 (propagation commune) doit être appliqué **avant** de relancer :
> il réduit mécaniquement le volume à réconcilier sur tous les départements.
