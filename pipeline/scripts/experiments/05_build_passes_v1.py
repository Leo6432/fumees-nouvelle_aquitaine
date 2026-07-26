from pathlib import Path
import pandas as pd

INPUT = Path(
    "data/processed/spatiotemporal_support_causal_v1.csv"
)

OUTPUT = Path(
    "data/processed/spatiotemporal_support_causal_passes_v1.csv"
)

MAX_INTERNAL_GAP_MIN = 15.0

df = pd.read_csv(INPUT)
df["dt_utc"] = pd.to_datetime(
    df["dt_utc"],
    utc=True,
)

df = df.sort_values(
    ["satellite", "instrument", "dt_utc"]
).reset_index(drop=True)

group_columns = [
    "satellite",
    "instrument",
]

gap_min = (
    df.groupby(group_columns)["dt_utc"]
      .diff()
      .dt.total_seconds()
      .div(60)
)

df["_new_pass"] = (
    gap_min.isna()
    | (gap_min > MAX_INTERNAL_GAP_MIN)
)

df["_pass_sequence"] = (
    df.groupby(group_columns)["_new_pass"]
      .cumsum()
      .astype(int)
)

df["pass_id"] = (
    df["satellite"].astype(str)
    + "_"
    + df["instrument"].astype(str)
    + "_"
    + df["_pass_sequence"]
        .astype(str)
        .str.zfill(3)
)

summary = (
    df.groupby(
        ["pass_id", "satellite", "instrument"],
        as_index=False,
    )
    .agg(
        pass_start_utc=("dt_utc", "min"),
        pass_end_utc=("dt_utc", "max"),
        n_observations=("dt_utc", "size"),
    )
)

summary["pass_time_utc"] = (
    summary["pass_start_utc"]
    + (
        summary["pass_end_utc"]
        - summary["pass_start_utc"]
    ) / 2
)

df = df.merge(
    summary[
        ["pass_id", "pass_time_utc"]
    ],
    on="pass_id",
    how="left",
)

df = df.drop(
    columns=[
        "_new_pass",
        "_pass_sequence",
    ]
)

df.to_csv(
    OUTPUT,
    index=False,
)

print(
    f"\nPassages créés : {len(summary)}"
)

print(
    summary[
        [
            "pass_id",
            "pass_start_utc",
            "pass_end_utc",
            "pass_time_utc",
            "n_observations",
        ]
    ]
    .sort_values("pass_time_utc")
    .to_string(index=False)
)

print("\nÉcrit :", OUTPUT)
