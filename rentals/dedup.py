from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import Listing
from .text import flat

ABBREVIATIONS = {
    r"\bstr\b\.?": "strada",
    r"\bbd\b\.?": "bulevardul",
    r"\bbld\b\.?": "bulevardul",
    r"\bsos\b\.?": "soseaua",
    r"\bcal\b\.?": "calea",
    r"\baleea\b": "alee",
}


@dataclass(frozen=True)
class MatchRules:
    surface_tolerance_sqm: float = 2.0
    price_tolerance: float = 0.05
    location_threshold: float = 85.0
    description_threshold: float = 90.0
    geo_meters: float = 150.0


def normalise(text: str | None) -> str:
    cleaned = flat(text)
    for pattern, replacement in ABBREVIATIONS.items():
        cleaned = re.sub(pattern, replacement, cleaned)
    return re.sub(r"[^a-z0-9 ]", " ", cleaned).replace("  ", " ").strip()


def address(listing: Listing) -> str:
    parts = [listing.street, listing.neighborhood, listing.locality]
    return normalise(" ".join(p for p in parts if p))


def close(a: float | None, b: float | None, tolerance: float, relative: bool = False) -> bool | None:
    if a is None or b is None:
        return None
    gap = abs(a - b)
    return gap <= tolerance * max(abs(a), abs(b)) if relative else gap <= tolerance


def same_ad(first: Listing, second: Listing, rules: MatchRules | None = None) -> bool:
    rules = rules or MatchRules()
    if first.county and second.county and first.county != second.county:
        return False
    if first.rooms is not None and second.rooms is not None and first.rooms != second.rooms:
        return False
    if not close(first.surface_sqm, second.surface_sqm, rules.surface_tolerance_sqm):
        return False
    if close(first.price_eur, second.price_eur, rules.price_tolerance, relative=True) is False:
        return False
    address_a, address_b = address(first), address(second)
    if address_a and address_b and fuzz.token_set_ratio(address_a, address_b) < rules.location_threshold:
        return False
    if first.street and second.street and address_a and address_b:
        return True
    return geo_close(first, second, rules.geo_meters) or text_similar(first, second, rules)


def distance_metres(first: Listing, second: Listing) -> float | None:
    values = (first.latitude, first.longitude, second.latitude, second.longitude)
    if any(v is None for v in values):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, values)
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(a))


def geo_close(first: Listing, second: Listing, metres: float) -> bool:
    distance = distance_metres(first, second)
    return distance is not None and distance <= metres


def text_similar(first: Listing, second: Listing, rules: MatchRules) -> bool:
    a, b = normalise(first.description)[:400], normalise(second.description)[:400]
    if not a or not b:
        return False
    return fuzz.token_set_ratio(a, b) >= rules.description_threshold


def cluster(listings: list[Listing], rules: MatchRules | None = None) -> list[list[int]]:
    parent = list(range(len(listings)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    blocks: dict[tuple, list[int]] = {}
    for index, item in enumerate(listings):
        blocks.setdefault((item.county, item.rooms), []).append(index)
    for members in blocks.values():
        members.sort(key=lambda i: listings[i].surface_sqm or -1.0)
        window = (rules or MatchRules()).surface_tolerance_sqm
        for position, i in enumerate(members):
            for j in members[position + 1 :]:
                gap = (listings[j].surface_sqm or -1.0) - (listings[i].surface_sqm or -1.0)
                if gap > window:
                    break
                if same_ad(listings[i], listings[j], rules):
                    parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for index in range(len(listings)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())
