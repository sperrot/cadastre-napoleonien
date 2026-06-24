-- ==================================================================
-- Migration 0002 — IIIF, licence et autorisation overlay/georef
-- À exécuter une fois dans le SQL Editor.
--
-- Contexte : l'ingestion FranceArchives apporte, par notice :
--   cote, manifeste IIIF, image (dao), et surtout la LICENCE déclarée
--   dans le manifeste. C'est la licence — pas la simple présence de
--   IIIF — qui autorise ou non l'overlay/géoréférencement.
--   Ex. AD Seine-Saint-Denis = Licence Ouverte → overlay OK.
--       AD Jura = conditions restrictives → overlay interdit sans accord.
-- ==================================================================

alter table document add column if not exists cote               text;     -- ex. "2047W/563"
alter table document add column if not exists iiif_manifest      text;     -- URL du manifeste IIIF
alter table document add column if not exists image_url          text;     -- vignette / dao
alter table document add column if not exists licence            text;     -- ex. "Licence Ouverte", "Restreint"
alter table document add column if not exists licence_overlay_ok boolean default false; -- la licence autorise-t-elle overlay/georef ?

-- Remarque : `iiif_url` (déjà présent) reste l'URL de l'Image API si on
-- la distingue du manifeste ; `iiif_manifest` porte le manifeste lui-même.
comment on column document.licence_overlay_ok is
  'Vrai uniquement si la licence de l''institution autorise la modification + rediffusion publique (ex. Licence Ouverte). Pilote l''activation de l''overlay/georef côté app.';
