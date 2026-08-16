"""Google TabFM as a research points head. Non-commercial weights."""

from __future__ import annotations

import numpy as np
import pandas as pd

CONTEXT_ROWS = 512
N_ESTIMATORS = 4
SEED = 42


def stratified_context_indices(minutes: pd.Series, points: pd.Series, n: int, seed: int = SEED) -> np.ndarray:
    """Keep zeros from drowning ICL context. Mix blanks, ordinary minutes, haulers."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(minutes))
    mins = pd.to_numeric(minutes, errors="coerce").fillna(0).to_numpy()
    pts = pd.to_numeric(points, errors="coerce").fillna(0).to_numpy()
    haulers = idx[(mins > 0) & (pts >= 5)]
    played = idx[(mins > 0) & (pts < 5)]
    blanks = idx[mins == 0]
    n_h = min(len(haulers), max(64, n // 5))
    n_p = min(len(played), max(n // 2, n - n_h - n // 5))
    n_b = min(len(blanks), n - n_h - n_p)
    pick = []
    if len(haulers):
        pick.append(rng.choice(haulers, size=n_h, replace=len(haulers) < n_h))
    if len(played):
        pick.append(rng.choice(played, size=n_p, replace=len(played) < n_p))
    if n_b and len(blanks):
        pick.append(rng.choice(blanks, size=n_b, replace=len(blanks) < n_b))
    chosen = np.concatenate(pick) if pick else rng.choice(idx, size=min(n, len(idx)), replace=False)
    if len(chosen) > n:
        chosen = rng.choice(chosen, size=n, replace=False)
    return np.unique(chosen)


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def fit_points_regressor(X: pd.DataFrame, y: pd.Series):
    from tabfm import TabFMRegressor
    from tabfm import tabfm_v1_0_0_pytorch as tabfm_v1_0_0

    device = "cuda" if cuda_available() else "cpu"
    model = tabfm_v1_0_0.load(model_type="regression", device=device)
    reg = TabFMRegressor(
        model=model,
        n_estimators=N_ESTIMATORS,
        max_num_rows=CONTEXT_ROWS,
        max_num_features=500,
        batch_size=16,
        random_state=SEED,
        verbose=False,
    )
    reg.fit(X.fillna(0), pd.to_numeric(y, errors="coerce").to_numpy())
    return reg


def predict_points(reg, X: pd.DataFrame) -> np.ndarray:
    return np.asarray(reg.predict(X.fillna(0)), dtype=float)
