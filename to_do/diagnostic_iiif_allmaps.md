# Diagnostic IIIF → Allmaps (par éditeur de serveur)

Pour géoréférencer dans **Allmaps**, il faut un **manifeste IIIF** servi avec un
CORS correct. Mesures réelles (origine simulée `editor.allmaps.org`). **Toujours
coller l'URL `…/manifest` dans Allmaps, jamais le lien ARK** (l'ARK est une page
de visionneuse, pas une ressource IIIF).

## 3 familles rencontrées

### A. Serveur « cache FOND.TIF » (un même éditeur) — Ain, Vosges, Val-d'Oise, Haute-Garonne
- Manifeste 200 `application/json` `ACAO:*` ; tuiles servies sur la base publique
  `…/xxx.jpg` avec `ACAO:*`.
- Deux « défauts » apparents, **tous deux NON bloquants** pour Allmaps :
  - `info.json` à `@id` **non canonique** (`…/iiif//<cache>/…/FOND.TIF`) → l'Ain
    et la Haute-Garonne marchent malgré lui (Allmaps prend le `@id` du *manifeste*).
  - **préflight CORS cassé** → la **Haute-Garonne a un préflight 502 et marche
    quand même**. Donc le préflight n'est PAS le différenciateur non plus.

| Dépt | Hôte | Manifeste | Préflight `OPTIONS` | `@id` canon. | Allmaps (URL `…/manifest`) | Licence manifeste |
|---|---|---|---|---|---|---|
| **Ain (01)** | `www.archives.ain.fr` | 200 `ACAO:*` | 200 `ACAO:*` | ❌ | ✅ **marche** (confirmé) | `attribution` seul |
| **Vosges (88)** | `recherche-archives.vosges.fr` | 200 `ACAO:*` | 200 `ACAO:*` | ❌ | ✅ très probable | ✅ **Licence Ouverte 2.0** |
| **Haute-Garonne (31)** | `archives.haute-garonne.fr` | 200 `ACAO:*` | **502** ❌ | ❌ | ✅ **marche** (confirmé) | `attribution` seul |
| **Val-d'Oise (95)** | `archives.valdoise.fr` | 200 `ACAO:*` | coupé ❌ | ❌ | ✅ **probable** (manifeste + tuiles `ACAO:*` OK, profil = Hte-Garonne ; échec initial = lien ARK) | `attribution` seul (manuelle OK) |

→ **Règle confirmée par l'utilisateur** : *« le manifeste IIIF marche dans Allmaps,
le lien visionneuse (bundle JS / ARK) non »*. **Coller systématiquement l'URL
`…/manifest`, jamais l'ARK/visionneuse.** Avec ça, toute cette famille marche en
direct — préflight et `@id` cassés inclus.

→ **Statut du proxy** : **aucun cas confirmé ne le nécessite à ce jour.** L'échec
Val-d'Oise initial s'explique très probablement par l'usage du lien ARK. À retester
avec son `…/manifest` avant de déployer quoi que ce soit. Le proxy reste un simple
filet si un serveur s'avérait réellement non chargeable manifeste-en-main.

### B. Visionneuse SPA mnesys — Doubs, Jura
- `archives.doubs.fr` / `portail-archives.doubs.fr` / `archives39.fr` : appli
  React. L'ARK n'est pas une ressource IIIF ; le manifeste existe (bouton
  « Copier le lien IIIF » du viewer) mais son URL est fabriquée à l'exécution.
- **Non testable sans l'URL réelle du manifeste** (bouton viewer, ou `#iiif_manifest`
  de la notice FranceArchives). Abandonné faute d'URL.

### C. Visionneuse ARK sans IIIF — Calvados
- `archives.calvados.fr` : feuilles à `dcterms:source` ARK + vignette, **aucun
  manifeste IIIF**. Allmaps inexploitable en l'état → il faudrait générer du IIIF
  à partir des images.

## Proxy de normalisation (`proxy/iiif-allmaps/`)

Reverse-proxy Cloudflare Worker (manifeste + info.json + tuiles avec CORS propre).
**Aucun cas confirmé ne le nécessite** : c'est un filet, conservé au cas où un
serveur s'avérerait non chargeable manifeste-en-main. Logique validée en réel sur
Vosges. Voir [`../proxy/iiif-allmaps/README.md`](../proxy/iiif-allmaps/README.md).

> Leçon (revue 2 fois) : ne pas conclure trop vite.
> - Hypothèse 1 « le `@id` FOND.TIF casse Allmaps » → **invalidée par l'Ain**.
> - Hypothèse 2 « le préflight cassé casse Allmaps » → **invalidée par la Haute-Garonne**
>   (préflight 502, marche quand même).
> Cause réelle = **lien ARK/visionneuse collé au lieu de l'URL `…/manifest`**.
> Toujours confronter à un cas qui MARCHE avant de bâtir une solution.
