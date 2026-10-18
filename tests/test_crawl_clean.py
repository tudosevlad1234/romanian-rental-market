import numpy as np
import pandas as pd
import pytest

from rentals import fx
from rentals.clean import Plausibility, build_dataset, enrich
from rentals.fetch import FetchError
from rentals.models import Listing
from rentals.pipeline import collect
from rentals.scrapers import CrawlReport, crawl
from rentals.store import Store
from rentals.synthetic import COUNTY_EFFECT, FakeSite, make_market

RATE = fx.RonPerEur(5.0, "2026-10-09", "test")


@pytest.fixture(scope="module")
def market():
    return make_market(200, seed=5)


def test_crawl_walks_every_page_and_reports_coverage(market):
    site = FakeSite(market, per_page=20)
    report = CrawlReport()
    listings = list(crawl("storia", ["cluj", "alba"], site, report=report))
    expected = [i for i in market.listings if i.source == "storia" and i.county in ("cluj", "alba")]
    assert sorted(i.source_id for i in listings) == sorted(i.source_id for i in expected)
    assert report.coverage == {"cluj": True, "alba": True}
    assert report.seen["cluj"] == {i.source_id for i in expected if i.county == "cluj"}


def test_crawl_max_pages_marks_county_incomplete(market):
    report = CrawlReport()
    listings = list(crawl("storia", ["bucuresti"], FakeSite(market, per_page=5), max_pages=2, report=report))
    assert len(listings) == 10 and report.coverage["bucuresti"] is False


def test_crawl_failure_marks_incomplete_and_continues(market):
    class Flaky(FakeSite):
        def get(self, url):
            if "alba" in url and "page=2" in url:
                raise FetchError("boom")
            return super().get(url)

    report = CrawlReport()
    listings = list(crawl("storia", ["alba", "cluj"], Flaky(market, per_page=5), report=report))
    assert report.coverage["alba"] is False and report.coverage["cluj"] is True
    assert report.failures == ["boom"] and any(i.county == "cluj" for i in listings)


def test_unknown_county_is_incomplete_not_an_error(market):
    report = CrawlReport()
    assert list(crawl("storia", ["atlantis"], FakeSite(market), report=report)) == []
    assert report.coverage == {"atlantis": False}


def test_detail_pages_only_fetched_when_fields_missing_and_not_known(market):
    site = FakeSite(market, per_page=50, hide_floor_every=7)
    counties = list(COUNTY_EFFECT)
    list(crawl("storia", counties, site))
    fetched = [u for u in site.requests if "/ro/oferta/" in u]
    hidden = [i for i in market.listings if i.source == "storia" and int(i.source_id) % 7 == 0]
    assert len(fetched) == len(hidden) > 0
    site.requests.clear()
    known = {i.source_id for i in hidden}
    list(crawl("storia", counties, site, known=known))
    assert not [u for u in site.requests if "/ro/oferta/" in u]


def test_collect_dedups_across_sites_and_tracks_disappearance(market):
    store = Store()
    collect(store, FakeSite(market), ["storia", "romimo"], list(COUNTY_EFFECT), RATE)
    frame = store.frame()
    storia = [i for i in market.listings if i.source == "storia"]
    assert len(frame) == len(storia)
    assert int((frame["n_sources"] == 2).sum()) == len([i for i in market.listings if i.source == "romimo"])
    smaller = make_market(200, seed=5)
    mirrored = {i.source_id[1:] for i in smaller.listings if i.source == "romimo"}
    removed = [i for i in smaller.listings if i.source == "storia" and i.source_id not in mirrored][:3]
    smaller.listings = [i for i in smaller.listings if i not in removed]
    collect(store, FakeSite(smaller), ["storia"], list(COUNTY_EFFECT), RATE)
    assert len(store.frame(active_only=True)) == len(frame) - 3


def test_prices_are_converted_to_eur(market):
    store = Store()
    collect(store, FakeSite(market), ["storia"], list(COUNTY_EFFECT), RATE)
    frame = store.frame()
    truth = {i.url: i.extra["true_rent_eur"] for i in market.listings if i.source == "storia"}
    ratio = frame.set_index("fingerprint")["price_eur"]
    assert ratio.notna().all()
    errors = [abs(row.price_eur / truth[row.url] - 1) for row in frame.itertuples()]
    assert max(errors) < 0.02


def test_enrich_fills_from_text_and_rejects_implausible():
    item = Listing(
        source="s", source_id="1", url="u", title="Apartament 3 camere 64 mp",
        description="etaj 4/10, constructie 1985",
        price=1500.0, currency=None,
    )  # fmt: skip
    out = enrich(item, RATE)
    assert (out.rooms, out.surface_sqm, out.floor, out.total_floors, out.year_built) == (3, 64.0, 4, 10, 1985)
    assert out.price_eur is None
    item.currency = "RON"
    assert enrich(item, RATE).price_eur == 300.0
    accented = Listing(source="s", source_id="3", url="u", description="Anul construcției: 1978")
    assert enrich(accented, RATE).year_built == 1978
    absurd = Listing(source="s", source_id="2", url="u", surface_sqm=2.0, rooms=40, floor=99, price=1.0, currency="EUR")
    cleaned = enrich(absurd, RATE, Plausibility())
    assert cleaned.surface_sqm is None and cleaned.rooms is None and cleaned.floor is None


def test_build_dataset_filters_flags_and_derives():
    frame = pd.DataFrame(
        {
            "fingerprint": list("abcdef"),
            "title": ["Apartament 2 camere", "Vand apartament", "Apartament 1 camera", "Apartament 3 camere",
                      "Apartament 2 camere", "Apartament 4 camere"],
            "description": [None] * 6,
            "price_eur": [500.0, 90000.0, 30.0, 700.0, 400.0, 900.0],
            "surface_sqm": [50.0, 50.0, 30.0, 70.0, 5.0, 100.0],
            "rooms": [2, 2, 1, 3, 2, 5],
            "floor": [0, 3, 1, None, 2, 5],
            "county": ["cluj"] * 6,
            "url": ["u"] * 6,
        }
    )  # fmt: skip
    data, reasons = build_dataset(frame)
    assert reasons.loc[1] == "sale" and reasons.notna().sum() == 1
    assert list(data["fingerprint"]) == ["a", "c", "d", "e", "f"]
    row = data.set_index("fingerprint")
    assert row.loc["a", "eur_per_sqm"] == 10.0 and row.loc["a", "ground_floor"] == 1.0
    assert np.isnan(row.loc["d", "ground_floor"])
    assert row.loc["c", "price_suspect_reason"] == "below_min"
    assert row.loc["f", "rooms_cat"] == 4 and row.loc["f", "rooms_topcoded"] == 1
    assert np.isclose(row.loc["a", "ln_rent"], np.log(500.0))
