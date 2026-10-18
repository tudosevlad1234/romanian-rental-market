from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .filters import FilterLimits, exclusion_reason
from .fx import RonPerEur
from .models import Listing
from .text import detect_currency, extract_rooms, extract_surface, extract_year, flat, floor_info


@dataclass(frozen=True)
class Plausibility:
    min_surface: float = 8.0
    max_surface: float = 400.0
    max_rooms: int = 10
    max_floor: int = 30
    min_rent_eur: float = 50.0
    max_eur_per_sqm: float = 40.0
    min_eur_per_sqm: float = 1.5


def enrich(listing: Listing, rate: RonPerEur, limits: Plausibility | None = None) -> Listing:
    limits = limits or Plausibility()
    text = f"{listing.title or ''} {listing.description or ''}"
    updated = replace(listing, extra=dict(listing.extra))
    if updated.rooms is None:
        updated.rooms = extract_rooms(listing.title) or extract_rooms(listing.description)
    if updated.surface_sqm is None:
        updated.surface_sqm = extract_surface(text)
    if updated.floor is None:
        floor, total = floor_info(text)
        updated.floor = floor
        updated.total_floors = updated.total_floors or total
    if updated.year_built is None:
        updated.year_built = extract_year(text) if "constructie" in flat(text) else None
    if updated.currency is None and updated.price is not None:
        updated.currency = detect_currency(text)
    updated.price_eur = rate.to_eur(updated.price, updated.currency)
    if updated.surface_sqm is not None and not limits.min_surface <= updated.surface_sqm <= limits.max_surface:
        updated.extra["surface_rejected"] = updated.surface_sqm
        updated.surface_sqm = None
    if updated.rooms is not None and not 1 <= updated.rooms <= limits.max_rooms:
        updated.rooms = None
    if updated.floor is not None and not -2 <= updated.floor <= limits.max_floor:
        updated.floor = None
    return updated


def clean_value(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def frame_to_listings(frame: pd.DataFrame) -> list[Listing]:
    names = (
        "title", "description", "price", "currency", "price_eur", "rooms", "surface_sqm", "floor",
        "total_floors", "year_built", "county", "locality", "neighborhood", "street", "latitude", "longitude",
    )  # fmt: skip
    listings = []
    for row in frame.to_dict(orient="records"):
        values = {name: clean_value(row.get(name)) for name in names}
        for name in ("rooms", "floor", "total_floors", "year_built"):
            if values[name] is not None:
                values[name] = int(values[name])
        listings.append(Listing(source="db", source_id=str(row.get("fingerprint")), url=row.get("url") or "", **values))
    return listings


def build_dataset(
    frame: pd.DataFrame,
    limits: Plausibility | None = None,
    filters: FilterLimits | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    limits = limits or Plausibility()
    filters = filters or FilterLimits()
    listings = frame_to_listings(frame)
    reasons = pd.Series([exclusion_reason(item, filters) for item in listings], index=frame.index)
    data = frame.loc[reasons.isna()].copy()
    data["eur_per_sqm"] = data["price_eur"] / data["surface_sqm"].where(data["surface_sqm"] > 0)
    suspect = pd.Series("", index=data.index)
    suspect[data["eur_per_sqm"] > limits.max_eur_per_sqm] = "eur_per_sqm_extreme"
    suspect[data["eur_per_sqm"] < limits.min_eur_per_sqm] = "eur_per_sqm_extreme"
    suspect[data["price_eur"] < limits.min_rent_eur] = "below_min"
    data["price_suspect"] = suspect != ""
    data["price_suspect_reason"] = suspect
    data["rooms_cat"] = data["rooms"].clip(upper=4)
    data["rooms_topcoded"] = (data["rooms"] >= 4).astype(int)
    data["ground_floor"] = (data["floor"] <= 0).astype("float").where(data["floor"].notna())
    data["ln_rent"] = np.log(data["price_eur"].where(data["price_eur"] > 0))
    data["ln_surface"] = np.log(data["surface_sqm"].where(data["surface_sqm"] > 0))
    return data, reasons
