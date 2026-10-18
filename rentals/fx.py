from __future__ import annotations

import json
import re
from dataclasses import dataclass

BNR_URL = "https://www.bnr.ro/nbrfxrates.xml"
BACKUP_URL = "https://api.frankfurter.app/latest?from=EUR&to=RON"
FALLBACK_RATE = 5.0
SANE_RANGE = (3.5, 7.5)

CUBE_DATE = re.compile(r'<Cube[^>]*\bdate="(\d{4}-\d{2}-\d{2})"')
EUR_RATE = re.compile(r'<Rate[^>]*\bcurrency="EUR"[^>]*>\s*([0-9]+(?:[.,][0-9]+)?)\s*</Rate>', re.I)


@dataclass(frozen=True)
class RonPerEur:
    rate: float
    date: str | None
    source: str

    def to_eur(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None or currency is None:
            return None
        code = currency.upper()
        if code == "EUR":
            return float(amount)
        if code in ("RON", "LEI", "LEU"):
            return float(amount) / self.rate
        return None


def is_sane(rate: float | None) -> bool:
    return rate is not None and SANE_RANGE[0] <= rate <= SANE_RANGE[1]


def parse_bnr(xml_text: str) -> RonPerEur | None:
    match = EUR_RATE.search(xml_text or "")
    if not match:
        return None
    rate = float(match.group(1).replace(",", "."))
    if not is_sane(rate):
        return None
    date = CUBE_DATE.search(xml_text)
    return RonPerEur(rate, date.group(1) if date else None, "BNR")


def parse_frankfurter(payload: str | dict) -> RonPerEur | None:
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        rate = float(data["rates"]["RON"])
    except (KeyError, TypeError, ValueError):
        return None
    return RonPerEur(rate, data.get("date"), "ECB via frankfurter") if is_sane(rate) else None


def fallback(rate: float = FALLBACK_RATE) -> RonPerEur:
    return RonPerEur(rate, None, "fallback constant")


def fetch_rate(fetcher, default: RonPerEur | None = None) -> RonPerEur:
    for url, parser in ((BNR_URL, parse_bnr), (BACKUP_URL, parse_frankfurter)):
        try:
            parsed = parser(fetcher.get(url))
        except Exception:
            parsed = None
        if parsed is not None:
            return parsed
    return default or fallback()
