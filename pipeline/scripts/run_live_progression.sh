#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p   data/raw   data/processed/experiments   data/web

export MPLBACKEND=Agg

echo "===== 1/9 — Téléchargement FIRMS ====="
python scripts/01_fetch_firms.py

echo "===== 2/9 — Emprises FIRMS cumulées ====="
python scripts/03_cumulative_detection_envelopes.py

echo "===== 3/9 — Support spatio-temporel ====="
python scripts/02_build_spatiotemporal_support.py

echo "===== 4/9 — Support causal ====="
python scripts/05_build_causal_support.py

echo "===== 5/9 — Regroupement par passage ====="
python scripts/experiments/05_build_passes_v1.py

echo "===== 6/9 — Distance caractéristique ====="
python scripts/experiments/06_characteristic_distance_by_pass.py

echo "===== 7/9 — Régularisation ====="
python scripts/experiments/07_regularize_characteristic_distance.py

echo "===== 8/9 — Progression observée ====="
bash scripts/experiments/08_fire_progression_passes_v1.sh

echo "===== 9/9 — Export web + projection plausible à 1 h ====="
python scripts/experiments/14_export_arrival_web_v1.py

echo
echo "===== SORTIES WEB ====="
ls -lh \
  data/web/detection_envelopes.geojson \
  data/web/fire_progression_arrival_v1.geojson \
  data/web/fire_progression_arrival_v1_manifest.json

python - <<'PY'
import json
from pathlib import Path

manifest = json.loads(
    Path(
        "data/web/fire_progression_arrival_v1_manifest.json"
    ).read_text()
)

snapshots = manifest.get("snapshots", [])
latest = snapshots[-1] if snapshots else {}

print("Passages :", len(snapshots))
print(
    "Dernier passage :",
    latest.get("pass_time_utc", "absent"),
)
print(
    "Projection +1 h affichable :",
    latest.get("projection_displayed", False),
)
PY
