"""Utilitaires partagés : configuration, projection, entrées/sorties."""
from __future__ import annotations
import os
import yaml
import numpy as np
import pandas as pd
import geopandas as gpd
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_config(path: str | None = None) -> dict:
    """Charge config/config.yaml (ou un chemin fourni)."""
    path = path or os.path.join(ROOT, "config", "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(cfg: dict, rel: str) -> str:
    """Résout un chemin relatif à la racine du projet."""
    return os.path.join(ROOT, rel)


def make_transformer(cfg: dict):
    """Transformer WGS84 -> projeté métrique (et inverse)."""
    fwd = Transformer.from_crs(cfg["crs_geographic"], cfg["crs_metric"], always_xy=True)
    inv = Transformer.from_crs(cfg["crs_metric"], cfg["crs_geographic"], always_xy=True)
    return fwd, inv


def fires_to_metric(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Ajoute colonnes x,y (mètres, CRS projeté) à un DataFrame lon/lat."""
    fwd, _ = make_transformer(cfg)
    x, y = fwd.transform(df["lon"].values, df["lat"].values)
    out = df.copy()
    out["x"] = x
    out["y"] = y
    return out


def save_geojson(gdf: gpd.GeoDataFrame, cfg: dict, name: str):
    """Écrit un GeoDataFrame en GeoJSON (WGS84) dans data/web."""
    web = resolve(cfg, cfg["outputs"]["web_dir"])
    os.makedirs(web, exist_ok=True)
    path = os.path.join(web, name)
    gdf.to_crs(cfg["crs_geographic"]).to_file(path, driver="GeoJSON")
    print(f"  écrit : {path}  ({len(gdf)} entités)")
    return path
