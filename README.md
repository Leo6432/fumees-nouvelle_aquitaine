# Fumées · Nouvelle-Aquitaine 🔥🛰️

Carte web permettant de visualiser les panaches de fumée, les foyers
détectés, la qualité de l’air et plusieurs informations utiles au suivi
des incendies en Nouvelle-Aquitaine.

**Site en ligne :**  
https://nicolaslecorvec.github.io/fumees-nouvelle_aquitaine/

## Ce que montre le site

### Imagerie satellite

La carte affiche les images en couleurs vraies les plus récentes fournies
par NASA GIBS / Worldview.

Le site ouvre sur l’image du jour et recule automatiquement d’un jour si
elle n’est pas encore disponible. Les panaches de fumée peuvent y être
visibles sous la forme de traînées grisâtres ou bleuâtres.

Satellites proposés :

- **VIIRS NOAA-20** — passage diurne vers 13 h 30 ;
- **VIIRS Suomi-NPP** — passage diurne vers 13 h 30 ;
- **MODIS Terra** — passage diurne vers 10 h 30 ;
- **MODIS Aqua** — passage diurne vers 13 h 30.

Les horaires indiqués sont approximatifs et varient selon la position de
l’orbite et la zone observée.

### Foyers détectés durant les dernières 48 heures

Les foyers correspondent aux anomalies thermiques détectées par les
capteurs VIIRS et diffusées par NASA FIRMS.

Pour chaque détection, la carte indique notamment :

- la date et l’heure d’acquisition ;
- le satellite ;
- la puissance radiative du feu, en MW ;
- le niveau de confiance.

Les symboles représentent des détections satellitaires et non
nécessairement des incendies confirmés au sol. Plusieurs détections peuvent
correspondre au même incendie.

Cette couche reste toujours relative aux dernières 48 heures, quelle que
soit la date choisie pour l’imagerie satellite.

### Qualité de l’air par commune

La couche **Indice ATMO par commune** affiche l’indice officiel produit par
Atmo France et les associations agréées de surveillance de la qualité de
l’air.

La couleur de chaque commune correspond à l’indice global :

- bon ;
- moyen ;
- dégradé ;
- mauvais ;
- très mauvais ;
- extrêmement mauvais.

Un clic sur une commune affiche également les sous-indices disponibles :

- PM2.5 ;
- PM10 ;
- ozone — O₃ ;
- dioxyde d’azote — NO₂ ;
- dioxyde de soufre — SO₂.

Le sélecteur permet de colorer les communes selon l’indice global ou selon
un polluant particulier.

La couche **Contrôle WMS — points** affiche la représentation fournie
directement par le serveur cartographique d’Atmo France. Elle sert
principalement à contrôler visuellement la cohérence de la couche
communale et peut rester désactivée en usage normal.

### Aérosols — indice ultraviolet OMPS

La couche OMPS représente un indice d’aérosols absorbants mesuré dans
l’ultraviolet.

Elle peut mettre en évidence certains panaches contenant notamment :

- des fumées d’incendie ;
- des poussières minérales ;
- des cendres volcaniques.

Cette couche est beaucoup plus grossière que l’imagerie VIIRS ou MODIS.
Elle doit être interprétée à l’échelle régionale et ne constitue ni une
mesure locale des particules fines ni un indicateur direct de l’exposition
de la population.

L’absence de signal peut aussi correspondre à une absence de passage
exploitable, à la présence de nuages ou à un panache trop faible pour être
détecté par ce produit.

### Vent actuel

Les flèches représentent le vent à 10 mètres issu du modèle ECMWF IFS,
obtenu par l’intermédiaire d’Open-Meteo.

La direction de la flèche indique vers où souffle le vent. Sa taille et sa
couleur donnent une indication de sa vitesse.

Cette couche est une information météorologique modélisée et ne constitue
pas une simulation de dispersion des fumées.

Elle représente toujours les conditions actuelles, indépendamment de la
date choisie pour l’image satellite.

### Surfaces brûlées

La couche **Surfaces brûlées 2026** utilise les données du système européen
EFFIS — European Forest Fire Information System.

À petite échelle, la carte affiche des repères ponctuels. En zoomant, les
périmètres détaillés des surfaces brûlées sont chargés lorsqu’ils sont
disponibles.

Cette couche peut être plus lente que les autres, car les données sont
rendues à la demande par le serveur cartographique EFFIS.

### Repères cartographiques

Les noms de villes et les principaux axes routiers peuvent être affichés
au-dessus des images satellitaires afin de faciliter leur localisation.

### Archives

Les images satellitaires peuvent être consultées jour par jour depuis le
24 novembre 2015.

Cette fonction permet notamment de revoir les incendies de Gironde de
l’été 2022 ou de comparer plusieurs épisodes passés.

Les autres couches n’ont pas nécessairement la même profondeur
historique :

- les foyers FIRMS restent limités aux dernières 48 heures ;
- le vent correspond aux conditions actuelles ;
- les surfaces brûlées correspondent à la saison en cours ;
- l’indice ATMO dépend des dates disponibles sur le serveur Atmo France.

## Limites à connaître

### Pas de temps réel satellitaire

Les satellites polaires utilisés ne fournissent généralement qu’une
observation diurne par jour et par satellite. Les images sont publiées
quelques heures après leur acquisition.

La situation au sol peut donc avoir changé depuis le passage du satellite.

### Nuages et résolution

Les nuages peuvent masquer totalement ou partiellement les fumées et les
surfaces brûlées.

Les images servies par GIBS sont adaptées à une analyse régionale. Elles ne
permettent pas de suivre précisément un front de feu à l’échelle d’une
habitation ou d’une parcelle.

### Interprétation des foyers

Une anomalie thermique satellitaire n’est pas automatiquement un incendie
de végétation confirmé. Des faux positifs ou des détections multiples d’un
même foyer sont possibles.

### Qualité de l’air

L’indice d’aérosols OMPS ne remplace pas les mesures de qualité de l’air.

Pour les informations sanitaires et les consignes officielles, consulter :

- [Atmo Nouvelle-Aquitaine](https://www.atmo-nouvelleaquitaine.org/) ;
- les préfectures concernées ;
- les services d’incendie et de secours.

## Données et outils utilisés

- **Imagerie satellitaire :**
  [NASA GIBS / Worldview](https://worldview.earthdata.nasa.gov/)
  — VIIRS et MODIS ;
- **Foyers actifs :**
  [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
  — anomalies thermiques VIIRS ;
- **Aérosols :**
  indice ultraviolet OMPS / Suomi-NPP — NASA ;
- **Qualité de l’air :**
  [Atmo France](https://www.atmo-france.org/) et les AASQA ;
- **Vent :**
  ECMWF IFS via [Open-Meteo](https://open-meteo.com/) ;
- **Surfaces brûlées :**
  [EFFIS](https://forest-fire.emergency.copernicus.eu/)
  — Copernicus Emergency Management Service / JRC ;
- **Limites communales :**
  IGN Admin Express COG 2026, Licence ouverte ;
- **Fond de carte :**
  © les contributeurs
  [OpenStreetMap](https://www.openstreetmap.org/copyright) ;
- **Repères cartographiques :**
  © CARTO ;
- **Bibliothèque cartographique :**
  [Leaflet](https://leafletjs.com/).

## Architecture technique

L’interface est constituée d’une page HTML statique hébergée gratuitement
sur GitHub Pages.

Une fonction Cloudflare Worker sert de proxy léger pour les requêtes NASA
FIRMS nécessitant une clé. La clé n’est jamais exposée dans le code envoyé
au navigateur.

Les autres données sont principalement obtenues directement depuis les
services web publics des producteurs.

Fichiers principaux :

- `index.html` : interface, carte et logique JavaScript ;
- `communes_na.geojson` : limites communales utilisées pour représenter
  l’indice ATMO.

## Modifier le site

Pour modifier le centrage initial de la carte, changer les coordonnées
utilisées dans :

```javascript
setView([44.9, 0.0], 7)
