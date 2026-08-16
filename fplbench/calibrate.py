"""OOF probability calibration for the DefCon classifier."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import StratifiedKFold

P_LO = 1e-6
P_HI = 1.0 - 1e-6
ISOTONIC_MIN_POSITIVES = 500  # Platt when labelled OOF positives are below this
OOF_FOLDS = 5
OOF_SEED = 42


def clip_proba(p: np.ndarray | pd.Series) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), P_LO, P_HI)


def brier(y: np.ndarray | pd.Series, p: np.ndarray | pd.Series) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = clip_proba(p)
    ok = np.isfinite(y_arr) & np.isfinite(p_arr)
    return float(brier_score_loss(y_arr[ok], p_arr[ok]))


def logloss(y: np.ndarray | pd.Series, p: np.ndarray | pd.Series) -> float:
    y_arr = np.asarray(y, dtype=float)
    p_arr = clip_proba(p)
    ok = np.isfinite(y_arr) & np.isfinite(p_arr)
    return float(log_loss(y_arr[ok], p_arr[ok]))


def holdout_defcon_mask(df: pd.DataFrame, *, train_gw_max: int = 28) -> pd.Series:
    """GW>train_gw_max, non-GK, minutes>0, labels+preds finite. Same rules as evaluate()."""
    y = pd.to_numeric(df["defcon_hit"], errors="coerce")
    p = pd.to_numeric(df["pred_defcon"], errors="coerce")
    gw = pd.to_numeric(df["GW"], errors="coerce")
    minutes = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
    pos = df["position"].astype(str).str.upper()
    return (
        y.notna()
        & p.notna()
        & np.isfinite(y)
        & np.isfinite(p)
        & ~pos.eq("GK")
        & (gw > train_gw_max)
        & (minutes > 0)
    )


def n_positives(y: np.ndarray | pd.Series) -> int:
    return int(np.sum(np.asarray(y, dtype=float) >= 0.5))


class ProbabilityCalibrator:
    """Thin joblib-friendly wrapper: transform(p) -> p_cal."""

    def __init__(self, method: str, backend: object):
        if method not in {"isotonic", "platt"}:
            raise ValueError(f"unknown calibrator method: {method}")
        self.method = method
        self.backend = backend

    def transform(self, p: np.ndarray | pd.Series) -> np.ndarray:
        arr = np.asarray(p, dtype=float).ravel()
        if self.method == "isotonic":
            out = np.asarray(self.backend.predict(arr), dtype=float)
        else:
            out = np.asarray(
                self.backend.predict_proba(arr.reshape(-1, 1))[:, 1], dtype=float
            )
        return out

    def __call__(self, p: np.ndarray | pd.Series) -> np.ndarray:
        return self.transform(p)


def apply_calibrator(cal: ProbabilityCalibrator, p: np.ndarray | pd.Series) -> np.ndarray:
    return clip_proba(cal.transform(p))


def fit_calibrator(
    p_oof: np.ndarray | pd.Series,
    y_oof: np.ndarray | pd.Series,
    method: str | None = None,
) -> ProbabilityCalibrator:
    y = np.asarray(y_oof, dtype=int)
    p = clip_proba(p_oof)
    if method is None:
        method = "platt" if n_positives(y) < ISOTONIC_MIN_POSITIVES else "isotonic"
    if method == "isotonic":
        backend = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        backend.fit(p, y)
        return ProbabilityCalibrator("isotonic", backend)
    if method == "platt":
        backend = LogisticRegression(solver="lbfgs", max_iter=1000)
        backend.fit(p.reshape(-1, 1), y)
        return ProbabilityCalibrator("platt", backend)
    raise ValueError(f"unknown calibrator method: {method}")


def oof_predict_proba(
    X: pd.DataFrame,
    y: pd.Series | np.ndarray,
    estimator: object,
    *,
    n_splits: int = OOF_FOLDS,
    seed: int = OOF_SEED,
) -> np.ndarray:
    """Collect clone(estimator) out-of-fold predict_proba[:, 1]."""
    X_df = pd.DataFrame(X).reset_index(drop=True)
    y_s = pd.Series(np.asarray(y, dtype=int)).reset_index(drop=True)
    oof = np.full(len(y_s), np.nan, dtype=float)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for train_idx, test_idx in skf.split(X_df, y_s):
        model = clone(estimator)
        model.fit(X_df.iloc[train_idx], y_s.iloc[train_idx])
        oof[test_idx] = model.predict_proba(X_df.iloc[test_idx])[:, 1]
    if not np.all(np.isfinite(oof)):
        raise RuntimeError("OOF DefCon probabilities contain non-finite values")
    return oof


@dataclass
class CalibrationChoice:
    shipped: bool
    method: str
    calibrator: ProbabilityCalibrator | None
    logloss_before: float
    brier_before: float
    logloss_after: float
    brier_after: float
    n_pos_oof: int
    note: str | None = None
    attempts: dict[str, dict[str, float]] = field(default_factory=dict)


def select_calibrator(
    p_oof: np.ndarray | pd.Series,
    y_oof: np.ndarray | pd.Series,
    p_hold: np.ndarray | pd.Series,
    y_hold: np.ndarray | pd.Series,
) -> CalibrationChoice:
    """Fit on OOF only. Ship iff holdout logloss AND Brier both strictly improve."""
    n_pos = n_positives(y_oof)
    primary = "platt" if n_pos < ISOTONIC_MIN_POSITIVES else "isotonic"
    secondary = "isotonic" if primary == "platt" else "platt"
    before_ll = logloss(y_hold, p_hold)
    before_br = brier(y_hold, p_hold)
    attempts: dict[str, dict[str, float]] = {}
    winner: tuple[str, ProbabilityCalibrator, float, float] | None = None
    first_after: tuple[float, float] | None = None

    for method in (primary, secondary):
        cal = fit_calibrator(p_oof, y_oof, method=method)
        p_after = apply_calibrator(cal, p_hold)
        after_ll = logloss(y_hold, p_after)
        after_br = brier(y_hold, p_after)
        attempts[method] = {"logloss": after_ll, "brier": after_br}
        if first_after is None:
            first_after = (after_ll, after_br)
        if after_ll < before_ll and after_br < before_br:
            winner = (method, cal, after_ll, after_br)
            break

    if winner is not None:
        method, cal, after_ll, after_br = winner
        return CalibrationChoice(
            shipped=True,
            method=method,
            calibrator=cal,
            logloss_before=before_ll,
            brier_before=before_br,
            logloss_after=after_ll,
            brier_after=after_br,
            n_pos_oof=n_pos,
            attempts=attempts,
        )

    after_ll, after_br = first_after if first_after is not None else (before_ll, before_br)
    return CalibrationChoice(
        shipped=False,
        method="none",
        calibrator=None,
        logloss_before=before_ll,
        brier_before=before_br,
        logloss_after=after_ll,
        brier_after=after_br,
        n_pos_oof=n_pos,
        note=(
            "Neither isotonic nor Platt improved both holdout logloss and Brier; "
            "kept raw DefCon head."
        ),
        attempts=attempts,
    )


def apply_calibrator_to_scaled_probs(
    p_scaled: np.ndarray | pd.Series,
    scale: np.ndarray | pd.Series,
    playable: np.ndarray | pd.Series,
    cal: ProbabilityCalibrator,
) -> np.ndarray:
    """Unscale availability, calibrate raw P, re-apply scale. GK / scale=0 stay 0."""
    p_scaled_arr = np.asarray(p_scaled, dtype=float)
    scale_arr = np.asarray(scale, dtype=float)
    playable_arr = np.asarray(playable, dtype=bool)
    raw = np.zeros_like(p_scaled_arr)
    nz = playable_arr & np.isfinite(scale_arr) & (scale_arr > 0)
    raw[nz] = p_scaled_arr[nz] / scale_arr[nz]
    out = np.zeros_like(p_scaled_arr)
    if playable_arr.any():
        out[playable_arr] = apply_calibrator(cal, raw[playable_arr])
    out = out * np.where(np.isfinite(scale_arr), scale_arr, 0.0)
    out[~playable_arr] = 0.0
    return out
