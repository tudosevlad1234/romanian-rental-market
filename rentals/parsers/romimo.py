from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Listing
from ..text import (
    detect_currency,
    extract_rooms,
    extract_surface,
    extract_year,
    flat,
    floor_info,
    listing_id_from_url,
    parse_number,
)

BASE_URL = "https://www.romimo.ro"
ONCLICK_URL = re.compile(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]")
COORDINATES = re.compile(r"var\s+lat\s*=\s*(-?\d+(?:\.\d+)?)\s*;\s*var\s+lng\s*=\s*(-?\d+(?:\.\d+)?)")
LABELS = {
    "suprafata": "surface",
    "numar camere": "rooms",
    "etaj": "floor",
    "anul constructiei": "year",
}


def search_url(county: str, page: int) -> str:
    return f"{BASE_URL}/apartamente/inchiriere/{county}/?pag={page}"


def card_url(card) -> str | None:
    link = card.find("a", href=True)
    if link is not None:
        return link["href"]
    match = ONCLICK_URL.search(card.get("onclick", ""))
    return match.group(1) if match else None


def parse_search(html: str, county: str) -> tuple[list[Listing], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for card in soup.select("div.article-item"):
        url = card_url(card)
        if not url:
            continue
        if url.startswith("/"):
            url = BASE_URL + url
        price_node = card.select_one(".article-price")
        price_text = price_node.get_text(" ", strip=True) if price_node else None
        title_node = card.select_one(".article-title, h2, h3")
        listings.append(
            Listing(
                source="romimo",
                source_id=listing_id_from_url(url),
                url=url,
                title=title_node.get_text(" ", strip=True) if title_node else None,
                price=parse_number(price_text),
                currency=detect_currency(price_text),
                county=county,
            )
        )
    pages = [
        int(m.group(1)) for a in soup.select("ul.pagination a") if (m := re.search(r"pag=(\d+)", a.get("href", "")))
    ]
    return listings, max(pages) if pages else None


def attributes(soup: BeautifulSoup) -> dict[str, str]:
    found = {}
    for item in soup.select("div.attribute-item"):
        label = item.select_one(".attribute-label")
        value = item.select_one(".attribute-value")
        if label is None or value is None:
            continue
        key = re.sub(r"[^a-z ]", "", flat(label.get_text(" ", strip=True)))
        found[key.strip()] = value.get_text("", strip=True)
    return found


def parse_detail(html: str, url: str, county: str | None = None) -> Listing:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    price_node = soup.select_one(".product-price")
    price_text = price_node.get_text(" ", strip=True) if price_node else None
    description_node = soup.select_one(".article-description")
    description = description_node.get_text(" ", strip=True) if description_node else None
    values = {}
    for key, value in attributes(soup).items():
        for prefix, name in LABELS.items():
            if key.startswith(prefix):
                values[name] = value
    places = [a.get_text(" ", strip=True) for a in soup.select(".detail-info a.maincolor")]
    coordinates = COORDINATES.search(html)
    floor, total_floors = floor_info(values.get("floor"))
    rooms = extract_rooms(values.get("rooms")) or extract_rooms(title.get_text() if title else None)
    return Listing(
        source="romimo",
        source_id=listing_id_from_url(url),
        url=url,
        title=title.get_text(" ", strip=True) if title else None,
        description=description,
        price=parse_number(price_text),
        currency=detect_currency(price_text),
        rooms=rooms,
        surface_sqm=extract_surface(values.get("surface")) or parse_number(values.get("surface")),
        floor=floor,
        total_floors=total_floors,
        year_built=extract_year(values.get("year")),
        county=county or (places[0].lower() if places else None),
        locality=places[1] if len(places) > 1 else None,
        latitude=float(coordinates.group(1)) if coordinates else None,
        longitude=float(coordinates.group(2)) if coordinates else None,
    )
