"""Audit géométrique de l'export web parallèle terre/eau.

Comparaison entité par entité entre :
- l'export web actuel non masqué ;
- l'export parallèle masqué par ESA WorldCover.

Le script vérifie :
- la concordance des passages et des entités ;
- les surfaces retirées et éventuellement ajoutées ;
- la validité des géométries ;
- les surfaces déclarées dans les propriétés ;
- le poids des fichiers ;
- les changements par catégorie.

Aucun fichier de production n'est modifié.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform


OLD_GEOJSON = Path(
    "pipeline/data/web/"
    "fire_progression_arrival_v1.geojson"
)

OLD_MANIFEST = Path(
    "pipeline/data/web/"
    "fire_progression_arrival_v1_manifest.json"
)

NEW_GEOJSON = Path(
    "pipeline/data/processed/experiments/"
    "land_water_mask_v1/parallel_export/"
    "fire_progression_arrival_landmask_v3.geojson"
)

NEW_MANIFEST = Path(
    "pipeline/data/processed/experiments/"
    "land_water_mask_v1/parallel_export/"
    "fire_progression_arrival_landmask_v3_manifest.json"
)

OUTPUT_DIR = Path(
    "pipeline/data/processed/experiments/"
    "land_water_mask_v1/parallel_export_audit_v3"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

TO_L93 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:2154",
    always_xy=True,
)

DIAGNOSTIC_CATEGORIES = [
    "firms_extent_snapshot",
    "historical_support",
    "observed_front",
    "plausible_front_1h",
]


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def feature_key(feature: dict) -> tuple[str, int]:
    properties = feature.get("properties", {})
    category = str(properties.get("category"))

    if category == "arrival_step":
        index = properties.get(
            "arrival_snapshot_index"
        )
    else:
        index = properties.get("snapshot_index")

    if index is None:
        raise RuntimeError(
            "Indice absent pour une entité de catégorie "
            f"{category!r}."
        )

    return category, int(index)


def build_index(
    feature_collection: dict,
) -> dict[tuple[str, int], dict]:
    index = {}

    for feature in feature_collection.get(
        "features",
        [],
    ):
        key = feature_key(feature)

        if key in index:
            raise RuntimeError(
                f"Clé dupliquée : {key}"
            )

        index[key] = feature

    return index


def metric_geometry(feature: dict):
    geometry = shape(feature["geometry"])

    if geometry.is_empty:
        return geometry

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    geometry = shapely_transform(
        TO_L93.transform,
        geometry,
    )

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    return geometry


def coordinate_count(geometry) -> int:
    if geometry is None or geometry.is_empty:
        return 0

    if geometry.geom_type == "Polygon":
        count = len(geometry.exterior.coords)

        for ring in geometry.interiors:
            count += len(ring.coords)

        return count

    if geometry.geom_type == "MultiPolygon":
        return sum(
            coordinate_count(part)
            for part in geometry.geoms
        )

    if hasattr(geometry, "geoms"):
        return sum(
            coordinate_count(part)
            for part in geometry.geoms
        )

    return 0


def declared_area(feature: dict) -> float:
    value = feature.get(
        "properties",
        {},
    ).get("area_km2")

    if value is None:
        return np.nan

    return float(value)


old_geojson = read_json(OLD_GEOJSON)
new_geojson = read_json(NEW_GEOJSON)

old_manifest = read_json(OLD_MANIFEST)
new_manifest = read_json(NEW_MANIFEST)

old_snapshot_times = [
    snapshot.get("pass_time_utc")
    for snapshot in old_manifest.get(
        "snapshots",
        [],
    )
]

new_snapshot_times = [
    snapshot.get("pass_time_utc")
    for snapshot in new_manifest.get(
        "snapshots",
        [],
    )
]

print("===== PRÉCONTRÔLE TEMPOREL =====")
print(
    "Passages ancien :",
    len(old_snapshot_times),
)
print(
    "Passages nouveau:",
    len(new_snapshot_times),
)
print(
    "Chronologies identiques :",
    old_snapshot_times == new_snapshot_times,
)

if old_snapshot_times != new_snapshot_times:
    raise RuntimeError(
        "Les deux exports ne reposent pas sur la même "
        "chronologie. Comparaison interrompue."
    )


old_index = build_index(old_geojson)
new_index = build_index(new_geojson)

old_keys = set(old_index)
new_keys = set(new_index)

common_keys = sorted(
    old_keys & new_keys,
    key=lambda item: (
        item[0],
        item[1],
    ),
)

missing_in_new = sorted(
    old_keys - new_keys
)

missing_in_old = sorted(
    new_keys - old_keys
)

print()
print("===== CONCORDANCE DES ENTITÉS =====")
print("Anciennes entités :", len(old_index))
print("Nouvelles entités :", len(new_index))
print("Clés communes     :", len(common_keys))
print("Absentes nouveau  :", len(missing_in_new))
print("Absentes ancien   :", len(missing_in_old))


rows = []

for category, index in common_keys:
    old_feature = old_index[
        (category, index)
    ]

    new_feature = new_index[
        (category, index)
    ]

    old_geometry = metric_geometry(
        old_feature
    )

    new_geometry = metric_geometry(
        new_feature
    )

    old_area_km2 = (
        old_geometry.area
        / 1_000_000.0
    )

    new_area_km2 = (
        new_geometry.area
        / 1_000_000.0
    )

    removed_geometry = old_geometry.difference(
        new_geometry
    )

    added_geometry = new_geometry.difference(
        old_geometry
    )

    shared_geometry = old_geometry.intersection(
        new_geometry
    )

    removed_area_km2 = (
        removed_geometry.area
        / 1_000_000.0
    )

    added_area_km2 = (
        added_geometry.area
        / 1_000_000.0
    )

    shared_area_km2 = (
        shared_geometry.area
        / 1_000_000.0
    )

    old_declared_area_km2 = declared_area(
        old_feature
    )

    new_declared_area_km2 = declared_area(
        new_feature
    )

    rows.append({
        "category":
            category,

        "feature_index":
            index,

        "old_area_km2":
            old_area_km2,

        "new_area_km2":
            new_area_km2,

        "net_change_km2":
            new_area_km2
            - old_area_km2,

        "net_change_percent":
            (
                100.0
                * (
                    new_area_km2
                    / old_area_km2
                    - 1.0
                )
                if old_area_km2 > 0
                else np.nan
            ),

        "removed_area_km2":
            removed_area_km2,

        "removed_percent":
            (
                100.0
                * removed_area_km2
                / old_area_km2
                if old_area_km2 > 0
                else np.nan
            ),

        "added_area_km2":
            added_area_km2,

        "added_percent_of_new":
            (
                100.0
                * added_area_km2
                / new_area_km2
                if new_area_km2 > 0
                else np.nan
            ),

        "shared_area_km2":
            shared_area_km2,

        "old_declared_area_km2":
            old_declared_area_km2,

        "new_declared_area_km2":
            new_declared_area_km2,

        "old_declared_minus_geometry_km2":
            (
                old_declared_area_km2
                - old_area_km2
                if np.isfinite(
                    old_declared_area_km2
                )
                else np.nan
            ),

        "new_declared_minus_geometry_km2":
            (
                new_declared_area_km2
                - new_area_km2
                if np.isfinite(
                    new_declared_area_km2
                )
                else np.nan
            ),

        "old_valid":
            bool(old_geometry.is_valid),

        "new_valid":
            bool(new_geometry.is_valid),

        "old_empty":
            bool(old_geometry.is_empty),

        "new_empty":
            bool(new_geometry.is_empty),

        "old_coordinate_count":
            coordinate_count(old_geometry),

        "new_coordinate_count":
            coordinate_count(new_geometry),
    })


comparison = pd.DataFrame(rows)

feature_csv = (
    OUTPUT_DIR
    / "landmask_feature_comparison_v3.csv"
)

comparison.to_csv(
    feature_csv,
    index=False,
)


category_summary = (
    comparison.groupby(
        "category",
        as_index=False,
    )
    .agg(
        feature_count=(
            "feature_index",
            "count",
        ),

        old_area_sum_km2=(
            "old_area_km2",
            "sum",
        ),

        new_area_sum_km2=(
            "new_area_km2",
            "sum",
        ),

        net_change_sum_km2=(
            "net_change_km2",
            "sum",
        ),

        removed_area_sum_km2=(
            "removed_area_km2",
            "sum",
        ),

        added_area_sum_km2=(
            "added_area_km2",
            "sum",
        ),

        maximum_added_area_km2=(
            "added_area_km2",
            "max",
        ),

        maximum_removed_percent=(
            "removed_percent",
            "max",
        ),

        old_coordinates_sum=(
            "old_coordinate_count",
            "sum",
        ),

        new_coordinates_sum=(
            "new_coordinate_count",
            "sum",
        ),
    )
)

category_summary[
    "coordinate_change_percent"
] = (
    100.0
    * (
        category_summary[
            "new_coordinates_sum"
        ]
        / category_summary[
            "old_coordinates_sum"
        ]
        - 1.0
    )
)

category_csv = (
    OUTPUT_DIR
    / "landmask_category_summary_v3.csv"
)

category_summary.to_csv(
    category_csv,
    index=False,
)


# ---------------------------------------------------------------
# Alertes sur les éventuelles extensions géométriques.
# ---------------------------------------------------------------

added_alerts = comparison.loc[
    comparison["added_area_km2"] > 0.01
].sort_values(
    "added_area_km2",
    ascending=False,
)

added_alerts_path = (
    OUTPUT_DIR
    / "landmask_added_area_alerts_v3.csv"
)

added_alerts.to_csv(
    added_alerts_path,
    index=False,
)


# ---------------------------------------------------------------
# Graphique des changements cumulés par catégorie.
# Les sommes concernent les entités temporelles, pas une union
# spatiale unique.
# ---------------------------------------------------------------

plot_summary = category_summary.copy()

positions = np.arange(
    len(plot_summary)
)

width = 0.38

figure, axis = plt.subplots(
    figsize=(11, 6),
    constrained_layout=True,
)

axis.bar(
    positions - width / 2,
    plot_summary[
        "removed_area_sum_km2"
    ],
    width=width,
    label="Surface retirée",
)

axis.bar(
    positions + width / 2,
    plot_summary[
        "added_area_sum_km2"
    ],
    width=width,
    label="Surface ajoutée",
)

axis.set_xticks(
    positions,
    plot_summary["category"],
    rotation=30,
    ha="right",
)

axis.set_ylabel(
    "Somme sur les entités temporelles (km²)"
)

axis.set_title(
    "Effet géométrique du masque terre/eau par catégorie"
)

axis.grid(
    axis="y",
    linewidth=0.4,
    alpha=0.4,
)

axis.legend()

category_plot = (
    OUTPUT_DIR
    / "landmask_category_area_changes_v3.png"
)

figure.savefig(
    category_plot,
    dpi=180,
)

plt.close(figure)


# ---------------------------------------------------------------
# Diagnostic cartographique des dernières entités.
# ---------------------------------------------------------------

figure, axes = plt.subplots(
    2,
    2,
    figsize=(15, 13),
    constrained_layout=True,
)

axes = axes.ravel()

for axis, category in zip(
    axes,
    DIAGNOSTIC_CATEGORIES,
):
    category_keys = [
        key
        for key in common_keys
        if key[0] == category
    ]

    if not category_keys:
        axis.set_title(
            f"{category}\nabsent"
        )
        axis.axis("off")
        continue

    latest_key = max(
        category_keys,
        key=lambda item: item[1],
    )

    old_geometry = metric_geometry(
        old_index[latest_key]
    )

    new_geometry = metric_geometry(
        new_index[latest_key]
    )

    removed_geometry = old_geometry.difference(
        new_geometry
    )

    added_geometry = new_geometry.difference(
        old_geometry
    )

    if not new_geometry.is_empty:
        gpd.GeoSeries(
            [new_geometry],
            crs="EPSG:2154",
        ).plot(
            ax=axis,
            alpha=0.45,
        )

    if not removed_geometry.is_empty:
        gpd.GeoSeries(
            [removed_geometry],
            crs="EPSG:2154",
        ).plot(
            ax=axis,
            alpha=0.8,
        )

    if not added_geometry.is_empty:
        gpd.GeoSeries(
            [added_geometry],
            crs="EPSG:2154",
        ).plot(
            ax=axis,
            alpha=0.9,
        )

    if not old_geometry.is_empty:
        gpd.GeoSeries(
            [old_geometry],
            crs="EPSG:2154",
        ).boundary.plot(
            ax=axis,
            linewidth=0.8,
        )

    matching_row = comparison.loc[
        (
            comparison["category"]
            == latest_key[0]
        )
        & (
            comparison["feature_index"]
            == latest_key[1]
        )
    ].iloc[0]

    axis.set_title(
        f"{category} — indice {latest_key[1]}\n"
        f"retiré : "
        f"{matching_row['removed_area_km2']:.3f} km² ; "
        f"ajouté : "
        f"{matching_row['added_area_km2']:.3f} km²"
    )

    axis.set_aspect("equal")
    axis.set_xlabel("X Lambert-93 (m)")
    axis.set_ylabel("Y Lambert-93 (m)")
    axis.grid(
        linewidth=0.3,
        alpha=0.35,
    )


legend_items = [
    Patch(
        alpha=0.45,
        label="Nouvelle géométrie",
    ),
    Patch(
        alpha=0.8,
        label="Surface retirée",
    ),
    Patch(
        alpha=0.9,
        label="Surface ajoutée",
    ),
    Line2D(
        [0],
        [0],
        linewidth=0.8,
        label="Contour ancien",
    ),
]

figure.legend(
    handles=legend_items,
    loc="lower center",
    ncol=4,
)

latest_plot = (
    OUTPUT_DIR
    / "landmask_latest_features_diagnostic_v3.png"
)

figure.savefig(
    latest_plot,
    dpi=180,
)

plt.close(figure)


old_size_bytes = OLD_GEOJSON.stat().st_size
new_size_bytes = NEW_GEOJSON.stat().st_size

checks = {
    "snapshot_chronology_identical":
        old_snapshot_times
        == new_snapshot_times,

    "feature_keys_identical":
        old_keys
        == new_keys,

    "all_new_geometries_valid":
        bool(comparison["new_valid"].all()),

    "no_new_geometry_empty":
        bool(
            ~comparison["new_empty"].any()
        ),

    "features_with_added_area_over_0_01_km2":
        int(len(added_alerts)),

    "maximum_added_area_km2":
        float(
            comparison[
                "added_area_km2"
            ].max()
        ),

    "old_geojson_size_bytes":
        old_size_bytes,

    "new_geojson_size_bytes":
        new_size_bytes,

    "size_change_percent":
        100.0
        * (
            new_size_bytes
            / old_size_bytes
            - 1.0
        ),
}

audit_manifest = {
    "model_version":
        "parallel_landmask_export_audit_v3",

    "old_geojson":
        str(OLD_GEOJSON),

    "new_geojson":
        str(NEW_GEOJSON),

    "checks":
        checks,

    "outputs": {
        "feature_comparison":
            str(feature_csv),

        "category_summary":
            str(category_csv),

        "added_area_alerts":
            str(added_alerts_path),

        "category_area_changes":
            str(category_plot),

        "latest_features_diagnostic":
            str(latest_plot),
    },
}

audit_manifest_path = (
    OUTPUT_DIR
    / "parallel_landmask_export_audit_v3.json"
)

audit_manifest_path.write_text(
    json.dumps(
        audit_manifest,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


print()
print("===== SYNTHÈSE PAR CATÉGORIE =====")
print(
    category_summary.to_string(
        index=False,
        float_format=lambda value: f"{value:.4f}",
    )
)

print()
print("===== PLUS GRANDES SURFACES AJOUTÉES =====")

print(
    comparison.sort_values(
        "added_area_km2",
        ascending=False,
    )[
        [
            "category",
            "feature_index",
            "old_area_km2",
            "new_area_km2",
            "removed_area_km2",
            "added_area_km2",
            "added_percent_of_new",
        ]
    ]
    .head(15)
    .to_string(
        index=False,
        float_format=lambda value: f"{value:.5f}",
    )
)

print()
print("===== CONTRÔLES =====")
print(
    json.dumps(
        checks,
        ensure_ascii=False,
        indent=2,
    )
)

print()
print("===== SORTIES =====")

for path in [
    feature_csv,
    category_csv,
    added_alerts_path,
    category_plot,
    latest_plot,
    audit_manifest_path,
]:
    print(path)
