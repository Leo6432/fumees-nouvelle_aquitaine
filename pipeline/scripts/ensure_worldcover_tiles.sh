#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BASE_URL="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DEST="data/external/worldcover_2021_v200"

mkdir -p "$DEST"


validate_tile() {
    local path="$1"
    local tile="$2"

    python - "$path" "$tile" <<'PY'
import math
import sys
from pathlib import Path

import rasterio


path = Path(sys.argv[1])
tile = sys.argv[2]

expected_bounds = {
    "N42W003": (-3.0, 42.0, 0.0, 45.0),
    "N45W003": (-3.0, 45.0, 0.0, 48.0),
}

if tile not in expected_bounds:
    raise RuntimeError(
        f"Tuile inattendue : {tile}"
    )

if not path.exists() or path.stat().st_size == 0:
    raise RuntimeError(
        f"Fichier absent ou vide : {path}"
    )

with rasterio.open(path) as src:
    actual_bounds = (
        float(src.bounds.left),
        float(src.bounds.bottom),
        float(src.bounds.right),
        float(src.bounds.top),
    )

    expected = expected_bounds[tile]

    checks = {
        "driver":
            src.driver == "GTiff",

        "crs":
            str(src.crs) == "EPSG:4326",

        "dimensions":
            src.width == 36000
            and src.height == 36000,

        "bands":
            src.count == 1,

        "dtype":
            src.dtypes[0] == "uint8",

        "nodata":
            src.nodata is not None
            and math.isclose(
                float(src.nodata),
                0.0,
                abs_tol=1e-9,
            ),

        "bounds":
            all(
                math.isclose(
                    actual,
                    reference,
                    abs_tol=1e-9,
                )
                for actual, reference
                in zip(
                    actual_bounds,
                    expected,
                )
            ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    if failed:
        raise RuntimeError(
            f"Tuile invalide {path.name} : "
            + ", ".join(failed)
        )

    print(
        f"WorldCover valide : {path.name} "
        f"({path.stat().st_size / 1024 / 1024:.1f} MiB)"
    )
PY
}


download_tile() {
    local tile="$1"
    local file="ESA_WorldCover_10m_2021_v200_${tile}_Map.tif"
    local target="${DEST}/${file}"
    local partial="${target}.part"

    echo "Téléchargement : ${file}"

    curl \
      --fail \
      --location \
      --retry 3 \
      --retry-delay 2 \
      --continue-at - \
      "${BASE_URL}/${file}" \
      --output "$partial"

    mv "$partial" "$target"
}


for TILE in N42W003 N45W003
do
    FILE="ESA_WorldCover_10m_2021_v200_${TILE}_Map.tif"
    TARGET="${DEST}/${FILE}"

    if [[ ! -s "$TARGET" ]]; then
        download_tile "$TILE"
    fi

    if ! validate_tile "$TARGET" "$TILE"
    then
        echo "Tuile invalide : nouveau téléchargement complet."
        rm -f "$TARGET" "${TARGET}.part"

        download_tile "$TILE"
        validate_tile "$TARGET" "$TILE"
    fi
done

echo
echo "===== WORLDCOVER DISPONIBLE ====="
ls -lh "$DEST"/*.tif
