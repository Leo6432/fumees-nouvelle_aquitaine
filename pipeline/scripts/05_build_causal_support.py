from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

INPUT = Path("data/processed/spatiotemporal_support_v1.csv")
OUTPUT = Path("data/processed/spatiotemporal_support_causal_v1.csv")

TEMPORAL_WINDOW_MIN = 90.0
TEMPORAL_DISTANCE_M = {
    "VIIRS": 1000.0,
    "MODIS": 1750.0,
}

df = pd.read_csv(INPUT)
df["dt_utc"] = pd.to_datetime(df["dt_utc"], utc=True)

for column in ["x", "y"]:
    df[column] = pd.to_numeric(df[column], errors="coerce")

df = df.dropna(subset=["x", "y", "dt_utc"]).copy()
df = df.sort_values("dt_utc").reset_index(drop=True)

if df["same_pass_supported"].dtype != bool:
    df["same_pass_supported"] = (
        df["same_pass_supported"]
        .astype(str)
        .str.lower()
        .eq("true")
    )

coordinates = df[["x", "y"]].to_numpy()
times_ns = df["dt_utc"].astype("int64").to_numpy()

instruments = (
    df["instrument"]
    .fillna("")
    .astype(str)
    .str.upper()
    .to_numpy()
)

tree = cKDTree(coordinates)

maximum_distance = max(
    TEMPORAL_DISTANCE_M.values()
)

candidate_lists = tree.query_ball_point(
    coordinates,
    r=maximum_distance,
)

window_ns = int(
    TEMPORAL_WINDOW_MIN
    * 60
    * 1_000_000_000
)

past_neighbour_count = np.zeros(
    len(df),
    dtype=int,
)

for index, candidates in enumerate(candidate_lists):
    threshold = TEMPORAL_DISTANCE_M.get(
        instruments[index],
        1000.0,
    )

    x0, y0 = coordinates[index]

    for candidate in candidates:
        if candidate == index:
            continue

        time_difference = (
            times_ns[index]
            - times_ns[candidate]
        )

        # Strictement passé : aucune confirmation future.
        if (
            time_difference <= 0
            or time_difference > window_ns
        ):
            continue

        distance = np.hypot(
            coordinates[candidate, 0] - x0,
            coordinates[candidate, 1] - y0,
        )

        if distance <= threshold:
            past_neighbour_count[index] += 1

df["past_temporal_neighbours"] = (
    past_neighbour_count
)

df["past_temporal_supported"] = (
    past_neighbour_count >= 1
)

df["support_class_causal"] = np.select(
    [
        df["same_pass_supported"],
        (
            ~df["same_pass_supported"]
            & df["past_temporal_supported"]
        ),
    ],
    [
        "same_pass",
        "past_confirmed",
    ],
    default="isolated",
)

df["observation_weight_causal"] = (
    df["support_class_causal"]
    .map({
        "same_pass": 1.00,
        "past_confirmed": 0.75,
        "isolated": 0.25,
    })
)

df.to_csv(OUTPUT, index=False)

print("\n===== SUPPORT CAUSAL =====")
print(
    df["support_class_causal"]
    .value_counts()
    .to_string()
)

if "support_class" in df.columns:
    removed = (
        df["support_class"].eq("temporal_only")
        & df["support_class_causal"].eq("isolated")
    ).sum()

    print(
        "\nConfirmations reposant uniquement "
        f"sur le futur supprimées : {removed}"
    )

print("\nÉcrit :", OUTPUT)
