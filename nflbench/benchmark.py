"""Point-in-time NFL player-week freezing, baselines, and scoring."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


POSITIONS = ("QB", "RB", "WR", "TE")
FORECAST_COLUMNS = (
    "season",
    "week",
    "player_id",
    "player_name",
    "position",
    "team",
    "opponent",
    "observed_at",
    "cutoff_at",
    "source_revision",
    "forecast_ewma4",
    "forecast_position_median",
    "history_games",
)


def _utc_timestamp(value: Any, *, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.tz_convert("UTC")


def _utc_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"missing required timestamp column: {column}")
    parsed = pd.to_datetime(frame[column], utc=True, errors="coerce")
    if parsed.isna().any():
        bad = list(frame.index[parsed.isna()][:5])
        raise ValueError(f"invalid or null {column} values at rows {bad}")
    return parsed


def validate_observed_before_cutoff(
    frame: pd.DataFrame,
    cutoff_at: Any,
    *,
    observed_column: str = "observed_at",
) -> pd.Series:
    """Fail closed if any supplied record was not knowable at the cutoff."""
    cutoff = _utc_timestamp(cutoff_at, label="cutoff_at")
    observed = _utc_series(frame, observed_column)
    late = observed > cutoff
    if late.any():
        preview_cols = [
            column
            for column in ("player_id", "season", "week", observed_column)
            if column in frame.columns
        ]
        preview = frame.loc[late, preview_cols].head(5).to_dict("records")
        raise ValueError(f"post-cutoff records are forbidden: {preview}")
    return observed


def freeze_player_week(candidates: pd.DataFrame, cutoff_at: Any) -> pd.DataFrame:
    """Freeze exactly one eligible row per player for one season/week."""
    required = {
        "season",
        "week",
        "player_id",
        "player_name",
        "position",
        "team",
        "opponent",
        "observed_at",
        "source_revision",
    }
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"missing candidate columns: {missing}")
    if candidates.empty:
        raise ValueError("candidate snapshot is empty")
    if candidates["season"].nunique(dropna=False) != 1 or candidates["week"].nunique(
        dropna=False
    ) != 1:
        raise ValueError("candidate snapshot must contain exactly one season and week")
    invalid_positions = sorted(set(candidates["position"].astype(str)) - set(POSITIONS))
    if invalid_positions:
        raise ValueError(f"unsupported fantasy positions: {invalid_positions}")
    if candidates["player_id"].astype(str).duplicated().any():
        dupes = sorted(
            candidates.loc[
                candidates["player_id"].astype(str).duplicated(keep=False), "player_id"
            ]
            .astype(str)
            .unique()
        )
        raise ValueError(f"duplicate frozen player IDs: {dupes[:5]}")

    observed = validate_observed_before_cutoff(candidates, cutoff_at)
    cutoff = _utc_timestamp(cutoff_at, label="cutoff_at")
    out = candidates.copy()
    out["player_id"] = out["player_id"].astype(str)
    out["week"] = pd.to_numeric(out["week"], errors="raise").astype(int)
    out["observed_at"] = observed.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["cutoff_at"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out.sort_values(["position", "player_id"], kind="mergesort").reset_index(
        drop=True
    )


def _ewma_last(values: pd.Series, *, span: int = 4) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna().tail(4)
    if clean.empty:
        return float("nan")
    return float(clean.ewm(span=span, adjust=False).mean().iloc[-1])


def build_baseline_forecasts(
    history: pd.DataFrame,
    frozen: pd.DataFrame,
) -> pd.DataFrame:
    """Build prior-four-week EWMA and prior-history position-median baselines."""
    required = {
        "season",
        "week",
        "player_id",
        "position",
        "fantasy_points",
        "observed_at",
        "source_revision",
    }
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError(f"missing history columns: {missing}")
    if frozen.empty:
        raise ValueError("frozen snapshot is empty")

    season = str(frozen["season"].iloc[0])
    week = int(frozen["week"].iloc[0])
    cutoff = frozen["cutoff_at"].iloc[0]
    if history["season"].astype(str).nunique(dropna=False) != 1:
        raise ValueError("feasibility baseline accepts one season of history")
    if str(history["season"].iloc[0]) != season:
        raise ValueError("history season does not match frozen season")
    weeks = pd.to_numeric(history["week"], errors="coerce")
    if weeks.isna().any() or (weeks >= week).any():
        leaked = history.loc[weeks >= week, ["player_id", "week"]].head(5)
        raise ValueError(
            "same-week or future outcomes are forbidden in baseline history: "
            f"{leaked.to_dict('records')}"
        )
    validate_observed_before_cutoff(history, cutoff)

    hist = history.copy()
    hist["player_id"] = hist["player_id"].astype(str)
    hist["fantasy_points"] = pd.to_numeric(hist["fantasy_points"], errors="coerce")
    if hist["fantasy_points"].isna().any():
        raise ValueError("history fantasy_points must be finite")
    if not np.isfinite(hist["fantasy_points"]).all():
        raise ValueError("history fantasy_points must be finite")

    position_medians = hist.groupby("position")["fantasy_points"].median()
    player_ewma = (
        hist.sort_values(["player_id", "week"], kind="mergesort")
        .groupby("player_id", sort=False)["fantasy_points"]
        .apply(_ewma_last)
    )
    history_games = hist.groupby("player_id").size()

    out = frozen.copy()
    out["forecast_position_median"] = pd.to_numeric(
        out["position"].map(position_medians), errors="coerce"
    ).fillna(0.0)
    out["forecast_ewma4"] = pd.to_numeric(
        out["player_id"].map(player_ewma), errors="coerce"
    )
    out["forecast_ewma4"] = out["forecast_ewma4"].fillna(
        out["forecast_position_median"]
    )
    out["history_games"] = (
        pd.to_numeric(out["player_id"].map(history_games), errors="coerce")
        .fillna(0)
        .astype(int)
    )
    for column in ("forecast_ewma4", "forecast_position_median"):
        out[column] = out[column].round(6)
    return out[list(FORECAST_COLUMNS)].sort_values(
        ["position", "player_id"], kind="mergesort"
    ).reset_index(drop=True)


def score_forecasts(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> dict[str, Any]:
    """Score every frozen player, including explicit DNP=0 rows."""
    required_actual = {"season", "week", "player_id", "fantasy_points", "played"}
    missing = sorted(required_actual - set(actuals.columns))
    if missing:
        raise ValueError(f"missing actual columns: {missing}")
    if actuals["player_id"].astype(str).duplicated().any():
        raise ValueError("actuals contain duplicate player IDs")

    left = forecasts.copy()
    right = actuals.copy()
    left["player_id"] = left["player_id"].astype(str)
    right["player_id"] = right["player_id"].astype(str)
    joined = left.merge(
        right[["season", "week", "player_id", "fantasy_points", "played"]],
        on=["season", "week", "player_id"],
        how="left",
        validate="one_to_one",
    )
    if joined["fantasy_points"].isna().any():
        missing_players = joined.loc[joined["fantasy_points"].isna(), "player_id"].tolist()
        raise ValueError(f"actuals missing frozen players: {missing_players[:5]}")
    actual = pd.to_numeric(joined["fantasy_points"], errors="coerce")
    played = pd.to_numeric(joined["played"], errors="coerce")
    if actual.isna().any() or played.isna().any():
        raise ValueError("actual fantasy_points and played must be numeric")
    invalid_dnp = played.eq(0) & actual.ne(0)
    if invalid_dnp.any():
        players = joined.loc[invalid_dnp, "player_id"].tolist()
        raise ValueError(f"DNP players must score zero: {players[:5]}")

    metrics: dict[str, Any] = {
        "season": str(joined["season"].iloc[0]),
        "week": int(joined["week"].iloc[0]),
        "n_frozen": int(len(joined)),
        "n_played": int(played.gt(0).sum()),
        "n_dnp": int(played.eq(0).sum()),
    }
    for forecast_column, label in (
        ("forecast_ewma4", "ewma4"),
        ("forecast_position_median", "position_median"),
    ):
        predicted = pd.to_numeric(joined[forecast_column], errors="coerce")
        if predicted.isna().any() or not np.isfinite(predicted).all():
            raise ValueError(f"{forecast_column} must be finite")
        error = predicted - actual
        metrics[f"mae_{label}"] = round(float(error.abs().mean()), 6)
        metrics[f"rmse_{label}"] = round(float(np.sqrt((error**2).mean())), 6)
        metrics[f"median_ae_{label}"] = round(float(error.abs().median()), 6)
    metrics["dnp_policy"] = "frozen players remain in denominator; DNP actual=0"
    return metrics


def canonical_csv_bytes(frame: pd.DataFrame, columns: tuple[str, ...]) -> bytes:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"missing canonical columns: {missing}")
    ordered = frame[list(columns)].sort_values(
        ["season", "week", "position", "player_id"], kind="mergesort"
    )
    buffer = io.StringIO(newline="")
    ordered.to_csv(buffer, index=False, lineterminator="\n", float_format="%.6f")
    return buffer.getvalue().encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

