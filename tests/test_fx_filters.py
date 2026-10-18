import pytest

from rentals import fx
from rentals.filters import exclusion_reason
from rentals.models import Listing

BNR = """<DataSet><Body><Cube date="2026-10-09"><Rate currency="EUR">5.0803</Rate>
<Rate currency="USD">4.3</Rate></Cube></Body></DataSet>"""


def test_parse_bnr():
    parsed = fx.parse_bnr(BNR)
    assert parsed.rate == 5.0803 and parsed.date == "2026-10-09" and parsed.source == "BNR"
    assert fx.parse_bnr("<xml/>") is None
    assert fx.parse_bnr(BNR.replace("5.0803", "50.8")) is None


def test_parse_frankfurter():
    assert fx.parse_frankfurter('{"rates": {"RON": 5.08}, "date": "2026-10-09"}').rate == 5.08
    assert fx.parse_frankfurter("{}") is None
    assert fx.parse_frankfurter({"rates": {"RON": 1.0}}) is None


def test_conversion():
    rate = fx.RonPerEur(5.0, None, "test")
    assert rate.to_eur(1000, "RON") == 200.0
    assert rate.to_eur(450, "EUR") == 450.0
    assert rate.to_eur(450, None) is None
    assert rate.to_eur(450, "USD") is None
    assert rate.to_eur(None, "RON") is None


class Fetcher:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url):
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_fetch_rate_falls_back_in_order():
    ok = '{"rates": {"RON": 5.1}}'
    assert fx.fetch_rate(Fetcher({fx.BNR_URL: BNR})).source == "BNR"
    assert fx.fetch_rate(Fetcher({fx.BNR_URL: RuntimeError("down"), fx.BACKUP_URL: ok})).rate == 5.1
    broken = Fetcher({fx.BNR_URL: "junk", fx.BACKUP_URL: RuntimeError("down")})
    assert fx.fetch_rate(broken).source == "fallback constant"


def listing(**values):
    base = dict(source="s", source_id="1", url="https://x.ro/a", title="Apartament 2 camere", price_eur=500.0)
    return Listing(**{**base, **values})


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"title": "Vand apartament 2 camere"}, "sale"),
        ({"title": "De inchiriat sau vanzare apartament"}, None),
        ({"price_eur": 85000.0}, "price_too_high"),
        ({"title": "Caut apartament de inchiriat"}, "wanted"),
        ({"url": "https://x.ro/cerere/1"}, "wanted"),
        ({"title": "Apartament regim hotelier"}, "short_term"),
        ({"price_eur": 60.0, "description": "tarif 60 euro pe noapte"}, "short_term"),
        ({"price_eur": 60.0, "description": "nu inchiriez in regim hotelier"}, None),
        ({"title": "Inchiriez camera in apartament"}, "room_share"),
        ({"title": "Inchiriez 1 camera"}, None),
        ({"title": "Birou de inchiriat"}, "non_residential"),
        ({"title": "Apartament 2 camere pretabil birou"}, None),
        ({}, None),
    ],
)
def test_exclusion_reason(values, reason):
    assert exclusion_reason(listing(**values)) == reason
