from pathlib import Path
import contextlib
import io
import json
import os
import runpy
import warnings

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


def local_cluster_extent_metric(coordinates):
    """
    Produit une enveloppe arrondie par cluster local.

    Les clusters restent séparés et tous les centres
    FIRMS sont englobés.
    """
    if not len(coordinates):
        return None

    tree = cKDTree(coordinates)
    parent = list(range(len(coordinates)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[
                parent[index]
            ]
            index = parent[index]

        return index

    def union(left, right):
        root_left = find(left)
        root_right = find(right)

        if root_left != root_right:
            parent[root_right] = root_left

    for left, right in tree.query_pairs(
        r=LOCAL_CLUSTER_LINK_M
    ):
        union(left, right)

    clusters = {}

    for index in range(len(coordinates)):
        clusters.setdefault(
            find(index),
            [],
        ).append(index)

    envelopes = []

    for indexes in clusters.values():
        buffered_points = [
            Point(
                coordinates[index, 0],
                coordinates[index, 1],
            ).buffer(
                POINT_BUFFER_M,
                resolution=16,
            )
            for index in indexes
        ]

        raw_geometry = unary_union(
            buffered_points
        )

        smooth_geometry = (
            raw_geometry
            .buffer(
                SMOOTH_OUT_M,
                resolution=24,
                join_style=1,
            )
            .buffer(
                -SMOOTH_IN_M,
                resolution=24,
                join_style=1,
            )
        )

        if smooth_geometry.is_empty:
            smooth_geometry = raw_geometry

        envelopes.append(
            smooth_geometry.simplify(
                100.0,
                preserve_topology=True,
            )
        )

    geometry = unary_union(envelopes)

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    return geometry


def firms_extent_for_time(points, timestamp):
    """
    Recalcule l'emprise cumulative en utilisant uniquement
    les détections acquises jusqu'au passage sélectionné.
    """
    cutoff = pd.Timestamp(timestamp)

    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    selected = (
        points.loc[
            points["pass_time_utc"] <= cutoff,
            ["x", "y"],
        ]
        .drop_duplicates()
    )

    coordinates = selected[
        ["x", "y"]
    ].to_numpy()

    metric_geometry = local_cluster_extent_metric(
        coordinates
    )

    if (
        metric_geometry is None
        or metric_geometry.is_empty
    ):
        return None, 0

    geometry_wgs84 = shapely_transform(
        TO_WGS84.transform,
        metric_geometry,
    )

    return geometry_wgs84, len(selected)

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
firms_points = load_firms_points()



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
            firms_points,
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
