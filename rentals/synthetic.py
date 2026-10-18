from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape

import numpy as np

from .fetch import FetchError
from .models import Listing

COUNTY_EFFECT = {
    "bucuresti": 0.35, "cluj": 0.25, "ilfov": 0.20, "brasov": 0.15, "constanta": 0.12,
    "timis": 0.12, "iasi": 0.08, "alba": -0.10,
}  # fmt: skip
TRUE = {"intercept": 3.0, "ln_surface": 0.85, "extra_room": 0.03, "ground_floor": -0.06, "noise": 0.18}
ROOM_WORDS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}
FLOOR_WORDS = {1: "FIRST", 2: "SECOND", 3: "THIRD", 4: "FOURTH", 5: "FIFTH"}
STREETS = [
    "Strada Libertatii",
    "Bulevardul Unirii",
    "Strada Florilor",
    "Calea Victoriei",
    "Strada Mihai Viteazu",
]
RON_PER_EUR = 5.0


@dataclass
class Market:
    listings: list[Listing]
    ron_per_eur: float = RON_PER_EUR
    truth: dict = field(default_factory=lambda: dict(TRUE, county_effect=COUNTY_EFFECT))


def make_market(n: int = 600, seed: int = 3, duplicate_share: float = 0.2) -> Market:
    rng = np.random.default_rng(seed)
    counties = list(COUNTY_EFFECT)
    listings = []
    for index in range(n):
        county = counties[rng.integers(len(counties))]
        surface = float(np.clip(rng.lognormal(np.log(52), 0.3), 18, 140).round())
        rooms = int(np.clip(round(surface / 24), 1, 5))
        floor = int(rng.integers(0, 9))
        log_rent = (
            TRUE["intercept"]
            + TRUE["ln_surface"] * np.log(surface)
            + TRUE["extra_room"] * (rooms - 2)
            + TRUE["ground_floor"] * (floor == 0)
            + COUNTY_EFFECT[county]
            + TRUE["noise"] * rng.standard_normal()
        )
        rent_eur = float(np.exp(log_rent))
        in_ron = rng.random() < 0.5
        listings.append(
            Listing(
                source="storia",
                source_id=f"{100000 + index}",
                url=f"https://www.storia.ro/ro/oferta/apartament-{100000 + index}",
                title=f"Apartament {rooms} camere de inchiriat {county.title()}",
                price=round(rent_eur * RON_PER_EUR) if in_ron else round(rent_eur),
                currency="RON" if in_ron else "EUR",
                rooms=rooms,
                surface_sqm=surface,
                floor=floor,
                total_floors=int(floor + rng.integers(0, 5)),
                county=county,
                locality=county.title(),
                neighborhood=f"Zona {int(rng.integers(1, 9))}",
                street=STREETS[int(rng.integers(len(STREETS)))],
                latitude=float(45 + rng.random()),
                longitude=float(24 + rng.random()),
                extra={"true_rent_eur": rent_eur},
            )
        )
    mirrored = []
    for item in listings[: int(n * duplicate_share)]:
        copy = Listing(**{**item.as_dict(), "source": "romimo", "source_id": f"r{item.source_id}"})
        copy.url = f"https://www.romimo.ro/anunt/{item.source_id}.html"
        copy.price = round(item.price * (1 + rng.uniform(-0.02, 0.02)))
        copy.extra = dict(item.extra)
        mirrored.append(copy)
    return Market(listings + mirrored)


def storia_item(listing: Listing, hide_floor: bool) -> dict:
    return {
        "id": int(listing.source_id),
        "slug": listing.url.rsplit("/", 1)[-1],
        "title": listing.title,
        "totalPrice": {"value": listing.price, "currency": listing.currency},
        "areaInSquareMeters": listing.surface_sqm,
        "roomsNumber": ROOM_WORDS.get(listing.rooms),
        "floorNumber": None
        if hide_floor
        else ("GROUND" if listing.floor == 0 else FLOOR_WORDS.get(listing.floor, f"floor_{listing.floor}")),
        "location": {
            "reverseGeocoding": {
                "locations": [
                    {"locationLevel": "city", "name": listing.locality},
                    {"locationLevel": "district", "name": listing.neighborhood},
                ]
            },
            "address": {"street": {"name": listing.street}},
            "coordinates": {"latitude": listing.latitude, "longitude": listing.longitude},
        },
    }


def render_storia_search(items: list[dict], total_pages: int) -> str:
    payload = {
        "props": {"pageProps": {"data": {"searchAds": {"items": items, "pagination": {"totalPages": total_pages}}}}}
    }
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'


def render_storia_offer(listing: Listing) -> str:
    characteristics = [
        {"key": "price", "value": str(listing.price), "currency": listing.currency},
        {"key": "m", "value": str(listing.surface_sqm)},
        {"key": "rooms_num", "value": str(listing.rooms)},
        {"key": "floor_no", "value": "ground_floor" if listing.floor == 0 else f"floor_{listing.floor}"},
        {"key": "building_floors_num", "value": str(listing.total_floors)},
    ]
    ad = {
        "title": listing.title,
        "description": f"<p>{escape(listing.title or '')}</p>",
        "characteristics": characteristics,
    }
    payload = {"props": {"pageProps": {"ad": ad}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></html>'


def render_romimo_search(listings: list[Listing], page: int, total_pages: int) -> str:
    cards = "".join(
        f'<div class="article-item" onclick="javascript:window.location.href=\'{item.url}\'">'
        f'<h2 class="article-title">{escape(item.title or "")}</h2>'
        f'<span class="article-price">{item.price:g} {"lei" if item.currency == "RON" else "EUR"}</span></div>'
        for item in listings
    )
    links = "".join(f'<li><a href="?pag={n}">{n}</a></li>' for n in range(1, total_pages + 1))
    return f'<html><body>{cards}<ul class="pagination">{links}</ul></body></html>'


def attribute(label: str, value: str) -> str:
    return (
        '<div class="attribute-item">'
        f'<div class="attribute-label"><strong>{label}</strong></div>'
        f'<div class="attribute-value">{value}</div></div>'
    )


def render_romimo_detail(listing: Listing) -> str:
    floor = "parter" if listing.floor == 0 else f"etaj {listing.floor}"
    currency = "RON" if listing.currency == "RON" else "EUR"
    title = escape(listing.title or "")
    return (
        f"<html><body><h1>{title}</h1>"
        f'<span class="product-price"><span>{listing.price:g}</span><span>{currency}</span></span>'
        '<div class="detail-info">'
        f'<a class="maincolor">{listing.county.title()}</a>, <a class="maincolor">{listing.locality}</a></div>'
        + attribute("Suprafata utila", f"{listing.surface_sqm:g} m<sup>2</sup>")
        + attribute("Numar camere", f"{listing.rooms} camere")
        + attribute("Etaj", floor)
        + f'<div class="article-description">{title}</div>'
        f"<script>var lat ={listing.latitude};\n var lng = {listing.longitude};</script></body></html>"
    )


class FakeSite:
    def __init__(self, market: Market, per_page: int = 36, hide_floor_every: int = 7):
        self.per_page = per_page
        self.hide_floor_every = hide_floor_every
        self.requests: list[str] = []
        self.by_source: dict[str, dict[str, list[Listing]]] = {"storia": {}, "romimo": {}}
        for item in market.listings:
            self.by_source[item.source].setdefault(item.county, []).append(item)
        self.offers = {i.url: i for i in market.listings if i.source == "storia"}
        self.details = {i.url: i for i in market.listings if i.source == "romimo"}

    def get(self, url: str) -> str:
        self.requests.append(url)
        if "storia.ro/ro/rezultate" in url:
            return self.storia_search(url)
        if "storia.ro/ro/oferta/" in url:
            return render_storia_offer(self.offers[url])
        if "romimo.ro/apartamente/inchiriere" in url:
            return self.romimo_search(url)
        if url in self.details:
            return render_romimo_detail(self.details[url])
        raise FetchError(f"{url}: HTTP 404")

    def page_slice(self, listings: list[Listing], page: int) -> tuple[list[Listing], int]:
        pages = max(1, -(-len(listings) // self.per_page))
        start = (page - 1) * self.per_page
        return listings[start : start + self.per_page], pages

    def storia_search(self, url: str) -> str:
        county = url.split("/apartament/")[1].split("?")[0]
        page = int(url.rsplit("page=", 1)[1])
        chunk, pages = self.page_slice(self.by_source["storia"].get(county, []), page)
        items = [storia_item(item, hide_floor=int(item.source_id) % self.hide_floor_every == 0) for item in chunk]
        return render_storia_search(items, pages)

    def romimo_search(self, url: str) -> str:
        county = url.split("/inchiriere/")[1].split("/")[0]
        page = int(url.rsplit("pag=", 1)[1])
        chunk, pages = self.page_slice(self.by_source["romimo"].get(county, []), page)
        return render_romimo_search(chunk, page, pages)
