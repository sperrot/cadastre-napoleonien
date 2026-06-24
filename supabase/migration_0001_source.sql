-- ==================================================================
-- Migration 0001 — ajout de l'attribution de source (mention CRPA)
-- À exécuter UNE FOIS dans le SQL Editor d'une base déjà créée.
-- (Sur une base neuve, schema.sql + seed.sql suffisent.)
-- ==================================================================

alter table document add column if not exists source     text;
alter table document add column if not exists source_url text;

-- Renseigne la source des lignes existantes d'après le département
-- (deux premiers caractères de l'INSEE).
update document
set source = case left(insee, 2)
      when '25' then 'Archives départementales du Doubs'
      when '39' then 'Archives départementales du Jura'
      when '31' then 'Archives départementales de la Haute-Garonne'
      when '21' then 'Archives départementales de la Côte-d''Or'
    end,
    source_url = case left(insee, 2)
      when '25' then 'https://portail-archives.doubs.fr'
      when '39' then 'https://archives39.fr'
      when '31' then 'https://archives.haute-garonne.fr'
      when '21' then 'https://archives.cotedor.fr'
    end
where source is null;
