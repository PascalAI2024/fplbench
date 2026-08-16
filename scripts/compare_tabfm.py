"""Compare Google TabFM (ICL, no training) against LightGBM on the same FPL panel.

TabFM's sklearn wrapper samples a bounded context (default 100 rows).
We report three things:

1. TabFM with a larger context + a small ensemble
2. LightGBM fitted on the *same* sampled context (fair ICL-sized compare)
3. Full-data LightGBM already written to outputs/models/val_metrics.json

Weights are non-commercial. This is a research probe only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.panel import feature_columns
from fplbench.paths import MODELS, PREDS, PROCESSED
from fplbench.tabfm_head import (
    CONTEXT_ROWS,
    N_ESTIMATORS,
    cuda_available,
    fit_points_regressor,
    predict_points,
    stratified_context_indices,
)
from fplbench.train import TRAIN_SEASONS, VAL_SEASON, last5_baseline

CONTEXT_ROWS = 512
VAL_ROWS = 2500
N_ESTIMATORS = 4
SEED = 42


def _xy(df: pd.DataFrame, feats: list[str], target: str) -> tuple[pd.DataFrame, pd.Series]:
    X = df[feats].apply(pd.to_numeric, errors="coerce")
    y = pd.to_numeric(df[target], errors="coerce")
    ok = y.notna()
    return X.loc[ok], y.loc[ok]


def _slice_metrics(y: np.ndarray, pred: np.ndarray, minutes: np.ndarray) -> dict:
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    minutes = np.asarray(minutes, dtype=float)
    ok = np.isfinite(y) & np.isfinite(pred)
    y, pred, minutes = y[ok], pred[ok], minutes[ok]
    out = {"n": int(len(y)), "mae": float(mean_absolute_error(y, pred)) if len(y) else None}
    played = minutes > 0
    if played.any():
        out["mae_played"] = float(mean_absolute_error(y[played], pred[played]))
        out["n_played"] = int(played.sum())
    haulers = y >= 5
    if haulers.any():
        out["mae_haulers"] = float(mean_absolute_error(y[haulers], pred[haulers]))
        out["n_haulers"] = int(haulers.sum())
    return out


def main() -> None:
    panel = pd.read_parquet(PROCESSED / "panel.parquet")
    feats = feature_columns(panel)
    train = panel[panel["season"].isin(TRAIN_SEASONS)]
    val = panel[panel["season"].eq(VAL_SEASON)]
    X_tr, y_tr = _xy(train, feats, "total_points")
    X_va, y_va = _xy(val, feats, "total_points")

    rng = np.random.default_rng(SEED)
    ctx_idx = stratified_context_indices(train.loc[X_tr.index, "minutes"], y_tr, n=min(CONTEXT_ROWS, len(X_tr)))
    val_idx = rng.choice(len(X_va), size=min(VAL_ROWS, len(X_va)), replace=False)
    X_ctx, y_ctx = X_tr.iloc[ctx_idx], y_tr.iloc[ctx_idx]
    X_q, y_q = X_va.iloc[val_idx], y_va.iloc[val_idx]
    minutes_q = pd.to_numeric(val.loc[X_q.index, "minutes"], errors="coerce").fillna(0).to_numpy()
    last5 = last5_baseline(val.loc[X_q.index]).to_numpy()
    xp = pd.to_numeric(val.loc[X_q.index, "xp_scraped"], errors="coerce").to_numpy()

    import lightgbm as lgb

    lgb_ctx = lgb.LGBMRegressor(
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=31,
        random_state=SEED,
        verbosity=-1,
    )
    t0 = time.perf_counter()
    lgb_ctx.fit(X_ctx, y_ctx)
    pred_lgb_ctx = lgb_ctx.predict(X_q)
    lgb_ctx_s = time.perf_counter() - t0

    t2 = time.perf_counter()
    reg = fit_points_regressor(X_ctx, y_ctx)
    pred_tabfm = predict_points(reg, X_q)
    tabfm_s = time.perf_counter() - t2

    y = y_q.to_numpy()
    report = {
        "setup": {
            "context_rows": int(len(X_ctx)),
            "val_rows": int(len(X_q)),
            "n_features": len(feats),
            "n_estimators": N_ESTIMATORS,
            "device": "cuda" if cuda_available() else "cpu",
            "context": "stratified",
            "model": "google/tabfm-1.0.0-pytorch",
            "license": "tabfm-non-commercial-v1.0 (research only)",
        },
        "tabfm": {**_slice_metrics(y, pred_tabfm, minutes_q), "seconds": round(tabfm_s, 2)},
        "lgbm_same_context": {**_slice_metrics(y, pred_lgb_ctx, minutes_q), "seconds": round(lgb_ctx_s, 2)},
        "last5": _slice_metrics(y, last5, minutes_q),
        "xp_scraped": _slice_metrics(y, xp, minutes_q),
        "lgbm_full_data_holdout": json.loads((MODELS / "val_metrics.json").read_text(encoding="utf-8")),
    }
    PREDS.mkdir(parents=True, exist_ok=True)
    out = PREDS / "tabfm_vs_lgbm.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
