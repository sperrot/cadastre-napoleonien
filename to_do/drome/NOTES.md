# Drôme (26) — portail Mnesys `archives.ladrome.fr`

**Objectif : le cadastre napoléonien de la rivière Drôme** — les 38 communes
que la rivière traverse ou longe, de sa source (La Bâtie-des-Fonds) à sa
confluence avec le Rhône (Livron / Loriol), sur 112,7 km.

## Ce qui a été vérifié (2026-11-23)

| Point | Constat |
|---|---|
| Portail | Mnesys (Naoned), même logiciel que le Jura et le Doubs |
| Fonds | formulaire « Cadastre » `search/form/47e6db60…` : « les plans de chaque commune jusqu'en 2002 », **sauf Romans-sur-Isère** (sur le site des archives de la ville, avec états de section et matrices 1825-1908) |
| Cadre de classement | archdesc `f6e10de9-0e70-4023-8366-c625f2560b7b` = `ark:/24626/1r85jlbwtgfk` ; API `/api/classificationPlan/v1/tree/{uuid}_{uuid}` déclarée dans la page (`#classification-plan-navigation`) |
| NAAN | `24626` |
| Captcha | reCAPTCHA déclaré sur le formulaire de recherche (`data-captcha="recaptcha"`) |
| FranceArchives | non vérifié (le harvester FA doit tourner en local) |
| TLS | ⚠️ le serveur **n'envoie pas son certificat intermédiaire** (*Gandi RSA Domain Validation Secure Server CA 4*). Les navigateurs le récupèrent seuls ; `requests` / `curl` échouent (`unable to get local issuer certificate`). L'intermédiaire officiel (crt.sectigo.com, chaîné à *Sectigo Public Server Authentication Root R46*) est versionné dans [`harvest/certs/gandi_rsa_dv_ca4.pem`](../../harvest/certs/gandi_rsa_dv_ca4.pem) et ajouté à certifi par le connecteur : la vérification reste complète. |

Non relevé : le nœud du cadastre napoléonien dans le cadre de classement, et
la forme exacte d'une planche (uuid média, `/images/<uuid>.jpg` comme au Jura ?).
L'outil de sécurité de la session Claude a refusé l'appel à l'API interne du
portail : **les étapes `--find` et `--check` sont à lancer en local**.

## Licence et CGU — ce qui bloque l'overlay

- [Réutilisation des informations publiques](https://archives.ladrome.fr/page/reutilisation-des-informations-publiques) :
  réutilisation **autorisée à des fins privées ou non commerciales**, mention
  obligatoire « Archives départementales de la Drôme (Arch. dép. Drôme ou
  AD26), cote, auteur(s) » ; **commerciale = licence avec redevance** (formulaire
  papier en double exemplaire).
- [CGU](https://archives.ladrome.fr/page/conditions-generales-d-utilisation) :
  « Aucune extraction intégrale ou substantielle, reproduction et/ou
  représentation […] du Site et de son contenu ne pourra en être faite sans
  l'accord préalable et écrit de l'éditeur. » Cookie `license` = acceptation des
  conditions de réutilisation des médias, exigé par le visualiseur.

Conséquences pour le repo :

1. **Pas une Licence Ouverte** → `licence_overlay_ok = false`, `statut = 'lien'`,
   pas de manifeste worker (le worker ne rediffuse pas les images AD26 ;
   `archives.ladrome.fr` n'est **pas** dans `ALLOWED` de `proxy/iiif-allmaps/worker.js`).
2. **Moisson ciblée** : le connecteur ne descend que les communes du corridor
   (≈ 10 % des 362 communes), à 1 requête/s. `--tout` n'est à lancer qu'avec
   l'accord écrit.
3. Même voie que l'AD39 : **demande écrite** (modèle ci-dessous). Une fois
   l'accord obtenu : `--licence-ouverte`, ajouter `archives.ladrome.fr` (+ cookie
   `license=true`) au worker, redéployer, recharger.

## Pipeline (en local)

```bash
pip install requests certifi
python harvest/harvest_drome.py --find                      # 1. nœud « cadastre napoléonien »
python harvest/harvest_drome.py --check <ark d'une planche>  # 2. calibrer image / cote / année
python harvest/harvest_drome.py --start <uuid> --limit 20    # 3. essai
python harvest/harvest_drome.py --start <uuid>               # 4. corridor → harvest/seed_drome.sql
python harvest/load_seed_to_supabase.py --replace-dept 26 harvest/seed_drome.sql
```

Une fois `--find` et `--check` passés, reporter ici l'uuid de départ et l'ark de
référence, et figer l'uuid dans `START` (comme pour le Jura).

Le rapport de fin de run liste :
- les communes riveraines **non couvertes** (pk + INSEE) ;
- les **nœuds-communes au nom inconnu** (anciennes communes) → `communes_alias.json["26"]` ;
- les rattachements via `CANDIDATS_HISTORIQUES` **à confirmer** (Recoubeau,
  Jansac, Piégros, La Clastre, Ponet, Blacons, et les formes courtes Luc,
  Montlaur, Montmaur, Lesches, Aouste, Livron, Loriol, Aix). Les noms ambigus
  dans le département (Beaumont, Saint-Sauveur, Saint-Auban, Mirabel) sont
  volontairement exclus.

## Corridor de la rivière

Produit par [`harvest/corridor_riviere.py`](../../harvest/corridor_riviere.py) depuis
la Géoplateforme IGN (BD TOPO `cours_d_eau` objet `COURDEAU0000002000803141`,
ADMIN EXPRESS COG). Communes retenues : intersectant le lit à 100 m près.
Résultat : [`harvest/corridor_drome.json`](../../harvest/corridor_drome.json) (filtre
du connecteur) et [`web/data/riviere_drome.geojson`](../../web/data/riviere_drome.geojson)
(calque « Rivière Drôme — communes riveraines » de la carte).

| pk (km) | INSEE | Commune | Anciennes communes (IGN) | Relation |
|---|---|---|---|---|
| 2.7 | 26030 | La Bâtie-des-Fonds |  | traversée |
| 6.6 | 26361 | Valdrôme |  | traversée |
| 11.7 | 26255 | Les Prés |  | traversée |
| 15.3 | 26040 | Beaurières |  | traversée |
| 17.3 | 26076 | Charens |  | traversée |
| 19.9 | 26164 | Lesches-en-Diois |  | traversée |
| 20.9 | 26036 | Beaumont-en-Diois |  | traversée |
| 26.4 | 26167 | Luc-en-Diois |  | traversée |
| 30.0 | 26204 | Montlaur-en-Diois |  | traversée |
| 32.3 | 26178 | Menglon |  | bordière (62 m) |
| 33.9 | 26262 | Recoubeau-Jansac |  | traversée |
| 36.1 | 26025 | Barnave |  | traversée |
| 37.1 | 26205 | Montmaur-en-Diois |  | traversée |
| 37.1 | 26327 | Saint-Roman |  | traversée |
| 40.0 | 26001 | Solaure en Diois | Molières-Glandaz, Aix-en-Diois | traversée |
| 41.4 | 26159 | Laval-d'Aix |  | traversée |
| 47.2 | 26113 | Die |  | traversée |
| 52.2 | 26246 | Ponet-et-Saint-Auban |  | traversée |
| 54.6 | 26299 | Sainte-Croix |  | traversée |
| 58.4 | 26248 | Pontaix |  | traversée |
| 61.6 | 26027 | Barsac |  | traversée |
| 64.0 | 26019 | Aurel |  | traversée |
| 64.4 | 26368 | Vercheny |  | traversée |
| 68.0 | 26122 | Espenel |  | traversée |
| 72.8 | 26289 | Saillans |  | traversée |
| 75.0 | 26328 | Saint-Sauveur-en-Diois |  | traversée |
| 76.5 | 26015 | Aubenasson |  | traversée |
| 80.6 | 26183 | Mirabel-et-Blacons |  | traversée |
| 81.2 | 26234 | Piégros-la-Clastre |  | traversée |
| 85.8 | 26011 | Aouste-sur-Sye |  | traversée |
| 89.6 | 26108 | Crest |  | traversée |
| 91.8 | 26115 | Divajeu |  | traversée |
| 93.8 | 26065 | Chabrillan |  | traversée |
| 94.5 | 26125 | Eurre |  | traversée |
| 98.9 | 26006 | Allex |  | traversée |
| 99.1 | 26144 | Grane |  | traversée |
| 107.1 | 26165 | Livron-sur-Drôme |  | traversée |
| 107.1 | 26166 | Loriol-sur-Drôme |  | traversée |

Le pk est la position, depuis la source, du centre de la portion de commune
riveraine (approximatif pour les communes qui bordent un long tronçon).

## Modèle de demande d'accord (à adapter, envoi à archives@ladrome.fr)

> Objet : demande d'autorisation de réutilisation — plans du cadastre
> napoléonien des communes riveraines de la Drôme
>
> Madame, Monsieur,
>
> Je développe un annuaire cartographique non commercial du cadastre
> napoléonien, qui recense par commune les plans numérisés par les archives
> départementales et renvoie vers leurs visionneuses (lien ARK, mention de la
> source et de la cote).
>
> Je souhaiterais y intégrer les plans napoléoniens (tableaux d'assemblage et
> feuilles de section) des 38 communes riveraines de la rivière Drôme, de
> La Bâtie-des-Fonds à Livron et Loriol. Cela suppose :
>
> 1. de relever, pour ces seules communes, les métadonnées des planches
>    (commune, cote, date, identifiant ARK) depuis votre portail, à un rythme
>    d'une requête par seconde ;
> 2. si vous l'acceptez, de superposer ces plans à la carte actuelle
>    (géoréférencement), ce qui implique d'afficher l'image transformée, avec
>    la mention « Arch. dép. Drôme, <cote> ».
>
> L'AD du Jura a accordé pour un usage comparable la Licence Ouverte Etalab
> sur les feuilles de son cadastre. Pourriez-vous m'indiquer si une
> autorisation équivalente est envisageable, pour le corridor de la Drôme
> voire pour l'ensemble du département ?
>
> Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations
> distinguées.
