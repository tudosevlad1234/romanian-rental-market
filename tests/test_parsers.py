from rentals.parsers import romimo, storia
from rentals.scrapers import romimo_detail, storia_detail


def test_storia_search_items(fixture):
    listings, pages = storia.parse_search(fixture("storia_search.html"), "cluj")
    assert pages == 2 and [i.source_id for i in listings] == ["1001", "1002", "1003"]
    first, second, third = listings
    assert (first.price, first.currency, first.rooms, first.surface_sqm, first.floor) == (
        450,
        "EUR",
        2,
        55.0,
        2,
    )
    assert first.locality == "Cluj-Napoca" and first.neighborhood == "Centru"
    assert first.street == "Strada Memorandumului" and first.county == "cluj"
    assert first.url == "https://www.storia.ro/ro/oferta/apartament-2-camere-cluj-IDa1"
    assert (second.currency, second.floor, second.rooms) == ("RON", 0, 1)
    assert third.price is None and third.currency is None and third.floor is None


def test_storia_search_without_data_returns_nothing():
    assert storia.parse_search("<html></html>", "cluj") == ([], None)
    assert storia.parse_search('<script id="__NEXT_DATA__">{broken</script>', "cluj") == ([], None)


def test_storia_offer(fixture):
    offer = storia.parse_offer(fixture("storia_offer.html"))
    assert offer["description"] == "Garsoniera mobilata. Bloc din 2012."
    assert (offer["price"], offer["currency"], offer["rooms"], offer["surface_sqm"]) == (
        1000.0,
        "RON",
        1,
        32.0,
    )
    assert (offer["floor"], offer["total_floors"]) == (3, 8)
    assert offer["locality"] == "Alba Iulia" and offer["street"] == "Strada Tolstoi"
    assert storia.parse_offer("<html></html>") == {}


def test_storia_urls_and_floor_codes():
    assert "bistrita--nasaud" in storia.search_url("bistrita-nasaud", 3)
    assert storia.search_url("cluj", 2).endswith("page=2")
    codes = ("SECOND", "floor_7", "GROUND", "ground_floor", "CELLAR", "GARRET", None)
    assert [storia.floor_number(code) for code in codes] == [2, 7, 0, 0, -1, None, None]


def test_storia_detail_fills_only_gaps(fixture):
    listings, _ = storia.parse_search(fixture("storia_search.html"), "cluj")
    merged = storia_detail(fixture("storia_offer.html"), listings[2])
    assert merged.price == 1000.0 and merged.rooms == 3 and merged.surface_sqm == 70.0
    assert merged.source_id == "1003" and merged.county == "cluj"


def test_romimo_search_cards(fixture):
    listings, pages = romimo.parse_search(fixture("romimo_search.html"), "alba")
    assert pages == 7 and len(listings) == 2
    assert listings[0].source_id == "0123456789abcdef0123456789abcdef"
    assert (listings[0].price, listings[0].currency) == (900.0, "RON")
    assert listings[1].url == "https://www.romimo.ro/anunt/fedcba9876543210fedcba9876543210.html"
    assert (listings[1].price, listings[1].currency) == (1250.0, "EUR")


def test_romimo_detail(fixture):
    url = "https://www.romimo.ro/anunt/0123456789abcdef0123456789abcdef.html"
    item = romimo.parse_detail(fixture("romimo_detail.html"), url)
    assert item.title == "Apartament De Inchiriat."
    assert (item.price, item.currency) == (900.0, "RON")
    assert item.surface_sqm == 58.0 and item.rooms == 2 and item.floor == 1 and item.year_built == 1970
    assert item.county == "alba" and item.locality == "Aiud"
    assert (item.latitude, item.longitude) == (46.3122222, 23.7291667)


def test_romimo_detail_merge_keeps_card_price(fixture):
    listings, _ = romimo.parse_search(fixture("romimo_search.html"), "alba")
    merged = romimo_detail(fixture("romimo_detail.html"), listings[0])
    assert merged.surface_sqm == 58.0 and merged.source_id == listings[0].source_id


def test_romimo_labels_with_either_romanian_t():
    html = (
        "<html><body><h1>Apartament 2 camere</h1>"
        '<div class="attribute-item"><div class="attribute-label">Suprafaţă utilă</div>'
        '<div class="attribute-value">61 m<sup>2</sup></div></div>'
        '<div class="attribute-item"><div class="attribute-label">Anul construcției</div>'
        '<div class="attribute-value">1982</div></div>'
        '<div class="attribute-item"><div class="attribute-label">Număr camere</div>'
        '<div class="attribute-value">2 camere</div></div></body></html>'
    )
    item = romimo.parse_detail(html, "https://www.romimo.ro/anunt/x.html", "cluj")
    assert (item.surface_sqm, item.year_built, item.rooms) == (61.0, 1982, 2)
