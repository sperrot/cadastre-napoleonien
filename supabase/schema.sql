-- ==================================================================
-- Cadastre napoléonien — schéma V0
-- À exécuter dans le SQL Editor de Supabase (PostGIS est déjà dispo).
-- ==================================================================

create extension if not exists postgis;

-- ------------------------------------------------------------------
-- Communes
-- En V0.0, les géométries de communes viennent de geo.api.gouv.fr
-- (côté client) : cette table n'est PAS nécessaire pour l'annuaire.
-- Elle est prévue pour les paliers suivants (cache local, jointures,
-- statistiques de couverture par département).
-- ------------------------------------------------------------------
create table if not exists commune (
  insee      text primary key,
  nom        text not null,
  dept       text not null,
  geom       geometry(MultiPolygon, 4326),
  centroid   geometry(Point, 4326)
);
create index if not exists commune_geom_idx on commune using gist (geom);
create index if not exists commune_dept_idx on commune (dept);

-- ------------------------------------------------------------------
-- Documents : un lien vers un plan du cadastre napoléonien.
-- C'est le cœur de la V0.0 (annuaire) et de la V0.1 (contribution).
--
-- Paliers de richesse (colonne `statut`) :
--   'lien'   : seul archive_url est rempli  (V0.0)
--   'bbox'   : + emprise approximative       (V0.2)
--   'georef' : + annotation Allmaps          (V0.3)
--   'valide' : vérifié par un contributeur de confiance
-- ------------------------------------------------------------------
create table if not exists document (
  id              uuid primary key default gen_random_uuid(),
  insee           text not null,                 -- FK logique vers commune.insee
  type            text not null
                    check (type in ('tableau_assemblage', 'section', 'feuille')),
  section_lettre  text,                           -- ex. 'A', 'B' (null pour tableau)
  feuille_num     int,                            -- numéro de feuille (sections en plusieurs feuilles)
  annee           int,                            -- millésime du plan (~1807-1850)
  archive_url     text not null,                  -- lien vers le viewer de l'archive
  source          text,                           -- attribution CRPA, ex. "Archives départementales du Jura"
  source_url      text,                           -- portail de l'institution (mention cliquable)
  cote            text,                           -- cote archivistique, ex. "2047W/563"
  iiif_url        text,                           -- URL de l'Image API IIIF si distincte du manifeste
  iiif_manifest   text,                           -- URL du manifeste IIIF (Allmaps)
  image_url       text,                           -- vignette / dao
  licence         text,                           -- ex. "Licence Ouverte", "Restreint"
  licence_overlay_ok boolean default false,       -- la licence autorise overlay/georef ?
  bbox            geometry(Polygon, 4326),        -- emprise approximative (palier bbox)
  georef          jsonb,                          -- annotation de géoréférencement Allmaps
  statut          text not null default 'lien'
                    check (statut in ('lien', 'bbox', 'georef', 'valide')),
  contributeur    text,                           -- email/pseudo (renseigné en V0.1)
  created_at      timestamptz not null default now()
);
create index if not exists document_insee_idx on document (insee);
create index if not exists document_type_idx  on document (type);

-- ------------------------------------------------------------------
-- Sécurité (RLS) : lecture publique, écriture verrouillée en V0.0.
-- La V0.1 ajoutera une policy d'insertion pour les contributeurs
-- authentifiés (auth.uid() is not null).
-- ------------------------------------------------------------------
alter table commune  enable row level security;
alter table document enable row level security;

drop policy if exists "lecture publique commune"  on commune;
drop policy if exists "lecture publique document" on document;

create policy "lecture publique commune"  on commune  for select using (true);
create policy "lecture publique document" on document for select using (true);

-- Droits explicites pour la Data API (nécessaire quand l'option
-- "Automatically expose new tables" est désactivée dans Supabase) :
-- les policies RLS ne s'appliquent qu'une fois le GRANT accordé.
grant usage on schema public to anon, authenticated;
grant select on commune  to anon, authenticated;
grant select on document to anon, authenticated;

-- Écriture pour les scripts de moisson locaux (harvest/, clé service_role) :
-- service_role contourne la RLS mais a quand même besoin des privilèges SQL.
grant usage on schema public to service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
alter default privileges in schema public grant all on tables    to service_role;
alter default privileges in schema public grant all on sequences to service_role;
