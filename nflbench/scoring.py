"""Fixed, auditable PPR scoring for NFLBench."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


PPR_WEIGHTS: Mapping[str, float] = {
    "passing_yards": 1 / 25,
    "passing_tds": 4,
    "interceptions": -2,
    "rushing_yards": 1 / 10,
    "rushing_tds": 6,
    "receptions": 1,
    "receiving_yards": 1 / 10,
    "receiving_tds": 6,
    "fumbles_lost": -2,
}


def ppr_points(frame: pd.DataFrame) -> pd.Series:
    """Compute NFLBench PPR points without silently accepting missing stats."""
    missing = [column for column in PPR_WEIGHTS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing PPR stat columns: {missing}")

    total = pd.Series(0.0, index=frame.index, dtype="float64")
    for column, weight in PPR_WEIGHTS.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any():
            bad = list(frame.index[values.isna()][:5])
            raise ValueError(f"non-numeric or null {column} values at rows {bad}")
        total = total + values.astype(float) * weight
    return total.round(6)

