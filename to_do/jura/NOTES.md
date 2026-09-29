# Jura (39) — portail Mnesys `archives39.fr`

## Licence

CGU par défaut restrictives (« ne pas diffuser/modifier sans accord écrit »).
**Accord écrit de l'AD39 obtenu (2026-09) : Licence Ouverte Etalab sur les
feuilles du cadastre** → `licence_overlay_ok = true`, statut `georef`.

## Source : API du plan de classement (HAR du 2026-09-29)

| Élément | Valeur |
|---|---|
| Racine (fonds « Cadastre », suffixe de session) | `1fcfd6ea-9d0d-412a-acda-da315013c1f2` |
| Départ « Documents cadastraux dits napoléoniens » | `5d09a609-34a0-4805-95af-ec46d2c1388b` |
| Enfants d'un nœud | `GET /api/classificationPlan/v1/children/{uuid}_{racine}` |
| Cookies | `license=true` + `PHPSESSID` (hCaptcha présent sur le site) |
| Planche | `data.url` = ark, `data.contentUrl` = `/record/36595/<ark>/content` |
| JPEG | `/ark:/36595/<ark>/<uuid_média>` |

Arbre : lettre → commune → **Plans parcellaires napoléoniens** (retenu) /
Etats de sections et matrices (écarté) → planches (TA, sections, feuilles).

Référence : Abergement-la-Ronce, TA — ark `7kbm3w2qnglr`, média
`09015152-973c-47cf-8c36-995ca8c72371`.

Pas de manifeste IIIF natif repéré → JPEG → IIIF par le worker
(`/static-manifest`, hôte `archives39.fr` ajouté, cookie `license=true`).

## Pipeline (en local)

```bash
python harvest/harvest_jura.py --check      # l'uuid média de référence doit être retrouvé
python harvest/harvest_jura.py --limit 30   # essai
python harvest/harvest_jura.py              # → harvest/seed_jura.sql
python harvest/load_seed_to_supabase.py harvest/seed_jura.sql
```

Worker à redéployer avant le chargement : `cd proxy/iiif-allmaps && npx wrangler deploy`.

## Points ouverts

- `--check` non encore passé : l'emplacement de l'uuid média dans `contentUrl`
  est supposé, pas relevé.
- Communes fusionnées avant 1943 : rattachées via la mention « fusionnée à
  celle de X » du titre ; le reste → `INSEE_a_reconcilier.md`.
- Année : absente des titres observés → `annee` null.
