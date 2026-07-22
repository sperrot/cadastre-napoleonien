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
 * Pagination Ligeo — RELEVÉE sur le portail, pas devinée :
 *   page 1 : /archive/resultats/cadastres/n:12?RECH_plan=1&type=cadastres
 *   page 2 : /archive/resultats/cadastres/archive/n:12/limit:50/page:2?RECH_plan=1&…
 * Noter le segment « /archive/ » SUPPLÉMENTAIRE, absent de la page 1.
 *
 * On garde limit:50, la valeur que le portail émet lui-même. Tenter de
 * l'augmenter est tentant (89 pages → 23) mais non vérifié : Ligeo tient l'état
 * de la recherche en session, et une limite que le serveur ne suit pas renvoie
 * la même page indéfiniment. Ne changer qu'après avoir contrôlé que page 1 et
 * page 2 diffèrent réellement.
 *
 * Reprise : les arks sont conservés dans window.__ARKS_AISNE. Si Anubis coupe
 * la session, recharge la page et RELANCE le script — il repart du acquis.
 *
 * Produit arks_aisne.tsv à passer à :
 *   python harvest/seed_aisne.py --arks arks_aisne.tsv
 */
(async () => {
  const DELAI_MS = 5000;        // Crawl-delay: 5 (robots.txt)
  const LIMITE = 50;            // valeur émise par le portail — cf. en-tête
  const ATTENDU = 4443;         // résultats annoncés
  const NAAN = '63271';
  const PAGES = Math.ceil(ATTENDU / LIMITE);

  // Acquis d'un éventuel run précédent (reprise après coupure Anubis)
  const vus = window.__ARKS_AISNE instanceof Map ? window.__ARKS_AISNE : new Map();
  window.__ARKS_AISNE = vus;
  if (vus.size) console.log(`reprise : ${vus.size} arks déjà collectés`);

  const arksDe = (doc) => {
    const s = new Set();
    for (const a of doc.querySelectorAll(`a[href*="ark:/${NAAN}/"]`)) {
      const m = a.getAttribute('href').match(new RegExp(`ark:/${NAAN}/([A-Za-z0-9]+)`));
      if (m) s.add(m[1]);
    }
    return s;
  };
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

  const telecharge = () => {
    const lignes = [...vus.entries()].map(([ark, lib]) => `${ark}\t${lib}`);
    const blob = new Blob([lignes.join('\n') + '\n'], { type: 'text/tab-separated-values' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'arks_aisne.tsv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    return lignes.length;
  };

  // <prefixe>/archive/n:<id>/limit:<L>/page:<N>?<query>, quelle que soit la
  // forme de l'URL courante (page 1 ou page N).
  const u0 = new URL(location.href);
  const mid = u0.pathname.match(/^(.*?)\/(?:archive\/)?(n:\d+)(?:\/.*)?$/);
  if (!mid) {
    console.error('URL inattendue — lance le script depuis la page de résultats.');
    return;
  }
  const urlPage = (n) =>
    new URL(`${mid[1]}/archive/${mid[2]}/limit:${LIMITE}/page:${n}${u0.search}`, u0).href;

  const charge = async (href) => {
    const rep = await fetch(href, { credentials: 'same-origin' });
    if (!rep.ok) return { erreur: `HTTP ${rep.status}` };
    const txt = await rep.text();
    if (/not a bot/i.test(txt)) return { erreur: 'Anubis' };
    return { doc: new DOMParser().parseFromString(txt, 'text/html') };
  };

  // --- Calibration : page 1 et page 2 doivent VRAIMENT différer ------------
  // Sans ce contrôle, une pagination inopérante fait tourner 89 requêtes pour
  // recollecter 50 fois la même page.
  const p1 = await charge(urlPage(1));
  if (!p1.doc) { console.error(`page 1 : ${p1.erreur}`); return; }
  const s1 = arksDe(p1.doc);
  await new Promise((r) => setTimeout(r, DELAI_MS));
  const p2 = await charge(urlPage(2));
  if (!p2.doc) { console.error(`page 2 : ${p2.erreur}`); return; }
  const s2 = arksDe(p2.doc);
  const communs = [...s2].filter((x) => s1.has(x)).length;
  console.log(`calibration : page 1 = ${s1.size} arks, page 2 = ${s2.size}, ` +
              `${communs} en commun`);
  if (s2.size === 0 || communs === s2.size) {
    console.error('La pagination ne bouge pas : page 2 ne contient rien de neuf.\n' +
                  'Ouvre la page 2 à la main et envoie-moi son URL exacte.');
    telecharge();
    return;
  }

  // --- Parcours ------------------------------------------------------------
  recolte(p1.doc); recolte(p2.doc);
  console.log(`pages 1-2 — ${vus.size} au total (~${PAGES} pages, ` +
              `~${Math.round(PAGES * DELAI_MS / 60000)} min)`);
  let vide = 0;
  for (let p = 3; p <= PAGES + 3; p++) {
    await new Promise((r) => setTimeout(r, DELAI_MS));
    const r = await charge(urlPage(p));
    if (!r.doc) {
      console.warn(`page ${p} : ${r.erreur} — arrêt. Les ${vus.size} arks acquis ` +
                   `sont gardés : recharge la page et RELANCE le script.`);
      break;
    }
    const n = recolte(r.doc);
    console.log(`page ${p}/${PAGES} — +${n}, ${vus.size} au total`);
    if (n === 0) { if (++vide >= 2) { console.log('deux pages sans nouveauté, fin.'); break; } }
    else vide = 0;
    if (vus.size >= ATTENDU) { console.log('compte attendu atteint.'); break; }
  }

  const total = telecharge();
  console.log(`TERMINÉ : ${total} arks (attendu ${ATTENDU}).`);
  if (total < ATTENDU * 0.98) {
    console.warn('Compte incomplet — dis-le avant de charger en base.');
  }
})();
