"""Comparaison des résolutions du masque terre/eau pour l'emprise FIRMS.

Le script :
- reprend la dernière emprise cumulative FIRMS ;
- reproduit le lissage graphique utilisé par l'export web ;
- applique WorldCover après rasterisation locale à 25, 50 et 100 m ;
- mesure le biais de rasterisation et la surface retirée ;
- n'altère aucun produit scientifique ni export web existant.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.features import shapes as raster_shapes
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from shapely.geometry import mapping, shape
from shapely.ops import unary_union


FIRMS_INPUT = Path(
    "pipeline/data/processed/detection_envelopes.gpkg"
)

WORLDCOVER_DIR = Path(
    "pipeline/data/external/worldcover_2021_v200"
)

OUTPUT_DIR = Path(
    "pipeline/data/processed/experiments/"
    "land_water_mask_v1/fine_resolution_comparison"
)

RESOLUTIONS_M = [
    25.0,
    50.0,
    100.0,
]

LAND_FRACTION_THRESHOLD = 0.50
MARGIN_M = 500.0

# Paramètres identiques à l'export web actuel.
FIRMS_DISPLAY_SMOOTH_M = 300.0
SIMPLIFY_M = 30.0

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def polygonize_mask(
    mask: np.ndarray,
    transform: Affine,
):
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

    geometry = unary_union(geometries)

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


if not FIRMS_INPUT.exists():
    raise FileNotFoundError(FIRMS_INPUT)

worldcover_paths = sorted(
    WORLDCOVER_DIR.glob(
        "ESA_WorldCover_10m_2021_v200_*_Map.tif"
    )
)

if len(worldcover_paths) != 2:
    raise RuntimeError(
        "Deux tuiles WorldCover attendues, "
        f"{len(worldcover_paths)} trouvée(s)."
    )


# ------------------------------------------------------------------
# 1. Dernière emprise cumulative FIRMS par cluster.
# ------------------------------------------------------------------

extents = gpd.read_file(
    FIRMS_INPUT,
    layer="cumulative_detection_envelopes",
).to_crs("EPSG:2154")

extents["observed_until_dt"] = pd.to_datetime(
    extents["observed_until_utc"],
    utc=True,
    errors="coerce",
)

latest = (
    extents.dropna(
        subset=[
            "cluster_id",
            "observed_until_dt",
            "geometry",
        ]
    )
    .sort_values(
        [
            "cluster_id",
            "observed_until_dt",
            "snapshot_index",
        ]
    )
    .groupby(
        "cluster_id",
        as_index=False,
    )
    .tail(1)
    .copy()
)

scientific_geometry = unary_union(
    latest.geometry.to_list()
)

if not scientific_geometry.is_valid:
    scientific_geometry = scientific_geometry.buffer(0)

display_geometry = (
    scientific_geometry
    .buffer(
        FIRMS_DISPLAY_SMOOTH_M,
        resolution=24,
        join_style=1,
    )
    .buffer(
        -FIRMS_DISPLAY_SMOOTH_M,
        resolution=24,
        join_style=1,
    )
)

if display_geometry.is_empty:
    display_geometry = scientific_geometry

if not display_geometry.is_valid:
    display_geometry = display_geometry.buffer(0)

display_vector_area_km2 = (
    display_geometry.area
    / 1_000_000.0
)


# ------------------------------------------------------------------
# 2. Lecture WorldCover limitée à l'emprise FIRMS.
# ------------------------------------------------------------------

gxmin, gymin, gxmax, gymax = display_geometry.bounds

gxmin -= MARGIN_M
gymin -= MARGIN_M
gxmax += MARGIN_M
gymax += MARGIN_M

to_wgs84 = Transformer.from_crs(
    "EPSG:2154",
    "EPSG:4326",
    always_xy=True,
)

corners = [
    to_wgs84.transform(gxmin, gymin),
    to_wgs84.transform(gxmin, gymax),
    to_wgs84.transform(gxmax, gymin),
    to_wgs84.transform(gxmax, gymax),
]

worldcover_bounds = (
    min(point[0] for point in corners),
    min(point[1] for point in corners),
    max(point[0] for point in corners),
    max(point[1] for point in corners),
)

datasets = [
    rasterio.open(path)
    for path in worldcover_paths
]

try:
    mosaic, mosaic_transform = merge(
        datasets,
        bounds=worldcover_bounds,
        nodata=0,
        dtype="uint8",
    )
finally:
    for dataset in datasets:
        dataset.close()

worldcover = mosaic[0]

source_land = (
    (worldcover != 0)
    & (worldcover != 80)
).astype(np.float32)


# ------------------------------------------------------------------
# 3. Comparaison des résolutions.
# ------------------------------------------------------------------

statistics = []
geometries_25m = []
diagnostic_25m = None

for resolution_m in RESOLUTIONS_M:
    xmin = (
        math.floor(gxmin / resolution_m)
        * resolution_m
    )

    ymin = (
        math.floor(gymin / resolution_m)
        * resolution_m
    )

    xmax = (
        math.ceil(gxmax / resolution_m)
        * resolution_m
    )

    ymax = (
        math.ceil(gymax / resolution_m)
        * resolution_m
    )

    nx = int(
        round(
            (xmax - xmin)
            / resolution_m
        )
    )

    ny = int(
        round(
            (ymax - ymin)
            / resolution_m
        )
    )

    grid_transform = Affine(
        resolution_m,
        0.0,
        xmin,
        0.0,
        -resolution_m,
        ymax,
    )

    land_fraction = np.zeros(
        (ny, nx),
        dtype=np.float32,
    )

    reproject(
        source=source_land,
        destination=land_fraction,
        src_transform=mosaic_transform,
        src_crs="EPSG:4326",
        dst_transform=grid_transform,
        dst_crs="EPSG:2154",
        resampling=Resampling.average,
        src_nodata=None,
        dst_nodata=0.0,
    )

    land_fraction = np.clip(
        land_fraction,
        0.0,
        1.0,
    )

    land_mask = (
        land_fraction
        >= LAND_FRACTION_THRESHOLD
    )

    # all_touched=False : classification par centre de cellule,
    # afin de limiter la surestimation de surface.
    raw_mask = rasterize(
        [
            (
                mapping(display_geometry),
                1,
            )
        ],
        out_shape=(ny, nx),
        transform=grid_transform,
        fill=0,
        dtype="uint8",
        all_touched=False,
    ).astype(bool)

    masked_mask = (
        raw_mask
        & land_mask
    )

    removed_mask = (
        raw_mask
        & ~land_mask
    )

    cell_area_km2 = (
        resolution_m
        * resolution_m
        / 1_000_000.0
    )

    raw_raster_area_km2 = (
        float(raw_mask.sum())
        * cell_area_km2
    )

    masked_raster_area_km2 = (
        float(masked_mask.sum())
        * cell_area_km2
    )

    removed_area_km2 = (
        raw_raster_area_km2
        - masked_raster_area_km2
    )

    raw_raster_geometry = polygonize_mask(
        raw_mask,
        grid_transform,
    )

    masked_geometry = polygonize_mask(
        masked_mask,
        grid_transform,
    )

    removed_geometry = polygonize_mask(
        removed_mask,
        grid_transform,
    )

    if masked_geometry is not None:
        masked_geometry = masked_geometry.simplify(
            SIMPLIFY_M,
            preserve_topology=True,
        )

        if not masked_geometry.is_valid:
            masked_geometry = masked_geometry.buffer(0)

    statistics.append({
        "resolution_m":
            resolution_m,

        "grid_height":
            ny,

        "grid_width":
            nx,

        "display_vector_area_km2":
            display_vector_area_km2,

        "raw_raster_area_km2":
            raw_raster_area_km2,

        "rasterization_bias_km2":
            raw_raster_area_km2
            - display_vector_area_km2,

        "rasterization_bias_percent":
            100.0
            * (
                raw_raster_area_km2
                / display_vector_area_km2
                - 1.0
            ),

        "masked_raster_area_km2":
            masked_raster_area_km2,

        "removed_area_km2":
            removed_area_km2,

        "removed_fraction_percent":
            (
                100.0
                * removed_area_km2
                / raw_raster_area_km2
                if raw_raster_area_km2 > 0
                else np.nan
            ),

        "masked_coordinate_count":
            coordinate_count(masked_geometry),
    })

    if math.isclose(
        resolution_m,
        25.0,
    ):
        geometries_25m = [
            {
                "version":
                    "display_vector_before_mask",

                "resolution_m":
                    np.nan,

                "area_km2":
                    display_vector_area_km2,

                "geometry":
                    display_geometry,
            },
            {
                "version":
                    "raw_raster_25m",

                "resolution_m":
                    25.0,

                "area_km2":
                    raw_raster_area_km2,

                "geometry":
                    raw_raster_geometry,
            },
            {
                "version":
                    "land_masked_25m",

                "resolution_m":
                    25.0,

                "area_km2":
                    masked_raster_area_km2,

                "geometry":
                    masked_geometry,
            },
            {
                "version":
                    "removed_water_25m",

                "resolution_m":
                    25.0,

                "area_km2":
                    removed_area_km2,

                "geometry":
                    removed_geometry,
            },
        ]

        diagnostic_25m = {
            "land_fraction":
                land_fraction,

            "raw_mask":
                raw_mask,

            "masked_mask":
                masked_mask,

            "removed_mask":
                removed_mask,

            "extent": [
                xmin,
                xmax,
                ymin,
                ymax,
            ],

            "display_geometry":
                display_geometry,

            "masked_geometry":
                masked_geometry,
        }


statistics_df = pd.DataFrame(statistics)

statistics_path = (
    OUTPUT_DIR
    / "firms_landmask_resolution_stats_v1.csv"
)

statistics_df.to_csv(
    statistics_path,
    index=False,
)


# ------------------------------------------------------------------
# 4. Géométries détaillées à 25 m.
# ------------------------------------------------------------------

comparison_gdf = gpd.GeoDataFrame(
    geometries_25m,
    geometry="geometry",
    crs="EPSG:2154",
)

comparison_path = (
    OUTPUT_DIR
    / "firms_landmask_25m_comparison_v1.gpkg"
)

comparison_gdf.to_file(
    comparison_path,
    layer="comparison",
    driver="GPKG",
)


# ------------------------------------------------------------------
# 5. Figure cartographique à 25 m.
# ------------------------------------------------------------------

if diagnostic_25m is None:
    raise RuntimeError(
        "Diagnostic 25 m absent."
    )

extent = diagnostic_25m["extent"]

figure, axes = plt.subplots(
    1,
    3,
    figsize=(18, 7),
    constrained_layout=True,
)

image = axes[0].imshow(
    diagnostic_25m["land_fraction"],
    origin="upper",
    extent=extent,
    vmin=0.0,
    vmax=1.0,
    cmap="viridis",
)

axes[0].set_title(
    "Fraction terrestre WorldCover\nrésolution 25 m"
)

figure.colorbar(
    image,
    ax=axes[0],
    fraction=0.046,
    pad=0.04,
)

axes[1].imshow(
    diagnostic_25m["removed_mask"],
    origin="upper",
    extent=extent,
    cmap="Reds",
)

axes[1].set_title(
    "Surface retirée de l'emprise FIRMS\nmasque 25 m"
)

axes[2].imshow(
    diagnostic_25m["masked_mask"],
    origin="upper",
    extent=extent,
    cmap="Greens",
)

axes[2].set_title(
    "Emprise FIRMS après masque\nrésolution 25 m"
)

for axis in axes:
    axis.set_aspect("equal")
    axis.set_xlabel("X Lambert-93 (m)")
    axis.set_ylabel("Y Lambert-93 (m)")
    axis.grid(
        linewidth=0.25,
        alpha=0.35,
    )

figure_path = (
    OUTPUT_DIR
    / "firms_landmask_25m_diagnostic_v1.png"
)

figure.savefig(
    figure_path,
    dpi=180,
)

plt.close(figure)


# ------------------------------------------------------------------
# 6. Graphique de sensibilité.
# ------------------------------------------------------------------

figure, axis = plt.subplots(
    figsize=(8, 5),
    constrained_layout=True,
)

axis.plot(
    statistics_df["resolution_m"],
    statistics_df[
        "rasterization_bias_percent"
    ],
    marker="o",
    label="Biais de rasterisation",
)

axis.plot(
    statistics_df["resolution_m"],
    statistics_df[
        "removed_fraction_percent"
    ],
    marker="o",
    label="Fraction retirée par le masque",
)

axis.axhline(
    0.0,
    linewidth=0.8,
)

axis.set_xlabel("Résolution du masque (m)")
axis.set_ylabel("Pourcentage (%)")
axis.set_title(
    "Sensibilité du masque FIRMS à la résolution"
)
axis.grid(
    linewidth=0.4,
    alpha=0.4,
)
axis.legend()

sensitivity_path = (
    OUTPUT_DIR
    / "firms_landmask_resolution_sensitivity_v1.png"
)

figure.savefig(
    sensitivity_path,
    dpi=180,
)

plt.close(figure)


# ------------------------------------------------------------------
# 7. Manifeste.
# ------------------------------------------------------------------

manifest = {
    "model_version":
        "firms_landmask_resolution_comparison_v1",

    "worldcover_product":
        "ESA WorldCover 2021 v200",

    "land_fraction_threshold":
        LAND_FRACTION_THRESHOLD,

    "resolutions_m":
        RESOLUTIONS_M,

    "display_smoothing_m":
        FIRMS_DISPLAY_SMOOTH_M,

    "simplification_m":
        SIMPLIFY_M,

    "display_vector_area_km2":
        display_vector_area_km2,

    "outputs": {
        "statistics":
            str(statistics_path),

        "comparison_gpkg":
            str(comparison_path),

        "diagnostic_25m":
            str(figure_path),

        "resolution_sensitivity":
            str(sensitivity_path),
    },
}

manifest_path = (
    OUTPUT_DIR
    / "firms_landmask_resolution_manifest_v1.json"
)

manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


print("===== COMPARAISON MASQUE FIRMS =====")
print(
    statistics_df.to_string(
        index=False,
        float_format=lambda value: f"{value:.4f}",
    )
)

print()
print("===== SORTIES =====")

for path in [
    statistics_path,
    comparison_path,
    figure_path,
    sensitivity_path,
    manifest_path,
]:
    print(path)
