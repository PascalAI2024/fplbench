"""Unit tests for DefCon probability calibration helpers (tiny fixtures only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from fplbench.calibrate import (
    apply_calibrator,
    apply_calibrator_to_scaled_probs,
    brier,
    fit_calibrator,
    holdout_defcon_mask,
    logloss,
    oof_predict_proba,
    select_calibrator,
)
from fplbench.train import DEFCON_TRAIN_GW_MAX, evaluate


def _miscalibrated_fixture(n: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    y = np.array([0] * (n - 30) + [1] * 30)
    rng.shuffle(y)
    # Under-confident scores still in (0, 1).
    p = np.clip(0.04 + 0.12 * y + rng.normal(0, 0.02, size=n), 1e-3, 0.35)
    return y, p


def test_fit_calibrator_is_callable_transform():
    y, p = _miscalibrated_fixture()
    cal = fit_calibrator(p, y, method="platt")
    assert callable(cal)
    assert hasattr(cal, "transform")
    p_cal = apply_calibrator(cal, p)
    assert p_cal.shape == p.shape
    assert np.all(p_cal > 0.0) and np.all(p_cal < 1.0)
    via_transform = cal.transform(p)
    assert via_transform.shape == p.shape


def test_brier_and_logloss_helpers_are_not_hardcoded():
    y = np.array([0.0, 1.0, 0.0, 1.0])
    p = np.array([0.1, 0.9, 0.2, 0.8])
    expected_brier = float(np.mean((p - y) ** 2))
    p_clip = np.clip(p, 1e-6, 1.0 - 1e-6)
    expected_ll = float(-np.mean(y * np.log(p_clip) + (1.0 - y) * np.log(1.0 - p_clip)))
    assert abs(brier(y, p) - expected_brier) < 1e-12
    assert abs(logloss(y, p) - expected_ll) < 1e-12
    p_worse = np.array([0.4, 0.5, 0.4, 0.5])
    assert brier(y, p_worse) > brier(y, p)
    assert logloss(y, p_worse) > logloss(y, p)


def test_evaluate_uses_holdout_mask_and_helpers():
    n = 8
    df = pd.DataFrame(
        {
            "GW": [10, 29, 30, 31, 32, 33, 34, 28],
            "position": ["DEF", "DEF", "GK", "MID", "FWD", "MID", "DEF", "DEF"],
            "minutes": [90, 90, 90, 0, 90, 90, 90, 90],
            "defcon_hit": [1, 1, 0, 0, 0, 1, 0, 1],
            "pred_defcon": [0.2, 0.8, 0.1, 0.3, 0.1, 0.7, 0.2, 0.9],
            "total_points": [2.0] * n,
            "pred_points": [2.0] * n,
            "pred_minutes": [90.0] * n,
            "xp_scraped": [2.0] * n,
            "total_points_r5": [2.0] * n,
            "pred_points_decomposed": [2.0] * n,
        }
    )
    mask = holdout_defcon_mask(df, train_gw_max=DEFCON_TRAIN_GW_MAX)
    # GW<=28, GK, and minutes=0 dropped; remaining rows 1, 4, 5, 6 (0-based).
    assert list(df.index[mask]) == [1, 4, 5, 6]
    metrics = evaluate(df)
    y = df.loc[mask, "defcon_hit"].to_numpy(dtype=float)
    p = df.loc[mask, "pred_defcon"].to_numpy(dtype=float)
    assert metrics["defcon_brier"] == brier(y, p)
    assert metrics["defcon_logloss"] == logloss(y, p)


def test_select_calibrator_ships_only_when_both_improve():
    y, p = _miscalibrated_fixture(n=200, seed=1)
    # Same-set OOF/holdout is only for the API; production fits OOF vs holdout-head.
    choice = select_calibrator(p, y, p, y)
    assert choice.logloss_before == logloss(y, p)
    assert choice.brier_before == brier(y, p)
    if choice.shipped:
        assert choice.calibrator is not None
        p_cal = apply_calibrator(choice.calibrator, p)
        assert choice.logloss_after < choice.logloss_before
        assert choice.brier_after < choice.brier_before
        assert abs(choice.logloss_after - logloss(y, p_cal)) < 1e-12
        assert abs(choice.brier_after - brier(y, p_cal)) < 1e-12
    else:
        assert choice.calibrator is None
        assert choice.method == "none"
        assert choice.note is not None


def test_oof_predict_proba_and_scaled_apply():
    rng = np.random.default_rng(2)
    X = pd.DataFrame({"a": rng.normal(size=80), "b": rng.normal(size=80)})
    y = pd.Series((X["a"] + 0.2 * X["b"] > 0).astype(int))
    est = LogisticRegression(solver="lbfgs", max_iter=200)
    oof = oof_predict_proba(X, y, est, n_splits=4, seed=2)
    assert oof.shape == (80,)
    assert np.all(np.isfinite(oof))
    assert np.all((oof > 0) & (oof < 1))

    cal = fit_calibrator(oof, y.to_numpy(), method="platt")
    scale = np.array([1.0, 0.5, 0.0, 0.8])
    playable = np.array([True, True, True, False])
    p_scaled = np.array([0.2, 0.1, 0.0, 0.3])
    out = apply_calibrator_to_scaled_probs(p_scaled, scale, playable, cal)
    assert out[2] == 0.0
    assert out[3] == 0.0
    raw = np.array([0.2, 0.1 / 0.5])
    cal_raw = apply_calibrator(cal, raw)
    assert abs(out[0] - cal_raw[0] * 1.0) < 1e-12
    assert abs(out[1] - cal_raw[1] * 0.5) < 1e-12
