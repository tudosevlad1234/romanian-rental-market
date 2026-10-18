from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Listing
from ..text import parse_number

BASE_URL = "https://www.storia.ro"
ROOM_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
}  # fmt: skip
FLOOR_WORDS = {
    "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5,
    "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10,
}  # fmt: skip
DOUBLE_HYPHEN = {"bistrita-nasaud": "bistrita--nasaud", "caras-severin": "caras--severin"}


def search_url(county: str, page: int) -> str:
    slug = DOUBLE_HYPHEN.get(county, county)
    return f"{BASE_URL}/ro/rezultate/inchiriere/apartament/{slug}?limit=36&by=LATEST&direction=DESC&page={page}"


def next_data(html: str) -> dict | None:
    element = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if element is None or not element.string:
        return None
    try:
        return json.loads(element.string)
    except json.JSONDecodeError:
        return None


def floor_number(value) -> int | None:
    if not value:
        return None
    code = str(value).strip().upper()
    if code in FLOOR_WORDS:
        return FLOOR_WORDS[code]
    match = re.search(r"FLOOR_(\d{1,2})$", code)
    if match:
        return int(match.group(1))
    if "GROUND" in code:
        return 0
    if "CELLAR" in code or "BASEMENT" in code:
        return -1
    return None


def place(location: dict | None) -> dict:
    location = location or {}
    levels: dict[str, str] = {}
    geocoding = (location.get("reverseGeocoding") or {}).get("locations") or []
    for level in geocoding:
        levels.setdefault(level.get("locationLevel"), level.get("name"))
    locality = next(
        (levels[k] for k in ("city", "county_capital", "commune", "village") if levels.get(k)),
        None,
    )
    street = ((location.get("address") or {}).get("street") or {}).get("name")
    coordinates = location.get("coordinates") or {}
    return {
        "locality": locality,
        "neighborhood": levels.get("district"),
        "street": street,
        "latitude": coordinates.get("latitude"),
        "longitude": coordinates.get("longitude"),
    }


def listing_from_item(item: dict, county: str) -> Listing | None:
    slug = item.get("slug")
    if not slug:
        return None
    total = item.get("totalPrice") or {}
    hidden = bool(item.get("hidePrice"))
    return Listing(
        source="storia",
        source_id=str(item.get("id") or slug),
        url=f"{BASE_URL}/ro/oferta/{slug}",
        title=item.get("title"),
        price=None if hidden else parse_number(total.get("value")),
        currency=None if hidden else total.get("currency"),
        rooms=ROOM_WORDS.get(str(item.get("roomsNumber") or "").upper()),
        surface_sqm=item.get("areaInSquareMeters"),
        floor=floor_number(item.get("floorNumber")),
        county=county,
        **place(item.get("location")),
    )


def parse_search(html: str, county: str) -> tuple[list[Listing], int | None]:
    data = next_data(html)
    page = (((data or {}).get("props") or {}).get("pageProps") or {}).get("data") or {}
    search = page.get("searchAds") if isinstance(page, dict) else None
    if not search:
        return [], None
    listings = [listing_from_item(item, county) for item in search.get("items") or []]
    pages = (search.get("pagination") or {}).get("totalPages")
    return [item for item in listings if item is not None], pages


def parse_offer(html: str) -> dict:
    data = next_data(html)
    ad = (((data or {}).get("props") or {}).get("pageProps") or {}).get("ad")
    if not ad:
        return {}
    characteristics = {c.get("key"): c for c in ad.get("characteristics") or [] if isinstance(c, dict)}
    description = ad.get("description")
    if description:
        description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
    total = (characteristics.get("building_floors_num") or {}).get("value")
    price = characteristics.get("price") or {}
    rooms = (characteristics.get("rooms_num") or {}).get("value")
    area = (characteristics.get("m") or {}).get("value")
    return {
        "title": ad.get("title"),
        "description": description,
        "floor": floor_number((characteristics.get("floor_no") or {}).get("value")),
        "total_floors": int(total) if total and str(total).isdigit() else None,
        "price": parse_number(price.get("value")),
        "currency": price.get("currency") or None,
        "rooms": int(rooms) if rooms and str(rooms).isdigit() else None,
        "surface_sqm": parse_number(area),
        **place(ad.get("location")),
    }
