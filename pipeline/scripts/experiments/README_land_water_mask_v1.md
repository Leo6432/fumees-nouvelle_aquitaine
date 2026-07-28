# Masque terre/eau WorldCover — validation V1

## Objectif

Supprimer les portions aquatiques des géométries publiées sur le web
sans modifier les géométries scientifiques sources.

## Source

- ESA WorldCover 2021 v200
- Résolution native : 10 m
- Tuiles :
  - N42W003
  - N45W003
- Classes considérées comme eau :
  - 0 : absence de classification / océan ouvert
  - 80 : plans d'eau permanents

## Couches raster

Les couches du modèle sont déjà définies sur une grille de 250 m.

Méthode retenue :

- agrégation de la fraction terrestre WorldCover à 250 m ;
- conservation des cellules avec une fraction terrestre >= 0,50 ;
- application du masque avant polygonisation et calcul de surface.

Le masque ne crée aucune nouvelle surface.

## Emprises FIRMS vectorielles

La rasterisation directe à 250 m a été rejetée :

- biais surfacique : +12,64 %.

Les prototypes suivants ont également été rejetés :

### Prototype V1

Rasterisation de l'emprise FIRMS à 25 m puis repolygonisation.

Problèmes :

- 25 emprises avec extension géométrique ;
- ajout maximal : 1,946 km² ;
- poids GeoJSON : +11,39 %.

### Prototype V2

Intersection avec l'ensemble du support terrestre polygonisé à 25 m.

Problèmes :

- ajout maximal résiduel : 0,077 km² ;
- complexité FIRMS : +709 % ;
- poids GeoJSON : +183,83 %.

## Méthode validée — V3

1. Reproduction exacte de la géométrie web historique.
2. Construction locale des composantes aquatiques WorldCover à 25 m.
3. Suppression des composantes aquatiques inférieures à 1 ha.
4. Simplification des limites aquatiques à 50 m.
5. Soustraction vectorielle de l'eau.
6. Intersection finale avec la géométrie web historique.

Cette dernière intersection garantit :

    géométrie masquée ⊆ géométrie web historique

## Résultats V3

- passages identiques : 57 ;
- entités identiques : 208 ;
- géométries valides : toutes ;
- géométries vides : aucune ;
- entités avec plus de 0,01 km² ajouté : 0 ;
- ajout maximal : 4,36e-13 km², correspondant au bruit numérique ;
- complexité des emprises FIRMS : +7,15 % ;
- taille du GeoJSON : +1,66 % ;
- surface FIRMS retirée : 60,90 km² cumulés sur 25 états temporels.

Les sommes temporelles ne représentent pas une union spatiale unique.

## Scripts retenus

- `21_build_land_water_mask_v1.py`
- `22_compare_firms_landmask_resolution_v1.py`
- `27_export_arrival_web_landmask_v3.py`
- `28_audit_parallel_landmask_export_v3.py`

## Statut

Méthode validée pour intégration dans l'export web.

Les géométries scientifiques du GPKG restent inchangées.
