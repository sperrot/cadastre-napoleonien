-- ==================================================================
-- Pilote Seine-Saint-Denis (licence ouverte, IIIF) — données réelles.
-- Première entrée issue de FranceArchives + manifeste IIIF SSD.
-- Sert aussi de MODÈLE de sortie pour le script d'ingestion.
--
-- Prérequis : migration_0002_iiif_licence.sql appliquée.
-- INSEE Sevran (93) = 93071.
-- ==================================================================

insert into document (
  insee, type, section_lettre, feuille_num, annee, cote,
  archive_url,
  iiif_manifest,
  image_url,
  source, source_url,
  licence, licence_overlay_ok,
  statut
) values (
  '93071', 'tableau_assemblage', null, null, 1819, '2047W/563',
  'https://francearchives.gouv.fr/fr/facomponent/1acb6ab26b032f1c727c5e1f4303db94f704368d',
  'https://archives.seinesaintdenis.fr/ark:/79690/vtaa40b4e94e1146672/manifest',
  'https://archives.seinesaintdenis.fr/ark:/79690/vtaa40b4e94e1146672/daoloc/0/vignette',
  'Archives départementales de la Seine-Saint-Denis', 'https://archives.seinesaintdenis.fr',
  'Licence Ouverte', true,
  'georef'   -- IIIF + Licence Ouverte → overlay/georef autorisé
);
