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

    # Fenêtre temporelle
    df = df[(df["hours_ago"] >= -0.5) & (df["hours_ago"] <= max_hours)].copy()

    # Dédoublonnage grossier (même point, même heure, sources multiples)
    df["rlat"] = df["lat"].round(3)
    df["rlon"] = df["lon"].round(3)
    df = df.sort_values("frp", ascending=False).drop_duplicates(
        subset=["rlat", "rlon", "acq_date", "acq_time"]
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

    out_dir = resolve(cfg, "data/raw")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "firms_detections.csv")
    df.to_csv(out, index=False)
    print(f"\n{len(df)} détections retenues (<= {max_hours} h)")
    print(f"écrit : {out}")


if __name__ == "__main__":
    main()
