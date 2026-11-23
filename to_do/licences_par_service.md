# Licences par service (institution) — table manuelle

Les manifestes IIIF / RDF FranceArchives de ces fonds **ne portent pas** de
licence machine-lisible (au mieux un champ `attribution`). La licence doit donc
être renseignée **à la main**, par institution, d'après les CGU du site des AD.
Le harvester (`resolve_licence`) renverra « À vérifier » : cette table fait foi.

| Service | Institution | Dépt | Licence (confirmée) | overlay_ok | Source / CGU |
|---|---|---|---|---|---|
| `34471` | AD Val-d'Oise | 95 | ✅ OK (confirmée Sylvain) | true | CGU archives.valdoise.fr |
| `33495` | AD Calvados | 14 | ✅ OK (confirmée Sylvain) | true | CGU archives.calvados.fr |
| `34393` | AD Seine-Saint-Denis | 93 | ✅ Licence Ouverte (détectée au run pilote) | true | manifeste IIIF |
| _à renseigner_ | AD Jura | 39 | ✅ Licence Ouverte Etalab — feuilles du cadastre (accord écrit AD39, 2026-09) | true | accord écrit (CGU par défaut restrictives) |
| — (Mnesys, hors FA) | AD Drôme | 26 | ⚠️ Réutilisation **non commerciale** avec mention « Arch. dép. Drôme, cote » ; commerciale = licence avec redevance. CGU : « aucune extraction intégrale ou substantielle » sans accord écrit | **false** (liens seuls) tant que pas d'accord écrit | [page réutilisation](https://archives.ladrome.fr/page/reutilisation-des-informations-publiques) · [CGU](https://archives.ladrome.fr/page/conditions-generales-d-utilisation) (lues le 2026-11-23) |

> `overlay_ok = true` → autorise la rediffusion publique des images (georef).
> À reverser dans le seed SQL (`licence`, `licence_overlay_ok`) en surcharge de
> ce que renvoie le harvester.
