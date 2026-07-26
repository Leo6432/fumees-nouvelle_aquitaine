"""
01 — Récupération des détections thermiques FIRMS.

Utilise le proxy Cloudflare du site (qui détient la clé FIRMS) pour rester
cohérent avec la carte web. Sauvegarde un CSV propre dans data/raw.

Usage :
    python scripts/01_fetch_firms.py
"""
from __future__ import annotations
import os
import io
import sys
import datetime as dt
import requests
import pandas as pd

from common import load_config, resolve, ROOT

# Proxy Cloudflare (même que le site). Modifiable si besoin.
PROXY = os.environ.get(
    "FIRMS_PROXY",
    "https://fumees-openaq.nicolaslecorvec.workers.dev",
).rstrip("/")

# Flux FIRMS (VIIRS = meilleure résolution ; MODIS complète la couverture).
SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"]


def fetch_source(source: str, bbox: list[float], days: int = 3) -> pd.DataFrame:
    """Récupère un flux FIRMS et renvoie un DataFrame (ou vide)."""
    west, south, east, north = bbox
    bbox_str = f"{west},{south},{east},{north}"
    url = f"{PROXY}/firms/{source}/{bbox_str}/{days}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    if not r.text.strip() or "\n" not in r.text:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(r.text))
    df["source"] = source
    return df


def to_utc(row) -> dt.datetime:
    """Combine acq_date + acq_time (UTC)."""
    t = str(int(row["acq_time"])).zfill(4)
    return dt.datetime.strptime(
        f"{row['acq_date']} {t[:2]}:{t[2:]}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=dt.timezone.utc)


def main():
    cfg = load_config()
    bbox = cfg["bbox"]
    max_hours = cfg["time_window"]["max_hours"]

    frames = []
    for s in SOURCES:
        try:
            df = fetch_source(s, bbox)
            print(f"{s:20s} : {len(df):5d} détections")
            if len(df):
                frames.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"{s:20s} : échec ({e})")

    if not frames:
        sys.exit("Aucune détection récupérée.")

    df = pd.concat(frames, ignore_index=True)

    # Normalisation
    df = df.rename(columns={"latitude": "lat", "longitude": "lon"})
    df["dt_utc"] = df.apply(to_utc, axis=1)
    now = dt.datetime.now(dt.timezone.utc)
    df["hours_ago"] = (now - df["dt_utc"]).dt.total_seconds() / 3600.0
    df["frp"] = pd.to_numeric(df.get("frp", 1), errors="coerce").fillna(1.0)

    # Dimensions nominales du pixel FIRMS en kilomètres.
    # Elles seront utilisées ensuite pour construire une empreinte
    # dépendant du pixel plutôt qu'un buffer circulaire fixe.
    for column in ("scan", "track"):
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    # Écarter uniquement les dates futures aberrantes.
    # Les détections anciennes sont conservées dans une archive cumulative.
    df = df[df["hours_ago"] >= -0.5].copy()

    out_dir = resolve(cfg, "data/raw")
    os.makedirs(out_dir, exist_ok=True)

    out = os.path.join(out_dir, "firms_detections.csv")
    history_out = os.path.join(out_dir, "firms_detections_history.csv")

    # Initialisation de l'historique :
    # - archive cumulative si elle existe déjà ;
    # - sinon fichier de travail existant, afin de ne rien perdre
    #   lors de la première exécution après cette modification.
    history = pd.DataFrame()
    history_seed = history_out if os.path.exists(history_out) else out

    if os.path.exists(history_seed):
        try:
            history = pd.read_csv(history_seed)
            print(
                f"Historique chargé : {len(history)} détections "
                f"depuis {history_seed}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"Historique illisible, ignoré : {e}")
            history = pd.DataFrame()

    # Fusion de l'historique existant et des données nouvellement téléchargées.
    if len(history):
        df = pd.concat([history, df], ignore_index=True, sort=False)

    # Normalisation temporelle après fusion.
    df["dt_utc"] = pd.to_datetime(df["dt_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["dt_utc", "lat", "lon"]).copy()

    now = dt.datetime.now(dt.timezone.utc)
    df["hours_ago"] = (
        now - df["dt_utc"]
    ).dt.total_seconds() / 3600.0

    df["frp"] = pd.to_numeric(
        df.get("frp", 1),
        errors="coerce",
    ).fillna(1.0)

    # Dédoublonnage grossier :
    # même position arrondie et même heure d'acquisition.
    # La détection avec le FRP maximal est conservée.
    df["rlat"] = pd.to_numeric(df["lat"], errors="coerce").round(3)
    df["rlon"] = pd.to_numeric(df["lon"], errors="coerce").round(3)

    df = (
        df.sort_values("frp", ascending=False)
        .drop_duplicates(
            subset=["rlat", "rlon", "acq_date", "acq_time"],
            keep="first",
        )
        .sort_values("dt_utc")
    )

    keep = [
        "lat",
        "lon",
        "dt_utc",
        "hours_ago",
        "frp",
        "scan",
        "track",
        "source",
        "acq_date",
        "acq_time",
        "confidence",
        "satellite",
        "instrument",
    ]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].reset_index(drop=True)

    # L'archive cumulative est la source de vérité et ne perd
    # aucune détection déjà enregistrée.
    df.to_csv(history_out, index=False)

    # Le fichier de travail reste limité à la fenêtre opérationnelle
    # configurée, afin de préserver le comportement des autres scripts.
    recent = df.loc[
        (df["hours_ago"] >= -0.5)
        & (df["hours_ago"] <= max_hours)
    ].copy()

    recent.to_csv(out, index=False)

    print(f"\n{len(df)} détections dans l'historique cumulatif")
    print(
        f"{len(recent)} détections dans la fenêtre "
        f"opérationnelle de {max_hours} h"
    )
    print(f"archive cumulative : {history_out}")
    print(f"vue opérationnelle : {out}")


if __name__ == "__main__":
    main()
