	 python - <<'PY'
from pathlib import Path
import math
import json

from affine import Affine
from pyproj import Transformer
from rasterio.features import shapes as raster_shapes
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scipy.ndimage import (
    distance_transform_edt,
    gaussian_filter,
    label,
)

INPUT = Path(
    "data/processed/spatiotemporal_support_causal_passes_v1.csv"
)

OUTPUT_PNG = Path(
    "data/processed/experiments/fire_progression_passes_v1.png"
)

OUTPUT_STATS = Path(
    "data/processed/experiments/fire_progression_passes_v1.csv"
)

OUTPUT_WEB_GEOJSON = Path(
    "data/processed/experiments/fire_progression_passes_v1.geojson"
)

OUTPUT_WEB_MANIFEST = Path(
    "data/processed/experiments/fire_progression_passes_v1_manifest.json"
)

TO_WGS84 = Transformer.from_crs(
    "EPSG:2154",
    "EPSG:4326",
    always_xy=True,
)

CELL_M = 250.0
PADDING_M = 3000.0

SPATIAL_SIGMA_M = 600.0
HISTORICAL_THRESHOLD = 0.10

ACTIVE_HALF_LIFE_H = 12.0

EVIDENCE_RELATIVE_THRESHOLD = 0.35
MIN_EVIDENCE_ABSOLUTE = 0.04

ADVANCE_DISTANCE_M = 2000.0

NEW_START_CONFIRM_DISTANCE_M = 1500.0
NEW_START_CONFIRM_WINDOW_H = 8.0

MIN_COMPONENT_AREA_KM2 = 0.20

SUPPORT_WEIGHTS = {
    "same_pass": 1.00,
    "past_confirmed": 0.75,
    "isolated": 0.25,
}

HISTORICAL_WEIGHTS = {
    "same_pass": 1.00,
    "past_confirmed": 0.75,
    "isolated": 0.00,
}



def mask_to_wgs84_geometry(mask):
    if not mask.any():
        return None

    raster = np.flipud(
        mask.astype(np.uint8)
    )

    transform = Affine(
        CELL_M,
        0.0,
        xmin,
        0.0,
        -CELL_M,
        ymax,
    )

    geometries = []

    for geometry_mapping, value in raster_shapes(
        raster,
        mask=raster.astype(bool),
        transform=transform,
    ):
        if int(value) != 1:
            continue

        geometry = shape(
            geometry_mapping
        )

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


def minimum_component_cells():
    return max(
        1,
        int(np.ceil(
            MIN_COMPONENT_AREA_KM2
            * 1_000_000.0
            / (CELL_M * CELL_M)
        )),
    )


def remove_small_components(mask):
    labelled, count = label(mask)

    if count == 0:
        return mask

    sizes = np.bincount(
        labelled.ravel()
    )

    valid_labels = np.where(
        sizes >= minimum_component_cells()
    )[0]

    valid_labels = valid_labels[
        valid_labels != 0
    ]

    return np.isin(
        labelled,
        valid_labels,
    )


def split_components(mask):
    labelled, count = label(mask)
    components = []

    if count == 0:
        return components

    sizes = np.bincount(
        labelled.ravel()
    )

    for component_id in range(
        1,
        count + 1,
    ):
        if (
            sizes[component_id]
            < minimum_component_cells()
        ):
            continue

        components.append(
            labelled == component_id
        )

    return components


def mask_area_km2(mask):
    return (
        float(mask.sum())
        * CELL_M
        * CELL_M
        / 1_000_000.0
    )


def mask_components(mask):
    _, count = label(mask)
    return int(count)


def distance_between_masks_m(
    first_mask,
    second_mask,
):
    if (
        not first_mask.any()
        or not second_mask.any()
    ):
        return np.inf

    distance = (
        distance_transform_edt(
            ~first_mask
        )
        * CELL_M
    )

    return float(
        distance[second_mask].min()
    )


# ---------------------------------------------------------
# Données
# ---------------------------------------------------------

df = pd.read_csv(INPUT)

df["pass_time_utc"] = pd.to_datetime(
    df["pass_time_utc"],
    utc=True,
)

for column in [
    "x",
    "y",
    "scan",
    "track",
]:
    df[column] = pd.to_numeric(
        df[column],
        errors="coerce",
    )

df = df.dropna(
    subset=["x", "y", "pass_time_utc"]
).copy()

df["active_weight"] = (
    df["support_class_causal"]
    .map(SUPPORT_WEIGHTS)
    .fillna(0.25)
)

df["historical_support_weight"] = (
    df["support_class_causal"]
    .map(HISTORICAL_WEIGHTS)
    .fillna(0.0)
)

df["pixel_area_km2"] = (
    df["scan"] * df["track"]
)

fallback_area = np.where(
    df["instrument"]
      .astype(str)
      .str.upper()
      .eq("MODIS"),
    1.0,
    0.375 * 0.375,
)

df["pixel_area_km2"] = (
    df["pixel_area_km2"]
    .where(
        df["pixel_area_km2"] > 0,
        fallback_area,
    )
    .fillna(
        pd.Series(
            fallback_area,
            index=df.index,
        )
    )
)

df["active_evidence_weight"] = (
    df["active_weight"]
    * df["pixel_area_km2"]
)

df["historical_evidence_weight"] = (
    df["historical_support_weight"]
    * df["pixel_area_km2"]
)


# ---------------------------------------------------------
# Grille
# ---------------------------------------------------------

xmin = (
    np.floor(
        (df["x"].min() - PADDING_M)
        / CELL_M
    )
    * CELL_M
)

xmax = (
    np.ceil(
        (df["x"].max() + PADDING_M)
        / CELL_M
    )
    * CELL_M
)

ymin = (
    np.floor(
        (df["y"].min() - PADDING_M)
        / CELL_M
    )
    * CELL_M
)

ymax = (
    np.ceil(
        (df["y"].max() + PADDING_M)
        / CELL_M
    )
    * CELL_M
)

nx = int(round(
    (xmax - xmin) / CELL_M
)) + 1

ny = int(round(
    (ymax - ymin) / CELL_M
)) + 1

sigma_cells = (
    SPATIAL_SIGMA_M / CELL_M
)

passages = {
    timestamp: group
    for timestamp, group in df.groupby(
        "pass_time_utc",
        sort=True,
    )
}

times = sorted(passages)


# ---------------------------------------------------------
# Pré-calcul des évidences
# ---------------------------------------------------------

prepared = []

full_historical_field = np.zeros(
    (ny, nx),
    dtype=float,
)

historical_single_pass_max = 0.0

for timestamp in times:
    current = passages[timestamp]

    columns = np.floor(
        (current["x"].to_numpy() - xmin)
        / CELL_M
    ).astype(int)

    rows = np.floor(
        (current["y"].to_numpy() - ymin)
        / CELL_M
    ).astype(int)

    valid = (
        (columns >= 0)
        & (columns < nx)
        & (rows >= 0)
        & (rows < ny)
    )

    active_impulse = np.zeros(
        (ny, nx),
        dtype=float,
    )

    historical_impulse = np.zeros_like(
        active_impulse
    )

    np.add.at(
        active_impulse,
        (
            rows[valid],
            columns[valid],
        ),
        current.loc[
            valid,
            "active_evidence_weight",
        ].to_numpy(),
    )

    np.add.at(
        historical_impulse,
        (
            rows[valid],
            columns[valid],
        ),
        current.loc[
            valid,
            "historical_evidence_weight",
        ].to_numpy(),
    )

    active_evidence = gaussian_filter(
        active_impulse,
        sigma=sigma_cells,
        mode="constant",
    )

    historical_evidence = gaussian_filter(
        historical_impulse,
        sigma=sigma_cells,
        mode="constant",
    )

    full_historical_field += (
        historical_evidence
    )

    historical_single_pass_max = max(
        historical_single_pass_max,
        float(
            historical_evidence.max()
        ),
    )

    prepared.append({
        "pass_time_utc": timestamp,
        "n_observations": len(current),
        "active_evidence":
            active_evidence,
        "historical_evidence":
            historical_evidence,
    })

full_historical_max = float(
    full_historical_field.max()
)


# ---------------------------------------------------------
# Modèle séquentiel
# ---------------------------------------------------------

active_state = np.zeros(
    (ny, nx),
    dtype=float,
)

history_score = np.zeros_like(
    active_state
)

historical_support = np.zeros(
    (ny, nx),
    dtype=bool,
)

pending_candidates = []
candidate_serial = 0

previous_time = None
snapshots = []
stats_rows = []

for snapshot_index, snapshot in enumerate(
    prepared,
    start=1,
):
    timestamp = snapshot["pass_time_utc"]

    if previous_time is None:
        prior_active = np.zeros_like(
            active_state
        )
    else:
        delta_h = (
            timestamp - previous_time
        ).total_seconds() / 3600.0

        decay = (
            2.0 **
            (-delta_h / ACTIVE_HALF_LIFE_H)
        )

        prior_active = (
            active_state * decay
        )

    active_state = (
        prior_active
        + snapshot["active_evidence"]
    )

    active_maximum = float(
        active_state.max()
    )

    evidence_absolute = (
        snapshot["historical_evidence"]
        / historical_single_pass_max
        if historical_single_pass_max > 0
        else snapshot[
            "historical_evidence"
        ]
    )

    evidence_maximum = float(
        evidence_absolute.max()
    )

    evidence_threshold = max(
        MIN_EVIDENCE_ABSOLUTE,
        EVIDENCE_RELATIVE_THRESHOLD
        * evidence_maximum,
    )

    robust_evidence = (
        evidence_absolute
        >= evidence_threshold
    )

    robust_evidence = (
        remove_small_components(
            robust_evidence
        )
    )

    previous_support = (
        historical_support.copy()
    )

    expired_now = 0
    remaining_candidates = []

    for candidate in pending_candidates:
        age_h = (
            timestamp
            - candidate["last_time"]
        ).total_seconds() / 3600.0

        if (
            age_h
            > NEW_START_CONFIRM_WINDOW_H
        ):
            expired_now += 1
        else:
            remaining_candidates.append(
                candidate
            )

    pending_candidates = (
        remaining_candidates
    )

    if snapshot_index == 1:
        persistence = np.zeros_like(
            robust_evidence
        )

        advance = np.zeros_like(
            robust_evidence
        )

        provisional_new = np.zeros_like(
            robust_evidence
        )

        confirmed_new = (
            robust_evidence.copy()
        )

        history_score += (
            snapshot[
                "historical_evidence"
            ]
            * robust_evidence
        )

    else:
        persistence = (
            robust_evidence
            & previous_support
        )

        if previous_support.any():
            distance_to_history_m = (
                distance_transform_edt(
                    ~previous_support
                )
                * CELL_M
            )

            outside_history = (
                robust_evidence
                & ~previous_support
            )

            advance = (
                outside_history
                & (
                    distance_to_history_m
                    <= ADVANCE_DISTANCE_M
                )
            )

            provisional_source = (
                outside_history
                & (
                    distance_to_history_m
                    > ADVANCE_DISTANCE_M
                )
            )

        else:
            advance = np.zeros_like(
                robust_evidence
            )

            provisional_source = (
                robust_evidence.copy()
            )

        persistence = remove_small_components(
            persistence
        )

        advance = remove_small_components(
            advance
        )

        history_score += (
            snapshot[
                "historical_evidence"
            ]
            * (
                persistence
                | advance
            )
        )

        provisional_new = np.zeros_like(
            robust_evidence
        )

        confirmed_new = np.zeros_like(
            robust_evidence
        )

        current_components = (
            split_components(
                provisional_source
            )
        )

        for current_component in current_components:
            best_index = None
            best_distance = np.inf

            for index, candidate in enumerate(
                pending_candidates
            ):
                time_difference_h = (
                    timestamp
                    - candidate[
                        "last_time"
                    ]
                ).total_seconds() / 3600.0

                if (
                    time_difference_h <= 0
                    or time_difference_h
                    > NEW_START_CONFIRM_WINDOW_H
                ):
                    continue

                distance_m = (
                    distance_between_masks_m(
                        candidate["mask"],
                        current_component,
                    )
                )

                if (
                    distance_m
                    < best_distance
                ):
                    best_distance = (
                        distance_m
                    )

                    best_index = index

            if (
                best_index is not None
                and best_distance
                <= NEW_START_CONFIRM_DISTANCE_M
            ):
                candidate = (
                    pending_candidates.pop(
                        best_index
                    )
                )

                promoted_mask = (
                    candidate["mask"]
                    | current_component
                )

                confirmed_new |= (
                    promoted_mask
                )

                history_score += (
                    candidate[
                        "evidence"
                    ]
                )

                history_score += (
                    snapshot[
                        "historical_evidence"
                    ]
                    * current_component
                )

            else:
                candidate_serial += 1

                candidate_evidence = (
                    snapshot[
                        "historical_evidence"
                    ]
                    * current_component
                )

                pending_candidates.append({
                    "candidate_id":
                        candidate_serial,

                    "first_time":
                        timestamp,

                    "last_time":
                        timestamp,

                    "mask":
                        current_component.copy(),

                    "evidence":
                        candidate_evidence.copy(),
                })

                provisional_new |= (
                    current_component
                )

    historical_support |= (
        persistence
        | advance
        | confirmed_new
    )

    historical_support = (
        remove_small_components(
            historical_support
        )
    )

    stats_rows.append({
        "snapshot_index":
            snapshot_index,

        "pass_time_utc":
            timestamp,

        "n_observations":
            snapshot[
                "n_observations"
            ],

        "persistence_area_km2":
            mask_area_km2(
                persistence
            ),

        "advance_area_km2":
            mask_area_km2(
                advance
            ),

        "provisional_new_area_km2":
            mask_area_km2(
                provisional_new
            ),

        "confirmed_new_area_km2":
            mask_area_km2(
                confirmed_new
            ),

        "pending_candidates":
            len(
                pending_candidates
            ),

        "expired_candidates_now":
            expired_now,

        "historical_support_area_km2":
            mask_area_km2(
                historical_support
            ),

        "historical_components":
            mask_components(
                historical_support
            ),
    })

    snapshots.append({
        "pass_time_utc":
            timestamp,

        "active_state":
            active_state.copy(),

        "historical_support":
            historical_support.copy(),

        "persistence":
            persistence.copy(),

        "advance":
            advance.copy(),

        "provisional_new":
            provisional_new.copy(),

        "confirmed_new":
            confirmed_new.copy(),
    })

    previous_time = timestamp


# ---------------------------------------------------------
# Résultats
# ---------------------------------------------------------

stats = pd.DataFrame(
    stats_rows
)

stats.to_csv(
    OUTPUT_STATS,
    index=False,
)

# ---------------------------------------------------------
# Export temporel web — GeoJSON WGS84
# ---------------------------------------------------------

OUTPUT_WEB_GEOJSON.parent.mkdir(
    parents=True,
    exist_ok=True,
)

features = []
manifest_snapshots = []

category_labels = {
    "historical_support":
        "Support historique confirmé",
    "observed_front":
        "Activité observée au passage",
    "persistence":
        "Persistance ou réactivation",
    "advance":
        "Avancée observée",
    "provisional_new":
        "Nouveau départ provisoire",
    "confirmed_new":
        "Nouveau départ confirmé",
}

for snapshot_index, snapshot in enumerate(
    snapshots,
    start=1,
):
    observed_front = (
        snapshot["persistence"]
        | snapshot["advance"]
        | snapshot["provisional_new"]
        | snapshot["confirmed_new"]
    )

    categories = {
        "historical_support":
            snapshot["historical_support"],
        "observed_front":
            observed_front,
        "persistence":
            snapshot["persistence"],
        "advance":
            snapshot["advance"],
        "provisional_new":
            snapshot["provisional_new"],
        "confirmed_new":
            snapshot["confirmed_new"],
    }

    timestamp = snapshot["pass_time_utc"]
    local_time = timestamp.tz_convert(
        "Europe/Paris"
    )

    snapshot_categories = []

    for category, mask in categories.items():
        geometry = mask_to_wgs84_geometry(
            mask
        )

        if geometry is None:
            continue

        area_km2 = mask_area_km2(
            mask
        )

        features.append({
            "type": "Feature",
            "properties": {
                "snapshot_index":
                    snapshot_index,
                "pass_time_utc":
                    timestamp.isoformat(),
                "dt_local":
                    local_time.isoformat(),
                "category":
                    category,
                "label":
                    category_labels[category],
                "area_km2":
                    round(area_km2, 3),
                "is_latest":
                    snapshot_index
                    == len(snapshots),
                "model_version":
                    "fire_progression_v4",
            },
            "geometry":
                mapping(geometry),
        })

        snapshot_categories.append({
            "category": category,
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
        "categories":
            snapshot_categories,
    })

geojson = {
    "type": "FeatureCollection",
    "name":
        "fire_progression_timeseries_v4",
    "features":
        features,
}

manifest = {
    "model_version":
        "fire_progression_v4",
    "crs":
        "EPSG:4326",
    "description":
        "Reconstitution causale de l’évolution "
        "spatio-temporelle de l’activité thermique FIRMS.",
    "parameters": {
        "cell_m":
            CELL_M,
        "spatial_sigma_m":
            SPATIAL_SIGMA_M,
        "active_half_life_h":
            ACTIVE_HALF_LIFE_H,
        "advance_distance_m":
            ADVANCE_DISTANCE_M,
        "new_start_confirmation_distance_m":
            NEW_START_CONFIRM_DISTANCE_M,
        "new_start_confirmation_window_h":
            NEW_START_CONFIRM_WINDOW_H,
    },
    "snapshots":
        manifest_snapshots,
}

OUTPUT_WEB_GEOJSON.write_text(
    json.dumps(
        geojson,
        ensure_ascii=False,
        separators=(",", ":"),
    )
)

OUTPUT_WEB_MANIFEST.write_text(
    json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    )
)

print(
    "\nGeoJSON web :",
    len(features),
    "entités pour",
    len(snapshots),
    "snapshots",
)

print(
    "\n===== PROGRESSION AVEC CONFIRMATION DES NOUVEAUX DÉPARTS ====="
)

print(
    stats[
        [
            "snapshot_index",
            "pass_time_utc",
            "n_observations",
            "persistence_area_km2",
            "advance_area_km2",
            "provisional_new_area_km2",
            "confirmed_new_area_km2",
            "pending_candidates",
            "expired_candidates_now",
            "historical_support_area_km2",
            "historical_components",
        ]
    ]
    .round(3)
    .to_string(index=False)
)


# ---------------------------------------------------------
# Planche
# ---------------------------------------------------------

historical_active_max = max(
    float(
        snapshot["active_state"].max()
    )
    for snapshot in snapshots
)

if len(snapshots) <= 16:
    selected_indices = list(
        range(len(snapshots))
    )
else:
    selected_indices = sorted(
        set(
            np.linspace(
                0,
                len(snapshots) - 1,
                16,
            )
            .round()
            .astype(int)
        )
    )

n_panels = len(selected_indices)
ncols = 4
nrows = math.ceil(
    n_panels / ncols
)

fig, axes = plt.subplots(
    nrows,
    ncols,
    figsize=(16, 4 * nrows),
    sharex=True,
    sharey=True,
    squeeze=False,
)

extent = [
    xmin,
    xmax,
    ymin,
    ymax,
]

x_coordinates = (
    xmin
    + np.arange(nx)
    * CELL_M
)

y_coordinates = (
    ymin
    + np.arange(ny)
    * CELL_M
)

for panel_index, selected_index in enumerate(
    selected_indices
):
    ax = axes.flat[
        panel_index
    ]

    snapshot = snapshots[
        selected_index
    ]

    active_absolute = (
        snapshot["active_state"]
        / historical_active_max
        if historical_active_max > 0
        else snapshot["active_state"]
    )

    ax.imshow(
        active_absolute,
        origin="lower",
        extent=extent,
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        alpha=0.85,
    )

    styles = [
        (
            snapshot[
                "historical_support"
            ],
            "grey",
            "dotted",
            0.8,
        ),
        (
            snapshot[
                "persistence"
            ],
            "black",
            "solid",
            1.2,
        ),
        (
            snapshot[
                "advance"
            ],
            "darkorange",
            "solid",
            2.0,
        ),
        (
            snapshot[
                "provisional_new"
            ],
            "red",
            "dashed",
            2.0,
        ),
        (
            snapshot[
                "confirmed_new"
            ],
            "magenta",
            "solid",
            2.4,
        ),
    ]

    for (
        mask,
        color,
        linestyle,
        linewidth,
    ) in styles:
        if not mask.any():
            continue

        ax.contour(
            x_coordinates,
            y_coordinates,
            mask.astype(float),
            levels=[0.5],
            colors=[color],
            linestyles=[linestyle],
            linewidths=[linewidth],
        )

    current = stats.iloc[
        selected_index
    ]

    local_time = (
        snapshot["pass_time_utc"]
        .tz_convert(
            "Europe/Paris"
        )
    )

    ax.set_title(
        local_time.strftime(
            "%d/%m %H:%M"
        )
        + "\n"
        + "avance="
        + f"{current['advance_area_km2']:.1f}"
        + " · provisoire="
        + f"{current['provisional_new_area_km2']:.1f}"
        + " · confirmé="
        + f"{current['confirmed_new_area_km2']:.1f}"
        + " km²",
        fontsize=9,
    )

    ax.set_aspect(
        "equal",
        adjustable="box",
    )

    ax.grid(alpha=0.2)

for panel_index in range(
    n_panels,
    nrows * ncols,
):
    axes.flat[
        panel_index
    ].axis("off")

fig.suptitle(
    "Évolution spatio-temporelle FIRMS\n"
    "gris : historique · noir : persistance · orange : avancée · "
    "rouge : départ provisoire · magenta : départ confirmé",
    fontsize=15,
)

fig.supxlabel(
    "Lambert-93 X (m)"
)

fig.supylabel(
    "Lambert-93 Y (m)"
)

fig.tight_layout(
    rect=[
        0.02,
        0.02,
        0.98,
        0.95,
    ]
)

fig.savefig(
    OUTPUT_PNG,
    dpi=180,
    bbox_inches="tight",
)

plt.close(fig)

print("\nÉcrit :", OUTPUT_STATS)
print("Écrit :", OUTPUT_PNG)
PY

