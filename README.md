# Fumées · Nouvelle-Aquitaine 🔥🛰️

Carte web pour suivre les panaches de fumée des incendies en Nouvelle-Aquitaine.

**Site en ligne :** https://TON-PSEUDO.github.io/fumees-na/
*(remplace TON-PSEUDO par ton pseudo GitHub)*

## Ce que montre le site

Le site propose deux vues, accessibles par les boutons en haut de page :

**Satellite (image du jour)** — l'imagerie satellite réelle en couleurs vraies
(NASA GIBS / Worldview). Les panaches de fumée y sont visibles en gris-bleu.
On peut choisir le jour, le satellite (VIIRS NOAA-20, VIIRS Suomi-NPP, MODIS
Terra ou Aqua), afficher les foyers détectés (détections thermiques VIIRS
375 m) et régler l'opacité pour voir les villes et routes en dessous.

**Prévision fumée (CAMS)** — une carte Windy intégrée affichant le modèle
Copernicus CAMS : particules fines PM2.5, monoxyde de carbone ou aérosols,
avec une animation heure par heure sur plusieurs jours.

## Limites à connaître

- L'imagerie satellite n'est **pas du temps réel** : chaque satellite ne
  passe qu'une fois par jour (Terra vers 10h30, les VIIRS vers 13h30) et
  l'image est publiée quelques heures après. Par défaut, le site affiche
  la veille.
- La vue prévision est un **modèle**, pas une observation : utile pour
  anticiper la dispersion des fumées, mais à prendre comme une estimation.
- Ce site est informatif. Pour les consignes de sécurité, se référer aux
  préfectures et aux services de secours.

## Données et outils utilisés

- Imagerie satellite : [NASA GIBS / Worldview](https://worldview.earthdata.nasa.gov/) (VIIRS et MODIS)
- Détection des foyers : NASA FIRMS (anomalies thermiques VIIRS 375 m)
- Prévision : [Windy.com](https://www.windy.com/) avec le modèle [Copernicus CAMS](https://atmosphere.copernicus.eu/)
- Fond de carte : © les contributeurs [OpenStreetMap](https://www.openstreetmap.org/copyright)
- Bibliothèque cartographique : [Leaflet](https://leafletjs.com/)

Aucune clé API, aucun serveur : une seule page HTML statique, hébergée
gratuitement sur GitHub Pages.

## Modifier le site

Tout le site tient dans `index.html`. Pour changer la zone affichée,
modifier les coordonnées dans le code JavaScript (`setView([44.9, 0.0], 7)`
pour la carte satellite, et `lat=44.9&lon=0.0` dans l'URL Windy pour la
prévision). Après chaque modification enregistrée (commit), GitHub Pages
republie le site automatiquement en une à deux minutes.
