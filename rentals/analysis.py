from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from patsy import dmatrices

FORMULA = "ln_rent ~ ln_surface + C(rooms_cat) + ground_floor + floor_missing + C(county_group)"


def formula_for(frame: pd.DataFrame, base: str = FORMULA) -> str:
    return base if frame["floor_missing"].nunique() > 1 else base.replace(" + floor_missing", "")


@dataclass
class Hedonic:
    result: object
    data: pd.DataFrame
    smearing: float
    cv: dict

    @property
    def r2(self) -> float:
        return float(self.result.rsquared)


def prepare(data: pd.DataFrame, min_county_obs: int = 30) -> pd.DataFrame:
    frame = data.dropna(subset=["ln_rent", "ln_surface", "rooms_cat", "county"]).copy()
    frame = frame[~frame["price_suspect"]]
    frame["floor_missing"] = frame["ground_floor"].isna().astype(int)
    frame["ground_floor"] = frame["ground_floor"].fillna(0.0)
    counts = frame["county"].value_counts()
    big = counts[counts >= min_county_obs].index
    frame["county_group"] = frame["county"].where(frame["county"].isin(big), "other")
    baseline = frame["county_group"].value_counts().idxmax()
    order = [baseline] + sorted(set(frame["county_group"]) - {baseline})
    frame["county_group"] = pd.Categorical(frame["county_group"], categories=order)
    return frame


def cross_validate(frame: pd.DataFrame, formula: str = FORMULA, folds: int = 5, seed: int = 0) -> dict:
    y, x = dmatrices(formula, frame, return_type="dataframe")
    order = np.random.default_rng(seed).permutation(len(frame))
    errors, targets = [], []
    for fold in range(folds):
        test = order[fold::folds]
        train = np.setdiff1d(order, test)
        beta, *_ = np.linalg.lstsq(x.to_numpy()[train], y.to_numpy()[train, 0], rcond=None)
        residual = y.to_numpy()[train, 0] - x.to_numpy()[train] @ beta
        smear = float(np.mean(np.exp(residual)))
        predicted = np.exp(x.to_numpy()[test] @ beta) * smear
        errors.append(predicted - np.exp(y.to_numpy()[test, 0]))
        targets.append(np.exp(y.to_numpy()[test, 0]))
    error, target = np.concatenate(errors), np.concatenate(targets)
    ratio = 1.0 - float(np.sum(error**2) / np.sum((target - target.mean()) ** 2))
    return {
        "folds": folds,
        "mae_eur": float(np.mean(np.abs(error))),
        "mape_pct": float(np.mean(np.abs(error) / target) * 100.0),
        "out_of_sample_r2": ratio,
    }


def fit_hedonic(data: pd.DataFrame, formula: str = FORMULA, min_county_obs: int = 30) -> Hedonic:
    frame = prepare(data, min_county_obs)
    formula = formula_for(frame, formula)
    y, x = dmatrices(formula, frame, return_type="dataframe")
    result = sm.OLS(y, x).fit(cov_type="HC3")
    smearing = float(np.mean(np.exp(result.resid)))
    frame["fair_rent_eur"] = np.exp(result.fittedvalues) * smearing
    frame["gap_pct"] = (frame["price_eur"] / frame["fair_rent_eur"] - 1.0) * 100.0
    return Hedonic(result, frame, smearing, cross_validate(frame, formula))


def effects_table(model: Hedonic) -> pd.DataFrame:
    params = model.result.params
    interval = model.result.conf_int()
    table = pd.DataFrame(
        {
            "coef": params,
            "robust_se": model.result.bse,
            "t": model.result.tvalues,
            "effect_pct": (np.exp(params) - 1.0) * 100.0,
            "ci_low_pct": (np.exp(interval[0]) - 1.0) * 100.0,
            "ci_high_pct": (np.exp(interval[1]) - 1.0) * 100.0,
        }
    )
    return table.drop(index="Intercept")


def county_summary(data: pd.DataFrame) -> pd.DataFrame:
    grouped = data.groupby("county")
    return pd.DataFrame(
        {
            "listings": grouped.size(),
            "median_rent_eur": grouped["price_eur"].median(),
            "median_eur_per_sqm": grouped["eur_per_sqm"].median(),
            "median_surface": grouped["surface_sqm"].median(),
        }
    ).sort_values("median_eur_per_sqm", ascending=False)


def best_value(model: Hedonic, top: int = 10) -> pd.DataFrame:
    columns = ["county", "title", "rooms", "surface_sqm", "price_eur", "fair_rent_eur", "gap_pct"]
    return model.data.sort_values("gap_pct").head(top)[[c for c in columns if c in model.data]]
