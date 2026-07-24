# Fumées · Nouvelle-Aquitaine 🔥🛰️

Carte web pour suivre les panaches de fumée des incendies en Nouvelle-Aquitaine.

**Site en ligne :** https://nicolaslecorvec.github.io/fumees-nouvelle_aquitaine/

## Ce que montre le site

L'imagerie satellite la plus récente en couleurs vraies (NASA GIBS /
Worldview) : le site ouvre sur l'image du jour et recule automatiquement
d'un jour si elle n'est pas encore publiée. Les panaches de fumée y sont
directement visibles en gris-bleu.

Couches et réglages disponibles :

- **Choix du satellite** : VIIRS NOAA-20, VIIRS Suomi-NPP (passages vers
  13h30) ou MODIS Terra (~10h30) / Aqua (~13h30) — plusieurs prises de vue
  du même jour.
- **Foyers détectés** : détections thermiques VIIRS 375 m (NASA FIRMS).
  Points de petite taille : zoomer pour bien les voir.
- **Aérosols (indice UV)** : indice d'aérosols OMPS (Suomi-NPP), l'outil
  utilisé pour suivre les panaches de fumée, de cendres volcaniques et de
  poussières, même à travers les nuages. Résolution ~2 km, intensité
  réglable.
- **Repères** : noms de villes et routes affichés par-dessus l'image.
- **Historique** : archives consultables jour par jour depuis fin 2015
  (utile pour revoir par exemple les incendies de Gironde de l'été 2022).

## Limites à connaître

- **Pas de temps réel** : chaque satellite ne passe qu'une fois par jour et
  l'image est publiée quelques heures après. La situation locale peut avoir
  changé depuis la prise de vue.
- Ce site est informatif. En cas de fumée visible ou d'odeur, se référer
  aux mesures et consignes officielles :
  [ATMO Nouvelle-Aquitaine](https://www.atmo-nouvelleaquitaine.org/) et
  les préfectures.

## Données et outils utilisés

- Imagerie satellite : [NASA GIBS / Worldview](https://worldview.earthdata.nasa.gov/) (VIIRS et MODIS)
- Détection des foyers : NASA FIRMS (anomalies thermiques VIIRS 375 m)
- Aérosols : indice UV OMPS Suomi-NPP (NASA)
- Fond de carte : © les contributeurs [OpenStreetMap](https://www.openstreetmap.org/copyright), labels © CARTO
- Bibliothèque cartographique : [Leaflet](https://leafletjs.com/)

Aucune clé API, aucun serveur : une seule page HTML statique, hébergée
gratuitement sur GitHub Pages.

## Modifier le site

Tout le site tient dans `index.html`. Pour changer la zone affichée,
modifier les coordonnées dans le code JavaScript (`setView([44.9, 0.0], 7)`).
Pour un autre usage (par exemple un suivi de panaches volcaniques), il
suffit de changer le centrage et, au besoin, les identifiants de couches
GIBS. Après chaque modification enregistrée (commit), GitHub Pages
republie le site automatiquement en une à deux minutes.
