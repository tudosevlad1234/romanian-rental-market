from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import Hedonic, best_value, county_summary, effects_table, fit_hedonic
from .clean import build_dataset, enrich
from .fx import RonPerEur, fallback
from .scrapers import CrawlReport, crawl
from .stata import export
from .store import Store


def collect(
    store: Store,
    fetcher,
    sites: list[str],
    counties: list[str],
    rate: RonPerEur | None = None,
    max_pages: int | None = None,
) -> dict[str, CrawlReport]:
    rate = rate or fallback()
    reports = {}
    for site in sites:
        report = CrawlReport()
        for listing in crawl(site, counties, fetcher, max_pages, store.known_ids(site), report):
            store.upsert(enrich(listing, rate))
        for county, complete in report.coverage.items():
            store.mark_disappeared(site, county, report.seen.get(county, set()), complete)
        reports[site] = report
    return reports


def analyse(store: Store, out: str | Path | None = None) -> tuple[pd.DataFrame, Hedonic]:
    data, reasons = build_dataset(store.frame())
    model = fit_hedonic(data)
    if out is not None:
        folder = Path(out)
        folder.mkdir(parents=True, exist_ok=True)
        export(model.data, folder)
        effects_table(model).round(4).to_csv(folder / "effects.csv")
        county_summary(data).round(2).to_csv(folder / "county_summary.csv")
        best_value(model).round(2).to_csv(folder / "best_value.csv", index=False)
        reasons.value_counts().rename("count").to_csv(folder / "exclusions.csv")
    return data, model
