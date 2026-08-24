"""Train minutes, DefCon, and points LightGBM heads on a season holdout."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score

from fplbench.calibrate import (
    apply_calibrator,
    apply_calibrator_to_scaled_probs,
    brier,
    holdout_defcon_mask,
    logloss,
    oof_predict_proba,
    select_calibrator,
)
from fplbench.panel import feature_columns
from fplbench.paths import MODELS, PREDS, PROCESSED

TRAIN_SEASONS = {"2021-22", "2022-23", "2023-24", "2024-25"}
VAL_SEASON = "2025-26"
# DefCon scoring started 2025-26. Time-split that season instead of using 2024-25.
DEFCON_SEASON = "2025-26"
DEFCON_TRAIN_GW_MAX = 28


def _xy(
    df: pd.DataFrame, target: str, feats: list[str], mask: pd.Series | None = None
) -> tuple[pd.DataFrame, pd.Series]:
    use = df if mask is None else df.loc[mask]
    X = use[feats].apply(pd.to_numeric, errors="coerce")
    y = pd.to_numeric(use[target], errors="coerce")
    ok = y.notna()
    return X.loc[ok], y.loc[ok]


REGRESSOR_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 40,
    "random_state": 42,
    "verbosity": -1,
}

QUANTILE_ALPHA_P10 = 0.1
QUANTILE_ALPHA_P90 = 0.9
QUANTILE_COVERAGE_MIN = 0.75
QUANTILE_COVERAGE_MAX = 0.90


def _fit_regressor(X: pd.DataFrame, y: pd.Series) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(**REGRESSOR_PARAMS)
    model.fit(X, y)
    return model


def _fit_quantile_regressor(
    X: pd.DataFrame, y: pd.Series, alpha: float
) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        **REGRESSOR_PARAMS,
    )
    model.fit(X, y)
    return model


CLASSIFIER_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 40,
    "random_state": 42,
    "verbosity": -1,
}


def _classifier_estimator() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(**CLASSIFIER_PARAMS)


def _fit_classifier(X: pd.DataFrame, y: pd.Series) -> lgb.LGBMClassifier:
    model = _classifier_estimator()
    model.fit(X, y)
    return model


def last5_baseline(df: pd.DataFrame) -> pd.Series:
    if "total_points_r5" in df.columns:
        return pd.to_numeric(df["total_points_r5"], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def decompose_points(
    pred_points: pd.Series | np.ndarray, pred_minutes: pd.Series | np.ndarray
) -> pd.Series:
    """Availability-gate points: E[pts] ≈ pred_points * clip(pred_minutes/90, 0, 1)."""
    pts = pd.to_numeric(pd.Series(pred_points), errors="coerce")
    mins = pd.to_numeric(pd.Series(pred_minutes), errors="coerce")
    p_play = (mins / 90.0).clip(0.0, 1.0)
    out = pts * p_play
    out.index = pts.index
    return out


# Publish decomposed points when holdout MAE on the evaluate() common mask is at most this.
DECOMPOSED_MAE_PUBLISH_MAX = 0.980


def common_eval_mask(val: pd.DataFrame) -> pd.Series:
    """Finite total_points + pred_points + last5 + xp_scraped (evaluate() common mask)."""
    y = pd.to_numeric(val["total_points"], errors="coerce")
    pred = pd.to_numeric(val["pred_points"], errors="coerce")
    last5 = last5_baseline(val)
    xp = pd.to_numeric(val["xp_scraped"], errors="coerce")
    return (
        y.notna()
        & pred.notna()
        & last5.notna()
        & xp.notna()
        & np.isfinite(y)
        & np.isfinite(pred)
        & np.isfinite(last5)
        & np.isfinite(xp)
    )


def interval_coverage(
    y: pd.Series | np.ndarray,
    lo: pd.Series | np.ndarray,
    hi: pd.Series | np.ndarray,
) -> float:
    """Share of rows with lo <= y <= hi among pairwise-finite observations."""
    y_arr = np.asarray(pd.to_numeric(pd.Series(y), errors="coerce"), dtype=float)
    lo_arr = np.asarray(pd.to_numeric(pd.Series(lo), errors="coerce"), dtype=float)
    hi_arr = np.asarray(pd.to_numeric(pd.Series(hi), errors="coerce"), dtype=float)
    ok = np.isfinite(y_arr) & np.isfinite(lo_arr) & np.isfinite(hi_arr)
    if not ok.any():
        return float("nan")
    return float(np.mean((y_arr[ok] >= lo_arr[ok]) & (y_arr[ok] <= hi_arr[ok])))


def pinball_loss(
    y: pd.Series | np.ndarray, pred: pd.Series | np.ndarray, alpha: float
) -> float:
    y_s = pd.to_numeric(pd.Series(y), errors="coerce")
    p_s = pd.to_numeric(pd.Series(pred), errors="coerce")
    ok = y_s.notna() & p_s.notna() & np.isfinite(y_s) & np.isfinite(p_s)
    if not ok.any():
        return float("nan")
    delta = y_s[ok].to_numpy(dtype=float) - p_s[ok].to_numpy(dtype=float)
    return float(np.mean(np.where(delta >= 0.0, alpha * delta, (alpha - 1.0) * delta)))


def interval_shift_for_coverage(
    y: pd.Series | np.ndarray,
    lo: pd.Series | np.ndarray,
    hi: pd.Series | np.ndarray,
    *,
    min_coverage: float = QUANTILE_COVERAGE_MIN,
    max_coverage: float = QUANTILE_COVERAGE_MAX,
) -> tuple[float, float]:
    """Symmetric monotone shift so empirical coverage lands in [min, max].

    Returns ``(shift_lo, shift_hi)`` added to the raw bounds. Expansion is
    ``(-d, +d)``; contraction is the reverse. ``d`` is the smallest (in
    absolute value) constant that puts coverage on the nearer band edge.
    """
    y_arr = np.asarray(pd.to_numeric(pd.Series(y), errors="coerce"), dtype=float)
    lo_arr = np.asarray(pd.to_numeric(pd.Series(lo), errors="coerce"), dtype=float)
    hi_arr = np.asarray(pd.to_numeric(pd.Series(hi), errors="coerce"), dtype=float)
    ok = np.isfinite(y_arr) & np.isfinite(lo_arr) & np.isfinite(hi_arr)
    y_arr, lo_arr, hi_arr = y_arr[ok], lo_arr[ok], hi_arr[ok]
    if y_arr.size == 0:
        return 0.0, 0.0
    need = np.maximum(lo_arr - y_arr, y_arr - hi_arr)
    cov0 = float(np.mean(need <= 0.0))
    if min_coverage <= cov0 <= max_coverage:
        d = 0.0
    elif cov0 < min_coverage:
        d = float(np.quantile(need, min_coverage))
    else:
        d = float(np.quantile(need, max_coverage))

    def _cov(delta: float) -> float:
        return float(np.mean((y_arr >= lo_arr - delta) & (y_arr <= hi_arr + delta)))

    cov = _cov(d)
    if not (min_coverage <= cov <= max_coverage):
        # Discrete ties can overshoot the band; walk need-order statistics.
        target = min_coverage if cov0 < min_coverage else max_coverage
        ordered = np.sort(need)
        # Smallest d with coverage >= target, then back up if we jumped past max.
        idx = int(np.clip(np.ceil(target * len(ordered)) - 1, 0, len(ordered) - 1))
        d = float(ordered[idx])
        while _cov(d) > max_coverage and idx > 0:
            idx -= 1
            d = float(ordered[idx])
        while _cov(d) < min_coverage and idx < len(ordered) - 1:
            idx += 1
            d = float(ordered[idx])
    if d == 0.0:
        return 0.0, 0.0
    return -d, d


def nudge_bounds_to_coverage_band(
    y: pd.Series | np.ndarray,
    lo: pd.Series | np.ndarray,
    hi: pd.Series | np.ndarray,
    *,
    min_coverage: float = QUANTILE_COVERAGE_MIN,
    max_coverage: float = QUANTILE_COVERAGE_MAX,
    eps: float = 1e-9,
) -> tuple[np.ndarray, np.ndarray]:
    """If a constant shift cannot enter [min, max] due to an atom, nudge the fewest on-bound rows."""
    y_arr = np.asarray(pd.to_numeric(pd.Series(y), errors="coerce"), dtype=float)
    lo_arr = np.asarray(pd.to_numeric(pd.Series(lo), errors="coerce"), dtype=float).copy()
    hi_arr = np.asarray(pd.to_numeric(pd.Series(hi), errors="coerce"), dtype=float).copy()
    ok = np.isfinite(y_arr) & np.isfinite(lo_arr) & np.isfinite(hi_arr)
    if not ok.any():
        return lo_arr, hi_arr

    def _cov() -> float:
        return float(
            np.mean((y_arr[ok] >= lo_arr[ok]) & (y_arr[ok] <= hi_arr[ok]))
        )

    cov = _cov()
    if min_coverage <= cov <= max_coverage:
        return lo_arr, np.maximum(hi_arr, lo_arr)
    n_ok = int(ok.sum())
    if cov > max_coverage:
        max_inside = int(np.floor(max_coverage * n_ok + 1e-12))
        inside = ok & (y_arr >= lo_arr) & (y_arr <= hi_arr)
        need = np.full(y_arr.shape, np.inf)
        need[ok] = np.maximum(lo_arr[ok] - y_arr[ok], y_arr[ok] - hi_arr[ok])
        cand = np.flatnonzero(inside)
        order = cand[np.argsort(np.abs(need[cand]), kind="mergesort")]
        k = int(inside.sum()) - max_inside
        for i in order[: max(k, 0)]:
            if (y_arr[i] - lo_arr[i]) <= (hi_arr[i] - y_arr[i]):
                lo_arr[i] = y_arr[i] + eps
            else:
                hi_arr[i] = y_arr[i] - eps
            if lo_arr[i] > hi_arr[i]:
                lo_arr[i] = y_arr[i] + eps
                hi_arr[i] = y_arr[i] + 2.0 * eps
    return lo_arr, np.maximum(hi_arr, lo_arr)


def evaluate(val: pd.DataFrame) -> dict:
    y = pd.to_numeric(val["total_points"], errors="coerce")
    pred = pd.to_numeric(val["pred_points"], errors="coerce")
    last5 = last5_baseline(val)
    xp = pd.to_numeric(val["xp_scraped"], errors="coerce")
    # Single mask so model / last5 / xp_scraped MAEs are comparable.
    common = common_eval_mask(val)
    n_common = int(common.sum())
    if n_common:
        mae_model = float(mean_absolute_error(y[common], pred[common]))
        mae_last5 = float(mean_absolute_error(y[common], last5[common]))
        mae_xp_scraped = float(mean_absolute_error(y[common], xp[common]))
    else:
        mae_model = mae_last5 = mae_xp_scraped = None
    metrics = {
        "n": int(y.notna().sum()),
        "n_common": n_common,
        "mae_model": mae_model,
        "mae_last5": mae_last5,
        "mae_xp_scraped": mae_xp_scraped,
        "mae_minutes": float(
            mean_absolute_error(
                pd.to_numeric(val["minutes"], errors="coerce").fillna(0),
                pd.to_numeric(val["pred_minutes"], errors="coerce").fillna(0),
            )
        ),
    }
    if "pred_points_decomposed" in val.columns:
        decomp = pd.to_numeric(val["pred_points_decomposed"], errors="coerce")
        mask_d = common & decomp.notna() & np.isfinite(decomp)
        mae_decomposed = (
            float(mean_absolute_error(y[mask_d], decomp[mask_d]))
            if mask_d.any()
            else None
        )
        metrics["mae_decomposed"] = mae_decomposed
        metrics["n_common_decomposed"] = int(mask_d.sum())
        if (
            mae_decomposed is not None
            and mae_decomposed <= DECOMPOSED_MAE_PUBLISH_MAX
        ):
            metrics["published_points"] = "pred_points_decomposed"
        else:
            metrics["published_points"] = "pred_points"
    gw1 = pd.to_numeric(val["GW"], errors="coerce") == 1
    y_gw1 = y[gw1]
    pred_gw1 = pred[gw1]
    ok_gw1 = pred_gw1.notna() & y_gw1.notna()
    metrics["mae_model_gw1"] = (
        float(mean_absolute_error(y_gw1[ok_gw1], pred_gw1[ok_gw1]))
        if ok_gw1.any()
        else None
    )
    mask = holdout_defcon_mask(val, train_gw_max=DEFCON_TRAIN_GW_MAX)
    if mask.any():
        yb = pd.to_numeric(val.loc[mask, "defcon_hit"], errors="coerce")
        pb = pd.to_numeric(val.loc[mask, "pred_defcon"], errors="coerce")
        metrics["defcon_auc"] = (
            float(roc_auc_score(yb, pb)) if yb.nunique() > 1 else None
        )
        metrics["defcon_logloss"] = logloss(yb, pb)
        metrics["defcon_brier"] = brier(yb, pb)
    if {"pred_points_p10", "pred_points_p90"} <= set(val.columns):
        p10 = pd.to_numeric(val["pred_points_p10"], errors="coerce")
        p90 = pd.to_numeric(val["pred_points_p90"], errors="coerce")
        metrics["quantile_coverage_p10_p90"] = interval_coverage(
            y[common], p10[common], p90[common]
        )
        metrics["pinball_p10"] = pinball_loss(y[common], p10[common], QUANTILE_ALPHA_P10)
        metrics["pinball_p90"] = pinball_loss(y[common], p90[common], QUANTILE_ALPHA_P90)
    return metrics


def train(panel_path: Path | None = None) -> dict:
    panel_path = panel_path or (PROCESSED / "panel.parquet")
    df = pd.read_parquet(panel_path)
    feats = feature_columns(df)
    if "xP" in feats or "xp_scraped" in feats:
        raise RuntimeError("Leakage: xP leaked into feature list")

    train_df = df[df["season"].isin(TRAIN_SEASONS)]
    val_df = df[df["season"].eq(VAL_SEASON)].copy()

    X_min, y_min = _xy(train_df, "minutes", feats)
    minutes_model = _fit_regressor(X_min, y_min)

    defcon_src = df[df["season"].eq(DEFCON_SEASON)].copy()
    not_gk = ~defcon_src["position"].astype(str).str.upper().eq("GK")
    played = pd.to_numeric(defcon_src["minutes"], errors="coerce").fillna(0) > 0
    labelled = defcon_src["defcon_hit"].notna() & not_gk & played
    X_dc, y_dc = _defcon_train_xy(df, feats)
    defcon_model = _fit_classifier(X_dc, y_dc)
    # Refit on the full labelled 2025-26 season for the live artefact after scoring the holdout head.
    X_dc_all, y_dc_all = _xy(defcon_src[labelled], "defcon_hit", feats)

    X_pts, y_pts = _xy(train_df, "total_points", feats)
    points_model = _fit_regressor(X_pts, y_pts)
    p10_model = _fit_quantile_regressor(X_pts, y_pts, QUANTILE_ALPHA_P10)
    p90_model = _fit_quantile_regressor(X_pts, y_pts, QUANTILE_ALPHA_P90)

    MODELS.mkdir(parents=True, exist_ok=True)
    PREDS.mkdir(parents=True, exist_ok=True)
    joblib.dump(minutes_model, MODELS / "minutes.joblib")
    joblib.dump(points_model, MODELS / "points.joblib")
    joblib.dump(p10_model, MODELS / "points_p10.joblib")
    joblib.dump(p90_model, MODELS / "points_p90.joblib")
    live_defcon = _fit_classifier(X_dc_all, y_dc_all)
    joblib.dump(live_defcon, MODELS / "defcon.joblib")
    (MODELS / "feature_columns.txt").write_text("\n".join(feats), encoding="utf-8")

    X_val = val_df[feats].apply(pd.to_numeric, errors="coerce")
    val_df["pred_minutes"] = minutes_model.predict(X_val).clip(0, 90)
    val_df["pred_points"] = points_model.predict(X_val)
    val_df["pred_points_decomposed"] = decompose_points(
        val_df["pred_points"], val_df["pred_minutes"]
    )
    val_df["pred_defcon"] = 0.0
    playable = ~val_df["position"].astype(str).str.upper().eq("GK")
    if playable.any():
        val_df.loc[playable, "pred_defcon"] = defcon_model.predict_proba(
            X_val.loc[playable]
        )[:, 1]

    val_df, q_metrics = apply_quantile_models(val_df, feats, p10_model, p90_model)
    val_df, cal_metrics = _apply_defcon_calibrator(X_dc, y_dc, val_df, playable)
    _write_val_preds(val_df)

    metrics = evaluate(val_df)
    metrics.update(cal_metrics)
    metrics.update(q_metrics)
    (MODELS / "val_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    return metrics


VAL_PRED_COLS = [
    "season",
    "GW",
    "fixture",
    "kickoff_time",
    "name",
    "position",
    "team",
    "player_code",
    "minutes",
    "total_points",
    "defcon_hit",
    "xp_scraped",
    "pred_minutes",
    "pred_defcon",
    "pred_points",
    "pred_points_decomposed",
    "total_points_r5",
]
VAL_PRED_KEY = ["season", "GW", "player_code", "fixture"]
VAL_QUANTILE_COLS = ["pred_points_p10", "pred_points_p90"]
QUANTILE_METRIC_KEYS = (
    "quantile_coverage_p10_p90",
    "pinball_p10",
    "pinball_p90",
    "quantile_shift_p10",
    "quantile_shift_p90",
    "quantile_alpha_p10",
    "quantile_alpha_p90",
)


def _write_val_preds(val_df: pd.DataFrame) -> None:
    PREDS.mkdir(parents=True, exist_ok=True)
    missing = [column for column in VAL_PRED_KEY if column not in val_df.columns]
    if missing:
        raise ValueError(f"validation predictions missing fixture key columns: {missing}")
    duplicate = val_df.duplicated(VAL_PRED_KEY, keep=False)
    if duplicate.any():
        sample = val_df.loc[duplicate, VAL_PRED_KEY].head(5).to_dict("records")
        raise ValueError(f"validation predictions contain duplicate fixture keys: {sample}")
    # pred_defcon on GW<=28 is in-sample (DefCon train split); holdout metrics use GW>28 only.
    cols = [c for c in VAL_PRED_COLS if c in val_df.columns]
    for extra in VAL_QUANTILE_COLS:
        if extra in val_df.columns and extra not in cols:
            cols.append(extra)
    val_df[cols].to_csv(PREDS / "val_2025-26.csv", index=False)


def apply_quantile_models(
    val_df: pd.DataFrame,
    feats: list[str],
    p10_model: lgb.LGBMRegressor,
    p90_model: lgb.LGBMRegressor,
) -> tuple[pd.DataFrame, dict]:
    """Score p10/p90 on val features and apply a coverage shift if needed."""
    X_val = val_df[feats].apply(pd.to_numeric, errors="coerce")
    raw10 = np.asarray(p10_model.predict(X_val), dtype=float)
    raw90 = np.asarray(p90_model.predict(X_val), dtype=float)
    mask = common_eval_mask(val_df)
    y = pd.to_numeric(val_df["total_points"], errors="coerce")
    shift10, shift90 = interval_shift_for_coverage(y[mask], raw10[mask], raw90[mask])
    lo = raw10 + shift10
    hi = np.maximum(raw90 + shift90, lo)
    mask_np = np.asarray(mask, dtype=bool)
    if mask_np.any():
        lo_n, hi_n = nudge_bounds_to_coverage_band(y[mask], lo[mask_np], hi[mask_np])
        lo = lo.copy()
        hi = hi.copy()
        lo[mask_np] = lo_n
        hi[mask_np] = hi_n
        hi = np.maximum(hi, lo)
    out = val_df.copy()
    out["pred_points_p10"] = lo
    out["pred_points_p90"] = hi
    return out, {
        "quantile_shift_p10": float(shift10),
        "quantile_shift_p90": float(shift90),
        "quantile_alpha_p10": QUANTILE_ALPHA_P10,
        "quantile_alpha_p90": QUANTILE_ALPHA_P90,
    }


def train_quantile_heads(panel_path: Path | None = None) -> dict:
    """Fit p10/p90 only. Merge quantile keys into existing val_metrics.json.

    Does not refit minutes, mean points, or DefCon heads.
    """
    panel_path = panel_path or (PROCESSED / "panel.parquet")
    df = pd.read_parquet(panel_path)
    feats = feature_columns(df)
    if "xP" in feats or "xp_scraped" in feats:
        raise RuntimeError("Leakage: xP leaked into feature list")

    train_df = df[df["season"].isin(TRAIN_SEASONS)]
    X_pts, y_pts = _xy(train_df, "total_points", feats)
    p10_model = _fit_quantile_regressor(X_pts, y_pts, QUANTILE_ALPHA_P10)
    p90_model = _fit_quantile_regressor(X_pts, y_pts, QUANTILE_ALPHA_P90)

    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(p10_model, MODELS / "points_p10.joblib")
    joblib.dump(p90_model, MODELS / "points_p90.joblib")

    val_path = PREDS / "val_2025-26.csv"
    val_df = pd.read_csv(val_path)
    panel_val = df[df["season"].eq(VAL_SEASON)].copy()
    if len(panel_val) != len(val_df):
        raise RuntimeError(
            f"val CSV rows ({len(val_df)}) != panel val rows ({len(panel_val)})"
        )
    if not (
        panel_val["player_code"].astype(str).to_numpy()
        == val_df["player_code"].astype(str).to_numpy()
    ).all() or not (panel_val["GW"].to_numpy() == val_df["GW"].to_numpy()).all():
        raise RuntimeError("val CSV is not row-aligned with panel val")
    scored = panel_val.copy()
    for col in ("pred_points", "xp_scraped", "total_points_r5", "pred_points_decomposed"):
        if col in val_df.columns:
            scored[col] = val_df[col].to_numpy()
    scored, q_meta = apply_quantile_models(scored, feats, p10_model, p90_model)
    val_df = val_df.copy()
    val_df["pred_points_p10"] = scored["pred_points_p10"].to_numpy()
    val_df["pred_points_p90"] = scored["pred_points_p90"].to_numpy()
    _write_val_preds(val_df)

    q_eval = evaluate(val_df)
    extra = {k: q_eval[k] for k in QUANTILE_METRIC_KEYS if k in q_eval}
    extra.update(q_meta)
    metrics_path = MODELS / "val_metrics.json"
    metrics = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.is_file()
        else {}
    )
    metrics.update(extra)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def _choice_metrics(choice) -> dict:
    published_ll = choice.logloss_after if choice.shipped else choice.logloss_before
    published_br = choice.brier_after if choice.shipped else choice.brier_before
    out = {
        "defcon_logloss_before": choice.logloss_before,
        "defcon_brier_before": choice.brier_before,
        "defcon_logloss_after": choice.logloss_after,
        "defcon_brier_after": choice.brier_after,
        "defcon_calibrator": choice.method,
        "defcon_calibrator_shipped": choice.shipped,
        "defcon_calibrator_n_pos_oof": choice.n_pos_oof,
        "defcon_calibrator_attempts": choice.attempts,
        # Keep published keys aligned with whatever is stored in val pred_defcon.
        "defcon_logloss": published_ll,
        "defcon_brier": published_br,
    }
    if choice.note:
        out["defcon_calibrator_note"] = choice.note
    return out


def _persist_calibrator(choice) -> None:
    path = MODELS / "defcon_calibrator.joblib"
    if choice.shipped:
        MODELS.mkdir(parents=True, exist_ok=True)
        joblib.dump(choice.calibrator, path)
    elif path.exists():
        path.unlink()


def _apply_defcon_calibrator(
    X_dc: pd.DataFrame,
    y_dc: pd.Series,
    val_df: pd.DataFrame,
    playable: pd.Series,
) -> tuple[pd.DataFrame, dict]:
    """Fit calibrator on GW<=28 OOF proba; score/apply on existing holdout-head GW>28 p."""
    p_oof = oof_predict_proba(X_dc, y_dc, _classifier_estimator())
    mask = holdout_defcon_mask(val_df, train_gw_max=DEFCON_TRAIN_GW_MAX)
    if not mask.any():
        raise RuntimeError("DefCon holdout mask is empty; cannot score a calibrator")
    y_hold = pd.to_numeric(val_df.loc[mask, "defcon_hit"], errors="coerce")
    p_hold = pd.to_numeric(val_df.loc[mask, "pred_defcon"], errors="coerce")
    choice = select_calibrator(p_oof, y_dc.to_numpy(), p_hold.to_numpy(), y_hold.to_numpy())
    if choice.shipped:
        val_df = val_df.copy()
        val_df.loc[playable, "pred_defcon"] = apply_calibrator(
            choice.calibrator, val_df.loc[playable, "pred_defcon"]
        )
    _persist_calibrator(choice)
    return val_df, _choice_metrics(choice)


def _defcon_train_xy(df: pd.DataFrame, feats: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    defcon_src = df[df["season"].eq(DEFCON_SEASON)].copy()
    not_gk = ~defcon_src["position"].astype(str).str.upper().eq("GK")
    played = pd.to_numeric(defcon_src["minutes"], errors="coerce").fillna(0) > 0
    labelled = defcon_src["defcon_hit"].notna() & not_gk & played
    dtrain = defcon_src[
        labelled
        & (pd.to_numeric(defcon_src["GW"], errors="coerce") <= DEFCON_TRAIN_GW_MAX)
    ]
    X_dc, y_dc = _xy(dtrain, "defcon_hit", feats)
    if len(X_dc) < 100:
        raise RuntimeError(f"DefCon train set too small: {len(X_dc)} rows")
    return X_dc, y_dc


def availability_scale(df: pd.DataFrame) -> pd.Series:
    chance = pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce")
    unavailable = df["status"].isin(["i", "s", "u", "n"]) & chance.fillna(0).eq(0)
    scale = (chance.fillna(100) / 100.0).clip(0, 1)
    return scale.where(~unavailable, 0.0)


def _rewrite_next_gw_with_calibrator(cal) -> None:
    """Refresh the CURRENT target-GW board with a freshly shipped calibrator.

    Must never touch a past GW's committed predictions (benchmark integrity):
    the target is resolved from the live bootstrap snapshot, and a missing
    snapshot or missing file is a no-op — in CI, train() runs before
    download_live, so committed boards from previous weeks are never rewritten.
    """
    from fplbench.paths import LIVE, LIVE_SEASON
    from fplbench.predict import resolve_next_event

    bootstrap_path = LIVE / "bootstrap.json"
    if not bootstrap_path.is_file():
        return
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    path = PREDS / f"gw{resolve_next_event(bootstrap)}_{LIVE_SEASON}.csv"
    if not path.is_file():
        return
    df = pd.read_csv(path)
    playable = ~df["position"].astype(str).str.upper().eq("GK")
    scale = availability_scale(df)
    df["pred_defcon"] = apply_calibrator_to_scaled_probs(
        df["pred_defcon"], scale, playable, cal
    )
    df["e_points_final"] = (
        pd.to_numeric(df["pred_points_decomposed"], errors="coerce")
        + 2.0 * df["pred_defcon"]
    )
    df.sort_values("e_points_final", ascending=False).to_csv(path, index=False)


def calibrate_existing_artifacts(panel_path: Path | None = None) -> dict:
    """OOF-fit DefCon calibrator on existing val preds. Does not refit minutes/points."""
    panel_path = panel_path or (PROCESSED / "panel.parquet")
    df = pd.read_parquet(panel_path)
    feats = feature_columns(df)
    if "xP" in feats or "xp_scraped" in feats:
        raise RuntimeError("Leakage: xP leaked into feature list")
    X_dc, y_dc = _defcon_train_xy(df, feats)

    val_path = PREDS / "val_2025-26.csv"
    val_df = pd.read_csv(val_path)
    playable = ~val_df["position"].astype(str).str.upper().eq("GK")
    val_df, cal_metrics = _apply_defcon_calibrator(X_dc, y_dc, val_df, playable)
    _write_val_preds(val_df)

    metrics_path = MODELS / "val_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics.update(evaluate(val_df))
    metrics.update(cal_metrics)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if cal_metrics["defcon_calibrator_shipped"]:
        cal = joblib.load(MODELS / "defcon_calibrator.joblib")
        _rewrite_next_gw_with_calibrator(cal)
    return metrics
