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
 * Pagination Ligeo — relevée sur le portail, pas devinée :
 *   page 1 : /archive/resultats/cadastres/n:12?…
 *   page 2 : /archive/resultats/cadastres/archive/n:12/limit:50/page:2?…
 * Noter le segment « /archive/ » SUPPLÉMENTAIRE et le segment « limit: ».
 * C'est ce dernier qui permet de réduire le nombre de pages : le script teste
 * d'abord une limite large et retombe sur 50 si le serveur la plafonne.
 *
 * Télécharge arks_aisne.tsv à passer à :
 *   python harvest/seed_aisne.py --arks arks_aisne.tsv
 */
(async () => {
  const DELAI_MS = 5000;        // Crawl-delay: 5 (robots.txt)
  const ATTENDU = 4443;         // nombre de résultats annoncé par le portail
  const MAX_PAGES = 400;        // garde-fou anti-boucle
  const NAAN = '63271';

  const vus = new Map();        // ark -> libellé (dédoublonne)

  const recolte = (doc) => {
    const avant = vus.size;
    for (const a of doc.querySelectorAll(`a[href*="ark:/${NAAN}/"]`)) {
      const m = a.getAttribute('href').match(new RegExp(`ark:/${NAAN}/([A-Za-z0-9]+)`));
      if (m && !vus.has(m[1])) {
        vus.set(m[1], (a.textContent || '').replace(/\s+/g, ' ').trim());
      }
    }
    return vus.size - avant;
  };

  // Reconstruit l'URL d'une page : <prefixe>/archive/n:<id>/limit:<L>/page:<N>?<query>
  const u0 = new URL(location.href);
  const mid = u0.pathname.match(/^(.*?)\/(?:archive\/)?(n:\d+)(?:\/.*)?$/);
  if (!mid) {
    console.error("URL inattendue — lance le script depuis la page de résultats.");
    return;
  }
  const urlPage = (n, limit) =>
    new URL(`${mid[1]}/archive/${mid[2]}/limit:${limit}/page:${n}${u0.search}`, u0).href;

  const charge = async (href) => {
    const rep = await fetch(href, { credentials: 'same-origin' });
    if (!rep.ok) return { erreur: `HTTP ${rep.status}` };
    const txt = await rep.text();
    if (/not a bot/i.test(txt)) return { erreur: 'Anubis' };
    return { doc: new DOMParser().parseFromString(txt, 'text/html') };
  };

  // 1) Quelle limite le serveur accepte-t-il vraiment ?
  let LIMITE = 50;
  for (const essai of [200, 100]) {
    const r = await charge(urlPage(1, essai));
    if (!r.doc) { console.log(`limit:${essai} → ${r.erreur}`); continue; }
    const tmp = new Set();
    for (const a of r.doc.querySelectorAll(`a[href*="ark:/${NAAN}/"]`)) {
      const m = a.getAttribute('href').match(new RegExp(`ark:/${NAAN}/([A-Za-z0-9]+)`));
      if (m) tmp.add(m[1]);
    }
    console.log(`limit:${essai} → ${tmp.size} arks sur la page 1`);
    if (tmp.size > LIMITE) { LIMITE = essai; break; }
    await new Promise((r2) => setTimeout(r2, DELAI_MS));
  }
  const pages = Math.ceil(ATTENDU / LIMITE);
  console.log(`limite retenue : ${LIMITE} → ~${pages} pages, ` +
              `~${Math.round(pages * DELAI_MS / 60000)} min`);

  // 2) Parcours
  let vide = 0;
  for (let p = 1; p <= Math.min(pages + 5, MAX_PAGES); p++) {
    const r = await charge(urlPage(p, LIMITE));
    if (!r.doc) {
      console.warn(`page ${p} : ${r.erreur} — arrêt. Recharge la page et relance ` +
                   `si c'est Anubis : les arks déjà vus seront reperdus, ` +
                   `mieux vaut repartir de zéro.`);
      break;
    }
    const n = recolte(r.doc);
    console.log(`page ${p}/${pages} — +${n}, ${vus.size} au total`);
    if (n === 0) { if (++vide >= 2) { console.log('deux pages sans nouveauté, fin.'); break; } }
    else vide = 0;
    if (vus.size >= ATTENDU) { console.log('compte attendu atteint.'); break; }
    await new Promise((r2) => setTimeout(r2, DELAI_MS));
  }

  // 3) Sortie
  const lignes = [...vus.entries()].map(([ark, lib]) => `${ark}\t${lib}`);
  console.log(`TERMINÉ : ${lignes.length} arks (attendu ${ATTENDU}).`);
  if (lignes.length < ATTENDU * 0.98) {
    console.warn('Compte incomplet — dis-le avant de charger en base.');
  }
  const blob = new Blob([lignes.join('\n') + '\n'], { type: 'text/tab-separated-values' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'arks_aisne.tsv';
  document.body.appendChild(a);
  a.click();
  a.remove();
})();
