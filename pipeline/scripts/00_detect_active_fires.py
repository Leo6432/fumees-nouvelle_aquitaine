"""
00 — Détection des feux actifs, à l'échelle nationale.

Sépare l'historique cumulé FIRMS (national) en clusters spatiaux
indépendants — un cluster = un feu — par le même algorithme
(union-find sur un rayon) que 03_cumulative_detection_envelopes.py
utilise pour isoler les foyers secondaires au sein d'UN feu déjà connu.
Ici, l'échelle est nationale : chaque cluster retenu devient un feu à
part entière, traité ensuite indépendamment par le pipeline complet
(orchestré par run_live_progression_multi.sh).

Un identifiant de feu stable est maintenu d'une exécution à l'autre
dans un registre (data/processed/fires_registry.json, versionné avec
le dépôt) : un cluster est rattaché au feu existant dont la bbox
précédente se recouvre le plus, sinon un nouvel identifiant est créé.

Sorties :
  data/raw/fires/<id>/firms_detections_history.csv   (par feu)
  data/processed/fires_index.json                      (feux actifs)
  data/processed/fires_registry.json                    (mis à jour)
"""
from __future__ import annotations

import json
import os
import shutil

import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from common import ROOT, fires_to_metric, load_config, resolve

# Publié et versionné avec le dépôt (le front-end le lit, et la
# stabilité des identifiants ne doit pas dépendre d'un cache GitHub
# Actions qui peut être évincé) — contrairement à l'état interne du
# pipeline (data/processed/, non versionné).
PUBLISHED_DIR = os.path.join(ROOT, "..", "data", "fire-progression")

BBOX_MARGIN_DEG = 0.15

# Tolère les imprécisions de simplification du contour et les feux à
# cheval sur la frontière : un centre de cluster à quelques km de la
# ligne officielle reste compté comme français plutôt que rejeté.
FRANCE_BOUNDARY_BUFFER_DEG = 0.05

FRANCE_BOUNDARY_URL = (
    "https://raw.githubusercontent.com/datasets/geo-countries/"
    "master/data/countries.geojson"
)


def load_france_boundary(cfg: dict):
    """
    Contour de la France (métropole + Corse), en cache local.

    Sans lui, la bbox de récupération nationale (large, simple
    rectangle) laisserait passer des détections en Belgique, aux
    Pays-Bas, en Allemagne, en Suisse ou en Italie près des
    frontières — pas de vrais feux français.
    """
    cache_path = resolve(cfg, "data/external/france_boundary.geojson")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    if not os.path.exists(cache_path):
        try:
            r = requests.get(FRANCE_BOUNDARY_URL, timeout=30)
            r.raise_for_status()
            countries = r.json()
            france = next(
                (
                    feat
                    for feat in countries["features"]
                    if feat["properties"].get("name") == "France"
                ),
                None,
            )
            if france is None:
                raise RuntimeError("France absente de la source de contours.")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"type": "FeatureCollection", "features": [france]}, f
                )
        except Exception as e:  # noqa: BLE001
            print(f"  contour France indisponible ({e}) — filtrage désactivé")
            return None

    with open(cache_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    geometry = unary_union(
        [shape(feat["geometry"]) for feat in payload["features"]]
    )
    return geometry.buffer(FRANCE_BOUNDARY_BUFFER_DEG)


def assign_spatial_clusters(
    df: pd.DataFrame,
    radius_km: float,
    min_points: int,
    max_clusters: int,
) -> pd.DataFrame:
    """Union-find sur un rayon — identique à 03_cumulative_detection_envelopes.py."""
    xy = df[["x", "y"]].to_numpy(dtype=float)
    tree = cKDTree(xy)
    pairs = tree.query_pairs(r=radius_km * 1000.0)

    parent = np.arange(len(df), dtype=int)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_left] = root_right

    for left, right in pairs:
        union(left, right)

    roots = np.array([find(i) for i in range(len(df))], dtype=int)
    values, counts = np.unique(roots, return_counts=True)

    ordered = [
        (int(root), int(count))
        for root, count in sorted(
            zip(values, counts), key=lambda item: int(item[1]), reverse=True
        )
        if int(count) >= min_points
    ][:max_clusters]

    output = df.copy()
    root_to_local_id = {root: i for i, (root, _) in enumerate(ordered, start=1)}
    output["local_cluster_id"] = [root_to_local_id.get(int(r), 0) for r in roots]
    return output.loc[output["local_cluster_id"] > 0].copy().reset_index(drop=True)


def bbox_iou(a: list[float], b: list[float]) -> float:
    """Recouvrement (IoU) de deux bbox [ouest, sud, est, nord]."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def load_registry(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"next_id": 1, "fires": {}}


def assign_stable_ids(clusters: list[dict], registry: dict) -> dict:
    """Rattache chaque cluster courant à un identifiant de feu stable."""
    previous = registry.get("fires", {})
    candidates = []
    for cluster in clusters:
        for fire_id, entry in previous.items():
            iou = bbox_iou(cluster["bbox"], entry["bbox"])
            if iou > 0:
                candidates.append((iou, fire_id, cluster["local_cluster_id"]))
    candidates.sort(reverse=True)

    assigned_id_by_local = {}
    used_fire_ids = set()
    for iou, fire_id, local_id in candidates:
        if local_id in assigned_id_by_local or fire_id in used_fire_ids:
            continue
        assigned_id_by_local[local_id] = fire_id
        used_fire_ids.add(fire_id)

    next_id = int(registry.get("next_id", 1))
    for cluster in clusters:
        local_id = cluster["local_cluster_id"]
        if local_id in assigned_id_by_local:
            cluster["fire_id"] = assigned_id_by_local[local_id]
        else:
            fire_id = f"f{next_id:04d}"
            next_id += 1
            cluster["fire_id"] = fire_id

    registry["next_id"] = next_id
    return registry


def main() -> None:
    cfg = load_config()

    input_path = resolve(cfg, "data/raw/firms_detections_history.csv")
    if not os.path.exists(input_path):
        raise SystemExit(
            "Historique FIRMS absent : lance d'abord 01_fetch_firms.py."
        )

    raw = pd.read_csv(input_path)
    raw["dt_utc"] = pd.to_datetime(raw["dt_utc"], utc=True, errors="coerce")
    raw = raw.dropna(subset=["dt_utc", "lon", "lat"]).reset_index(drop=True)
    raw = fires_to_metric(raw, cfg)

    clustered = assign_spatial_clusters(
        raw,
        radius_km=float(cfg["cluster"]["radius_km"]),
        min_points=int(cfg["cluster"]["min_points"]),
        max_clusters=int(cfg["cluster"].get("max_active_fires", 20)),
    )

    if clustered.empty:
        raise SystemExit("Aucun feu suffisamment soutenu à l'échelle nationale.")

    france_boundary = load_france_boundary(cfg)
    retire_after_days = float(cfg["cluster"].get("retire_after_days", 5))
    retire_cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=retire_after_days)

    clusters = []
    rejected_foreign = 0
    rejected_dormant = 0
    for local_id in sorted(clustered["local_cluster_id"].unique()):
        subset = clustered.loc[clustered["local_cluster_id"] == local_id].copy()
        west, east = float(subset["lon"].min()), float(subset["lon"].max())
        south, north = float(subset["lat"].min()), float(subset["lat"].max())
        centroid_lon = float(subset["lon"].mean())
        centroid_lat = float(subset["lat"].mean())

        if france_boundary is not None and not france_boundary.contains(
            Point(centroid_lon, centroid_lat)
        ):
            rejected_foreign += 1
            continue

        # Un feu éteint depuis longtemps garde ses vieux points dans
        # l'historique cumulé pour toujours : sans cette coupure, il
        # continuerait à être retraité (krigeage compris) à chaque
        # exécution, indéfiniment. Ses dernières sorties publiées
        # restent en ligne telles quelles, juste plus mises à jour.
        if subset["dt_utc"].max() < retire_cutoff:
            rejected_dormant += 1
            continue

        clusters.append(
            {
                "local_cluster_id": int(local_id),
                "bbox": [
                    west - BBOX_MARGIN_DEG,
                    south - BBOX_MARGIN_DEG,
                    east + BBOX_MARGIN_DEG,
                    north + BBOX_MARGIN_DEG,
                ],
                "centroid": [centroid_lon, centroid_lat],
                "n_detections": int(len(subset)),
                "first_detection_utc": subset["dt_utc"].min().isoformat(),
                "last_detection_utc": subset["dt_utc"].max().isoformat(),
                "rows": subset.drop(
                    columns=["x", "y", "local_cluster_id"]
                ),
            }
        )

    if rejected_foreign:
        print(
            f"  {rejected_foreign} cluster(s) écarté(s) hors du "
            "territoire français"
        )
    if rejected_dormant:
        print(
            f"  {rejected_dormant} feu(x) écarté(s), éteint(s) depuis "
            f"plus de {retire_after_days:.0f} jours"
        )

    os.makedirs(PUBLISHED_DIR, exist_ok=True)
    registry_path = os.path.join(PUBLISHED_DIR, "fires_registry.json")
    registry = load_registry(registry_path)
    registry = assign_stable_ids(clusters, registry)

    now_iso = pd.Timestamp.now(tz="UTC").isoformat()
    for cluster in clusters:
        entry = registry["fires"].setdefault(
            cluster["fire_id"],
            {"first_seen_utc": now_iso},
        )
        entry["bbox"] = cluster["bbox"]
        entry["centroid"] = cluster["centroid"]
        entry["last_seen_utc"] = now_iso
        entry["last_detection_utc"] = cluster["last_detection_utc"]
        entry["n_detections"] = cluster["n_detections"]

    fires_raw_dir = resolve(cfg, "data/raw/fires")
    os.makedirs(fires_raw_dir, exist_ok=True)

    fires_index = []
    for cluster in sorted(clusters, key=lambda c: c["n_detections"], reverse=True):
        fire_id = cluster["fire_id"]
        fire_dir = os.path.join(fires_raw_dir, fire_id)
        os.makedirs(fire_dir, exist_ok=True)
        out_csv = os.path.join(fire_dir, "firms_detections_history.csv")
        cluster["rows"].to_csv(out_csv, index=False)

        fires_index.append(
            {
                "id": fire_id,
                "bbox": cluster["bbox"],
                "centroid": cluster["centroid"],
                "n_detections": cluster["n_detections"],
                "first_detection_utc": cluster["first_detection_utc"],
                "last_detection_utc": cluster["last_detection_utc"],
            }
        )

        print(
            f"  {fire_id} : {cluster['n_detections']} détections, "
            f"centre {cluster['centroid'][1]:.3f}N {cluster['centroid'][0]:.3f}E"
        )

    fires_index_path = os.path.join(PUBLISHED_DIR, "fires_index.json")
    with open(fires_index_path, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at_utc": now_iso, "fires": fires_index},
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    print(f"\n{len(fires_index)} feu(x) actif(s) détecté(s) nationalement.")
    print("Écrit :", fires_index_path)
    print("Écrit :", registry_path)


if __name__ == "__main__":
    main()
