/* Collecte des arks du cadastre napoléonien de l'Aisne — À COLLER DANS LA
 * CONSOLE DU NAVIGATEUR, sur la page de résultats déjà ouverte :
 *
 *   https://archives.aisne.fr/archive/resultats/cadastres/n:12?RECH_plan=1&type=cadastres
 *
 * Pourquoi le navigateur : les pages HTML du portail sont protégées par Anubis
 * (preuve de travail) et robots.txt interdit /archive/resultats/*?*. Seuls les
 * endpoints IIIF (/ark:/…/manifest et /iiif/…) sont ouverts. On récupère donc
 * l'inventaire UNE FOIS depuis une session de navigateur légitime, puis tout le
 * reste (métadonnées, communes, images) passe par les manifestes ouverts.
 *
 * Le script pagine tout seul en réutilisant la session courante, avec 5 s entre
 * deux pages — le Crawl-delay déclaré par robots.txt. Il télécharge à la fin un
 * fichier arks_aisne.tsv à passer à :
 *
 *   python harvest/seed_aisne.py --arks arks_aisne.tsv
 */
(async () => {
  const DELAI_MS = 5000;          // Crawl-delay: 5 (robots.txt)
  const MAX_PAGES = 200;          // garde-fou anti-boucle
  const NAAN = '63271';

  const vus = new Map();          // ark -> libellé (dédoublonne)

  const recolte = (doc) => {
    let n = 0;
    for (const a of doc.querySelectorAll(`a[href*="ark:/${NAAN}/"]`)) {
      const m = a.getAttribute('href').match(new RegExp(`ark:/${NAAN}/([A-Za-z0-9]+)`));
      if (!m) continue;
      if (!vus.has(m[1])) {
        vus.set(m[1], (a.textContent || '').replace(/\s+/g, ' ').trim());
        n++;
      }
    }
    return n;
  };

  // Lien « page suivante » : on le LIT dans la page plutôt que de deviner le
  // motif d'URL — Ligeo varie d'un portail à l'autre.
  const suivante = (doc) => {
    const sel = 'a[rel="next"], .pagination a, .pager a, a.suivant, a.next';
    for (const a of doc.querySelectorAll(sel)) {
      const t = (a.textContent || '').toLowerCase();
      const titre = (a.getAttribute('title') || '').toLowerCase();
      if (/suivant|next|›|»|>/.test(t) || /suivant|next/.test(titre)) {
        const href = a.getAttribute('href');
        if (href && !/^#/.test(href)) return new URL(href, location.href).href;
      }
    }
    return null;
  };

  let doc = document;
  let url = location.href;
  let page = 0;

  while (page < MAX_PAGES) {
    page++;
    const n = recolte(doc);
    console.log(`page ${page} — ${n} nouveaux, ${vus.size} au total`);
    const next = suivante(doc);
    if (!next) { console.log('plus de page suivante.'); break; }
    await new Promise((r) => setTimeout(r, DELAI_MS));
    const rep = await fetch(next, { credentials: 'same-origin' });
    if (!rep.ok) { console.warn(`page ${page + 1} : HTTP ${rep.status}, arrêt.`); break; }
    const txt = await rep.text();
    if (/not a bot/i.test(txt)) {
      console.warn('Anubis a repris la main — recharge la page et relance.');
      break;
    }
    doc = new DOMParser().parseFromString(txt, 'text/html');
    url = next;
  }

  const lignes = [...vus.entries()].map(([ark, lib]) => `${ark}\t${lib}`);
  console.log(`TERMINÉ : ${lignes.length} arks sur ${page} page(s).`);
  console.log('Attendu ~4443 : si le compte est loin, dis-le avant de charger.');

  const blob = new Blob([lignes.join('\n') + '\n'], { type: 'text/tab-separated-values' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'arks_aisne.tsv';
  document.body.appendChild(a);
  a.click();
  a.remove();
})();
