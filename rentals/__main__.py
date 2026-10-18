from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import fx
from .analysis import effects_table
from .fetch import PoliteFetcher
from .pipeline import analyse, collect
from .scrapers import SITES
from .store import Store
from .synthetic import COUNTY_EFFECT, TRUE, FakeSite, make_market


def demo(out: str, seed: int, listings: int) -> int:
    market = make_market(listings, seed)
    store = Store(":memory:")
    site = FakeSite(market)
    reports = collect(store, site, list(SITES), list(COUNTY_EFFECT), fx.RonPerEur(market.ron_per_eur, None, "demo"))
    data, model = analyse(store, out)
    frame = store.frame()
    print(f"advertised listings: {len(market.listings)}   distinct apartments stored: {len(frame)}")
    print(f"listed on both sites: {int((frame['n_sources'] > 1).sum())}   pages fetched: {len(site.requests)}")
    print(f"complete county crawls: {sum(sum(r.coverage.values()) for r in reports.values())}")
    elasticity = float(model.result.params["ln_surface"])
    print(f"surface elasticity: estimated {elasticity:.3f}   true {TRUE['ln_surface']}")
    effects = effects_table(model)
    print(effects.round(3).to_string())
    print(f"R2 {model.r2:.3f}   out-of-sample R2 {model.cv['out_of_sample_r2']:.3f}   MAPE {model.cv['mape_pct']:.1f}%")
    print(f"outputs written to {Path(out).resolve()}")
    store.close()
    return 0


def scrape(args) -> int:
    fetcher = PoliteFetcher(delay=args.delay, user_agent=args.user_agent)
    store = Store(args.db)
    rate = fx.fetch_rate(fetcher)
    print(f"RON per EUR: {rate.rate} ({rate.source})")
    reports = collect(store, fetcher, args.site, args.county, rate, args.max_pages)
    for site, report in reports.items():
        print(site, "coverage", report.coverage, "failures", len(report.failures))
    store.close()
    return 0


def analyse_command(args) -> int:
    store = Store(args.db)
    data, model = analyse(store, args.out)
    print(model.result.summary().tables[1])
    print(pd.Series(model.cv).round(3).to_string())
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rentals")
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="run everything offline on a synthetic market")
    demo_parser.add_argument("--out", default="output")
    demo_parser.add_argument("--seed", type=int, default=3)
    demo_parser.add_argument("--listings", type=int, default=600)
    scrape_parser = commands.add_parser("scrape", help="collect live listings into a SQLite database")
    scrape_parser.add_argument("--site", nargs="+", default=["storia"], choices=sorted(SITES))
    scrape_parser.add_argument("--county", nargs="+", required=True)
    scrape_parser.add_argument("--db", default="listings.db")
    scrape_parser.add_argument("--max-pages", type=int, default=None)
    scrape_parser.add_argument("--delay", type=float, default=2.5)
    scrape_parser.add_argument("--user-agent", required=True, help="identify yourself, e.g. 'my-thesis (me@uni.ro)'")
    analyse_parser = commands.add_parser("analyse", help="clean the database and fit the hedonic model")
    analyse_parser.add_argument("--db", default="listings.db")
    analyse_parser.add_argument("--out", default="output")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo(args.out, args.seed, args.listings)
    return scrape(args) if args.command == "scrape" else analyse_command(args)


if __name__ == "__main__":
    sys.exit(main())
