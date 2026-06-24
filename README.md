# Cadastre napoléonien — annuaire cartographique

Visualiseur web léger pour retrouver, par commune, les plans du **cadastre
napoléonien** numérisés par les archives départementales (tableaux
d'assemblage, sections, feuilles).

> **État : V0.0 — « annuaire cartographique ».**
> Carte + recherche de commune + liens vers les plans d'archives.
> Aucune image hébergée, aucun géoréférencement (paliers suivants).

## Principe : le plus léger possible

| Composant | Choix | Coût |
|-----------|-------|------|
| Front | Statique (MapLibre GL JS, CDN) | 0 € (GitHub/Cloudflare Pages) |
| Fond de carte | OSM raster (sans clé) | 0 € |
| Communes (recherche + contours) | [geo.api.gouv.fr](https://geo.api.gouv.fr) côté client | 0 € (rien à héberger) |
| Liens d'archives | table `document` dans Supabase | 0 € (free tier) |
| Images des plans | **restent chez les archives** (lien sortant) | 0 € |

L'app n'héberge donc **aucune image** : elle indexe et cartographie des liens.
Le travail lent et non automatisable — retrouver le bon lien par commune dans
chaque portail (Mnesys, Ligeo, EAD… chaque département diffère) — est destiné à
être **crowdsourcé** (palier V0.1).

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

## Démarrage local

La V0.0 fonctionne **sans Supabase** (carte + recherche seules) :

```bash
cd web
python -m http.server 8000   # ou tout serveur statique
# → http://localhost:8000
```

Pour afficher les liens d'archives, brancher Supabase :

1. Créer un projet sur [supabase.com](https://supabase.com) (free tier).
2. SQL Editor → exécuter `supabase/schema.sql` puis `supabase/seed.sql`.
3. `cp web/config.example.js web/config.js` et renseigner `SUPABASE_URL` +
   `SUPABASE_ANON_KEY` (Settings → API). La clé `anon` est publique :
   l'écriture reste verrouillée par les *Row Level Security policies*.

## Utilisation

- **Rechercher** une commune par son nom (autocomplete).
- **Cliquer** sur la carte : sélectionne la commune sous le pointeur.
- Le panneau liste les plans disponibles, groupés en *tableau d'assemblage →
  sections → feuilles*, chaque entrée ouvrant le viewer de l'archive.

## Feuille de route

- **V0.0** ✅ Annuaire cartographique (lecture).
- **V0.2** Superposition d'emprises approximatives (`ImageOverlay` par bbox).
- **V0.3** Géoréférencement réel via [Allmaps](https://allmaps.org) (annotations
  JSON, rendu déformé côté navigateur, sans serveur de tuiles) + sections au
  zoom fort.
- **V1** Workflow de validation, couverture multi-départements, exports.
