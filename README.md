# Romanian Rental Market Analysis

A research pipeline for studying apartment rents in Romania: scrapers for public listing sites,
cleaning and currency conversion, cross-site de-duplication, a SQLite store, a hedonic
(log-linear) rent model in Python and an equivalent Stata script.

Stack: Python, requests, BeautifulSoup, (optional) Selenium, pandas, statsmodels, Stata.

> The repository ships **no scraped data**. The demo runs offline on a synthetic market with a
> known rent-generating process, served by a fake in-memory website. It checks that every stage of
> the pipeline works and that the model recovers the truth; it says nothing about real Romanian rents.

## Setup

Requires Python 3.10 or newer.

```bash
git clone https://github.com/tudosevlad1234/romanian-rental-market.git
cd romanian-rental-market
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Optional, only if you need a real browser for JavaScript-rendered pages:

```bash
pip install -e ".[selenium]"     # also needs Chrome installed
```

## Try it offline

```bash
python -m rentals demo --out output
```

The demo generates 720 advertisements (600 apartments, 120 of them also posted on a second site),
crawls two fake sites, converts lei to euro, merges the cross-posted ads, fits the model and writes
`output/`:

```
advertised listings: 720   distinct apartments stored: 600
listed on both sites: 120   pages fetched: 234
surface elasticity: estimated 0.848   true 0.85
R2 0.701   out-of-sample R2 0.675   MAPE 15.4%
```

| File | Contents |
| --- | --- |
| `rentals.csv`, `rentals.dta` | analysis dataset for pandas, R or Stata |
| `effects.csv` | model coefficients with robust errors and percentage effects |
| `county_summary.csv` | listings, median rent and rent per m2 by county |
| `best_value.csv` | listings priced furthest below the model's fair rent |
| `exclusions.csv` | how many ads were dropped and why |

## Collect real data

```bash
python -m rentals scrape --site storia --county cluj brasov --max-pages 3 \
    --user-agent "my-thesis (me@university.ro)" --db listings.db
python -m rentals analyse --db listings.db --out output
```

The scraper is deliberately polite:

- it identifies itself with the `--user-agent` you must supply;
- it reads and obeys each site's `robots.txt` (a 401/403 or a server error on `robots.txt`, or not
  being able to reach it, is treated as "no access"; a 404 means no rules);
- it waits 2.5 seconds between requests to a host and backs off on HTTP 429 and 5xx, honouring
  `Retry-After`;
- it only downloads a detail page when the search card is missing rooms, surface, price or floor.

**Check each site's terms of use and local law before collecting data, and do not republish raw
listings.** Selectors and JSON paths in `rentals/parsers/` reflect the sites' markup when this was
written and will need updating when a site changes; the parsers are tested against saved sample pages
in `tests/fixtures/`, not against the live sites.

County slugs are the lower-case, hyphenated county names used in each site's URLs (`cluj`,
`bistrita-nasaud`, `bucuresti`, ...).

## Pipeline

| Stage | Module | What it does |
| --- | --- | --- |
| Fetch | `fetch.py` | `PoliteFetcher` (requests) and optional `SeleniumFetcher`, same interface |
| Parse | `parsers/storia.py`, `parsers/romimo.py` | search cards and detail pages into `Listing` records |
| Crawl | `scrapers.py` | walks every page of a county, reports whether the walk was complete |
| Extract | `text.py` | Romanian number formats, currencies, rooms, surface, floor and year from free text |
| Convert | `fx.py` | RON to EUR from the National Bank of Romania file, falling back to ECB data, then a constant |
| Filter | `filters.py` | drops sales, wanted ads, short-term lets, room shares and non-residential ads |
| Dedup | `dedup.py`, `store.py` | one row per physical apartment across sites; same-site ads are never merged |
| Store | `store.py` | SQLite with sources, price history and disappearance tracking |
| Clean | `clean.py` | plausibility limits, EUR per m2, suspect-price flags |
| Model | `analysis.py` | log rent on log surface, rooms, ground floor and county, HC3 errors, smearing-corrected fair rent, 5-fold out-of-sample check |
| Stata | `stata.py`, `stata/analysis.do` | `.csv` and `.dta` export and the equivalent Stata regression |

### De-duplication

Two ads are the same apartment when they agree on county and rooms, have a surface within 2 m2 and
(when both give one) a price within 5%, and then pass one more test: the same street, or map pins
within 150 m, or near-identical descriptions. Ads from the same site are never merged. The test suite
checks that a synthetic market with 120 planted cross-posts yields exactly 120 merges and no false ones.

### Disappeared listings

An ad is only marked as gone when its county was crawled **to the last page without an error**. A
crawl that hit a failed page or the page limit leaves everything in that county untouched.

Price history is kept per site, so the same flat asking 500 EUR on one site and 510 EUR on another
is not counted as a price change every time the two sites are crawled.

### The model

```
ln(rent_eur) = b0 + b1 ln(surface) + rooms category + ground floor + county + e
```

Standard errors are HC3. Fair rent is `exp(fitted) x mean(exp(residual))` (Duan smearing) so it is not
biased low by the log transform, and `gap_pct` compares the asking rent with it.
Counties with fewer than 30 listings are pooled; rows flagged as suspect prices are excluded.

## Stata

```
python -m rentals analyse --db listings.db --out output
cd output
do ../stata/analysis.do
```

`analysis.do` imports `rentals.csv`, runs `hettest` and `ovtest` on the plain OLS fit, then fits the
same specification as Python with `vce(hc3)` (same pooled county groups, same base county), computes
the smearing factor and fair rent, and repeats the model for ads listed on more than one site. **The .do file has not been run in Stata** (Stata was not available when this was
written). The `.dta` export is verified by reading it back in pandas, and a test checks that every
column the script uses exists in the export.

## Tests

108 tests, all offline:

- number, currency, rooms, surface and floor extraction, including Romanian formats and diacritics
- parsers against saved sample pages, including missing and hidden fields
- robots.txt, throttling, retry and `Retry-After` behaviour using a fake HTTP session
- crawl coverage, page limits, failures and detail-page economy against a fake multi-page site
- de-duplication rules and the SQLite store, including price history and disappearance logic
- the model recovering the surface elasticity and county effects of the synthetic market
- CSV and `.dta` round trips and the command-line demo

```bash
pytest
ruff check .
```

## Limitations

- Only two sites are implemented (Storia and Romimo). Adding one means a `parse_search` and a
  `search_url` function in `rentals/parsers/` and an entry in `scrapers.SITES`.
- Parsers were not run against the live sites in this repository's test environment.
- The model controls for size, rooms, floor and county only. Neighbourhood, building age and
  condition are not in it, and asking rents are not transacted rents.
- Not investment or legal advice.

## License

MIT
