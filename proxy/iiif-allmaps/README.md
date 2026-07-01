# Proxy de normalisation IIIF → Allmaps

Filet pour les fonds IIIF dont le serveur a un **CORS défaillant** côté Allmaps.

> ⚠️ Portée à jour : **aucun cas confirmé ne nécessite ce proxy.** Les serveurs
> « cache FOND.TIF » (**Ain, Vosges, Haute-Garonne** ✅ confirmés ; Val-d'Oise à
> retester) **marchent en direct dans Allmaps** quand on colle l'URL `…/manifest`
> (et non le lien ARK/visionneuse). Ni le `@id` non canonique ni un préflight cassé
> (Haute-Garonne = 502 et marche) ne bloquent. Ce Worker reste un **filet** au cas
> où un serveur s'avérerait non chargeable manifeste-en-main. Diagnostic complet :
> [`../to_do/diagnostic_iiif_allmaps.md`](../to_do/diagnostic_iiif_allmaps.md).

## Ce que fait le Worker

| Route | Rôle |
|---|---|
| `GET /manifest?u=<URL manifeste origine>` | renvoie le manifeste avec chaque `service.@id`/`id` réécrit vers le proxy |
| `GET /iiif/<ENC>/info.json` | renvoie l'info.json origine, `@id`/`id` **forcé** sur la base proxy, `content-type: application/json` + CORS |
| `GET /iiif/<ENC>/<region>/<size>/<rot>/<quality>.jpg` | relaie la tuile vers la **base publique** origine (celle qui sert vraiment) |

`<ENC>` = URI publique du service image, *percent-encodée*. Anti-open-proxy :
seuls les hôtes listés dans `ALLOWED` (worker.js) sont relayés — ajouter les
nouveaux départements là.

## Déploiement (Cloudflare Workers, gratuit)

```bash
npm i -g wrangler
wrangler login
cd proxy/iiif-allmaps
wrangler deploy        # → https://iiif-allmaps.<compte>.workers.dev
```

## Usage dans Allmaps

Au lieu de coller le manifeste origine, colle dans Allmaps Editor :

```
https://iiif-allmaps.<compte>.workers.dev/manifest?u=<URL_DU_MANIFESTE_ENCODÉE>
```

Exemple (Vosges) — `u` = manifeste origine encodé :

```
https://iiif-allmaps.<compte>.workers.dev/manifest?u=https%3A%2F%2Frecherche-archives.vosges.fr%2Fark%3A%2F50275%2F1093257%2Fmanifest
```

## Limites

- Couvre les serveurs « `@id` interne / tuiles publiques OK ». Ne règle PAS les
  fonds **sans IIIF** (ex. Calvados, visionneuse ARK) : il faut alors générer du
  IIIF à partir des images.
- Rediffusion publique des images : OK si la licence l'autorise (Vosges =
  **Licence Ouverte 2.0**, détectée dans le manifeste). Vérifier par institution.
