-- Migration 0003 — assainissement de la base document (DDL)
-- À exécuter dans Supabase → SQL Editor.
--
-- Les DML (nettoyage doublons, mauvais rattachements, chargement Doubs+71) ont
-- été appliqués via PostgREST le 2026-07-20 par harvest/load_doubs_direct.py et
-- harvest/load_seed_to_supabase.py (base à 29 993 documents à l'issue).
--
-- Cette migration ajoute :
--   1. Contrainte UNIQUE(archive_url) — rend le rechargement idempotent
--   2. Index de performance
--   3. Vue d'agrégats consommée par la GED (Phase 4)

-- 1) UNIQUE ---------------------------------------------------------
-- Si des doublons résiduels bloquent la création, les lister d'abord :
--   select archive_url, count(*) from document group by 1 having count(*) > 1;
alter table document
  add constraint document_archive_url_key unique (archive_url);

-- 2) Index ----------------------------------------------------------
create index if not exists document_dept_idx      on document (left(insee, 2));
create index if not exists document_overlay_idx   on document (licence_overlay_ok);
create index if not exists document_source_idx    on document (source);
create index if not exists document_annee_idx     on document (annee);

-- 3) Vue d'agrégats (agrège 30 000 lignes en 1 requête pour la GED) ---
-- Sécurité : le paramètre security_invoker garde le check RLS de document.
create or replace view v_document_stats_dept
  with (security_invoker = true) as
select
  left(insee, 2)                                                as dept,
  count(*)                                                      as total,
  count(*) filter (where licence_overlay_ok is true)            as overlay_ok,
  count(*) filter (where iiif_manifest is not null)             as with_iiif,
  count(*) filter (where type = 'tableau_assemblage')           as nb_assemblages,
  count(*) filter (where type = 'section')                      as nb_sections,
  count(*) filter (where type = 'feuille')                      as nb_feuilles,
  count(distinct insee)                                         as nb_communes
from document
group by 1;

-- Les vues créées avec `security_invoker=true` sont automatiquement lisibles
-- par les rôles ayant SELECT sur les tables sous-jacentes (déjà accordé aux
-- rôles anon/authenticated dans schema.sql lignes 79-81). Aucun GRANT explicite
-- nécessaire.

comment on view v_document_stats_dept is
  'Compteurs par département consommés par la GED (web/app.js). '
  'Remplace le fetch de ~30 000 lignes à l''ouverture du panneau Documents.';
