# Fumées · Nouvelle-Aquitaine 🔥🛰️

Carte web consacrée au suivi régional des panaches de fumée, des anomalies
thermiques détectées par satellite, de la qualité de l’air et de plusieurs
informations utiles lors des incendies en Nouvelle-Aquitaine.

**Site en ligne :**  
https://nicolaslecorvec.github.io/fumees-nouvelle_aquitaine/

## Principe général

Le site s’ouvre volontairement sur une vue simple :

- le choix du jour ;
- le choix du satellite ;
- l’image satellitaire.

Les autres informations sont regroupées dans le panneau dépliant
**Couches et réglages**. Elles sont désactivées au démarrage afin de laisser
l’image satellite lisible. Chaque utilisateur peut ensuite activer les
couches qui l’intéressent.

## Ce que montre le site

### Imagerie satellitaire

La carte permet de consulter des images en couleurs naturelles provenant de
deux services complémentaires :

- **NASA GIBS / Worldview** pour VIIRS et MODIS ;
- **Copernicus Data Space** pour Sentinel-3 OLCI.

Pour les couches NASA, le site tente d’abord d’afficher l’image du jour. Si
elle n’est pas encore publiée, il peut reculer automatiquement vers la
dernière image disponible.

Les panaches de fumée apparaissent généralement comme des traînées grisâtres
ou bleuâtres, parfois très étendues au-dessus du continent ou de l’océan.

Satellites proposés :

- **VIIRS NOAA-20** — passage diurne généralement autour du début d’après-midi ;
- **VIIRS Suomi-NPP** — passage diurne généralement autour du début d’après-midi ;
- **MODIS Terra** — passage diurne généralement en fin de matinée ;
- **MODIS Aqua** — passage diurne généralement au début de l’après-midi ;
- **Sentinel-3 OLCI, 3A + 3B** — image régionale d’environ 300 m de résolution nominale.

Les horaires indiqués sont approximatifs. Ils varient selon la trace orbitale,
la latitude, le satellite et la zone réellement observée.

L’image Sentinel-3 peut être une mosaïque composée de plusieurs bandes de
passage ou de plusieurs acquisitions de Sentinel-3A et Sentinel-3B. Les
limites obliques parfois visibles correspondent alors aux raccords entre
scènes.

### Détections thermiques FIRMS des dernières 48 heures

La couche **Foyers actuels (48 h)** utilise les anomalies thermiques diffusées
par NASA FIRMS.

Sources interrogées :

- **VIIRS NOAA-20** ;
- **VIIRS NOAA-21** ;
- **VIIRS Suomi-NPP** ;
- **MODIS Terra et Aqua**.

La fenêtre affichée est une vraie fenêtre glissante de 48 heures, calculée à
partir de l’heure d’acquisition de chaque détection.

Les couleurs représentent l’âge de la détection :

- **0–8 h** : rouge foncé ;
- **8–16 h** : rouge ;
- **16–24 h** : orange ;
- **24–32 h** : orange clair ;
- **32–40 h** : jaune ;
- **40–48 h** : jaune très clair.

La légende est interactive. Un clic sur une classe horaire masque les autres
détections. Un second clic, ou le bouton **Tous les foyers**, rétablit
l’ensemble des points.

Pour chaque détection, la fenêtre d’information indique notamment :

- la date et l’heure d’acquisition en UTC ;
- l’âge de la détection ;
- le satellite et l’instrument ;
- le flux FIRMS utilisé ;
- la puissance radiative du feu, en MW ;
- le niveau de confiance.

Ces symboles représentent des **pixels thermiques détectés par satellite**,
et non nécessairement des incendies distincts ou confirmés au sol. Plusieurs
points voisins peuvent appartenir au même feu, à la même zone chaude ou à
plusieurs passages successifs.

Cette couche reste toujours relative aux dernières 48 heures, quelle que soit
la date choisie pour l’image satellite.

### Qualité de l’air par commune

La couche **Indice ATMO par commune** affiche l’indice officiel produit par
Atmo France et les associations agréées de surveillance de la qualité de
l’air.

La date demandée correspond au jour choisi dans l’interface, sous réserve que
les données soient disponibles sur le serveur Atmo France.

La couleur de chaque commune peut représenter :

- l’indice global ;
- les particules PM2.5 ;
- les particules PM10 ;
- l’ozone — O₃ ;
- le dioxyde d’azote — NO₂ ;
- le dioxyde de soufre — SO₂.

Un clic sur une commune affiche le détail des sous-indices disponibles.

La couche **Contrôle WMS (points)** affiche directement la représentation
cartographique fournie par le serveur Atmo France. Elle sert principalement à
contrôler visuellement la cohérence de la couche communale et peut rester
désactivée en usage normal.

### Aérosols — indice ultraviolet OMPS

La couche **Aérosols OMPS (AI)** représente un indice d’aérosols absorbants
mesuré dans l’ultraviolet.

Elle peut mettre en évidence certains panaches contenant notamment :

- des fumées d’incendie ;
- des poussières minérales ;
- des cendres volcaniques.

Cette donnée est beaucoup plus grossière que l’imagerie VIIRS, MODIS ou
Sentinel-3. Elle doit être interprétée à l’échelle régionale.

Elle ne constitue ni une mesure locale des particules fines, ni un indicateur
direct de l’exposition de la population.

L’absence de signal peut correspondre à une absence de passage exploitable, à
la présence de nuages ou à un panache trop faible pour être détecté par ce
produit.

### Vent actuel

Les flèches représentent le vent à 10 mètres issu du modèle ECMWF IFS, obtenu
par l’intermédiaire d’Open-Meteo.

La direction de la flèche indique vers où souffle le vent. Sa taille et sa
couleur donnent une indication de sa vitesse.

Cette couche est une information météorologique modélisée. Elle ne constitue
pas une simulation de dispersion des fumées.

Le vent correspond toujours aux conditions actuelles, indépendamment de la
date choisie pour l’image satellite.

### Surfaces brûlées

La couche **Surfaces brûlées (EFFIS)** utilise les données du système européen
EFFIS — European Forest Fire Information System.

À petite échelle, la carte affiche des repères ponctuels. À partir d’un niveau
de zoom plus élevé, elle demande les périmètres détaillés lorsqu’ils sont
disponibles.

La période interrogée commence au 1er janvier de l’année sélectionnée et se
termine au jour choisi dans l’interface.

Cette couche peut être plus lente que les autres, car les données sont
rendues à la demande par le serveur cartographique EFFIS.

### Repères cartographiques

La couche **Repères (villes, routes)** ajoute les noms de lieux et les
principaux axes routiers au-dessus de l’image satellite.

Elle est désactivée au démarrage afin de conserver une vue satellitaire aussi
lisible que possible.

### Réglages d’affichage

Le panneau **Couches et réglages** permet aussi de modifier :

- l’opacité de l’image satellite ;
- l’intensité visuelle de la couche d’aérosols OMPS.

Sur mobile, la légende FIRMS est automatiquement réduite afin de ne pas
masquer une trop grande partie de la carte.

## Archives

Les images NASA peuvent être consultées jour par jour à partir du
24 novembre 2015, sous réserve de la disponibilité réelle de chaque produit.

Cette fonction permet notamment de revoir les incendies de Gironde de l’été
2022 ou de comparer plusieurs épisodes passés.

Sentinel-3 OLCI dispose de sa propre période de disponibilité, liée au début
des missions Sentinel-3 et aux acquisitions présentes dans Copernicus Data
Space.

Les autres couches n’ont pas nécessairement la même profondeur historique :

- les détections FIRMS restent limitées aux dernières 48 heures ;
- le vent correspond aux conditions actuelles ;
- les surfaces brûlées dépendent des données EFFIS disponibles pour l’année choisie ;
- l’indice ATMO dépend des dates présentes sur le serveur Atmo France ;
- OMPS dépend des passages et produits disponibles dans NASA GIBS.

## Limites à connaître

### Pas de temps réel satellitaire

Les satellites polaires utilisés ne fournissent pas une observation continue.
Les images sont acquises lors de passages orbitaux, puis publiées après leur
traitement.

La situation au sol peut donc avoir changé depuis le passage du satellite.

### Nuages, raccords et résolution

Les nuages peuvent masquer totalement ou partiellement les fumées et les
surfaces brûlées.

Les raccords visibles dans certaines images Sentinel-3 peuvent correspondre à
plusieurs bandes de passage assemblées dans une même mosaïque.

Les images sont adaptées à une analyse régionale. Elles ne permettent pas de
suivre précisément un front de feu à l’échelle d’une habitation ou d’une
parcelle.

### Interprétation des détections thermiques

Une anomalie thermique satellitaire n’est pas automatiquement un incendie de
végétation confirmé.

Des faux positifs, des pixels adjacents, des doublons ou plusieurs détections
du même feu sont possibles.

La taille des symboles dépend de la puissance radiative déclarée par FIRMS.
Elle ne représente pas directement la superficie brûlée.

### Qualité de l’air

L’indice d’aérosols OMPS ne remplace pas les mesures réglementaires de qualité
de l’air.

Pour les informations sanitaires et les consignes officielles, consulter :

- [Atmo Nouvelle-Aquitaine](https://www.atmo-nouvelleaquitaine.org/) ;
- les préfectures concernées ;
- les services d’incendie et de secours.

## Données et outils utilisés

- **Imagerie VIIRS et MODIS :**
  [NASA GIBS / Worldview](https://worldview.earthdata.nasa.gov/) ;
- **Imagerie Sentinel-3 OLCI :**
  Copernicus Sentinel-3A et Sentinel-3B via
  [Copernicus Data Space](https://dataspace.copernicus.eu/) ;
- **Détections thermiques :**
  [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
  — VIIRS et MODIS ;
- **Aérosols :**
  indice ultraviolet OMPS / Suomi-NPP via NASA GIBS ;
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

L’interface est une page HTML statique hébergée sur GitHub Pages.

Un Cloudflare Worker sert de proxy et de couche de cache pour plusieurs
services :

- NASA FIRMS ;
- Copernicus Data Space / Sentinel Hub ;
- Atmo France ;
- OpenAQ, lorsque cette route est utilisée.

Les clés et secrets ne sont jamais inclus dans le fichier HTML envoyé au
navigateur.

Secrets utilisés dans le Worker :

```text
FIRMS_KEY
OPENAQ_KEY
CDSE_CLIENT_ID
CDSE_CLIENT_SECRET
```

Les identifiants `CDSE_CLIENT_ID` et `CDSE_CLIENT_SECRET` correspondent à un
client OAuth Copernicus Data Space. Ils sont différents des credentials S3
utilisés avec AWS CLI.

Fichiers principaux :

- `index.html` : interface, carte et logique JavaScript ;
- `communes_na.geojson` : limites communales de Nouvelle-Aquitaine ;
- `worker_fumees_sentinel3.js` : proxy Cloudflare pour FIRMS, Atmo et Sentinel-3.

## Modifier le site

### Centrage initial

Pour modifier le centrage initial de la carte, changer les coordonnées et le
niveau de zoom dans :

```javascript
const map = L.map('map', { zoomControl: true })
  .setView([44.9, 0.0], 7);
```

### Emprise FIRMS

L’emprise interrogée par NASA FIRMS est définie dans :

```javascript
const FIRMS_BBOX = '-2.0,42.6,2.6,47.2';
```

L’ordre des valeurs est :

```text
ouest,sud,est,nord
```

### Emprise Sentinel-3

L’image Sentinel-3 est demandée sur une emprise régionale fixe :

```javascript
const SENTINEL3_BOUNDS = L.latLngBounds([
  [42.4, -2.2],
  [47.4,  2.9]
]);
```

La même emprise doit rester cohérente avec le paramètre `bbox` envoyé au
Worker.

### Fréquence d’actualisation FIRMS

La carte tente une actualisation des détections FIRMS toutes les quinze
minutes lorsque l’onglet est visible :

```javascript
const FIRMS_REFRESH_MS = 15 * 60 * 1000;
```

Le Worker applique également son propre cache afin de limiter les appels
répétés à NASA FIRMS.

## Avertissement

Cette carte est un outil de visualisation et de compréhension régionale.

Elle ne remplace pas :

- les consignes des autorités ;
- les cartes opérationnelles des services de secours ;
- les observations de terrain ;
- les mesures réglementaires de qualité de l’air.
