from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import pandas as pd

from .dedup import MatchRules, same_ad
from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    fingerprint TEXT PRIMARY KEY,
    title TEXT, description TEXT, price REAL, currency TEXT, price_eur REAL,
    rooms INTEGER, surface_sqm REAL, floor INTEGER, total_floors INTEGER, year_built INTEGER,
    county TEXT, locality TEXT, neighborhood TEXT, street TEXT,
    latitude REAL, longitude REAL, first_seen REAL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS sources (
    source TEXT NOT NULL, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
    url TEXT, county TEXT, first_seen REAL, last_seen REAL, active INTEGER DEFAULT 1,
    PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS price_history (
    fingerprint TEXT NOT NULL, source TEXT NOT NULL, observed_at REAL NOT NULL, price_eur REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_block ON listings (county, rooms);
"""

COLUMNS = (
    "title", "description", "price", "currency", "price_eur", "rooms", "surface_sqm", "floor",
    "total_floors", "year_built", "county", "locality", "neighborhood", "street", "latitude", "longitude",
)  # fmt: skip


class Store:
    def __init__(self, path: str | Path = ":memory:", rules: MatchRules | None = None, clock=time.time):
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.rules = rules or MatchRules()
        self.clock = clock

    def close(self) -> None:
        self.connection.close()

    def known_ids(self, source: str) -> set[str]:
        rows = self.connection.execute("SELECT source_id FROM sources WHERE source = ?", (source,))
        return {row["source_id"] for row in rows}

    def candidates(self, listing: Listing) -> list[tuple[str, Listing]]:
        rows = self.connection.execute(
            "SELECT * FROM listings WHERE county IS ? AND (rooms IS ? OR rooms IS NULL OR ? IS NULL)",
            (listing.county, listing.rooms, listing.rooms),
        ).fetchall()
        return [(row["fingerprint"], self.row_to_listing(row)) for row in rows]

    @staticmethod
    def row_to_listing(row: sqlite3.Row) -> Listing:
        values = {name: row[name] for name in COLUMNS}
        return Listing(source="db", source_id=row["fingerprint"], url="", **values)

    def sources_of(self, fingerprint: str) -> set[str]:
        rows = self.connection.execute("SELECT source FROM sources WHERE fingerprint = ?", (fingerprint,))
        return {row["source"] for row in rows}

    def match(self, listing: Listing) -> str | None:
        for fingerprint, existing in self.candidates(listing):
            if listing.source in self.sources_of(fingerprint):
                continue
            if same_ad(listing, existing, self.rules):
                return fingerprint
        return None

    def upsert(self, listing: Listing) -> tuple[str, str]:
        now = self.clock()
        row = self.connection.execute(
            "SELECT fingerprint FROM sources WHERE source = ? AND source_id = ?",
            (listing.source, listing.source_id),
        ).fetchone()
        if row is not None:
            fingerprint, outcome = row["fingerprint"], "known"
        else:
            fingerprint = self.match(listing)
            outcome = "mirror" if fingerprint else "new"
            fingerprint = fingerprint or uuid.uuid4().hex[:16]
        self.connection.execute(
            "INSERT INTO sources (source, source_id, fingerprint, url, county, first_seen, last_seen, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT(source, source_id) DO UPDATE SET "
            "last_seen = excluded.last_seen, active = 1, url = excluded.url",
            (listing.source, listing.source_id, fingerprint, listing.url, listing.county, now, now),
        )
        self.write_listing(fingerprint, listing, now)
        return fingerprint, outcome

    def write_listing(self, fingerprint: str, listing: Listing, now: float) -> None:
        existing = self.connection.execute("SELECT * FROM listings WHERE fingerprint = ?", (fingerprint,)).fetchone()
        if existing is None:
            columns = ", ".join(("fingerprint", *COLUMNS, "first_seen", "last_seen"))
            marks = ", ".join("?" * (len(COLUMNS) + 3))
            values = [fingerprint, *(getattr(listing, c) for c in COLUMNS), now, now]
            self.connection.execute(f"INSERT INTO listings ({columns}) VALUES ({marks})", values)
        else:
            current = self.row_to_listing(existing)
            merged = listing.merge(current)
            assignments = ", ".join(f"{c} = ?" for c in COLUMNS)
            values = [getattr(merged, c) for c in COLUMNS]
            self.connection.execute(
                f"UPDATE listings SET {assignments}, last_seen = ? WHERE fingerprint = ?",
                [*values, now, fingerprint],
            )
        if listing.price_eur is not None:
            last = self.connection.execute(
                "SELECT price_eur FROM price_history WHERE fingerprint = ? AND source = ? "
                "ORDER BY observed_at DESC, rowid DESC LIMIT 1",
                (fingerprint, listing.source),
            ).fetchone()
            if last is None or abs(last["price_eur"] - listing.price_eur) > 1e-9:
                self.connection.execute(
                    "INSERT INTO price_history (fingerprint, source, observed_at, price_eur) VALUES (?, ?, ?, ?)",
                    (fingerprint, listing.source, now, listing.price_eur),
                )
        self.connection.commit()

    def mark_disappeared(self, source: str, county: str, seen_ids: set[str], complete: bool) -> int:
        if not complete:
            return 0
        rows = self.connection.execute(
            "SELECT source_id FROM sources WHERE source = ? AND county = ? AND active = 1", (source, county)
        ).fetchall()
        gone = [row["source_id"] for row in rows if row["source_id"] not in seen_ids]
        for source_id in gone:
            self.connection.execute(
                "UPDATE sources SET active = 0 WHERE source = ? AND source_id = ?", (source, source_id)
            )
        self.connection.commit()
        return len(gone)

    def frame(self, active_only: bool = False) -> pd.DataFrame:
        query = (
            "SELECT l.*, group_concat(DISTINCT s.source) AS sources, count(DISTINCT s.source) AS n_sources, "
            "max(s.active) AS active, min(s.url) AS url FROM listings l "
            "JOIN sources s ON s.fingerprint = l.fingerprint GROUP BY l.fingerprint"
        )
        data = pd.read_sql_query(query, self.connection)
        history = pd.read_sql_query(
            "SELECT fingerprint, count(*) - count(DISTINCT source) AS n_price_changes "
            "FROM price_history GROUP BY fingerprint",
            self.connection,
        )
        data = data.merge(history, on="fingerprint", how="left").fillna({"n_price_changes": 0})
        return data[data["active"] == 1] if active_only else data
