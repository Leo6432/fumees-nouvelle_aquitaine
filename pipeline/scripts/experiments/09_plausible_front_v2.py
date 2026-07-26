from pathlib import Path
import json
import math
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from scipy.ndimage import (
    binary_erosion,
    distance_transform_edt,
    gaussian_filter,
)
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform


GEOJSON_INPUT = Path(
    "data/processed/experiments/"
    "fire_progression_passes_v1.geojson"
)

MANIFEST_INPUT = Path(
    "data/processed/experiments/"
    "fire_progression_passes_v1_manifest.json"
)

STATS_INPUT = Path(
    "data/processed/experiments/"
    "fire_progression_passes_v1.csv"
)

DISTANCE_INPUT = Path(
    "data/processed/"
    "characteristic_distance_regularized_v1.csv"
)

OUTPUT_CSV = Path(
    "data/processed/experiments/"
    "plausible_front_v2.csv"
)

OUTPUT_PNG = Path(
    "data/processed/experiments/"
    "plausible_front_v2.png"
)


CELL_M = 250.0
PADDING_M = 3000.0

MAX_REFERENCE_GAP_H = 3.0
MIN_OBSERVATIONS = 10
MIN_COHERENT_BOUNDARY_FRACTION = 0.25

MAX_PROJECTED_DISTANCE_M = 2000.0
UNCERTAINTY_FACTOR = 0.50

HORIZONS_H = [1.0, 3.0]

PROJECTION_SPEED_SCALE = float(
    os.environ.get(
        "PROJECTION_SPEED_SCALE",
        "0.25",
    )
)


TO_LAMBERT93 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:2154",
    always_xy=True,
)


def feature_geometry_l93(feature):
    geometry = shape(
        feature["geometry"]
    )

    if geometry.is_empty:
        return None

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    if geometry.is_empty:
        return None

    return shapely_transform(
        TO_LAMBERT93.transform,
        geometry,
    )


def mask_area_km2(mask):
    return (
        float(mask.sum())
        * CELL_M
        * CELL_M
        / 1_000_000.0
    )


def boundary_mask(mask):
    if not mask.any():
        return np.zeros_like(
            mask,
            dtype=bool,
        )

    eroded = binary_erosion(
        mask,
        structure=np.ones(
            (3, 3),
            dtype=bool,
        ),
        border_value=0,
    )

    return mask & ~eroded


def confidence_level(
    eligible,
    gap_h,
    n_previous,
    n_current,
    coherent_fraction,
):
    if not eligible:
        return "indisponible"

    minimum_n = min(
        n_previous,
        n_current,
    )

    if (
        gap_h <= 1.5
        and minimum_n >= 50
        and coherent_fraction >= 0.60
    ):
        return "élevée"

    if (
        gap_h <= 3.0
        and minimum_n >= 20
        and coherent_fraction >= 0.40
    ):
        return "moyenne"

    return "faible"


geojson = json.loads(
    GEOJSON_INPUT.read_text()
)

manifest = json.loads(
    MANIFEST_INPUT.read_text()
)

stats = pd.read_csv(
    STATS_INPUT
)

distances = pd.read_csv(
    DISTANCE_INPUT
)


stats_time_column = (
    "pass_time_utc"
    if "pass_time_utc" in stats.columns
    else "dt_utc"
)

stats[stats_time_column] = pd.to_datetime(
    stats[stats_time_column],
    utc=True,
)

distances["pass_time_utc"] = pd.to_datetime(
    distances["pass_time_utc"],
    utc=True,
)


stats_by_index = stats.set_index(
    "snapshot_index"
)

distance_by_time = {
    timestamp:
        float(distance)
    for timestamp, distance in zip(
        distances["pass_time_utc"],
        distances[
            "distance_regularized_m"
        ],
    )
}


features_by_snapshot = {}

all_l93_geometries = []

for feature in geojson["features"]:
    properties = (
        feature.get("properties")
        or {}
    )

    snapshot_index = int(
        properties["snapshot_index"]
    )

    category = properties.get(
        "category"
    )

    geometry = feature_geometry_l93(
        feature
    )

    if geometry is None:
        continue

    features_by_snapshot.setdefault(
        snapshot_index,
        {},
    )[category] = geometry

    all_l93_geometries.append(
        geometry
    )


if not all_l93_geometries:
    raise SystemExit(
        "Aucune géométrie exploitable."
    )


xmin = min(
    geometry.bounds[0]
    for geometry in all_l93_geometries
) - PADDING_M

ymin = min(
    geometry.bounds[1]
    for geometry in all_l93_geometries
) - PADDING_M

xmax = max(
    geometry.bounds[2]
    for geometry in all_l93_geometries
) + PADDING_M

ymax = max(
    geometry.bounds[3]
    for geometry in all_l93_geometries
) + PADDING_M


xmin = (
    math.floor(xmin / CELL_M)
    * CELL_M
)

ymin = (
    math.floor(ymin / CELL_M)
    * CELL_M
)

xmax = (
    math.ceil(xmax / CELL_M)
    * CELL_M
)

ymax = (
    math.ceil(ymax / CELL_M)
    * CELL_M
)


nx = int(
    round(
        (xmax - xmin)
        / CELL_M
    )
)

ny = int(
    round(
        (ymax - ymin)
        / CELL_M
    )
)


transform = Affine(
    CELL_M,
    0.0,
    xmin,
    0.0,
    -CELL_M,
    ymax,
)


def geometry_to_mask(geometry):
    if geometry is None:
        return np.zeros(
            (ny, nx),
            dtype=bool,
        )

    return rasterize(
        [
            (
                mapping(geometry),
                1,
            )
        ],
        out_shape=(ny, nx),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    ).astype(bool)


snapshots = []

for snapshot_record in manifest["snapshots"]:
    snapshot_index = int(
        snapshot_record[
            "snapshot_index"
        ]
    )

    time_value = (
        snapshot_record.get(
            "pass_time_utc"
        )
        or snapshot_record.get(
            "dt_utc"
        )
    )

    timestamp = pd.Timestamp(
        time_value
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(
            "UTC"
        )

    geometries = features_by_snapshot.get(
        snapshot_index,
        {},
    )

    observed_mask = geometry_to_mask(
        geometries.get(
            "observed_front"
        )
    )

    historical_mask = geometry_to_mask(
        geometries.get(
            "historical_support"
        )
    )

    if snapshot_index in stats_by_index.index:
        stats_row = stats_by_index.loc[
            snapshot_index
        ]

        n_observations = int(
            stats_row[
                "n_observations"
            ]
        )
    else:
        n_observations = 0

    characteristic_distance_m = (
        distance_by_time.get(
            timestamp,
            np.nan,
        )
    )

    snapshots.append({
        "snapshot_index":
            snapshot_index,

        "timestamp":
            timestamp,

        "n_observations":
            n_observations,

        "characteristic_distance_m":
            characteristic_distance_m,

        "observed":
            observed_mask,

        "historical":
            historical_mask,
    })


snapshots.sort(
    key=lambda record:
        record["timestamp"]
)


rows = []
projection_records = []


for index, current in enumerate(
    snapshots
):
    current_mask = current["observed"]
    current_boundary = boundary_mask(
        current_mask
    )

    projection = {
        "snapshot_index":
            current["snapshot_index"],

        "timestamp":
            current["timestamp"],

        "current":
            current_mask,

        "historical":
            current["historical"],

        "plus_1h":
            current_mask.copy(),

        "plus_3h":
            current_mask.copy(),

        "uncertainty_1h":
            current_mask.copy(),

        "uncertainty_3h":
            current_mask.copy(),

        "confidence":
            "indisponible",
    }

    if index == 0:
        rows.append({
            "snapshot_index":
                current["snapshot_index"],

            "pass_time_utc":
                current["timestamp"],

            "reference_time_utc":
                pd.NaT,

            "gap_h":
                np.nan,

            "n_previous":
                0,

            "n_current":
                current[
                    "n_observations"
                ],

            "distance_characteristic_m":
                current[
                    "characteristic_distance_m"
                ],

            "coherent_boundary_fraction":
                0.0,

            "median_apparent_speed_kmh":
                np.nan,

            "p90_apparent_speed_kmh":
                np.nan,

            "confidence":
                "indisponible",

            "current_area_km2":
                mask_area_km2(
                    current_mask
                ),

            "projected_1h_area_km2":
                mask_area_km2(
                    current_mask
                ),

            "projected_3h_area_km2":
                mask_area_km2(
                    current_mask
                ),
        })

        projection_records.append(
            projection
        )

        continue

    previous = snapshots[index - 1]

    previous_mask = previous[
        "observed"
    ]

    gap_h = (
        current["timestamp"]
        - previous["timestamp"]
    ).total_seconds() / 3600.0

    characteristic_distance_m = (
        current[
            "characteristic_distance_m"
        ]
    )

    if not np.isfinite(
        characteristic_distance_m
    ):
        characteristic_distance_m = 600.0

    correspondence_radius_m = min(
        2500.0,
        max(
            1000.0,
            1.5
            * characteristic_distance_m,
        ),
    )

    eligible_basic = (
        gap_h > 0
        and gap_h
            <= MAX_REFERENCE_GAP_H
        and previous_mask.any()
        and current_mask.any()
        and current_boundary.any()
        and previous[
            "n_observations"
        ] >= MIN_OBSERVATIONS
        and current[
            "n_observations"
        ] >= MIN_OBSERVATIONS
    )

    coherent_fraction = 0.0
    speed_boundary = np.zeros(
        current_mask.shape,
        dtype=float,
    )

    if eligible_basic:
        distance_to_previous_m = (
            distance_transform_edt(
                ~previous_mask
            )
            * CELL_M
        )

        coherent_boundary = (
            current_boundary
            & (
                distance_to_previous_m
                <= correspondence_radius_m
            )
        )

        coherent_fraction = (
            float(
                coherent_boundary.sum()
            )
            / float(
                current_boundary.sum()
            )
        )

        raw_speed_m_h = np.zeros(
            current_mask.shape,
            dtype=float,
        )

        raw_speed_m_h[
            coherent_boundary
        ] = (
            distance_to_previous_m[
                coherent_boundary
            ]
            / gap_h
        )

        numerator = gaussian_filter(
            raw_speed_m_h,
            sigma=1.5,
            mode="constant",
        )

        denominator = gaussian_filter(
            coherent_boundary.astype(
                float
            ),
            sigma=1.5,
            mode="constant",
        )

        smooth_speed = np.divide(
            numerator,
            denominator,
            out=np.zeros_like(
                numerator
            ),
            where=denominator > 0,
        )

        speed_boundary[
            current_boundary
        ] = smooth_speed[
            current_boundary
        ]

    eligible = (
        eligible_basic
        and coherent_fraction
            >= MIN_COHERENT_BOUNDARY_FRACTION
    )

    confidence = confidence_level(
        eligible,
        gap_h,
        previous["n_observations"],
        current["n_observations"],
        coherent_fraction,
    )

    positive_speeds = speed_boundary[
        current_boundary
        & (speed_boundary > 0)
    ]

    if eligible and len(
        positive_speeds
    ):
        distance_to_boundary_cells, indices = (
            distance_transform_edt(
                ~current_boundary,
                return_indices=True,
            )
        )

        distance_to_boundary_m = (
            distance_to_boundary_cells
            * CELL_M
        )

        nearest_speed_m_h = (
            speed_boundary[
                indices[0],
                indices[1],
            ]
        )

        uncertainty_m = (
            UNCERTAINTY_FACTOR
            * characteristic_distance_m
        )

        for horizon_h in HORIZONS_H:
            projected_distance_m = np.minimum(
                nearest_speed_m_h
                * horizon_h
                * PROJECTION_SPEED_SCALE,
                MAX_PROJECTED_DISTANCE_M,
            )

            projected_mask = (
                current_mask
                | (
                    ~current_mask
                    & (
                        distance_to_boundary_m
                        <= projected_distance_m
                    )
                    & (
                        nearest_speed_m_h > 0
                    )
                )
            )

            uncertainty_mask = (
                current_mask
                | (
                    ~current_mask
                    & (
                        distance_to_boundary_m
                        <= (
                            projected_distance_m
                            + uncertainty_m
                        )
                    )
                    & (
                        nearest_speed_m_h > 0
                    )
                )
            )

            if horizon_h == 1.0:
                projection["plus_1h"] = (
                    projected_mask
                )

                projection[
                    "uncertainty_1h"
                ] = uncertainty_mask

            elif horizon_h == 3.0:
                projection["plus_3h"] = (
                    projected_mask
                )

                projection[
                    "uncertainty_3h"
                ] = uncertainty_mask

    projection["confidence"] = (
        confidence
    )

    rows.append({
        "snapshot_index":
            current["snapshot_index"],

        "pass_time_utc":
            current["timestamp"],

        "reference_time_utc":
            previous["timestamp"],

        "gap_h":
            gap_h,

        "n_previous":
            previous[
                "n_observations"
            ],

        "n_current":
            current[
                "n_observations"
            ],

        "distance_characteristic_m":
            characteristic_distance_m,

        "coherent_boundary_fraction":
            coherent_fraction,

        "median_apparent_speed_kmh":
            (
                float(
                    np.median(
                        positive_speeds
                    )
                )
                / 1000.0
                if len(
                    positive_speeds
                )
                else np.nan
            ),

        "p90_apparent_speed_kmh":
            (
                float(
                    np.percentile(
                        positive_speeds,
                        90,
                    )
                )
                / 1000.0
                if len(
                    positive_speeds
                )
                else np.nan
            ),

        "confidence":
            confidence,

        "current_area_km2":
            mask_area_km2(
                current_mask
            ),

        "projected_1h_area_km2":
            mask_area_km2(
                projection[
                    "plus_1h"
                ]
            ),

        "projected_3h_area_km2":
            mask_area_km2(
                projection[
                    "plus_3h"
                ]
            ),
    })

    projection_records.append(
        projection
    )


result = pd.DataFrame(
    rows
)

result.to_csv(
    OUTPUT_CSV,
    index=False,
)


figure, axes = plt.subplots(
    6,
    4,
    figsize=(15, 21),
    sharex=True,
    sharey=True,
)

axes = axes.ravel()

extent = [
    xmin,
    xmax,
    ymin,
    ymax,
]


for axis, record in zip(
    axes,
    projection_records,
):
    historical = record[
        "historical"
    ]

    current = record[
        "current"
    ]

    projected_1h = record[
        "plus_1h"
    ]

    projected_3h = record[
        "plus_3h"
    ]

    uncertainty_3h = record[
        "uncertainty_3h"
    ]

    if historical.any():
        axis.imshow(
            historical.astype(float),
            extent=extent,
            origin="upper",
            cmap="Greys",
            vmin=0,
            vmax=1,
            alpha=0.16,
        )

    if uncertainty_3h.any():
        axis.contourf(
            uncertainty_3h.astype(float),
            levels=[0.5, 1.5],
            extent=extent,
            origin="upper",
            colors=["#d86cff"],
            alpha=0.08,
        )

    if current.any():
        axis.contour(
            current.astype(float),
            levels=[0.5],
            extent=extent,
            origin="upper",
            colors=["#ff8c1a"],
            linewidths=1.8,
        )

    if projected_1h.any():
        axis.contour(
            projected_1h.astype(float),
            levels=[0.5],
            extent=extent,
            origin="upper",
            colors=["#e53935"],
            linewidths=1.3,
            linestyles="--",
        )


    local_time = record[
        "timestamp"
    ].tz_convert(
        "Europe/Paris"
    )

    matching = result.loc[
        result["snapshot_index"]
        == record["snapshot_index"]
    ].iloc[0]

    axis.set_title(
        local_time.strftime(
            "%d/%m %H:%M"
        )
        + "\n"
        + "cohérence : "
        + str(
            matching["confidence"]
        )
        + " · cohérence : "
        + f"{matching['coherent_boundary_fraction']:.0%}",
        fontsize=8,
    )

    axis.grid(
        alpha=0.15
    )


for axis in axes[
    len(projection_records):
]:
    axis.set_visible(False)


figure.suptitle(
    "Progression FIRMS plausible à court terme — prototype V2\n"
    "orange : observé · rouge tireté : +1 h · "
    "magenta pointillé : +3 h · halo : incertitude",
    fontsize=14,
)

figure.supxlabel(
    "Lambert-93 X (m)"
)

figure.supylabel(
    "Lambert-93 Y (m)"
)

figure.tight_layout(
    rect=[
        0.02,
        0.02,
        0.98,
        0.96,
    ]
)

figure.savefig(
    OUTPUT_PNG,
    dpi=180,
    bbox_inches="tight",
)

plt.close(
    figure
)


print(
    "\n===== FRONT PLAUSIBLE V1 ====="
)

print(
    result["confidence"]
    .value_counts()
    .to_string()
)

print(
    "\nPassages avec projection :",
    int(
        result["confidence"]
        .ne("indisponible")
        .sum()
    ),
    "/",
    len(result),
)

print(
    "\n===== DERNIÈRES PROJECTIONS ====="
)

print(
    result[
        [
            "snapshot_index",
            "pass_time_utc",
            "gap_h",
            "n_current",
            "distance_characteristic_m",
            "coherent_boundary_fraction",
            "median_apparent_speed_kmh",
            "confidence",
            "current_area_km2",
            "projected_1h_area_km2",
            "projected_3h_area_km2",
        ]
    ]
    .tail(10)
    .round(3)
    .to_string(index=False)
)

print("\nÉcrit :", OUTPUT_CSV)
print("Écrit :", OUTPUT_PNG)
