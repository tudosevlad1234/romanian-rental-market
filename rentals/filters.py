from __future__ import annotations

import re
from dataclasses import dataclass

from .text import flat


@dataclass(frozen=True)
class FilterLimits:
    max_rent_eur: float = 10000.0
    short_term_ceiling_eur: float = 120.0


APARTMENT = re.compile(
    r"\b(apartament\w*|apt\b|ap\b|garsonier\w*|studio\w*|penthouse|duplex|\d\s*cam\w*|"
    r"doua camere|trei camere|patru camere)"
)
SHORT_TERM_TITLE = re.compile(
    r"regim hotel\w*|regim de hotel|\bpe noapte\b|/\s*noapte|\bper noapte\b|\bcazare\b|\bpe zi\b"
)
SHORT_TERM_DESCRIPTION = re.compile(r"\d[\d.,]*\s*(?:lei|ron|euro|eur|€)\s*(?:/|pe|per)\s*(?:noapte|zi)\b")
NEGATION = re.compile(r"(\bnu\b|\bfara\b|exclus\w*|\binterzis\w*)\W+(?:\w+\W+){0,4}$")
ROOM_SHARE = re.compile(
    r"\b(?:inchiriez|ofer|dau|inchiriere|disponibila?)\s+(?:o\s+)?camera\b|"
    r"\bcaut\w*\s+coleg\w*|\bloc in camera\b|\bpat in camera\b"
)
COUNTED_ROOM = re.compile(r"(?:\d|\bo|\buna|\bcu)\s+camera\b")
NON_RESIDENTIAL = re.compile(
    r"\b(birou|birouri|spatiu\w*\s+comercia\w*|depozit\w*|hala|hale|teren\w*|showroom|"
    r"cabinet medical|rulota|spatiu industrial)\b"
)
WANTED = re.compile(r"^\s*caut\b|\bcaut\s+(?:urgent\s+)?(?:apartament|garsonier\w*|chirie|camera)")
SALE_TITLE = re.compile(r"\bvand\b|\bde vanzare\b|\bspre vanzare\b|\bse vinde\b|\bcumpar\w*\b")
RENT_WORD = re.compile(r"\binchir\w*|\bchiri\w*")


def exclusion_reason(listing, limits: FilterLimits | None = None) -> str | None:
    limits = limits or FilterLimits()
    title = flat(listing.title)
    description = flat(listing.description)
    price = listing.price_eur
    if SALE_TITLE.search(title):
        plausible = price is not None and price <= limits.max_rent_eur
        if not (RENT_WORD.search(title) and plausible):
            return "sale"
    if price is not None and price > limits.max_rent_eur:
        return "price_too_high"
    if "cerere" in (listing.url or "").lower() or WANTED.search(title):
        return "wanted"
    if SHORT_TERM_TITLE.search(title):
        return "short_term"
    cheap = price is None or price < limits.short_term_ceiling_eur
    if cheap and SHORT_TERM_DESCRIPTION.search(description):
        return "short_term"
    if cheap:
        for match in re.finditer(r"regim hotel\w*", description):
            if not NEGATION.search(description[max(0, match.start() - 40) : match.start()]):
                return "short_term"
    if ROOM_SHARE.search(title) and not COUNTED_ROOM.search(title):
        return "room_share"
    if NON_RESIDENTIAL.search(title) and not APARTMENT.search(title):
        return "non_residential"
    return None
