import numpy as np
import pandas as pd
import pytest

from rentals import __main__ as cli
from rentals import fx
from rentals.analysis import best_value, county_summary, effects_table, fit_hedonic, prepare
from rentals.clean import build_dataset
from rentals.pipeline import analyse, collect
from rentals.stata import export, stata_frame
from rentals.store import Store
from rentals.synthetic import COUNTY_EFFECT, TRUE, FakeSite, make_market


@pytest.fixture(scope="module")
def pipeline():
    market = make_market(900, seed=11)
    store = Store()
    collect(
        store,
        FakeSite(market),
        ["storia", "romimo"],
        list(COUNTY_EFFECT),
        fx.RonPerEur(market.ron_per_eur, None, "t"),
    )
    data, reasons = build_dataset(store.frame())
    return market, data, fit_hedonic(data)


def test_hedonic_recovers_surface_elasticity(pipeline):
    _, _, model = pipeline
    assert abs(model.result.params["ln_surface"] - TRUE["ln_surface"]) < 0.08


def test_hedonic_recovers_county_ordering_and_size(pipeline):
    _, _, model = pipeline
    params = model.result.params
    baseline = model.data["county_group"].cat.categories[0]
    for county in ("bucuresti", "cluj", "constanta"):
        estimate = params[f"C(county_group)[T.{county}]"]
        truth = COUNTY_EFFECT[county] - COUNTY_EFFECT[baseline]
        assert abs(estimate - truth) < 0.1
    assert params["C(county_group)[T.bucuresti]"] > params["C(county_group)[T.cluj]"]


def test_fair_rent_is_unbiased_and_gap_centred(pipeline):
    _, _, model = pipeline
    frame = model.data
    assert abs(np.log(frame["price_eur"]).mean() - np.log(frame["fair_rent_eur"]).mean()) < 0.03
    assert abs(frame["gap_pct"].median()) < 5.0
    assert model.smearing > 1.0


def test_out_of_sample_fit_is_reported(pipeline):
    _, _, model = pipeline
    assert model.cv["folds"] == 5
    assert 0.4 < model.cv["out_of_sample_r2"] <= model.r2 + 0.05
    assert model.cv["mape_pct"] < 25


def test_effects_table_and_summaries(pipeline):
    _, data, model = pipeline
    effects = effects_table(model)
    assert "Intercept" not in effects.index and (effects["ci_low_pct"] <= effects["ci_high_pct"]).all()
    summary = county_summary(data)
    assert summary["listings"].sum() == len(data) and summary["median_eur_per_sqm"].is_monotonic_decreasing
    assert best_value(model, 5)["gap_pct"].is_monotonic_increasing


def test_prepare_pools_small_counties_and_drops_suspects():
    frame = pd.DataFrame(
        {
            "ln_rent": np.log(np.linspace(300, 900, 90)), "ln_surface": np.log(np.linspace(30, 90, 90)),
            "rooms_cat": [2] * 90, "county": ["a"] * 60 + ["b"] * 25 + ["c"] * 5,
            "price_suspect": [False] * 88 + [True] * 2, "ground_floor": [np.nan] * 10 + [0.0] * 80,
        }
    )  # fmt: skip
    prepared = prepare(frame, min_county_obs=30)
    assert len(prepared) == 88
    assert set(prepared["county_group"]) == {"a", "other"}
    assert prepared["floor_missing"].sum() == 10


def test_stata_export_round_trips(pipeline, tmp_path):
    _, data, model = pipeline
    paths = export(model.data, tmp_path)
    csv = pd.read_csv(paths["csv"])
    dta = pd.read_stata(paths["dta"])
    assert len(csv) == len(dta) == len(model.data)
    assert np.allclose(csv["price_eur"], dta["price_eur"])
    assert set(dta["county"]) == set(model.data["county"])
    assert stata_frame(model.data)["price_suspect"].isin([0, 1]).all()


def test_stata_do_file_uses_exported_columns():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "stata" / "analysis.do").read_text()
    for column in (
        "ln_rent",
        "ln_surface",
        "rooms_cat",
        "ground_floor",
        "price_suspect",
        "county",
        "n_sources",
    ):
        assert column in script and column in cli_columns()


def cli_columns():
    from rentals.stata import STATA_COLUMNS

    return STATA_COLUMNS


def test_analyse_writes_outputs(tmp_path):
    market = make_market(400, seed=2)
    store = Store()
    collect(store, FakeSite(market), ["storia"], list(COUNTY_EFFECT), fx.RonPerEur(market.ron_per_eur, None, "t"))
    analyse(store, tmp_path)
    for name in (
        "rentals.csv",
        "rentals.dta",
        "effects.csv",
        "county_summary.csv",
        "best_value.csv",
        "exclusions.csv",
    ):
        assert (tmp_path / name).exists()


def test_cli_demo_runs_end_to_end(tmp_path, capsys):
    assert cli.main(["demo", "--out", str(tmp_path), "--listings", "300"]) == 0
    output = capsys.readouterr().out
    assert "surface elasticity" in output and "listed on both sites" in output
    assert (tmp_path / "rentals.dta").exists()


def test_cli_scrape_requires_user_agent():
    with pytest.raises(SystemExit):
        cli.main(["scrape", "--county", "cluj"])
