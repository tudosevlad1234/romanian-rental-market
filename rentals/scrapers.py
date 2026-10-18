from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .fetch import FetchError
from .models import Listing
from .parsers import romimo, storia

log = logging.getLogger("rentals.scrapers")


@dataclass
class SiteSpec:
    name: str
    search_url: Callable[[str, int], str]
    parse_search: Callable[[str, str], tuple[list[Listing], int | None]]
    detail: Callable[[str, Listing], Listing] | None = None
    max_pages_cap: int = 300


@dataclass
class CrawlReport:
    coverage: dict[str, bool] = field(default_factory=dict)
    pages: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    seen: dict[str, set[str]] = field(default_factory=dict)


def storia_detail(html: str, listing: Listing) -> Listing:
    fields = storia.parse_offer(html)
    enriched = Listing(source=listing.source, source_id=listing.source_id, url=listing.url, county=listing.county)
    for key, value in fields.items():
        setattr(enriched, key, value)
    return listing.merge(enriched)


def romimo_detail(html: str, listing: Listing) -> Listing:
    parsed = romimo.parse_detail(html, listing.url, listing.county)
    return parsed.merge(listing) if parsed.price is not None else listing.merge(parsed)


SITES: dict[str, SiteSpec] = {
    "storia": SiteSpec("storia", storia.search_url, storia.parse_search, storia_detail),
    "romimo": SiteSpec("romimo", romimo.search_url, romimo.parse_search, romimo_detail),
}


def needs_detail(listing: Listing) -> bool:
    return None in (listing.rooms, listing.surface_sqm, listing.price) or listing.floor is None


def crawl(
    site: str,
    counties: list[str],
    fetcher,
    max_pages: int | None = None,
    known: set[str] | None = None,
    report: CrawlReport | None = None,
    fetch_details: bool = True,
) -> Iterator[Listing]:
    spec = SITES[site]
    report = report if report is not None else CrawlReport()
    known = known or set()
    limit = min(max_pages or spec.max_pages_cap, spec.max_pages_cap)
    for county in counties:
        status = "limit"
        seen: set[str] = set()
        total_pages: int | None = None
        page = 1
        while page <= limit:
            try:
                html = fetcher.get(spec.search_url(county, page))
            except FetchError as error:
                report.failures.append(str(error))
                status = "error"
                break
            listings, pages = spec.parse_search(html, county)
            if not listings:
                status = "end" if page > 1 else "empty"
                break
            total_pages = pages or total_pages
            report.pages[county] = page
            for item in listings:
                if item.source_id in seen:
                    continue
                seen.add(item.source_id)
                if spec.detail and fetch_details and item.source_id not in known and needs_detail(item):
                    item = fetch_detail(spec, fetcher, item, report)
                yield item
            if total_pages is not None and page >= total_pages:
                status = "end"
                break
            page += 1
        report.coverage[county] = status == "end"
        report.seen[county] = seen


def fetch_detail(spec: SiteSpec, fetcher, item: Listing, report: CrawlReport) -> Listing:
    try:
        return spec.detail(fetcher.get(item.url), item)
    except FetchError as error:
        report.failures.append(str(error))
        return item
