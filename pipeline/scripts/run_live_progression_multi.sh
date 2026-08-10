#!/usr/bin/env bash
# Orchestrateur multi-feux : récupère FIRMS à l'échelle nationale,
# détecte chaque feu actif indépendamment, puis rejoue le pipeline
# d'analyse existant (steps 2 à 10 de run_live_progression.sh) une
# fois par feu, sans le modifier — seule l'entrée (l'historique FIRMS
# filtré à CE feu) change d'une itération à l'autre.
#
# Pourquoi rejouer le même pipeline en boucle plutôt que le rendre
# "multi-feux" en interne : le krigeage/isochrones/temps d'arrivée
# n'ont de sens que pour UN feu cohérent à la fois, et ce pipeline est
# déjà validé sur ce cas — le ré-écrire pour qu'il comprenne plusieurs
# feux simultanés serait risqué. Cette boucle lui fait juste croire,
# à chaque itération, qu'il n'y a toujours eu qu'un seul feu.
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p \
  data/raw \
  data/processed/experiments \
  data/processed/fires_state \
  data/web \
  ../data/fire-progression/fires

export MPLBACKEND=Agg

echo "===== 1/3 — Téléchargement FIRMS (national) ====="
python3 scripts/01_fetch_firms.py

echo
echo "===== 2/3 — Détection des feux actifs ====="
python3 scripts/00_detect_active_fires.py

FIRES_INDEX="../data/fire-progression/fires_index.json"

if [[ ! -s "$FIRES_INDEX" ]]; then
    echo "Aucun feu actif détecté — rien à analyser."
    exit 0
fi

FIRE_IDS=$(python3 -c "
import json
d = json.load(open('$FIRES_INDEX'))
print(' '.join(f['id'] for f in d['fires']))
")

echo
echo "===== 3/3 — Analyse par feu ====="
echo "Feux à traiter : ${FIRE_IDS}"

for FIRE_ID in $FIRE_IDS
do
    echo
    echo "----- Feu ${FIRE_ID} -----"

    read -r BBOX_W BBOX_S BBOX_E BBOX_N <<< "$(python3 -c "
import json
d = json.load(open('$FIRES_INDEX'))
fire = next(f for f in d['fires'] if f['id'] == '$FIRE_ID')
print(*fire['bbox'])
")"

    # Sorties publiées (versionnées avec le dépôt, lues par le site).
    ARCHIVE_DIR="../data/fire-progression/fires/${FIRE_ID}"
    mkdir -p "$ARCHIVE_DIR"

    # État interne du pipeline (pas versionné — seulement mis en
    # cache GitHub Actions d'une exécution à l'autre).
    STATE_DIR="data/processed/fires_state/${FIRE_ID}"
    mkdir -p "$STATE_DIR"

    # --- Prépare l'état d'entrée de CE feu dans les chemins fixes
    #     que le pipeline existant attend. ---
    cp "data/raw/fires/${FIRE_ID}/firms_detections_history.csv" \
       "data/raw/firms_detections_history.csv"

    # Emprise cumulée précédente de CE feu (continuité des
    # identifiants de cluster et plancher anti-régression dans
    # 03_cumulative_detection_envelopes.py) — sinon un feu propre.
    rm -f "data/processed/detection_envelopes.gpkg"
    if [[ -f "${STATE_DIR}/detection_envelopes.gpkg" ]]; then
        cp "${STATE_DIR}/detection_envelopes.gpkg" \
           "data/processed/detection_envelopes.gpkg"
    fi

    bash scripts/ensure_worldcover_tiles.sh \
        "$BBOX_W" "$BBOX_S" "$BBOX_E" "$BBOX_N"

    echo "  --- support spatio-temporel ---"
    python3 scripts/02_build_spatiotemporal_support.py

    echo "  --- emprises FIRMS cumulées ---"
    python3 scripts/03_cumulative_detection_envelopes.py

    echo "  --- support causal ---"
    python3 scripts/05_build_causal_support.py

    echo "  --- regroupement par passage ---"
    python3 scripts/experiments/05_build_passes_v1.py

    echo "  --- distance caractéristique ---"
    python3 scripts/experiments/06_characteristic_distance_by_pass.py

    echo "  --- régularisation ---"
    python3 scripts/experiments/07_regularize_characteristic_distance.py

    echo "  --- progression observée ---"
    bash scripts/experiments/08_fire_progression_passes_v1.sh

    echo "  --- export web + projection plausible ---"
    python3 scripts/29_export_arrival_web_landmask_v1.py

    # --- Archive les sorties de CE feu avant que le suivant
    #     n'écrase les mêmes chemins fixes. ---
    cp "data/web/detection_envelopes.geojson" \
       "${ARCHIVE_DIR}/detection_envelopes.geojson"

    cp "data/web/fire_progression_arrival_v1.geojson" \
       "${ARCHIVE_DIR}/fire_progression_arrival_v1.geojson"

    cp "data/web/fire_progression_arrival_v1_manifest.json" \
       "${ARCHIVE_DIR}/fire_progression_arrival_v1_manifest.json"

    cp "data/processed/detection_envelopes.gpkg" \
       "${STATE_DIR}/detection_envelopes.gpkg"

    echo "  archivé : ${ARCHIVE_DIR} (publié), ${STATE_DIR} (état interne)"
done

echo
echo "===== TERMINÉ ====="
echo "Feux traités : ${FIRE_IDS}"
