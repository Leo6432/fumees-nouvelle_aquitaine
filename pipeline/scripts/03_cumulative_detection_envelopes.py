"""
03 — Emprises cumulées des détections actives FIRMS.

Ce produit ne constitue ni un périmètre brûlé, ni un front de feu continu.
Il représente l'union cumulative des pixels de feu actif détectés par
les passages satellitaires successifs.

Sorties :
  data/web/detection_envelopes.geojson
  data/processed/detection_envelopes.gpkg
  data/processed/detection_envelopes_manifest.json
"""
from __future__ import annotations

import json
import os
from datetime import timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point
from shapely.ops import unary_union

from common import (
    fires_to_metric,
    load_config,
    resolve,
    save_geojson,
)


SNAPSHOT_STEP_HOURS = 6

# Empreintes circulaires prudentes autour des centres de pixels.
FOOTPRINT_RADIUS_M = {
    "VIIRS": 300.0,
    "MODIS": 750.0,
}

# Une nouvelle détection doit être soutenue par une voisine du même passage,
# ou être proche de l'emprise cumulative déjà établie.
SAME_PASS_NEIGHBOUR_M = 2000.0
CONTINUITY_DISTANCE_M = 3000.0

# Comble uniquement les très petits interstices entre pixels adjacents.
SMALL_GAP_CLOSING_M = 100.0

# Simplification purement graphique des frontières exportées.
BOUNDARY_SIMPLIFY_M = 30.0


def assign_spatial_clusters(
    df: pd.DataFrame,
    radius_km: float,
    min_points: int,
    max_clusters: int,
) -> pd.DataFrame:
    """Assigne les principaux clusters spatiaux par union-find."""
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

    roots = np.array(
        [find(index) for index in range(len(df))],
        dtype=int,
    )

    values, counts = np.unique(
        roots,
        return_counts=True,
    )

    ordered = [
        (int(root), int(count))
        for root, count in sorted(
            zip(values, counts),
            key=lambda item: int(item[1]),
            reverse=True,
        )
        if int(count) >= min_points
    ][:max_clusters]

    if not ordered:
        raise SystemExit("Aucun incendie suffisamment soutenu.")

    root_to_cluster = {
        root: cluster_id
        for cluster_id, (root, _) in enumerate(
            ordered,
            start=1,
        )
    }

    output = df.copy()
    output["cluster_id"] = [
        root_to_cluster.get(int(root), 0)
        for root in roots
    ]

    output = (
        output.loc[output["cluster_id"] > 0]
        .copy()
        .reset_index(drop=True)
    )

    return output


def confidence_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Conserve :
      - VIIRS : confiance nominale ou haute ;
      - MODIS : confiance numérique >= 30.
    """
    instrument = (
        df["instrument"]
        .astype(str)
        .str.upper()
    )

    confidence_text = (
        df["confidence"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    confidence_numeric = pd.to_numeric(
        df["confidence"],
        errors="coerce",
    )

    keep_viirs = (
        instrument.eq("VIIRS")
        & confidence_text.isin(["n", "h"])
    )

    keep_modis = (
        instrument.eq("MODIS")
        & confidence_numeric.ge(30)
    )

    return (
        df.loc[keep_viirs | keep_modis]
        .copy()
        .reset_index(drop=True)
    )


def supported_pass_points(
    pass_df: pd.DataFrame,
    cumulative_geometry,
) -> pd.DataFrame:
    """
    Écarte un point isolé sauf s'il prolonge une emprise déjà observée.
    """
    xy = pass_df[["x", "y"]].to_numpy(dtype=float)

    if len(pass_df) >= 2:
        tree = cKDTree(xy)
        neighbours = tree.query_ball_point(
            xy,
            r=SAME_PASS_NEIGHBOUR_M,
        )

        same_pass_support = np.array(
            [len(items) >= 2 for items in neighbours],
            dtype=bool,
        )
    else:
        same_pass_support = np.zeros(
            len(pass_df),
            dtype=bool,
        )

    continuity_support = np.zeros(
        len(pass_df),
        dtype=bool,
    )

    if (
        cumulative_geometry is not None
        and not cumulative_geometry.is_empty
    ):
        continuity_support = np.array(
            [
                cumulative_geometry.distance(
                    Point(float(x), float(y))
                ) <= CONTINUITY_DISTANCE_M
                for x, y in xy
            ],
            dtype=bool,
        )

    keep = same_pass_support | continuity_support

    return (
        pass_df.loc[keep]
        .copy()
        .reset_index(drop=True)
    )


def pass_footprint(pass_df: pd.DataFrame):
    """Union des empreintes des pixels retenus pour un passage."""
    footprints = []

    for row in pass_df.itertuples():
        instrument = str(row.instrument).upper()

        radius = FOOTPRINT_RADIUS_M.get(
            instrument,
            300.0,
        )

        footprints.append(
            Point(
                float(row.x),
                float(row.y),
            ).buffer(radius)
        )

    if not footprints:
        return None

    geometry = unary_union(footprints)

    if SMALL_GAP_CLOSING_M > 0:
        geometry = (
            geometry
            .buffer(SMALL_GAP_CLOSING_M)
            .buffer(-SMALL_GAP_CLOSING_M)
        )

    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    return geometry


def build_cluster_states(
    cluster_df: pd.DataFrame,
) -> list[dict]:
    """Construit l'emprise cumulative après chaque passage soutenu."""
    cluster_df = cluster_df.sort_values(
        ["dt_utc", "source", "lon", "lat"]
    )

    cumulative = None
    cumulative_detection_count = 0
    cumulative_sources: set[str] = set()
    states = []

    grouped = cluster_df.groupby(
        ["dt_utc", "source", "satellite", "instrument"],
        sort=True,
        dropna=False,
    )

    for (
        dt_utc,
        source,
        satellite,
        instrument,
    ), pass_df in grouped:
        supported = supported_pass_points(
            pass_df,
            cumulative,
        )

        if supported.empty:
            print(
                "  passage écarté :",
                dt_utc,
                source,
                f"({len(pass_df)} détection(s), aucune soutenue)",
            )
            continue

        footprint = pass_footprint(supported)

        if footprint is None or footprint.is_empty:
            continue

        if cumulative is None:
            cumulative = footprint
        else:
            cumulative = unary_union(
                [cumulative, footprint]
            )

        if not cumulative.is_valid:
            cumulative = cumulative.buffer(0)

        cumulative_detection_count += len(supported)
        cumulative_sources.add(str(source))

        states.append(
            {
                "observed_until": pd.Timestamp(dt_utc),
                "geometry": cumulative,
                "supported_detections_cumulative":
                    cumulative_detection_count,
                "sources_cumulative":
                    sorted(cumulative_sources),
                "last_source": str(source),
                "last_satellite": str(satellite),
                "last_instrument": str(instrument),
            }
        )

    return states


def select_six_hour_snapshots(
    states: list[dict],
) -> list[dict]:
    """
    Sélectionne l'état réellement observé le plus récent à chaque pas de 6 h.
    Aucun passage futur n'est utilisé.
    """
    if not states:
        return []

    first_time = states[0]["observed_until"]
    last_time = states[-1]["observed_until"]

    targets = [first_time]

    target = first_time + timedelta(
        hours=SNAPSHOT_STEP_HOURS
    )

    while target < last_time:
        targets.append(target)
        target += timedelta(
            hours=SNAPSHOT_STEP_HOURS
        )

    targets.append(last_time)

    selected = []
    previous_state_index = None

    for target_time in targets:
        valid_indices = [
            index
            for index, state in enumerate(states)
            if state["observed_until"] <= target_time
        ]

        if not valid_indices:
            continue

        state_index = valid_indices[-1]

        if state_index == previous_state_index:
            continue

        state = states[state_index].copy()
        state["target_time"] = target_time
        selected.append(state)

        previous_state_index = state_index

    return selected


def iso_utc(timestamp: pd.Timestamp) -> str:
    return (
        timestamp
        .tz_convert("UTC")
        .isoformat()
        .replace("+00:00", "Z")
    )


def main() -> None:
    cfg = load_config()

    input_path = resolve(
        cfg,
        "data/raw/firms_detections_history.csv",
    )

    if not os.path.exists(input_path):
        raise SystemExit(
            "Historique FIRMS absent : lance d'abord "
            "01_fetch_firms.py."
        )

    raw = pd.read_csv(input_path)
    raw["dt_utc"] = pd.to_datetime(
        raw["dt_utc"],
        utc=True,
        errors="coerce",
    )

    raw = raw.dropna(
        subset=["dt_utc", "lon", "lat"]
    ).reset_index(drop=True)

    start_value = cfg["time_window"].get("start", "auto")

    if start_value != "auto":
        start_utc = pd.Timestamp(start_value)

        if start_utc.tzinfo is None:
            start_utc = start_utc.tz_localize("UTC")
        else:
            start_utc = start_utc.tz_convert("UTC")

        raw = raw.loc[
            raw["dt_utc"] >= start_utc
        ].copy()

        print(
            "Origine historique des emprises :",
            start_utc.isoformat(),
        )

    raw = fires_to_metric(raw, cfg)

    clustered = assign_spatial_clusters(
        raw,
        radius_km=float(
            cfg["cluster"]["radius_km"]
        ),
        min_points=int(
            cfg["cluster"]["min_points"]
        ),
        max_clusters=int(
            cfg["cluster"].get("max_clusters", 2)
        ),
    )

    filtered = confidence_filter(clustered)

    print(
        "Détections conservées après contrôle de confiance :",
        len(filtered),
        "/",
        len(clustered),
    )

    polygon_records = []
    line_records = []
    manifest_clusters = []

    for cluster_id in sorted(
        filtered["cluster_id"].unique()
    ):
        cluster_df = filtered.loc[
            filtered["cluster_id"] == cluster_id
        ].copy()

        print(
            f"\nCluster {cluster_id} : "
            f"{len(cluster_df)} détections après confiance"
        )

        states = build_cluster_states(cluster_df)

        if not states:
            print("  aucun état cumulatif valide")
            continue

        snapshots = select_six_hour_snapshots(
            states
        )

        first_time = states[0]["observed_until"]
        last_time = states[-1]["observed_until"]

        for snapshot_index, snapshot in enumerate(
            snapshots,
            start=1,
        ):
            polygon = snapshot["geometry"]

            elapsed_h = (
                snapshot["observed_until"]
                - first_time
            ).total_seconds() / 3600.0

            remaining_h = (
                last_time
                - snapshot["observed_until"]
            ).total_seconds() / 3600.0

            properties = {
                "cluster_id": int(cluster_id),
                "snapshot_index": int(snapshot_index),
                "estimated_time_utc": iso_utc(
                    snapshot["observed_until"]
                ),
                "observed_until_utc": iso_utc(
                    snapshot["observed_until"]
                ),
                "target_time_utc": iso_utc(
                    snapshot["target_time"]
                ),
                "arrival_h": float(elapsed_h),
                "hours_ago": float(remaining_h),
                "supported_detections_cumulative":
                    int(
                        snapshot[
                            "supported_detections_cumulative"
                        ]
                    ),
                "sources_cumulative":
                    ", ".join(
                        snapshot["sources_cumulative"]
                    ),
                "last_source":
                    snapshot["last_source"],
                "last_satellite":
                    snapshot["last_satellite"],
                "last_instrument":
                    snapshot["last_instrument"],
                "detected_area_km2":
                    float(polygon.area / 1_000_000.0),
                "product_type":
                    "cumulative_active_fire_detection_extent",
            }

            polygon_records.append(
                {
                    **properties,
                    "geometry": polygon,
                }
            )

            boundary = polygon.boundary.simplify(
                BOUNDARY_SIMPLIFY_M,
                preserve_topology=True,
            )

            line_records.append(
                {
                    **properties,
                    "geometry": boundary,
                }
            )

        manifest_clusters.append(
            {
                "cluster_id": int(cluster_id),
                "first_supported_detection_utc":
                    iso_utc(first_time),
                "last_supported_detection_utc":
                    iso_utc(last_time),
                "pass_states": len(states),
                "published_snapshots":
                    len(snapshots),
                "final_detected_area_km2":
                    float(
                        states[-1]["geometry"].area
                        / 1_000_000.0
                    ),
            }
        )

        print(
            f"  {len(states)} passages soutenus ; "
            f"{len(snapshots)} étapes publiées ; "
            f"aire finale détectée : "
            f"{states[-1]['geometry'].area / 1_000_000.0:.2f} km²"
        )

    if not polygon_records:
        raise SystemExit(
            "Aucune emprise cumulative n'a été produite."
        )

    polygons = gpd.GeoDataFrame(
        polygon_records,
        geometry="geometry",
        crs=cfg["crs_metric"],
    )

    lines = gpd.GeoDataFrame(
        line_records,
        geometry="geometry",
        crs=cfg["crs_metric"],
    )

    processed_dir = resolve(
        cfg,
        cfg["outputs"]["processed_dir"],
    )

    os.makedirs(
        processed_dir,
        exist_ok=True,
    )

    gpkg_path = os.path.join(
        processed_dir,
        "detection_envelopes.gpkg",
    )

    # Stabilisation des identifiants de clusters entre exécutions.
    #
    # Les clusters bruts sont classés par nombre de détections. Leur ordre
    # pourrait donc changer. On raccorde ici chaque cluster courant au
    # cluster précédent présentant le meilleur recouvrement géométrique.
    if os.path.exists(gpkg_path):
        previous_ids = gpd.read_file(
            gpkg_path,
            layer="cumulative_detection_envelopes",
        )

        if not previous_ids.empty:
            previous_ids = previous_ids.to_crs(
                cfg["crs_metric"]
            ).copy()

            previous_ids["observed_until_dt"] = pd.to_datetime(
                previous_ids["observed_until_utc"],
                utc=True,
                errors="coerce",
            )

            polygons["observed_until_dt"] = pd.to_datetime(
                polygons["observed_until_utc"],
                utc=True,
                errors="coerce",
            )

            previous_final_ids = (
                previous_ids.sort_values(
                    [
                        "cluster_id",
                        "observed_until_dt",
                        "snapshot_index",
                    ]
                )
                .groupby("cluster_id", as_index=False)
                .tail(1)
            )

            current_final_ids = (
                polygons.sort_values(
                    [
                        "cluster_id",
                        "observed_until_dt",
                        "snapshot_index",
                    ]
                )
                .groupby("cluster_id", as_index=False)
                .tail(1)
            )

            candidate_pairs = []

            for old_row in previous_final_ids.itertuples():
                for new_row in current_final_ids.itertuples():
                    intersection_area = old_row.geometry.intersection(
                        new_row.geometry
                    ).area

                    union_area = old_row.geometry.union(
                        new_row.geometry
                    ).area

                    iou = (
                        intersection_area / union_area
                        if union_area > 0
                        else 0.0
                    )

                    candidate_pairs.append(
                        (
                            float(intersection_area),
                            float(iou),
                            int(old_row.cluster_id),
                            int(new_row.cluster_id),
                        )
                    )

            candidate_pairs.sort(reverse=True)

            cluster_id_map = {}
            used_previous_ids = set()

            for (
                intersection_area,
                iou,
                previous_cluster_id,
                current_cluster_id,
            ) in candidate_pairs:
                if intersection_area <= 0:
                    continue

                if current_cluster_id in cluster_id_map:
                    continue

                if previous_cluster_id in used_previous_ids:
                    continue

                cluster_id_map[current_cluster_id] = (
                    previous_cluster_id
                )
                used_previous_ids.add(previous_cluster_id)

            current_ids = sorted(
                int(value)
                for value in polygons["cluster_id"].unique()
            )

            next_available_id = 1

            for current_cluster_id in current_ids:
                if current_cluster_id in cluster_id_map:
                    continue

                if (
                    current_cluster_id
                    not in used_previous_ids
                ):
                    assigned_id = current_cluster_id
                else:
                    while next_available_id in used_previous_ids:
                        next_available_id += 1

                    assigned_id = next_available_id

                cluster_id_map[current_cluster_id] = assigned_id
                used_previous_ids.add(assigned_id)

            polygons["cluster_id"] = (
                polygons["cluster_id"]
                .astype(int)
                .map(cluster_id_map)
                .astype(int)
            )

            lines["cluster_id"] = (
                lines["cluster_id"]
                .astype(int)
                .map(cluster_id_map)
                .astype(int)
            )

            for item in manifest_clusters:
                item["cluster_id"] = int(
                    cluster_id_map[
                        int(item["cluster_id"])
                    ]
                )

            polygons = polygons.drop(
                columns=["observed_until_dt"]
            )

            print(
                "Correspondance persistante des clusters :",
                ", ".join(
                    f"{old_id}->{new_id}"
                    for old_id, new_id in sorted(
                        cluster_id_map.items()
                    )
                ),
            )

    # Garantie de non-régression entre deux exécutions.
    #
    # Si une ancienne sortie existe, son emprise finale devient un
    # plancher géométrique : aucune portion déjà publiée ne peut
    # disparaître lors du recalcul suivant.
    if os.path.exists(gpkg_path):
        previous = gpd.read_file(
            gpkg_path,
            layer="cumulative_detection_envelopes",
        )

        if not previous.empty:
            previous = previous.to_crs(
                cfg["crs_metric"]
            ).copy()

            previous["observed_until_dt"] = pd.to_datetime(
                previous["observed_until_utc"],
                utc=True,
                errors="coerce",
            )

            polygons["observed_until_dt"] = pd.to_datetime(
                polygons["observed_until_utc"],
                utc=True,
                errors="coerce",
            )

            previous_final = (
                previous.sort_values(
                    [
                        "cluster_id",
                        "observed_until_dt",
                        "snapshot_index",
                    ]
                )
                .groupby("cluster_id", as_index=False)
                .tail(1)
            )

            current_final = (
                polygons.sort_values(
                    [
                        "cluster_id",
                        "observed_until_dt",
                        "snapshot_index",
                    ]
                )
                .groupby("cluster_id", as_index=False)
                .tail(1)
            )

            restored_area_m2 = 0.0

            for old_row in previous_final.itertuples():
                old_geometry = old_row.geometry

                if (
                    old_geometry is None
                    or old_geometry.is_empty
                ):
                    continue

                candidates = []

                for new_row in current_final.itertuples():
                    new_geometry = new_row.geometry

                    intersection_area = (
                        old_geometry.intersection(
                            new_geometry
                        ).area
                    )

                    distance = old_geometry.distance(
                        new_geometry
                    )

                    candidates.append(
                        (
                            float(intersection_area),
                            -float(distance),
                            int(new_row.cluster_id),
                        )
                    )

                if not candidates:
                    raise SystemExit(
                        "Aucun cluster courant disponible pour "
                        "préserver l'ancienne emprise."
                    )

                _, _, matched_cluster_id = max(
                    candidates
                )

                old_time = pd.Timestamp(
                    old_row.observed_until_dt
                )

                eligible = (
                    polygons["cluster_id"].eq(
                        matched_cluster_id
                    )
                    & polygons[
                        "observed_until_dt"
                    ].ge(old_time)
                )

                if not eligible.any():
                    raise SystemExit(
                        "La nouvelle chronologie se termine avant "
                        "l'ancienne sortie : publication refusée."
                    )

                for index in polygons.index[eligible]:
                    current_geometry = polygons.at[
                        index,
                        "geometry",
                    ]

                    missing = old_geometry.difference(
                        current_geometry
                    )

                    if missing.is_empty:
                        continue

                    restored_area_m2 += missing.area

                    updated = unary_union(
                        [
                            current_geometry,
                            old_geometry,
                        ]
                    )

                    if not updated.is_valid:
                        updated = updated.buffer(0)

                    polygons.at[
                        index,
                        "geometry",
                    ] = updated

                    polygons.at[
                        index,
                        "detected_area_km2",
                    ] = float(
                        updated.area / 1_000_000.0
                    )

            polygons = polygons.drop(
                columns=["observed_until_dt"]
            )

            # Les lignes doivent être reconstruites à partir des
            # polygones éventuellement restaurés.
            lines = polygons.copy()
            lines["geometry"] = polygons.geometry.apply(
                lambda geometry: geometry.boundary.simplify(
                    BOUNDARY_SIMPLIFY_M,
                    preserve_topology=True,
                )
            )
            lines = gpd.GeoDataFrame(
                lines,
                geometry="geometry",
                crs=cfg["crs_metric"],
            )

            print(
                "Plancher inter-exécutions : "
                f"{restored_area_m2 / 1_000_000.0:.6f} km² "
                "restaurés"
            )

        os.remove(gpkg_path)

    polygons.to_file(
        gpkg_path,
        layer="cumulative_detection_envelopes",
        driver="GPKG",
    )

    web_path = save_geojson(
        lines,
        cfg,
        "detection_envelopes.geojson",
    )

    metadata = {
        "generated_at_utc":
            pd.Timestamp.now(tz="UTC")
            .isoformat()
            .replace("+00:00", "Z"),
        "product_type":
            "cumulative_active_fire_detection_extent",
        "product_label":
            "Emprises cumulées des détections actives FIRMS",
        "not_a_burn_perimeter": True,
        "not_a_continuous_fire_front": True,
        "not_an_arrival_time_interpolation": True,
        "snapshot_step_hours":
            SNAPSHOT_STEP_HOURS,
        "confidence_filter": {
            "VIIRS": ["nominal", "high"],
            "MODIS_minimum": 30,
        },
        "footprint_radius_m":
            FOOTPRINT_RADIUS_M,
        "same_pass_neighbour_m":
            SAME_PASS_NEIGHBOUR_M,
        "continuity_distance_m":
            CONTINUITY_DISTANCE_M,
        "clusters":
            manifest_clusters,
    }

    with open(
        web_path,
        "r",
        encoding="utf-8",
    ) as stream:
        payload = json.load(stream)

    payload["metadata"] = metadata
    payload["bbox"] = [
        float(value)
        for value in lines.to_crs(
            cfg["crs_geographic"]
        ).total_bounds
    ]

    with open(
        web_path,
        "w",
        encoding="utf-8",
    ) as stream:
        json.dump(
            payload,
            stream,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    manifest_path = os.path.join(
        processed_dir,
        "detection_envelopes_manifest.json",
    )

    with open(
        manifest_path,
        "w",
        encoding="utf-8",
    ) as stream:
        json.dump(
            metadata,
            stream,
            ensure_ascii=False,
            indent=2,
        )

    print("\nÉcrit :", gpkg_path)
    print("Écrit :", web_path)
    print("Écrit :", manifest_path)
    print("Nombre total d'étapes :", len(lines))


if __name__ == "__main__":
    main()
