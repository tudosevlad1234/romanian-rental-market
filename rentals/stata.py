from __future__ import annotations

from pathlib import Path

import pandas as pd

STATA_COLUMNS = (
    "fingerprint", "county", "county_group", "locality", "neighborhood", "price_eur", "surface_sqm", "rooms",
    "rooms_cat", "floor", "ground_floor", "floor_missing", "total_floors", "year_built", "eur_per_sqm", "ln_rent",
    "ln_surface", "price_suspect", "n_sources", "sources", "latitude", "longitude",
)  # fmt: skip


def stata_frame(data: pd.DataFrame) -> pd.DataFrame:
    frame = data[[c for c in STATA_COLUMNS if c in data]].copy()
    for column in frame.columns:
        if isinstance(frame[column].dtype, pd.CategoricalDtype):
            frame[column] = frame[column].astype(str)
        elif pd.api.types.is_bool_dtype(frame[column]):
            frame[column] = frame[column].astype(int)
        elif pd.api.types.is_string_dtype(frame[column]) or frame[column].dtype == object:
            frame[column] = frame[column].fillna("").astype(str)
    return frame


def export(data: pd.DataFrame, directory: str | Path) -> dict[str, Path]:
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    frame = stata_frame(data)
    csv_path, dta_path = folder / "rentals.csv", folder / "rentals.dta"
    frame.to_csv(csv_path, index=False)
    frame.to_stata(dta_path, write_index=False, version=118)
    return {"csv": csv_path, "dta": dta_path}
