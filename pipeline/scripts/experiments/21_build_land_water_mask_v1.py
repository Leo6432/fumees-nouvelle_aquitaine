"""Diagnostic expérimental du masque terre/eau WorldCover.

Le script :
- reproduit exactement la grille 250 m du modèle de progression ;
- agrège ESA WorldCover 2021 à cette grille ;
- compare plusieurs seuils de fraction terrestre ;
- applique provisoirement le masque à la dernière emprise FIRMS ;
- ne modifie aucun produit scientifique ou export web existant.
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


ROOT = Path(".")

PROGRESSION_INPUT = Path(
    "pipeline/data/processed/experiments/"
    "fire_progression_passes_v1.geojson"
)

FIRMS_EXTENTS_INPUT = Path(
    "pipeline/data/processed/detection_envelopes.gpkg"
)

WORLDCOVER_DIR = Path(
    "pipeline/data/external/worldcover_2021_v200"
)

OUTPUT_DIR = Path(
    "pipeline/data/processed/experiments/"
    "land_water_mask_v1"
)

CELL_M = 250.0
PADDING_M = 3000.0
SELECTED_THRESHOLD = 0.50

THRESHOLDS = [
    0.10,
    0.25,
    0.50,
    0.75,
]

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def polygonize_mask(
    mask: np.ndarray,
    transform: Affine,
) -> object | None:
    """Transforme un masque booléen en géométrie EPSG:2154."""

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


if not PROGRESSION_INPUT.exists():
    raise FileNotFoundError(PROGRESSION_INPUT)

if not FIRMS_EXTENTS_INPUT.exists():
    raise FileNotFoundError(FIRMS_EXTENTS_INPUT)

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
# 1. Reconstruction exacte de la grille utilisée par le modèle.
# ------------------------------------------------------------------

progression = gpd.read_file(PROGRESSION_INPUT)

progression = progression.loc[
    progression.geometry.notna()
    & ~progression.geometry.is_empty
].copy()

if progression.empty:
    raise RuntimeError(
        "Aucune géométrie de progression exploitable."
    )

progression_l93 = progression.to_crs("EPSG:2154")

xmin, ymin, xmax, ymax = progression_l93.total_bounds

xmin = (
    math.floor(
        (xmin - PADDING_M) / CELL_M
    )
    * CELL_M
)

ymin = (
    math.floor(
        (ymin - PADDING_M) / CELL_M
    )
    * CELL_M
)

xmax = (
    math.ceil(
        (xmax + PADDING_M) / CELL_M
    )
    * CELL_M
)

ymax = (
    math.ceil(
        (ymax + PADDING_M) / CELL_M
    )
    * CELL_M
)

nx = int(
    round(
        (xmax - xmin) / CELL_M
    )
)

ny = int(
    round(
        (ymax - ymin) / CELL_M
    )
)

model_transform = Affine(
    CELL_M,
    0.0,
    xmin,
    0.0,
    -CELL_M,
    ymax,
)


# ------------------------------------------------------------------
# 2. Emprise géographique nécessaire dans WorldCover.
# ------------------------------------------------------------------

to_wgs84 = Transformer.from_crs(
    "EPSG:2154",
    "EPSG:4326",
    always_xy=True,
)

corners_wgs84 = [
    to_wgs84.transform(xmin, ymin),
    to_wgs84.transform(xmin, ymax),
    to_wgs84.transform(xmax, ymin),
    to_wgs84.transform(xmax, ymax),
]

worldcover_bounds = (
    min(point[0] for point in corners_wgs84),
    min(point[1] for point in corners_wgs84),
    max(point[0] for point in corners_wgs84),
    max(point[1] for point in corners_wgs84),
)


# ------------------------------------------------------------------
# 3. Lecture limitée à l'emprise utile et mosaïquage.
# ------------------------------------------------------------------

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

# Classes WorldCover :
# 0  = nodata, notamment océan ouvert ;
# 80 = plans d'eau permanents.
#
# Toutes les autres classes sont considérées ici comme terre,
# y compris zones humides, mangroves, neige et glace.
source_land = (
    (worldcover != 0)
    & (worldcover != 80)
).astype(np.float32)


# ------------------------------------------------------------------
# 4. Agrégation de la fraction terrestre vers la grille 250 m.
# ------------------------------------------------------------------

land_fraction = np.zeros(
    (ny, nx),
    dtype=np.float32,
)

reproject(
    source=source_land,
    destination=land_fraction,
    src_transform=mosaic_transform,
    src_crs="EPSG:4326",
    dst_transform=model_transform,
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


# ------------------------------------------------------------------
# 5. Dernière emprise cumulative FIRMS disponible.
# ------------------------------------------------------------------

extents = gpd.read_file(
    FIRMS_EXTENTS_INPUT,
    layer="cumulative_detection_envelopes",
).to_crs("EPSG:2154")

extents["observed_until_dt"] = pd.to_datetime(
    extents["observed_until_utc"],
    utc=True,
    errors="coerce",
)

extents = extents.dropna(
    subset=[
        "cluster_id",
        "observed_until_dt",
        "geometry",
    ]
).sort_values(
    [
        "cluster_id",
        "observed_until_dt",
        "snapshot_index",
    ]
)

latest_extents = (
    extents.groupby(
        "cluster_id",
        as_index=False,
    )
    .tail(1)
    .copy()
)

raw_geometry = unary_union(
    latest_extents.geometry.to_list()
)

if not raw_geometry.is_valid:
    raw_geometry = raw_geometry.buffer(0)

raw_mask = rasterize(
    [
        (
            mapping(raw_geometry),
            1,
        )
    ],
    out_shape=(ny, nx),
    transform=model_transform,
    fill=0,
    dtype="uint8",
    all_touched=True,
).astype(bool)

cell_area_km2 = (
    CELL_M
    * CELL_M
    / 1_000_000.0
)

raw_grid_area_km2 = (
    float(raw_mask.sum())
    * cell_area_km2
)


# ------------------------------------------------------------------
# 6. Comparaison des seuils.
# ------------------------------------------------------------------

statistics = []

for threshold in THRESHOLDS:
    land_mask = (
        land_fraction
        >= threshold
    )

    masked_firms = (
        raw_mask
        & land_mask
    )

    masked_area_km2 = (
        float(masked_firms.sum())
        * cell_area_km2
    )

    removed_area_km2 = (
        raw_grid_area_km2
        - masked_area_km2
    )

    removed_fraction = (
        removed_area_km2
        / raw_grid_area_km2
        if raw_grid_area_km2 > 0
        else np.nan
    )

    statistics.append({
        "land_fraction_threshold":
            threshold,

        "raw_grid_area_km2":
            raw_grid_area_km2,

        "masked_grid_area_km2":
            masked_area_km2,

        "removed_grid_area_km2":
            removed_area_km2,

        "removed_fraction":
            removed_fraction,

        "land_cells":
            int(land_mask.sum()),

        "raw_firms_cells":
            int(raw_mask.sum()),

        "masked_firms_cells":
            int(masked_firms.sum()),
    })

statistics_df = pd.DataFrame(statistics)

statistics_path = (
    OUTPUT_DIR
    / "land_mask_threshold_stats_v1.csv"
)

statistics_df.to_csv(
    statistics_path,
    index=False,
)


# ------------------------------------------------------------------
# 7. Export du raster de fraction terrestre.
# ------------------------------------------------------------------

land_fraction_path = (
    OUTPUT_DIR
    / "land_fraction_250m_v1.tif"
)

with rasterio.open(
    land_fraction_path,
    "w",
    driver="GTiff",
    height=ny,
    width=nx,
    count=1,
    dtype="float32",
    crs="EPSG:2154",
    transform=model_transform,
    nodata=-9999.0,
    compress="deflate",
) as destination:
    destination.write(
        land_fraction.astype(np.float32),
        1,
    )


# ------------------------------------------------------------------
# 8. Export des géométries avant/après au seuil sélectionné.
# ------------------------------------------------------------------

selected_land_mask = (
    land_fraction
    >= SELECTED_THRESHOLD
)

selected_masked_firms = (
    raw_mask
    & selected_land_mask
)

raw_grid_geometry = polygonize_mask(
    raw_mask,
    model_transform,
)

masked_grid_geometry = polygonize_mask(
    selected_masked_firms,
    model_transform,
)

comparison_rows = []

if raw_grid_geometry is not None:
    comparison_rows.append({
        "version":
            "raw_grid",

        "land_fraction_threshold":
            np.nan,

        "area_km2":
            raw_grid_area_km2,

        "geometry":
            raw_grid_geometry,
    })

if masked_grid_geometry is not None:
    comparison_rows.append({
        "version":
            "land_masked",

        "land_fraction_threshold":
            SELECTED_THRESHOLD,

        "area_km2":
            float(
                selected_masked_firms.sum()
            )
            * cell_area_km2,

        "geometry":
            masked_grid_geometry,
    })

comparison_gdf = gpd.GeoDataFrame(
    comparison_rows,
    geometry="geometry",
    crs="EPSG:2154",
).to_crs("EPSG:4326")

comparison_path = (
    OUTPUT_DIR
    / "firms_extent_landmask_comparison_v1.geojson"
)

comparison_gdf.to_file(
    comparison_path,
    driver="GeoJSON",
)


# ------------------------------------------------------------------
# 9. Figure diagnostique.
# ------------------------------------------------------------------

removed_mask = (
    raw_mask
    & ~selected_land_mask
)

extent = [
    xmin,
    xmax,
    ymin,
    ymax,
]

figure, axes = plt.subplots(
    1,
    4,
    figsize=(20, 7),
    constrained_layout=True,
)

image = axes[0].imshow(
    land_fraction,
    origin="upper",
    extent=extent,
    vmin=0.0,
    vmax=1.0,
    cmap="viridis",
)

axes[0].set_title(
    "Fraction terrestre\nWorldCover → grille 250 m"
)

figure.colorbar(
    image,
    ax=axes[0],
    fraction=0.046,
    pad=0.04,
)

axes[1].imshow(
    raw_mask,
    origin="upper",
    extent=extent,
    cmap="Greys",
)

axes[1].set_title(
    "Emprise FIRMS brute\nrasterisée à 250 m"
)

axes[2].imshow(
    removed_mask,
    origin="upper",
    extent=extent,
    cmap="Reds",
)

axes[2].set_title(
    "Cellules supprimées\n"
    f"seuil terre ≥ {SELECTED_THRESHOLD:.2f}"
)

axes[3].imshow(
    selected_masked_firms,
    origin="upper",
    extent=extent,
    cmap="Greens",
)

axes[3].set_title(
    "Emprise FIRMS masquée\n"
    f"seuil terre ≥ {SELECTED_THRESHOLD:.2f}"
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
    / "land_mask_diagnostic_v1.png"
)

figure.savefig(
    figure_path,
    dpi=180,
)

plt.close(figure)


# ------------------------------------------------------------------
# 10. Manifeste.
# ------------------------------------------------------------------

selected_stats = statistics_df.loc[
    np.isclose(
        statistics_df[
            "land_fraction_threshold"
        ],
        SELECTED_THRESHOLD,
    )
].iloc[0]

manifest = {
    "model_version":
        "land_water_mask_v1",

    "worldcover_product":
        "ESA WorldCover 2021 v200",

    "worldcover_tiles": [
        path.name
        for path in worldcover_paths
    ],

    "grid_crs":
        "EPSG:2154",

    "cell_m":
        CELL_M,

    "grid_shape": [
        ny,
        nx,
    ],

    "grid_bounds_l93": [
        xmin,
        ymin,
        xmax,
        ymax,
    ],

    "selected_land_fraction_threshold":
        SELECTED_THRESHOLD,

    "raw_grid_area_km2":
        float(
            selected_stats[
                "raw_grid_area_km2"
            ]
        ),

    "masked_grid_area_km2":
        float(
            selected_stats[
                "masked_grid_area_km2"
            ]
        ),

    "removed_grid_area_km2":
        float(
            selected_stats[
                "removed_grid_area_km2"
            ]
        ),

    "removed_fraction":
        float(
            selected_stats[
                "removed_fraction"
            ]
        ),

    "outputs": {
        "statistics":
            str(statistics_path),

        "land_fraction":
            str(land_fraction_path),

        "comparison_geojson":
            str(comparison_path),

        "diagnostic_figure":
            str(figure_path),
    },
}

manifest_path = (
    OUTPUT_DIR
    / "land_water_mask_v1_manifest.json"
)

manifest_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


print("===== MASQUE TERRE/EAU V1 =====")
print("Grille :", ny, "x", nx)
print("Seuil sélectionné :", SELECTED_THRESHOLD)

print()
print("===== STATISTIQUES PAR SEUIL =====")
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
    land_fraction_path,
    comparison_path,
    figure_path,
    manifest_path,
]:
    print(path)
