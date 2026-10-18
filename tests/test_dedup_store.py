from rentals.dedup import MatchRules, cluster, normalise, same_ad
from rentals.models import Listing
from rentals.store import Store


def make(source="storia", source_id="1", **values):
    base = dict(
        url=f"https://x/{source_id}", county="cluj", rooms=2, surface_sqm=55.0, price_eur=500.0,
        street="Strada Florilor", neighborhood="Zorilor", locality="Cluj-Napoca",
        latitude=46.77, longitude=23.59,
    )  # fmt: skip
    return Listing(source=source, source_id=source_id, **{**base, **values})


def test_normalise_expands_street_abbreviations():
    assert normalise("Str. Mihai Eminescu") == "strada mihai eminescu"
    assert normalise("Bd. Unirii") == "bulevardul unirii"


def test_same_ad_accepts_identical_apartment_with_small_noise():
    assert same_ad(make(), make("romimo", "9", price_eur=510.0, surface_sqm=54.0))


def test_same_ad_rejects_each_conflicting_field():
    base = make()
    assert not same_ad(base, make("romimo", "9", county="iasi"))
    assert not same_ad(base, make("romimo", "9", rooms=3))
    assert not same_ad(base, make("romimo", "9", surface_sqm=60.0))
    assert not same_ad(base, make("romimo", "9", surface_sqm=None))
    assert not same_ad(base, make("romimo", "9", price_eur=700.0))
    assert not same_ad(base, make("romimo", "9", street="Calea Turzii", neighborhood="Gheorgheni"))


def test_same_ad_needs_evidence_when_street_missing():
    other = make("romimo", "9", street=None, neighborhood=None, latitude=None, longitude=None)
    assert not same_ad(make(), other)
    first = make(description="Apartament luminos cu doua camere, mobilat modern, zona linistita")
    other.description = first.description
    assert same_ad(first, other)


def test_same_ad_uses_map_pin_when_street_missing():
    near = make("romimo", "9", street=None, latitude=46.7705, longitude=23.5901)
    far = make("romimo", "9", street=None, latitude=46.80, longitude=23.62)
    assert same_ad(make(), near) and not same_ad(make(), far)


def test_missing_price_does_not_block_a_match():
    assert same_ad(make(), make("romimo", "9", price_eur=None))


def test_cluster_groups_duplicates_across_blocks():
    items = [
        make(source_id="1"),
        make("romimo", "2"),
        make(source_id="3", surface_sqm=90.0, rooms=3),
        make("romimo", "4", surface_sqm=90.0, rooms=3),
    ]
    groups = sorted(sorted(g) for g in cluster(items))
    assert groups == [[0, 1], [2, 3]]
    assert MatchRules().surface_tolerance_sqm == 2.0


def test_store_new_known_and_mirror():
    store = Store()
    fingerprint, outcome = store.upsert(make())
    assert outcome == "new"
    assert store.upsert(make())[1] == "known"
    mirror_fingerprint, mirror_outcome = store.upsert(make("romimo", "9", price_eur=505.0))
    assert (mirror_outcome, mirror_fingerprint) == ("mirror", fingerprint)
    frame = store.frame()
    assert (
        len(frame) == 1
        and frame.loc[0, "n_sources"] == 2
        and frame.loc[0, "sources"] in ("romimo,storia", "storia,romimo")
    )
    assert store.known_ids("storia") == {"1"} and store.known_ids("romimo") == {"9"}


def test_same_site_listings_are_never_merged():
    store = Store()
    store.upsert(make(source_id="1"))
    _, outcome = store.upsert(make(source_id="2"))
    assert outcome == "new" and len(store.frame()) == 2


def test_price_history_records_changes_only():
    store = Store()
    store.upsert(make())
    store.upsert(make())
    store.upsert(make(price_eur=450.0))
    frame = store.frame()
    assert frame.loc[0, "n_price_changes"] == 1 and frame.loc[0, "price_eur"] == 450.0


def test_price_differences_between_sites_are_not_price_changes():
    store = Store()
    for _ in range(3):
        store.upsert(make())
        store.upsert(make("romimo", "9", price_eur=510.0))
    assert store.frame().loc[0, "n_price_changes"] == 0
    store.upsert(make("romimo", "9", price_eur=490.0))
    assert store.frame().loc[0, "n_price_changes"] == 1


def test_known_listing_fills_gaps_without_overwriting():
    store = Store()
    store.upsert(make(floor=None))
    store.upsert(make(floor=4, price_eur=500.0))
    store.upsert(make(floor=None, surface_sqm=55.0))
    assert store.frame().loc[0, "floor"] == 4


def test_disappearance_requires_complete_coverage():
    store = Store()
    for index in range(3):
        store.upsert(make(source_id=str(index), surface_sqm=30.0 + 10 * index))
    assert store.mark_disappeared("storia", "cluj", {"0"}, complete=False) == 0
    assert len(store.frame(active_only=True)) == 3
    assert store.mark_disappeared("storia", "cluj", {"0"}, complete=True) == 2
    assert len(store.frame(active_only=True)) == 1


def test_store_persists_to_disk(tmp_path):
    path = tmp_path / "rentals.db"
    first = Store(path)
    first.upsert(make())
    first.close()
    second = Store(path)
    assert len(second.frame()) == 1
