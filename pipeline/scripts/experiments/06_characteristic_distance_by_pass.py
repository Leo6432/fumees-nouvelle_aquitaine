from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

INPUT = Path(
    "data/processed/spatiotemporal_support_causal_passes_v1.csv"
)
OUTPUT = Path(
    "data/processed/characteristic_distance_by_pass_v1.csv"
)

df = pd.read_csv(INPUT)
df["pass_time_utc"] = pd.to_datetime(
    df["pass_time_utc"],
    utc=True,
)

rows = []

for pass_id, group in df.groupby("pass_id", sort=False):
    group = group.dropna(subset=["x", "y"]).copy()
    coordinates = group[["x", "y"]].to_numpy(float)

    if len(coordinates) >= 2:
        tree = cKDTree(coordinates)
        distances, _ = tree.query(coordinates, k=2)
        nearest = distances[:, 1]
    else:
        nearest = np.array([], dtype=float)

    rows.append({
        "pass_id": pass_id,
        "pass_time_utc": group["pass_time_utc"].iloc[0],
        "satellite": group["satellite"].iloc[0],
        "instrument": group["instrument"].iloc[0],
        "n_observations": len(group),
        "nn_mean_m": (
            float(np.mean(nearest))
            if len(nearest) else np.nan
        ),
        "nn_median_m": (
            float(np.median(nearest))
            if len(nearest) else np.nan
        ),
        "nn_p75_m": (
            float(np.percentile(nearest, 75))
            if len(nearest) else np.nan
        ),
        "nn_p90_m": (
            float(np.percentile(nearest, 90))
            if len(nearest) else np.nan
        ),
    })

result = (
    pd.DataFrame(rows)
    .sort_values("pass_time_utc")
    .reset_index(drop=True)
)

result["gap_previous_h"] = (
    result["pass_time_utc"]
    .diff()
    .dt.total_seconds()
    .div(3600)
)

result["distance_characteristic_m"] = (
    result["nn_p75_m"]
    .clip(lower=250, upper=2000)
)

result.to_csv(OUTPUT, index=False)

print("\n===== DISTANCE CARACTÉRISTIQUE PAR PASSAGE =====")
print(
    result[
        [
            "pass_time_utc",
            "pass_id",
            "n_observations",
            "gap_previous_h",
            "nn_mean_m",
            "nn_median_m",
            "nn_p75_m",
            "nn_p90_m",
            "distance_characteristic_m",
        ]
    ].round(1).to_string(index=False)
)

print("\n===== SYNTHÈSE PAR INSTRUMENT =====")
print(
    result.groupby("instrument")
    .agg(
        n_passages=("pass_id", "size"),
        median_nn_m=("nn_median_m", "median"),
        median_p75_m=("nn_p75_m", "median"),
        p90_des_p75_m=("nn_p75_m", lambda x: x.quantile(.9)),
    )
    .round(1)
    .to_string()
)

print("\nÉcrit :", OUTPUT)
