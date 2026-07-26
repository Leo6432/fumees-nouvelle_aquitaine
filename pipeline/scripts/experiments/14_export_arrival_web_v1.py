from pathlib import Path
import contextlib
import io
import json
import os
import runpy
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from rasterio.features import shapes as raster_shapes
from scipy.spatial import cKDTree
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union


MODEL = Path(
    "scripts/experiments/09_plausible_front_v2.py"
)

OUTPUT_GEOJSON = Path(
    "data/web/fire_progression_arrival_v1.geojson"
)

OUTPUT_MANIFEST = Path(
    "data/web/fire_progression_arrival_v1_manifest.json"
)

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


def mask_area_km2(mask):
    return (
        float(mask.sum())
        * cell_m
        * cell_m
        / 1_000_000.0
    )


def mask_to_wgs84(mask):
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
    "cumulative_local_point_clusters_v2"
)

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
        return None, 0

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
        return None, 0

    if not metric_geometry.is_valid:
        metric_geometry = metric_geometry.buffer(0)

    geometry_wgs84 = shapely_transform(
        TO_WGS84.transform,
        metric_geometry,
    )

    point_count = int(
        selected[
            "supported_detections_cumulative"
        ].sum()
    )

    return geometry_wgs84, point_count


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
                "fire_progression_arrival_v1",
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

    extent_geometry, extent_point_count = (
        firms_extent_for_time(
            firms_extents,
            timestamp,
        )
    )

    if extent_geometry is not None:
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
                    "fire_progression_arrival_v1",
            },
            "geometry":
                mapping(extent_geometry),
        })

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
                    "fire_progression_arrival_v1",
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
        "fire_progression_arrival_v1",

    "features":
        features,
}


manifest = {
    "model_version":
        "fire_progression_arrival_v1",

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
