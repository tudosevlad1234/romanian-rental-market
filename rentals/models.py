from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str | None = None
    price_eur: float | None = None
    rooms: int | None = None
    surface_sqm: float | None = None
    floor: int | None = None
    total_floors: int | None = None
    year_built: int | None = None
    county: str | None = None
    locality: str | None = None
    neighborhood: str | None = None
    street: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    def merge(self, other: Listing) -> Listing:
        merged = {}
        for item in fields(self):
            if item.name == "extra":
                merged["extra"] = {**other.extra, **self.extra}
                continue
            mine = getattr(self, item.name)
            merged[item.name] = mine if mine not in (None, "") else getattr(other, item.name)
        return Listing(**merged)
