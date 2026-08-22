"""Score the live 2026/27 player list for the next gameweek."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from fplbench.calibrate import apply_calibrator
from fplbench.form import player_end_of_season_row
from fplbench.ingest import load_season_players
from fplbench.opponent import attach_live_opponent_xgc
from fplbench.panel import attach_prior_season_setpiece_orders
from fplbench.paths import LIVE, LIVE_SEASON, MODELS, PREDS, PROCESSED, SEASONS
from fplbench.tabfm_head import (
    fit_points_regressor,
    predict_points,
    stratified_context_indices,
)
from fplbench.train import TRAIN_SEASONS, availability_scale, decompose_points

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _tabfm_points(
    panel: pd.DataFrame, feats: list[str], live: pd.DataFrame, feat_cols: list[str]
) -> pd.Series:
    train = panel[panel["season"].isin(TRAIN_SEASONS)].copy()
    X_tr = train[feats].apply(pd.to_numeric, errors="coerce")
    y_tr = pd.to_numeric(train["total_points"], errors="coerce")
    ok = y_tr.notna()
    X_tr, y_tr = X_tr.loc[ok], y_tr.loc[ok]
    ctx = stratified_context_indices(train.loc[ok, "minutes"], y_tr, n=512)
    reg = fit_points_regressor(X_tr.iloc[ctx], y_tr.iloc[ctx])
    preds = predict_points(reg, live[list(feat_cols)])
    chance = pd.to_numeric(live["chance_of_playing_next_round"], errors="coerce")
    unavailable = live["status"].isin(["i", "s", "u", "n"]) & chance.fillna(0).eq(0)
    scale = (chance.fillna(100) / 100.0).clip(0, 1)
    scale = scale.where(~unavailable, 0.0)
    return pd.Series(preds, index=live.index) * scale


def fill_scoring_feature_nans(
    df: pd.DataFrame, feature_cols: list[str]
) -> pd.DataFrame:
    """Fill NaN on prior_* and scoring feature columns with 0 (new players / missing hist)."""
    out = df.copy()
    prior_cols = [c for c in out.columns if c.startswith("prior_")]
    for col in set(prior_cols) | set(feature_cols):
        if col not in out.columns:
            out[col] = 0.0
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def _end_of_season_features(
    panel: pd.DataFrame, season: str, feats: list[str]
) -> pd.DataFrame:
    src = panel[panel["season"].eq(season)].copy()
    if src.empty:
        return pd.DataFrame(columns=["player_code"] + feats)
    rows = [player_end_of_season_row(g) for _, g in src.groupby("player_code")]
    hist = pd.DataFrame(rows)
    for col in feats:
        if col not in hist.columns:
            hist[col] = 0
    return hist


def _next_fixtures(
    elements: pd.DataFrame, fixtures: pd.DataFrame, teams: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for _, fx in fixtures.sort_values(["event", "kickoff_time"]).iterrows():
        if pd.isna(fx.get("event")):
            continue
        if bool(fx.get("finished")):
            continue
        rows.append(
            {
                "team": int(fx["team_h"]),
                "was_home": 1,
                "fdr": fx.get("team_h_difficulty"),
                "opponent": int(fx["team_a"]),
                "event": fx["event"],
                "kickoff_time": fx.get("kickoff_time"),
            }
        )
        rows.append(
            {
                "team": int(fx["team_a"]),
                "was_home": 0,
                "fdr": fx.get("team_a_difficulty"),
                "opponent": int(fx["team_h"]),
                "event": fx["event"],
                "kickoff_time": fx.get("kickoff_time"),
            }
        )
    fx_long = pd.DataFrame(rows)
    if fx_long.empty:
        return fx_long
    # DGW: two unfinished fixtures in the same event is not yet supported.
    counts = fx_long.groupby(["team", "event"]).size()
    multi = counts[counts >= 2]
    if len(multi):
        samples = [
            f"team={t} event={e} n={int(n)}"
            for (t, e), n in multi.head(5).items()
        ]
        raise NotImplementedError(
            "Double gameweek (2+ unfinished fixtures in the same event) is not "
            f"supported yet: {', '.join(samples)}"
        )
    fx_long = fx_long.sort_values("event").drop_duplicates("team", keep="first")
    team_name = teams.set_index("id")["name"].to_dict()
    fx_long["team_name"] = fx_long["team"].map(team_name)
    fx_long["opponent_name"] = fx_long["opponent"].map(team_name)
    return fx_long


def _prepare_live_merged() -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    """Live player list + next-fixture features. Returns (merged, feats, panel)."""
    bootstrap = json.loads((LIVE / "bootstrap.json").read_text(encoding="utf-8"))
    fixtures = pd.read_csv(LIVE / "fixtures.csv")
    teams = pd.DataFrame(bootstrap["teams"])
    elements = pd.DataFrame(bootstrap["elements"])
    feats = (MODELS / "feature_columns.txt").read_text(encoding="utf-8").splitlines()
    panel = pd.read_parquet(PROCESSED / "panel.parquet")
    hist = _end_of_season_features(panel, "2025-26", feats)

    live = elements.copy()
    live["player_code"] = live["code"].astype(str)
    live["position"] = live["element_type"].map(POS)
    live["value"] = live["now_cost"]
    live["gw_in_season"] = 1
    live["name"] = live["web_name"]

    fx = _next_fixtures(live, fixtures, teams)
    live = live.merge(fx, on="team", how="left")

    # Carry last-season lags / priors via player_code. GW1 has no in-season history.
    merged = live.merge(hist, on="player_code", how="left", suffixes=("", "_hist"))
    for col in feats:
        if col not in merged.columns and f"{col}_hist" in merged.columns:
            merged[col] = merged[f"{col}_hist"]
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = pd.to_numeric(merged[col], errors="coerce")

    # New players / missing hist: same 0-fill as panel for prior_* and scoring features.
    merged = fill_scoring_feature_nans(merged, feats)
    # Live season uses the last historical players_raw snapshot (prior-season rule).
    # End-of-season form rows do not carry set-piece orders; overwrite any 0-fill.
    merged = attach_prior_season_setpiece_orders(
        merged, load_season_players(SEASONS[-1])
    )
    # GW1 opponent r5 is the last 5 completed GWs of the prior season.
    merged = attach_live_opponent_xgc(merged, panel, SEASONS[-1])
    merged["is_new_to_fpl"] = (
        pd.to_numeric(merged.get("prior_minutes", 0), errors="coerce")
        .fillna(0)
        .eq(0)
        .astype(int)
    )
    merged["gw_in_season"] = 1
    merged["was_home"] = pd.to_numeric(merged["was_home"], errors="coerce").fillna(0)
    merged["fdr"] = pd.to_numeric(merged["fdr"], errors="coerce")
    merged["value"] = pd.to_numeric(merged["now_cost"], errors="coerce")
    return merged, feats, panel


def _quantile_shifts() -> tuple[float, float]:
    path = MODELS / "val_metrics.json"
    if not path.is_file():
        return 0.0, 0.0
    metrics = json.loads(path.read_text(encoding="utf-8"))
    return (
        float(metrics.get("quantile_shift_p10", 0.0) or 0.0),
        float(metrics.get("quantile_shift_p90", 0.0) or 0.0),
    )


def apply_quantile_heads(
    X: pd.DataFrame,
    lift: pd.Series,
    scale: pd.Series,
    pred_minutes: pd.Series,
    pred_defcon: pd.Series,
) -> dict[str, pd.Series]:
    """Score p10/p90 if joblibs exist. Missing models → empty dict (no crash)."""
    p10_path = MODELS / "points_p10.joblib"
    p90_path = MODELS / "points_p90.joblib"
    if not p10_path.is_file() or not p90_path.is_file():
        return {}
    p10_model = joblib.load(p10_path)
    p90_model = joblib.load(p90_path)
    shift10, shift90 = _quantile_shifts()
    raw10 = pd.Series(p10_model.predict(X), index=X.index, dtype=float) + shift10
    raw90 = pd.Series(p90_model.predict(X), index=X.index, dtype=float) + shift90
    raw90 = pd.Series(np.maximum(raw90.to_numpy(), raw10.to_numpy()), index=X.index)
    factor = (lift * scale).reindex(X.index)
    pred10 = raw10 * factor
    pred90 = raw90 * factor
    e_p90 = decompose_points(pred90, pred_minutes) + 2.0 * pd.to_numeric(
        pred_defcon, errors="coerce"
    ).fillna(0.0)
    return {
        "pred_points_p10": pred10,
        "pred_points_p90": pred90,
        "e_points_p90": e_p90,
    }


def attach_quantiles_to_gw1(path: Path | None = None) -> pd.DataFrame:
    """Add quantile columns to an existing GW CSV without refitting TabFM."""
    dest = path or (PREDS / "gw1_2026-27.csv")
    existing = pd.read_csv(dest)
    merged, feats, _panel = _prepare_live_merged()
    X = merged[feats]
    minutes_model = joblib.load(MODELS / "minutes.joblib")
    raw_minutes = pd.Series(minutes_model.predict(X), index=merged.index).clip(0, 90)
    start_rate = (
        pd.to_numeric(merged.get("prior_starts"), errors="coerce").fillna(0)
        / pd.to_numeric(merged.get("prior_games"), errors="coerce").replace(0, np.nan)
    ).fillna(0)
    last_start = pd.to_numeric(merged.get("starts_l1"), errors="coerce").fillna(0) >= 0.5
    typical = pd.to_numeric(merged.get("prior_minutes_pg"), errors="coerce").fillna(0)
    regular = (
        (merged["status"].eq("a")) & (start_rate >= 0.6) & last_start & (typical >= 60)
    )
    blended = raw_minutes.copy()
    blended.loc[regular] = np.maximum(
        blended.loc[regular], typical.loc[regular].clip(upper=90)
    )
    lift = (blended / raw_minutes.replace(0, np.nan)).fillna(1.0).clip(0.5, 2.0)
    scale = availability_scale(merged)
    by_id = existing.set_index("id")
    minutes = merged["id"].map(by_id["pred_minutes"])
    defcon = merged["id"].map(by_id["pred_defcon"])
    qcols = apply_quantile_heads(X, lift, scale, minutes, defcon)
    if not qcols:
        return existing
    for col, series in qcols.items():
        mapped = pd.Series(series.to_numpy(), index=merged["id"])
        existing[col] = existing["id"].map(mapped)
    existing["e_points_p90"] = decompose_points(
        existing["pred_points_p90"], existing["pred_minutes"]
    ) + 2.0 * pd.to_numeric(existing["pred_defcon"], errors="coerce").fillna(0)
    existing.to_csv(dest, index=False)
    return existing


def predict_next_gw(*, skip_tabfm: bool = False) -> pd.DataFrame:
    merged, feats, panel = _prepare_live_merged()

    minutes_model = joblib.load(MODELS / "minutes.joblib")
    defcon_model = joblib.load(MODELS / "defcon.joblib")
    points_model = joblib.load(MODELS / "points.joblib")
    cal_path = MODELS / "defcon_calibrator.joblib"
    defcon_calibrator = joblib.load(cal_path) if cal_path.is_file() else None
    merged = merged.copy()
    X = merged[feats]
    raw_minutes = pd.Series(minutes_model.predict(X), index=merged.index).clip(0, 90)
    start_rate = (
        pd.to_numeric(merged.get("prior_starts"), errors="coerce").fillna(0)
        / pd.to_numeric(merged.get("prior_games"), errors="coerce").replace(0, np.nan)
    ).fillna(0)
    last_start = (
        pd.to_numeric(merged.get("starts_l1"), errors="coerce").fillna(0) >= 0.5
    )
    typical = pd.to_numeric(merged.get("prior_minutes_pg"), errors="coerce").fillna(0)
    regular = (
        (merged["status"].eq("a")) & (start_rate >= 0.6) & last_start & (typical >= 60)
    )
    blended = raw_minutes.copy()
    blended.loc[regular] = np.maximum(
        blended.loc[regular], typical.loc[regular].clip(upper=90)
    )
    merged["pred_minutes"] = blended

    raw_points = pd.Series(points_model.predict(X), index=merged.index)
    lift = (blended / raw_minutes.replace(0, np.nan)).fillna(1.0).clip(0.5, 2.0)
    merged["pred_points"] = raw_points * lift
    merged["pred_defcon"] = 0.0
    playable = ~merged["position"].eq("GK")
    if playable.any():
        raw_defcon = defcon_model.predict_proba(X.loc[playable])[:, 1]
        if defcon_calibrator is not None:
            raw_defcon = apply_calibrator(defcon_calibrator, raw_defcon)
        merged.loc[playable, "pred_defcon"] = raw_defcon
    scale = availability_scale(merged)
    merged["pred_minutes"] = merged["pred_minutes"] * scale
    merged["pred_points"] = merged["pred_points"] * scale
    merged["pred_defcon"] = merged["pred_defcon"] * scale
    # Minutes head as P(play) ≈ clip(pred_minutes/90, 0, 1); gates raw points.
    merged["pred_points_decomposed"] = decompose_points(
        merged["pred_points"], merged["pred_minutes"]
    )
    merged["ep_next"] = pd.to_numeric(merged["ep_next"], errors="coerce")
    merged["season"] = LIVE_SEASON
    import importlib.util

    if skip_tabfm or importlib.util.find_spec("tabfm") is None:
        # tabfm is a research-only optional dep (non-commercial license) and is
        # not installed in CI; the published board uses the LightGBM path.
        merged["pred_points_tabfm"] = np.nan
    else:
        merged["pred_points_tabfm"] = _tabfm_points(
            panel, feats, merged, X.columns.tolist()
        )
    # Published board: minutes-gated points + expected DefCon (2 * P(hit)).
    # pred_points alone omits the minutes head; DefCon was not in the points train years.
    merged["e_points_final"] = (
        merged["pred_points_decomposed"] + 2.0 * merged["pred_defcon"]
    )
    for col, series in apply_quantile_heads(
        X, lift, scale, merged["pred_minutes"], merged["pred_defcon"]
    ).items():
        merged[col] = series

    out_cols = [
        "id",
        "player_code",
        "web_name",
        "position",
        "team_name",
        "opponent_name",
        "was_home",
        "fdr",
        "now_cost",
        "selected_by_percent",
        "status",
        "chance_of_playing_next_round",
        "news",
        "ep_next",
        "pred_minutes",
        "pred_defcon",
        "pred_points",
        "pred_points_decomposed",
        "pred_points_tabfm",
        "e_points_final",
        "event",
    ]
    for extra in ("pred_points_p10", "pred_points_p90", "e_points_p90"):
        if extra in merged.columns and extra not in out_cols:
            out_cols.insert(out_cols.index("event"), extra)
    out = merged[out_cols].sort_values("e_points_final", ascending=False)
    PREDS.mkdir(parents=True, exist_ok=True)
    path = PREDS / "gw1_2026-27.csv"
    out.to_csv(path, index=False)
    return out
