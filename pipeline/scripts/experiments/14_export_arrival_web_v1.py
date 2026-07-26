from pathlib import Path
import contextlib
import io
import json
import os
import runpy
import warnings

import numpy as np
from pyproj import Transformer
from rasterio.features import shapes as raster_shapes
from shapely.geometry import mapping, shape
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
