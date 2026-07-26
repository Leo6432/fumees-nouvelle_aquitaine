from pathlib import Path
import numpy as np
import pandas as pd

INPUT = Path("data/processed/characteristic_distance_by_pass_v1.csv")
OUTPUT = Path("data/processed/characteristic_distance_regularized_v1.csv")

df = pd.read_csv(INPUT)
df["pass_time_utc"] = pd.to_datetime(df["pass_time_utc"], utc=True)

instrument_reference = {
    "VIIRS": 430.0,
    "MODIS": 1112.0,
}

instrument_bounds = {
    "VIIRS": (300.0, 800.0),
    "MODIS": (700.0, 1500.0),
}

def regularize(row):
    reference = instrument_reference[row["instrument"]]
    lower, upper = instrument_bounds[row["instrument"]]

    raw = row["nn_p75_m"]
    n = int(row["n_observations"])

    if not np.isfinite(raw) or n < 2:
        return reference, 0.0, "instrument_fallback"

    raw = float(np.clip(raw, lower, upper))

    # Rétrécissement vers la valeur instrumentale.
    # À n=20 : poids 0,40 ; à n=100 : 0,77 ; à n=400 : 0,93.
    weight = n / (n + 30.0)

    value = (
        weight * raw
        + (1.0 - weight) * reference
    )

    return value, weight, "pass_shrunk"

result = df.apply(
    lambda row: regularize(row),
    axis=1,
    result_type="expand",
)

result.columns = [
    "distance_regularized_m",
    "pass_weight",
    "distance_source",
]

df = pd.concat([df, result], axis=1)

df["distance_regularized_m"] = (
    df["distance_regularized_m"].round(1)
)

df["pass_weight"] = df["pass_weight"].round(3)

df.to_csv(OUTPUT, index=False)

print(
    df[
        [
            "pass_time_utc",
            "pass_id",
            "instrument",
            "n_observations",
            "nn_p75_m",
            "distance_regularized_m",
            "pass_weight",
            "distance_source",
        ]
    ].to_string(index=False)
)

print("\n===== SYNTHÈSE =====")
print(
    df.groupby("instrument")
      .agg(
          n=("pass_id", "size"),
          median_m=("distance_regularized_m", "median"),
          min_m=("distance_regularized_m", "min"),
          max_m=("distance_regularized_m", "max"),
      )
      .round(1)
      .to_string()
)

print("\nÉcrit :", OUTPUT)
