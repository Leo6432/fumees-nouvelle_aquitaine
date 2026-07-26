from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from common import fires_to_metric, load_config


INPUT = Path(
    os.environ.get(
        "SUPPORT_INPUT",
        "data/raw/firms_detections.csv",
    )
)

OUTPUT = Path(
    os.environ.get(
        "SUPPORT_OUTPUT",
        "data/processed/spatiotemporal_support_v1.csv",
    )
)

SAME_PASS_DISTANCE_M = {
    "VIIRS": 750.0,
    "MODIS": 1500.0,
}

TEMPORAL_DISTANCE_M = {
    "VIIRS": 1000.0,
    "MODIS": 1750.0,
}

TEMPORAL_WINDOW_MIN = 90.0


def normalise_instrument(value: object) -> str:
    instrument = str(value or "").strip().upper()

    if "VIIRS" in instrument:
        return "VIIRS"

    if "MODIS" in instrument:
        return "MODIS"

    return instrument


def main() -> None:
    cfg = load_config()

    df = pd.read_csv(INPUT)

    if "dt_utc" not in df.columns:
        acquisition_time = (
            df["acq_time"]
            .fillna(0)
            .astype(int)
            .astype(str)
            .str.zfill(4)
        )

        df["dt_utc"] = pd.to_datetime(
            df["acq_date"].astype(str)
            + " "
            + acquisition_time.str[:2]
            + ":"
            + acquisition_time.str[2:]
            + ":00",
            utc=True,
            errors="coerce",
        )
    else:
        df["dt_utc"] = pd.to_datetime(
            df["dt_utc"],
            utc=True,
            errors="coerce",
        )

    numeric_columns = [
        "lat",
        "lon",
        "hours_ago",
        "frp",
        "scan",
        "track",
        "acq_time",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    df = df.dropna(
        subset=[
            "lat",
            "lon",
            "dt_utc",
        ]
    ).copy()

    df = fires_to_metric(
        df,
        cfg,
    )

    instruments = (
        df["instrument"]
        .map(normalise_instrument)
        .to_numpy()
    )

    coordinates = df[
        ["x", "y"]
    ].to_numpy()

    times_ns = (
        df["dt_utc"]
        .astype("int64")
        .to_numpy()
    )

    same_pass_neighbours = np.zeros(
        len(df),
        dtype=int,
    )

    # Passage exact : même horodatage satellitaire.
    for _, indexes in df.groupby(
        "dt_utc",
        sort=False,
    ).groups.items():
        indexes = np.asarray(
            list(indexes),
            dtype=int,
        )

        if len(indexes) < 2:
            continue

        pass_coordinates = coordinates[
            indexes
        ]

        tree = cKDTree(
            pass_coordinates
        )

        for local_index, global_index in enumerate(
            indexes
        ):
            radius = SAME_PASS_DISTANCE_M.get(
                instruments[global_index],
                750.0,
            )

            neighbours = tree.query_ball_point(
                pass_coordinates[local_index],
                r=radius,
            )

            same_pass_neighbours[
                global_index
            ] = max(
                0,
                len(neighbours) - 1,
            )

    maximum_temporal_distance = max(
        TEMPORAL_DISTANCE_M.values()
    )

    global_tree = cKDTree(
        coordinates
    )

    candidate_lists = (
        global_tree.query_ball_point(
            coordinates,
            r=maximum_temporal_distance,
        )
    )

    temporal_neighbours = np.zeros(
        len(df),
        dtype=int,
    )

    temporal_window_ns = int(
        TEMPORAL_WINDOW_MIN
        * 60
        * 1_000_000_000
    )

    for index, candidates in enumerate(
        candidate_lists
    ):
        radius = TEMPORAL_DISTANCE_M.get(
            instruments[index],
            1000.0,
        )

        x0, y0 = coordinates[index]

        for candidate in candidates:
            if candidate == index:
                continue

            time_difference = abs(
                times_ns[index]
                - times_ns[candidate]
            )

            # Les voisins du même passage sont traités séparément.
            if (
                time_difference == 0
                or time_difference > temporal_window_ns
            ):
                continue

            distance = np.hypot(
                coordinates[candidate, 0] - x0,
                coordinates[candidate, 1] - y0,
            )

            if distance <= radius:
                temporal_neighbours[index] += 1

    df["same_pass_neighbours"] = (
        same_pass_neighbours
    )

    df["temporal_neighbours"] = (
        temporal_neighbours
    )

    df["same_pass_supported"] = (
        df["same_pass_neighbours"] >= 1
    )

    df["temporal_supported"] = (
        df["temporal_neighbours"] >= 1
    )

    df["support_class"] = np.select(
        [
            df["same_pass_supported"],
            (
                ~df["same_pass_supported"]
                & df["temporal_supported"]
            ),
        ],
        [
            "same_pass",
            "temporal_only",
        ],
        default="isolated",
    )

    df["observation_weight"] = (
        df["support_class"]
        .map({
            "same_pass": 1.00,
            "temporal_only": 0.75,
            "isolated": 0.25,
        })
    )

    output_columns = [
        "lat",
        "lon",
        "dt_utc",
        "hours_ago",
        "frp",
        "scan",
        "track",
        "source",
        "acq_date",
        "acq_time",
        "confidence",
        "satellite",
        "instrument",
        "x",
        "y",
        "same_pass_supported",
        "temporal_supported",
        "same_pass_neighbours",
        "temporal_neighbours",
        "support_class",
        "observation_weight",
    ]

    missing = [
        column
        for column in output_columns
        if column not in df.columns
    ]

    if missing:
        raise RuntimeError(
            "Colonnes absentes : "
            + ", ".join(missing)
        )

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df[output_columns].to_csv(
        OUTPUT,
        index=False,
    )

    print("===== SUPPORT SPATIO-TEMPOREL =====")
    print(
        df["support_class"]
        .value_counts()
        .to_string()
    )
    print("\nÉcrit :", OUTPUT)


if __name__ == "__main__":
    main()
