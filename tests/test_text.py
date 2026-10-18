import pytest

from rentals import text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.200", 1200.0), ("1,200", 1200.0), ("1 200", 1200.0), ("1.234,56", 1234.56),
        ("1,234.56", 1234.56), ("12,5", 12.5), ("45.5", 45.5), ("900 RON", 900.0),
        ("1.250.000", 1250000.0), ("abc", None), (None, None), (700, 700.0),
    ],
)  # fmt: skip
def test_parse_number(raw, expected):
    assert text.parse_number(raw) == expected


def test_detect_currency_and_price():
    assert text.detect_currency("450 EUR") == "EUR"
    assert text.detect_currency("2.500 lei") == "RON"
    assert text.detect_currency("pret 300 €") == "EUR"
    assert text.detect_currency("pret 300") is None
    assert text.parse_price("1.250 lei") == (1250.0, "RON")
    assert text.parse_price("700", assume="EUR") == (700.0, "EUR")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Apartament 2 camere", 2), ("garsoniera confort 1", 1), ("doua camere decomandat", 2),
        ("3 cam. zona centrala", 3), ("studio nou", 1), ("trei camere", 3), ("casa cu curte", None),
    ],
)  # fmt: skip
def test_extract_rooms(raw, expected):
    assert text.extract_rooms(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("suprafata 54 mp", 54.0), ("45,5 m²", 45.5), ("62 m2 utili", 62.0), ("fara suprafata", None)],
)
def test_extract_surface(raw, expected):
    assert text.extract_surface(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("etaj 3", (3, None)), ("Etajul 2/8", (2, 8)), ("parter", (0, None)), ("parter/4", (0, 4)),
        ("demisol", (-1, None)), ("subsol", (-2, None)), ("3 din 10", (3, 10)), ("5", (5, None)),
        ("nimic", (None, None)), (None, (None, None)),
    ],
)  # fmt: skip
def test_floor_info(raw, expected):
    assert text.floor_info(raw) == expected


def test_diacritics_and_flat():
    assert text.strip_diacritics("Închiriez în Timișoara ăâîșț") == "Inchiriez in Timisoara aaist"
    assert text.flat("  Apartament\xa0 DE   Închiriat ") == "apartament de inchiriat"


def test_listing_id_from_url():
    code = "0123456789abcdef0123456789abcdef"
    assert text.listing_id_from_url(f"https://x.ro/anunt/{code}.html") == code
    assert text.listing_id_from_url("https://x.ro/ro/oferta/apartament-IDa1?x=1") == "apartament-IDa1"
    assert text.extract_year("constructie 1970") == 1970
