from pathlib import Path
import contextlib
import io
import json
import math
import os
import runpy
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
import rasterio
from affine import Affine
from rasterio.features import rasterize
from rasterio.features import shapes as raster_shapes
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from scipy.spatial import cKDTree
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union


MODEL = Path(
    "scripts/experiments/09_plausible_front_v2.py"
)

OUTPUT_DIR = Path(
    "data/processed/experiments/"
    "land_water_mask_v1/parallel_export"
)

OUTPUT_GEOJSON = (
    OUTPUT_DIR
    / "fire_progression_arrival_landmask_v3.geojson"
)

OUTPUT_MANIFEST = (
    OUTPUT_DIR
    / "fire_progression_arrival_landmask_v3_manifest.json"
)

WORLDCOVER_DIR = Path(
    "data/external/worldcover_2021_v200"
)

LAND_FRACTION_THRESHOLD = 0.50
FIRMS_LANDMASK_RESOLUTION_M = 25.0
WATER_BOUNDARY_SIMPLIFY_M = 50.0
MIN_WATER_COMPONENT_AREA_M2 = 10_000.0
WORLDCOVER_BOUNDS_MARGIN_DEG = 0.02

VALID_PROJECTION_LEVELS = {
    "moyenne",
    "élevée",
}

os.environ["PROJECTION_SPEED_SCALE"] = "0.25"
warnings.filterwarnings("ignore")

with contextlib.redirect_stdout(io.StringIO()):
    model = runpy.run_path(str(MODEL))

records = model["projection_records"]
results = model["result"].set_index("snapshot_index")
transform = model["transform"]
cell_m = float(model["CELL_M"])

TO_WGS84 = Transformer.from_crs(
    "EPSG:2154",
    "EPSG:4326",
    always_xy=True,
)


MODEL_HEIGHT, MODEL_WIDTH = (
    records[0]["historical"].shape
)

MODEL_XMIN = float(transform.c)
MODEL_YMAX = float(transform.f)

MODEL_XMAX = (
    MODEL_XMIN
    + MODEL_WIDTH
    * float(transform.a)
)

MODEL_YMIN = (
    MODEL_YMAX
    + MODEL_HEIGHT
    * float(transform.e)
)

FIRMS_LANDMASK_CACHE = {}


def load_worldcover_source():
    """Charge WorldCover sur l'emprise utile du modèle."""

    paths = sorted(
        WORLDCOVER_DIR.glob(
            "ESA_WorldCover_10m_2021_v200_*_Map.tif"
        )
    )

    if not paths:
        raise FileNotFoundError(
            "Aucune tuile ESA WorldCover trouvée dans "
            f"{WORLDCOVER_DIR}."
        )

    corners = [
        TO_WGS84.transform(
            MODEL_XMIN,
            MODEL_YMIN,
        ),
        TO_WGS84.transform(
            MODEL_XMIN,
            MODEL_YMAX,
        ),
        TO_WGS84.transform(
            MODEL_XMAX,
            MODEL_YMIN,
        ),
        TO_WGS84.transform(
            MODEL_XMAX,
            MODEL_YMAX,
        ),
    ]

    bounds = (
        min(point[0] for point in corners)
        - WORLDCOVER_BOUNDS_MARGIN_DEG,

        min(point[1] for point in corners)
        - WORLDCOVER_BOUNDS_MARGIN_DEG,

        max(point[0] for point in corners)
        + WORLDCOVER_BOUNDS_MARGIN_DEG,

        max(point[1] for point in corners)
        + WORLDCOVER_BOUNDS_MARGIN_DEG,
    )

    datasets = [
        rasterio.open(path)
        for path in paths
    ]

    try:
        mosaic, mosaic_transform = merge(
            datasets,
            bounds=bounds,
            nodata=0,
            dtype="uint8",
        )
    finally:
        for dataset in datasets:
            dataset.close()

    worldcover = mosaic[0]

    # WorldCover :
    # 0  = absence de classification / océan ouvert ;
    # 80 = plans d'eau permanents.
    source_land = (
        (worldcover != 0)
        & (worldcover != 80)
    ).astype(np.float32)

    return (
        source_land,
        mosaic_transform,
        [path.name for path in paths],
    )


def reproject_land_fraction(
    destination_shape,
    destination_transform,
):
    """Agrège la fraction terrestre sur une grille cible."""

    destination = np.zeros(
        destination_shape,
        dtype=np.float32,
    )

    reproject(
        source=WORLDCOVER_SOURCE_LAND,
        destination=destination,
        src_transform=WORLDCOVER_SOURCE_TRANSFORM,
        src_crs="EPSG:4326",
        dst_transform=destination_transform,
        dst_crs="EPSG:2154",
        resampling=Resampling.average,
        src_nodata=None,
        dst_nodata=0.0,
    )

    return np.clip(
        destination,
        0.0,
        1.0,
    )


def polygonize_metric_mask(
    mask,
    mask_transform,
):
    """Polygonise un masque booléen en EPSG:2154."""

    geometries = []

    for geometry_mapping, value in raster_shapes(
        mask.astype(np.uint8),
        mask=mask,
        transform=mask_transform,
    ):
        if int(value) != 1:
            continue

        geometry = shape(geometry_mapping)

        if not geometry.is_valid:
            geometry = geometry.buffer(0)

        if not geometry.is_empty:
            geometries.append(geometry)

    if not geometries:
        return None

    geometry = unary_union(geometries)

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    if geometry.is_empty:
        return None

    return geometry


(
    WORLDCOVER_SOURCE_LAND,
    WORLDCOVER_SOURCE_TRANSFORM,
    WORLDCOVER_TILE_NAMES,
) = load_worldcover_source()


MODEL_LAND_FRACTION = reproject_land_fraction(
    (MODEL_HEIGHT, MODEL_WIDTH),
    transform,
)

MODEL_LAND_MASK = (
    MODEL_LAND_FRACTION
    >= LAND_FRACTION_THRESHOLD
)


FINE_WIDTH = int(
    round(
        (MODEL_XMAX - MODEL_XMIN)
        / FIRMS_LANDMASK_RESOLUTION_M
    )
)

FINE_HEIGHT = int(
    round(
        (MODEL_YMAX - MODEL_YMIN)
        / FIRMS_LANDMASK_RESOLUTION_M
    )
)

FINE_TRANSFORM = Affine(
    FIRMS_LANDMASK_RESOLUTION_M,
    0.0,
    MODEL_XMIN,
    0.0,
    -FIRMS_LANDMASK_RESOLUTION_M,
    MODEL_YMAX,
)

FINE_LAND_FRACTION = reproject_land_fraction(
    (FINE_HEIGHT, FINE_WIDTH),
    FINE_TRANSFORM,
)

FINE_LAND_MASK = (
    FINE_LAND_FRACTION
    >= LAND_FRACTION_THRESHOLD
)


def polygon_parts(geometry):
    """Retourne uniquement les composantes polygonales."""

    if geometry is None or geometry.is_empty:
        return []

    if geometry.geom_type == "Polygon":
        return [geometry]

    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)

    if hasattr(geometry, "geoms"):
        parts = []

        for component in geometry.geoms:
            parts.extend(
                polygon_parts(component)
            )

        return parts

    return []


def mask_vector_geometry_to_land(geometry):
    """Soustrait les surfaces aquatiques à la géométrie web.

    L'entrée est la géométrie web déjà simplifiée exactement comme
    dans l'export historique. La sortie est donc explicitement
    contenue dans l'ancienne géométrie publiée.

    Les petites composantes aquatiques inférieures à 1 ha sont
    ignorées afin d'éviter une explosion de la complexité GeoJSON.
    """

    if geometry is None or geometry.is_empty:
        return None

    cache_key = geometry.wkb

    if cache_key in FIRMS_LANDMASK_CACHE:
        return FIRMS_LANDMASK_CACHE[cache_key]

    gxmin, gymin, gxmax, gymax = geometry.bounds
    resolution = FIRMS_LANDMASK_RESOLUTION_M

    col_min = max(
        0,
        int(
            math.floor(
                (gxmin - MODEL_XMIN)
                / resolution
            )
        ) - 1,
    )

    col_max = min(
        FINE_WIDTH,
        int(
            math.ceil(
                (gxmax - MODEL_XMIN)
                / resolution
            )
        ) + 1,
    )

    row_min = max(
        0,
        int(
            math.floor(
                (MODEL_YMAX - gymax)
                / resolution
            )
        ) - 1,
    )

    row_max = min(
        FINE_HEIGHT,
        int(
            math.ceil(
                (MODEL_YMAX - gymin)
                / resolution
            )
        ) + 1,
    )

    if (
        row_max <= row_min
        or col_max <= col_min
    ):
        FIRMS_LANDMASK_CACHE[cache_key] = geometry
        return geometry

    local_transform = (
        FINE_TRANSFORM
        * Affine.translation(
            col_min,
            row_min,
        )
    )

    local_land_mask = FINE_LAND_MASK[
        row_min:row_max,
        col_min:col_max,
    ]

    local_water_mask = ~local_land_mask

    water_geometry = polygonize_metric_mask(
        local_water_mask,
        local_transform,
    )

    if (
        water_geometry is None
        or water_geometry.is_empty
    ):
        FIRMS_LANDMASK_CACHE[cache_key] = geometry
        return geometry

    water_parts = [
        part
        for part in polygon_parts(
            water_geometry
        )
        if (
            part.area
            >= MIN_WATER_COMPONENT_AREA_M2
            and part.intersects(geometry)
        )
    ]

    if not water_parts:
        FIRMS_LANDMASK_CACHE[cache_key] = geometry
        return geometry

    water_geometry = unary_union(
        water_parts
    )

    if not water_geometry.is_valid:
        water_geometry = water_geometry.buffer(0)

    water_geometry = water_geometry.simplify(
        WATER_BOUNDARY_SIMPLIFY_M,
        preserve_topology=True,
    )

    if not water_geometry.is_valid:
        water_geometry = water_geometry.buffer(0)

    result = geometry.difference(
        water_geometry
    )

    # Garantie stricte par rapport à la géométrie web historique.
    result = result.intersection(
        geometry
    )

    if not result.is_valid:
        result = result.buffer(0)

    if result.is_empty:
        result = None

    FIRMS_LANDMASK_CACHE[cache_key] = result

    return result


def mask_area_km2(mask):
    masked = (
        np.asarray(mask, dtype=bool)
        & MODEL_LAND_MASK
    )

    return (
        float(masked.sum())
        * cell_m
        * cell_m
        / 1_000_000.0
    )


def mask_to_wgs84(mask):
    mask = (
        np.asarray(mask, dtype=bool)
        & MODEL_LAND_MASK
    )

    if not mask.any():
        return None

    geometries = []

    for geometry_mapping, value in raster_shapes(
        mask.astype(np.uint8),
        mask=mask,
        transform=transform,
    ):
        if int(value) != 1:
            continue

        geometry = shape(geometry_mapping)

        if not geometry.is_valid:
            geometry = geometry.buffer(0)

        if not geometry.is_empty:
            geometries.append(geometry)

    if not geometries:
        return None

    geometry = unary_union(
        geometries
    ).simplify(
        50.0,
        preserve_topology=True,
    )

    return shapely_transform(
        TO_WGS84.transform,
        geometry,
    )



FIRMS_POINTS_INPUT = Path(
    "data/processed/"
    "spatiotemporal_support_causal_passes_v1.csv"
)

FIRMS_EXTENT_METHOD = (
    "cumulative_detection_extent_smoothed_landmasked_web_v1"
)

# Lissage réservé à l'affichage web.
# Closing symétrique : aucune expansion nette théorique.
FIRMS_DISPLAY_SMOOTH_M = 300.0

# Connexion maximale entre détections d'un même incendie local.
LOCAL_CLUSTER_LINK_M = 10_000.0

# Marge englobant chaque centre de détection.
POINT_BUFFER_M = 900.0

# Fermeture arrondie à l'intérieur de chaque cluster.
SMOOTH_OUT_M = 2_500.0
SMOOTH_IN_M = 2_000.0


def load_firms_points():
    points = pd.read_csv(
        FIRMS_POINTS_INPUT,
        usecols=[
            "x",
            "y",
            "pass_time_utc",
        ],
    )

    points["x"] = pd.to_numeric(
        points["x"],
        errors="coerce",
    )

    points["y"] = pd.to_numeric(
        points["y"],
        errors="coerce",
    )

    points["pass_time_utc"] = pd.to_datetime(
        points["pass_time_utc"],
        utc=True,
        errors="coerce",
    )

    return (
        points
        .dropna(
            subset=[
                "x",
                "y",
                "pass_time_utc",
            ]
        )
        .sort_values("pass_time_utc")
        .reset_index(drop=True)
    )


def load_cumulative_firms_extents():
    """
    Charge les emprises cumulées déjà calculées et validées
    par 03_cumulative_detection_envelopes.py.
    """
    path = Path(
        "data/processed/detection_envelopes.gpkg"
    )

    if not path.exists():
        raise FileNotFoundError(
            "Emprises cumulées absentes : "
            "lancer 03_cumulative_detection_envelopes.py."
        )

    extents = gpd.read_file(
        path,
        layer="cumulative_detection_envelopes",
    ).to_crs("EPSG:2154")

    extents["observed_until_dt"] = pd.to_datetime(
        extents["observed_until_utc"],
        utc=True,
        errors="coerce",
    )

    return (
        extents.dropna(
            subset=["observed_until_dt", "geometry"]
        )
        .sort_values(
            [
                "cluster_id",
                "observed_until_dt",
                "snapshot_index",
            ]
        )
        .reset_index(drop=True)
    )


def firms_extent_for_time(extents, timestamp):
    """
    Pour chaque cluster, sélectionne la dernière emprise
    cumulative disponible au passage demandé, puis fusionne
    les clusters actifs.
    """
    cutoff = pd.Timestamp(timestamp)

    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    available = extents.loc[
        extents["observed_until_dt"] <= cutoff
    ].copy()

    if available.empty:
        return None, 0, None

    selected = (
        available.groupby(
            "cluster_id",
            as_index=False,
        )
        .tail(1)
        .copy()
    )

    metric_geometry = unary_union(
        selected.geometry.to_list()
    )

    if metric_geometry.is_empty:
        return None, 0, None

    if not metric_geometry.is_valid:
        metric_geometry = metric_geometry.buffer(0)

    # Lissage purement graphique de l'emprise publiée.
    # La géométrie scientifique du GPKG reste inchangée.
    display_geometry = (
        metric_geometry
        .buffer(
            FIRMS_DISPLAY_SMOOTH_M,
            resolution=24,
            join_style=1,
        )
        .buffer(
            -FIRMS_DISPLAY_SMOOTH_M,
            resolution=24,
            join_style=1,
        )
    )

    if display_geometry.is_empty:
        display_geometry = metric_geometry

    if not display_geometry.is_valid:
        display_geometry = display_geometry.buffer(0)

    # Reproduction exacte de la géométrie web historique.
    baseline_geometry = display_geometry.simplify(
        30.0,
        preserve_topology=True,
    )

    if not baseline_geometry.is_valid:
        baseline_geometry = baseline_geometry.buffer(0)

    metric_geometry = mask_vector_geometry_to_land(
        baseline_geometry
    )

    if (
        metric_geometry is None
        or metric_geometry.is_empty
    ):
        return None, 0, None

    geometry_wgs84 = shapely_transform(
        TO_WGS84.transform,
        metric_geometry,
    )

    point_count = int(
        selected[
            "supported_detections_cumulative"
        ].sum()
    )

    extent_state_key = tuple(
        sorted(
            (
                int(row.cluster_id),
                int(row.snapshot_index),
            )
            for row in selected.itertuples()
        )
    )

    return (
        geometry_wgs84,
        point_count,
        extent_state_key,
    )


arrival_index = np.full(
    records[0]["historical"].shape,
    -1,
    dtype=np.int16,
)

for index, record in enumerate(records):
    newly_detected = (
        record["historical"]
        & (arrival_index < 0)
    )

    arrival_index[newly_detected] = index


features = []
manifest_snapshots = []
firms_extents = load_cumulative_firms_extents()
last_firms_extent_state_key = None


# Une seule géométrie par étape de première détection.
for index, record in enumerate(records):
    mask = arrival_index == index
    geometry = mask_to_wgs84(mask)

    if geometry is None:
        continue

    timestamp = record["timestamp"]
    local_time = timestamp.tz_convert(
        "Europe/Paris"
    )

    features.append({
        "type": "Feature",
        "properties": {
            "category":
                "arrival_step",

            "arrival_snapshot_index":
                int(record["snapshot_index"]),

            "first_detected_utc":
                timestamp.isoformat(),

            "first_detected_local":
                local_time.isoformat(),

            "area_km2":
                round(
                    mask_area_km2(mask),
                    3,
                ),

            "label":
                "Première détection FIRMS",

            "model_version":
                "fire_progression_arrival_landmask_v3",
        },
        "geometry":
            mapping(geometry),
    })


# États propres à chaque passage.
for record in records:
    snapshot_index = int(
        record["snapshot_index"]
    )

    timestamp = record["timestamp"]
    local_time = timestamp.tz_convert(
        "Europe/Paris"
    )

    diagnostics = results.loc[
        snapshot_index
    ]

    coherence_level = str(
        record["confidence"]
    )

    coherence_fraction = float(
        diagnostics[
            "coherent_boundary_fraction"
        ]
    )

    categories = {
        "historical_support":
            record["historical"],

        "observed_front":
            record["current"],
    }

    projection_displayed = (
        coherence_level
        in VALID_PROJECTION_LEVELS
        and not np.array_equal(
            record["plus_1h"],
            record["current"],
        )
    )

    if projection_displayed:
        categories[
            "plausible_front_1h"
        ] = record["plus_1h"]

    snapshot_categories = []

    (
        extent_geometry,
        extent_point_count,
        extent_state_key,
    ) = firms_extent_for_time(
        firms_extents,
        timestamp,
    )

    if extent_geometry is not None:
        if (
            extent_state_key
            != last_firms_extent_state_key
        ):
            features.append({
                "type": "Feature",
                "properties": {
                    "category":
                        "firms_extent_snapshot",

                    "snapshot_index":
                        snapshot_index,

                    "pass_time_utc":
                        timestamp.isoformat(),

                    "dt_local":
                        local_time.isoformat(),

                    "label":
                        "Emprise FIRMS cumulée à ce passage",

                    "interpretation":
                        "Enveloppe des détections FIRMS, "
                        "pas une surface brûlée",

                    "cumulative":
                        True,

                    "point_count":
                        int(extent_point_count),

                    "extent_method":
                        FIRMS_EXTENT_METHOD,

                    "local_cluster_link_m":
                        LOCAL_CLUSTER_LINK_M,

                    "model_version":
                        "fire_progression_arrival_landmask_v3",
                },
                "geometry":
                    mapping(extent_geometry),
            })

            last_firms_extent_state_key = (
                extent_state_key
            )

        snapshot_categories.append({
            "category":
                "firms_extent_snapshot",

            "point_count":
                int(extent_point_count),
        })

    for category, mask in categories.items():
        geometry = mask_to_wgs84(mask)

        if geometry is None:
            continue

        area_km2 = mask_area_km2(mask)

        labels = {
            "historical_support":
                "Isoline temporelle",

            "observed_front":
                "Activité observée",

            "plausible_front_1h":
                "Progression plausible à +1 h",
        }

        features.append({
            "type": "Feature",
            "properties": {
                "category":
                    category,

                "snapshot_index":
                    snapshot_index,

                "pass_time_utc":
                    timestamp.isoformat(),

                "dt_local":
                    local_time.isoformat(),

                "area_km2":
                    round(area_km2, 3),

                "label":
                    labels[category],

                "coherence_level":
                    coherence_level,

                "coherence_fraction":
                    round(
                        coherence_fraction,
                        3,
                    ),

                "projection_displayed":
                    projection_displayed,

                "model_version":
                    "fire_progression_arrival_landmask_v3",
            },
            "geometry":
                mapping(geometry),
        })

        snapshot_categories.append({
            "category":
                category,

            "area_km2":
                round(area_km2, 3),
        })

    manifest_snapshots.append({
        "snapshot_index":
            snapshot_index,

        "pass_time_utc":
            timestamp.isoformat(),

        "dt_local":
            local_time.isoformat(),

        "coherence_level":
            coherence_level,

        "coherence_fraction":
            round(
                coherence_fraction,
                3,
            ),

        "projection_displayed":
            projection_displayed,

        "categories":
            snapshot_categories,
    })


geojson = {
    "type":
        "FeatureCollection",

    "name":
        "fire_progression_arrival_landmask_v3",

    "features":
        features,
}


manifest = {
    "model_version":
        "fire_progression_arrival_landmask_v3",

    "description":
        "Évolution observée des détections FIRMS, "
        "représentée par l’âge de première détection.",

    "display_layers": [
        "firms_extent_snapshot",
        "arrival_surface",
        "temporal_isolines",
        "observed_front",
        "plausible_front_1h",
    ],

    "projection": {
        "horizon_h":
            1,

        "speed_scale":
            0.25,

        "recursive":
            False,
    },

    "land_water_mask": {
        "enabled":
            True,

        "worldcover_product":
            "ESA WorldCover 2021 v200",

        "worldcover_tiles":
            WORLDCOVER_TILE_NAMES,

        "land_fraction_threshold":
            LAND_FRACTION_THRESHOLD,

        "raster_layers_resolution_m":
            cell_m,

        "firms_extent_resolution_m":
            FIRMS_LANDMASK_RESOLUTION_M,

        "water_boundary_simplify_m":
            WATER_BOUNDARY_SIMPLIFY_M,

        "minimum_water_component_area_m2":
            MIN_WATER_COMPONENT_AREA_M2,

        "firms_mask_method":
            "vector_water_subtraction_v3",

        "water_classes": [
            0,
            80,
        ],

        "scientific_geometries_modified":
            False,
    },

    "snapshots":
        manifest_snapshots,
}


OUTPUT_GEOJSON.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_GEOJSON.write_text(
    json.dumps(
        geojson,
        ensure_ascii=False,
        separators=(",", ":"),
    )
)

OUTPUT_MANIFEST.write_text(
    json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    )
)


print("Snapshots :", len(records))
print(
    "Étapes de première détection :",
    sum(
        feature["properties"]["category"]
        == "arrival_step"
        for feature in features
    ),
)
print("Entités GeoJSON :", len(features))
print("Écrit :", OUTPUT_GEOJSON)
print("Écrit :", OUTPUT_MANIFEST)
