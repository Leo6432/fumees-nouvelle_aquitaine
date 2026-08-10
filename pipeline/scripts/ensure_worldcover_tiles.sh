#!/usr/bin/env bash
# Télécharge (et met en cache) les tuiles ESA WorldCover nécessaires à
# UNE bbox donnée, puis prépare le dossier de travail avec uniquement
# ces tuiles-là (le reste de la France, mis en cache ailleurs, ne
# ralentit pas le mosaïquage de chaque feu).
#
# Usage : ensure_worldcover_tiles.sh WEST SOUTH EAST NORTH
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -ne 4 ]]; then
    echo "Usage : ensure_worldcover_tiles.sh WEST SOUTH EAST NORTH" >&2
    exit 1
fi

WEST="$1"; SOUTH="$2"; EAST="$3"; NORTH="$4"

BASE_URL="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
CACHE="data/external/worldcover_2021_v200_cache"
DEST="data/external/worldcover_2021_v200"

mkdir -p "$CACHE" "$DEST"

TILES=$(python3 - "$WEST" "$SOUTH" "$EAST" "$NORTH" <<'PY'
import math
import sys

west, south, east, north = (float(v) for v in sys.argv[1:5])

def band(value):
    return int(math.floor(value / 3.0) * 3)

lon_bands = range(band(west), band(east) + 1, 3)
lat_bands = range(band(south), band(north) + 1, 3)

for lat in lat_bands:
    ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
    for lon in lon_bands:
        ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
        print(f"{ns}{ew}")
PY
)

# Clarifié une fois pour toutes : dossier de travail = seulement les
# tuiles de CE feu (des liens symboliques vers le cache partagé).
find "$DEST" -maxdepth 1 -type l -delete


validate_tile() {
    local path="$1"
    local tile="$2"

    python3 - "$path" "$tile" <<'PY'
import math
import re
import sys
from pathlib import Path

import rasterio

path = Path(sys.argv[1])
tile = sys.argv[2]

m = re.fullmatch(r"([NS])(\d{2})([EW])(\d{3})", tile)
if not m:
    raise RuntimeError(f"Nom de tuile inattendu : {tile}")

ns, lat_str, ew, lon_str = m.groups()
lat0 = int(lat_str) * (1 if ns == "N" else -1)
lon0 = int(lon_str) * (1 if ew == "E" else -1)
expected = (float(lon0), float(lat0), float(lon0 + 3), float(lat0 + 3))

if not path.exists() or path.stat().st_size == 0:
    raise RuntimeError(f"Fichier absent ou vide : {path}")

with rasterio.open(path) as src:
    actual_bounds = (
        float(src.bounds.left),
        float(src.bounds.bottom),
        float(src.bounds.right),
        float(src.bounds.top),
    )

    checks = {
        "driver": src.driver == "GTiff",
        "crs": str(src.crs) == "EPSG:4326",
        "dimensions": src.width == 36000 and src.height == 36000,
        "bands": src.count == 1,
        "dtype": src.dtypes[0] == "uint8",
        "nodata": (
            src.nodata is not None
            and math.isclose(float(src.nodata), 0.0, abs_tol=1e-9)
        ),
        "bounds": all(
            math.isclose(actual, reference, abs_tol=1e-9)
            for actual, reference in zip(actual_bounds, expected)
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]

    if failed:
        raise RuntimeError(
            f"Tuile invalide {path.name} : " + ", ".join(failed)
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
    local target="${CACHE}/${file}"
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


for TILE in $TILES
do
    FILE="ESA_WorldCover_10m_2021_v200_${TILE}_Map.tif"
    CACHED="${CACHE}/${FILE}"

    if [[ ! -s "$CACHED" ]]; then
        # Certaines tuiles couvrent la mer/l'étranger et n'existent
        # pas côté ESA (ex. tuile presque entièrement en mer) : on ne
        # bloque pas tout le run pour ça, on l'ignore simplement.
        if ! download_tile "$TILE"; then
            echo "  tuile ${TILE} indisponible, ignorée."
            continue
        fi
    fi

    if ! validate_tile "$CACHED" "$TILE"
    then
        echo "Tuile invalide : nouveau téléchargement complet."
        rm -f "$CACHED" "${CACHED}.part"
        if ! download_tile "$TILE"; then
            echo "  tuile ${TILE} indisponible, ignorée."
            continue
        fi
        validate_tile "$CACHED" "$TILE"
    fi

    ln -sf "../worldcover_2021_v200_cache/${FILE}" "${DEST}/${FILE}"
done

echo
echo "===== WORLDCOVER DISPONIBLE POUR CETTE EMPRISE ====="
ls -lh "$DEST"/*.tif
