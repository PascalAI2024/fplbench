"""Tests for LightGBM quantile helpers (fixtures only — no hardcoded board numbers)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fplbench.predict import apply_quantile_heads
from fplbench.squad import format_squad_md, pick_squad
from fplbench.train import (
    QUANTILE_COVERAGE_MAX,
    QUANTILE_COVERAGE_MIN,
    _fit_quantile_regressor,
    common_eval_mask,
    decompose_points,
    evaluate,
    interval_coverage,
    interval_shift_for_coverage,
    nudge_bounds_to_coverage_band,
    pinball_loss,
)
from tests.test_pick_squad import _tiny_pool


def test_interval_coverage_on_fixture():
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    lo = np.array([0.0, 1.0, 2.0, 3.0, 10.0])
    hi = np.array([2.0, 3.0, 4.0, 5.0, 11.0])
    # last row 5 ∉ [10, 11]
    assert interval_coverage(y, lo, hi) == pytest.approx(0.8)


def test_interval_coverage_ignores_nonfinite():
    y = np.array([1.0, 2.0, np.nan, 4.0])
    lo = np.array([0.0, 3.0, 0.0, 3.0])
    hi = np.array([2.0, 4.0, 1.0, 5.0])
    # finite rows: 1 in [0,2] yes; 2 in [3,4] no; 4 in [3,5] yes → 2/3
    assert interval_coverage(y, lo, hi) == pytest.approx(2.0 / 3.0)


def test_pinball_loss_matches_definition():
    y = np.array([0.0, 2.0, 4.0])
    pred = np.array([1.0, 2.0, 3.0])
    alpha = 0.1
    # residuals y-pred: -1, 0, 1
    # rho = (alpha-1)*(-1), 0, alpha*1 → 0.9, 0, 0.1 → mean 1/3
    assert pinball_loss(y, pred, alpha) == pytest.approx(1.0 / 3.0)


def test_interval_shift_puts_coverage_in_band():
    rng = np.random.default_rng(0)
    y = rng.normal(loc=3.0, scale=2.0, size=400)
    # Tight band around the mean — well below 75% coverage.
    lo = np.full_like(y, y.mean() - 0.25)
    hi = np.full_like(y, y.mean() + 0.25)
    raw = interval_coverage(y, lo, hi)
    assert raw < QUANTILE_COVERAGE_MIN
    s_lo, s_hi = interval_shift_for_coverage(y, lo, hi)
    adj_lo = lo + s_lo
    adj_hi = hi + s_hi
    assert (adj_lo <= adj_hi).all()
    cov = interval_coverage(y, adj_lo, adj_hi)
    assert QUANTILE_COVERAGE_MIN <= cov <= QUANTILE_COVERAGE_MAX


def test_nudge_breaks_onbound_atom_over_max_coverage():
    """Constant shift cannot split a need==0 atom; per-row nudge must enter the band."""
    n = 100
    y = np.zeros(n)
    lo = np.zeros(n)
    hi = np.ones(n)
    # 91 exact-lower-bound hits + 9 misses → 0.91, just over 0.90
    y[91:] = 3.0
    assert interval_coverage(y, lo, hi) == pytest.approx(0.91)
    assert interval_shift_for_coverage(y, lo, hi) == (0.0, 0.0)
    lo2, hi2 = nudge_bounds_to_coverage_band(y, lo, hi)
    cov = interval_coverage(y, lo2, hi2)
    assert QUANTILE_COVERAGE_MIN <= cov <= QUANTILE_COVERAGE_MAX


def test_interval_shift_is_zero_when_already_in_band():
    y = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    lo = np.array([0.0, 1.0, 2.0, 3.0, 9.0])
    hi = np.array([2.0, 3.0, 4.0, 5.0, 11.0])
    # 5/5 = 100% is outside the band — use 4/5 = 80%
    y = np.array([1.0, 2.0, 3.0, 4.0, 20.0])
    assert interval_coverage(y, lo, hi) == pytest.approx(0.8)
    assert interval_shift_for_coverage(y, lo, hi) == (0.0, 0.0)


def test_e_points_p90_uses_decompose_and_defcon():
    pred_p90 = pd.Series([10.0, 6.0, 4.0])
    minutes = pd.Series([90.0, 45.0, 0.0])
    pred_defcon = pd.Series([0.25, 0.10, 0.40])
    got = decompose_points(pred_p90, minutes) + 2.0 * pred_defcon
    expected = pd.Series([10.0 * 1.0 + 0.5, 6.0 * 0.5 + 0.2, 4.0 * 0.0 + 0.8])
    pd.testing.assert_series_equal(got, expected, check_names=False)


def test_common_eval_mask_matches_evaluate_n_common():
    df = pd.DataFrame(
        {
            "total_points": [2.0, 3.0, np.nan, 1.0],
            "pred_points": [2.0, np.nan, 1.0, 1.5],
            "xp_scraped": [2.0, 2.0, 2.0, 2.0],
            "total_points_r5": [1.0, 1.0, 1.0, 1.0],
            "minutes": [90.0, 90.0, 90.0, 90.0],
            "pred_minutes": [80.0, 80.0, 80.0, 80.0],
            "GW": [2, 3, 4, 5],
            "position": ["MID"] * 4,
            "defcon_hit": [0, 0, 0, 0],
            "pred_defcon": [0.1, 0.1, 0.1, 0.1],
        }
    )
    mask = common_eval_mask(df)
    metrics = evaluate(df)
    assert int(mask.sum()) == metrics["n_common"] == 2


def test_format_squad_md_includes_captain_p90_when_present():
    df = _tiny_pool()
    df["e_points_p90"] = df["e_points_final"] + 1.25
    result = pick_squad(df)
    md = format_squad_md(result)
    cap_p90 = float(
        result.squad.loc[
            result.squad["web_name"] == result.captain_name, "e_points_p90"
        ].iloc[0]
    )
    assert f"e_points_final={result.captain_points:.3f}" in md
    assert f"e_points_p90={cap_p90:.3f}" in md


def test_format_squad_md_omits_p90_when_absent():
    result = pick_squad(_tiny_pool())
    md = format_squad_md(result)
    assert "e_points_p90" not in md


def test_apply_quantile_heads_skips_when_joblibs_missing(tmp_path, monkeypatch):
    import fplbench.predict as predict_mod

    monkeypatch.setattr(predict_mod, "MODELS", tmp_path)
    X = pd.DataFrame({"a": [1.0, 2.0]})
    ones = pd.Series([1.0, 1.0])
    assert apply_quantile_heads(X, ones, ones, ones, ones) == {}


def test_shipped_quantile_coverage_in_required_band():
    path = Path(__file__).resolve().parents[1] / "outputs" / "models" / "val_metrics.json"
    if not path.is_file():
        pytest.skip("val_metrics.json missing")
    metrics = json.loads(path.read_text(encoding="utf-8"))
    if "quantile_coverage_p10_p90" not in metrics:
        pytest.skip("quantile coverage not recorded yet")
    cov = float(metrics["quantile_coverage_p10_p90"])
    assert QUANTILE_COVERAGE_MIN <= cov <= QUANTILE_COVERAGE_MAX


def test_fit_quantile_regressor_uses_quantile_objective():
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"a": rng.normal(size=80), "b": rng.normal(size=80)})
    y = pd.Series(0.5 * X["a"] + X["b"] + rng.normal(scale=0.2, size=80))
    model = _fit_quantile_regressor(X, y, 0.1)
    assert model.objective == "quantile"
    assert model.get_params()["alpha"] == pytest.approx(0.1)
    preds = model.predict(X)
    assert preds.shape == (80,)
    assert np.all(np.isfinite(preds))
