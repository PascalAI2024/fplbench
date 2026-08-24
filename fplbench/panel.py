"""Build a leakage-safe player-fixture panel from vaastav dumps."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fplbench.form import player_end_of_season_row
from fplbench.ingest import (
    SETPIECE_ORDER_COLS,
    load_season_fixtures,
    load_season_merged,
    load_season_players,
    load_season_teams,
)
from fplbench.opponent import OPP_XGC_COLS, attach_opponent_xgc
from fplbench.paths import PROCESSED, SEASONS
from fplbench.scoring import defcon_count, defcon_hit

LAG_COLS = [
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "bps",
    "starts",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "ict_index",
    "influence",
    "creativity",
    "threat",
    "clearances_blocks_interceptions",
    "recoveries",
    "tackles",
    "defensive_contribution",
    "yellow_cards",
    "red_cards",
    "selected",
    "defcon_count",
    "defcon_hit",
]
FIXTURE_KEYS = ["season", "GW", "player_code", "fixture"]


def _normalize_merged(df: pd.DataFrame) -> pd.DataFrame:
    if "GW" in df.columns and "round" not in df.columns:
        df["round"] = df["GW"]
    if "round" in df.columns and "GW" not in df.columns:
        df["GW"] = df["round"]
    for col in (
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "ict_index",
        "influence",
        "creativity",
        "threat",
        "xP",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _attach_codes(merged: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    out = merged.merge(
        players[["season", "element", "code", "web_name"]],
        on=["season", "element"],
        how="left",
        validate="many_to_one",
    )
    missing = out["code"].isna()
    if missing.any():
        # Last resort: season-local id so lags still work inside a season.
        out.loc[missing, "code"] = (
            out.loc[missing, "season"].astype(str)
            + ":"
            + out.loc[missing, "element"].astype(str)
        )
    out["player_code"] = out["code"].astype(str)
    return out


def _attach_fdr(df: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    fx = fixtures.rename(columns={"id": "fixture"})
    keep = [
        c
        for c in (
            "season",
            "fixture",
            "team_h_difficulty",
            "team_a_difficulty",
            "team_h",
            "team_a",
        )
        if c in fx.columns
    ]
    out = df.merge(
        fx[keep],
        on=["season", "fixture"],
        how="left",
        validate="many_to_one",
    )
    if {"team_h_difficulty", "team_a_difficulty", "was_home"}.issubset(out.columns):
        out["fdr"] = out["team_a_difficulty"].where(
            out["was_home"], out["team_h_difficulty"]
        )
    else:
        out["fdr"] = pd.NA
    return out


def join_setpiece_orders(df: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """Join same-season players_raw set-piece order snapshots onto GW rows.

    Values are end-of-season snapshots. Call
    ``shift_setpiece_orders_to_prior_season`` before training or scoring.
    """
    out = df.copy()
    src = players.copy()
    cols = [c for c in SETPIECE_ORDER_COLS if c in src.columns]
    if not cols:
        for c in SETPIECE_ORDER_COLS:
            if c not in out.columns:
                out[c] = np.nan
        return out
    if "player_code" not in src.columns and "code" in src.columns:
        src["player_code"] = src["code"].astype(str)
    if {"season", "element"}.issubset(src.columns) and {
        "season",
        "element",
    }.issubset(out.columns):
        keys = ["season", "element"]
    elif {"season", "player_code"}.issubset(src.columns) and {
        "season",
        "player_code",
    }.issubset(out.columns):
        keys = ["season", "player_code"]
    else:
        raise ValueError(
            "join_setpiece_orders needs season+element or season+player_code"
        )
    extra = src[keys + cols].drop_duplicates(subset=keys)
    for c in cols:
        extra[c] = pd.to_numeric(extra[c], errors="coerce")
    drop_cols = [c for c in SETPIECE_ORDER_COLS if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    out = out.merge(extra, on=keys, how="left")
    for c in SETPIECE_ORDER_COLS:
        if c not in out.columns:
            out[c] = np.nan
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def shift_setpiece_orders_to_prior_season(df: pd.DataFrame) -> pd.DataFrame:
    """Replace snapshot orders with the prior season's values by player_code.

    First season in the frame, new players, and nulls become 0. Historical
    players_raw is an end-of-season dump, so same-season orders leak.
    """
    if "player_code" not in df.columns:
        raise ValueError("shift_setpiece_orders_to_prior_season requires player_code")
    out = df.copy()
    for c in SETPIECE_ORDER_COLS:
        if c not in out.columns:
            out[c] = np.nan
        out[c] = pd.to_numeric(out[c], errors="coerce")
    seasons = sorted(out["season"].astype(str).unique())
    prev_of = {seasons[i]: seasons[i - 1] for i in range(1, len(seasons))}
    snap = (
        out.assign(_s=out["season"].astype(str), _p=out["player_code"].astype(str))
        .groupby(["_s", "_p"], as_index=False)[list(SETPIECE_ORDER_COLS)]
        .first()
        .set_index(["_s", "_p"])
    )
    keys = pd.MultiIndex.from_arrays(
        [
            out["season"].astype(str).map(prev_of),
            out["player_code"].astype(str),
        ]
    )
    mapped = snap.reindex(keys)
    mapped.index = out.index
    for c in SETPIECE_ORDER_COLS:
        out[c] = pd.to_numeric(mapped[c], errors="coerce").fillna(0)
    return out


def attach_prior_season_setpiece_orders(
    df: pd.DataFrame, prior_players: pd.DataFrame
) -> pd.DataFrame:
    """Map a prior-season players_raw snapshot onto df by player_code. Missing → 0."""
    out = df.copy()
    src = prior_players.copy()
    if "player_code" not in src.columns:
        if "code" not in src.columns:
            for c in SETPIECE_ORDER_COLS:
                out[c] = 0.0
            return out
        src["player_code"] = src["code"].astype(str)
    src["player_code"] = src["player_code"].astype(str)
    src = src.drop_duplicates(subset=["player_code"])
    if "player_code" not in out.columns:
        raise ValueError("attach_prior_season_setpiece_orders requires player_code")
    out["player_code"] = out["player_code"].astype(str)
    lookup = src.set_index("player_code")
    for c in SETPIECE_ORDER_COLS:
        if c in lookup.columns:
            out[c] = pd.to_numeric(
                out["player_code"].map(lookup[c]), errors="coerce"
            ).fillna(0)
        else:
            out[c] = 0.0
    return out


def _prior_season_lookup(df: pd.DataFrame) -> pd.DataFrame:
    played = df[df["minutes"].fillna(0) > 0].copy()
    agg = played.groupby(["season", "player_code"], as_index=False).agg(
        prior_games=("minutes", "size"),
        prior_minutes=("minutes", "sum"),
        prior_points=("total_points", "sum"),
        prior_xg=("expected_goals", "sum"),
        prior_xa=("expected_assists", "sum"),
        prior_defcon_hits=("defcon_hit", "sum"),
        prior_starts=("starts", "sum"),
    )
    agg["prior_ppg"] = agg["prior_points"] / agg["prior_games"]
    agg["prior_minutes_pg"] = agg["prior_minutes"] / agg["prior_games"]
    agg["prior_xg90"] = agg["prior_xg"] / agg["prior_minutes"].clip(lower=1) * 90
    agg["prior_defcon_rate"] = agg["prior_defcon_hits"] / agg["prior_games"]
    seasons = sorted(df["season"].unique())
    nxt = {s: seasons[i + 1] for i, s in enumerate(seasons) if i + 1 < len(seasons)}
    agg["next_season"] = agg["season"].map(nxt)
    return (
        agg.dropna(subset=["next_season"])
        .drop(columns=["season"])
        .rename(columns={"next_season": "season"})
    )


def deduplicate_fixture_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove exact source duplicates and reject conflicting fixture rows."""
    if not set(FIXTURE_KEYS).issubset(df.columns):
        return df.copy()
    duplicate_mask = df.duplicated(FIXTURE_KEYS, keep=False)
    if not duplicate_mask.any():
        return df.copy()

    conflicts = []
    for key, group in df.loc[duplicate_mask].groupby(
        FIXTURE_KEYS, sort=False, dropna=False
    ):
        if len(group.drop_duplicates()) > 1:
            conflicts.append(key)
    if conflicts:
        preview = conflicts[:3]
        raise ValueError(
            "conflicting duplicate player-fixture rows for "
            f"{preview}{' ...' if len(conflicts) > len(preview) else ''}"
        )
    return df.drop_duplicates(FIXTURE_KEYS, keep="first").copy()


def add_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Add prior-appearance form without leaking between same-GW fixtures.

    Historical DGWs contain one row per player-fixture. Candidates retain the
    existing appearance-window semantics, but each gameweek receives the
    candidate available before its first fixture. That safe value is then
    broadcast to every fixture row in the same gameweek.
    """
    out = deduplicate_fixture_rows(df)
    sort_cols = ["season", "player_code", "GW"]
    if "kickoff_time" in out.columns:
        sort_cols.append("kickoff_time")
    if "fixture" in out.columns:
        sort_cols.append("fixture")
    out = out.sort_values(sort_cols, kind="mergesort").copy()
    present = [col for col in LAG_COLS if col in out.columns]
    event_keys = ["season", "player_code", "GW"]
    player_groups = [out["season"], out["player_code"]]
    event_groups = [out[key] for key in event_keys]
    first_fixture = ~out.duplicated(event_keys, keep="first")
    for col in present:
        series = pd.to_numeric(out[col], errors="coerce")
        candidates = {
            f"{col}_l1": series.groupby(player_groups).shift(1),
            f"{col}_r3": series.groupby(player_groups).transform(
                lambda values: values.shift(1).rolling(3, min_periods=1).mean()
            ),
            f"{col}_r5": series.groupby(player_groups).transform(
                lambda values: values.shift(1).rolling(5, min_periods=1).mean()
            ),
        }
        for target, candidate in candidates.items():
            safe_first = candidate.where(first_fixture)
            out[target] = safe_first.groupby(event_groups).transform("first")
    out["gw_in_season"] = out["GW"]
    return out


def apply_prior_season_gw1_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Overwrite GW1 lag features with prior-season end-of-season form (matches live predict)."""
    df = df.copy()
    seasons = sorted(df["season"].astype(str).unique())
    prev_of = {seasons[i]: seasons[i - 1] for i in range(1, len(seasons))}
    if not prev_of:
        return df

    for season, prev_season in prev_of.items():
        prev_src = df[df["season"].astype(str).eq(prev_season)]
        if prev_src.empty:
            continue
        rows = [
            player_end_of_season_row(g)
            for _, g in prev_src.groupby("player_code", sort=False)
        ]
        hist = pd.DataFrame(rows)
        if hist.empty or "player_code" not in hist.columns:
            continue
        lag_cols = [c for c in hist.columns if c.endswith(("_l1", "_r3", "_r5"))]
        if not lag_cols:
            continue
        hist_idx = hist.set_index("player_code")
        for col in lag_cols:
            hist_idx[col] = pd.to_numeric(hist_idx[col], errors="coerce")
        gw1_mask = df["season"].astype(str).eq(season) & (
            pd.to_numeric(df["GW"], errors="coerce") == 1
        )
        if not gw1_mask.any():
            continue
        codes = df.loc[gw1_mask, "player_code"].astype(str)
        for col in lag_cols:
            if col not in df.columns:
                df[col] = np.nan
            df[col] = pd.to_numeric(df[col], errors="coerce")
            mapped = pd.to_numeric(codes.map(hist_idx[col]), errors="coerce")
            present = mapped.notna()
            if not present.any():
                continue
            idx = mapped.index[present]
            # Assign via array to avoid pandas dtype upcast guards on partial NaN columns.
            col_vals = df[col].to_numpy(dtype="float64", copy=True, na_value=np.nan)
            pos = df.index.get_indexer(idx)
            col_vals[pos] = mapped.loc[present].to_numpy(
                dtype="float64", na_value=np.nan
            )
            df[col] = col_vals
    return df


def build_panel(seasons: tuple[str, ...] = SEASONS) -> pd.DataFrame:
    frames = []
    player_frames = []
    fixture_frames = []
    team_frames = []
    for season in seasons:
        merged = _normalize_merged(load_season_merged(season))
        players = load_season_players(season)
        fixtures = load_season_fixtures(season)
        frames.append(_attach_codes(merged, players))
        player_frames.append(players)
        fixture_frames.append(fixtures)
        team_frames.append(load_season_teams(season))
    df = pd.concat(frames, ignore_index=True)
    df = deduplicate_fixture_rows(df)
    fixtures = pd.concat(fixture_frames, ignore_index=True)
    teams = pd.concat(team_frames, ignore_index=True)
    df = _attach_fdr(df, fixtures)

    if "clearances_blocks_interceptions" not in df.columns:
        df["clearances_blocks_interceptions"] = pd.NA
    if "recoveries" not in df.columns:
        df["recoveries"] = pd.NA

    df["defcon_count"] = defcon_count(
        df["position"], df["clearances_blocks_interceptions"], df["recoveries"]
    )
    df["defcon_hit"] = defcon_hit(
        df["position"], df["clearances_blocks_interceptions"], df["recoveries"]
    )
    df["played"] = (pd.to_numeric(df["minutes"], errors="coerce").fillna(0) > 0).astype(
        int
    )
    df["started"] = (
        pd.to_numeric(df.get("starts", 0), errors="coerce").fillna(0).clip(0, 1)
    )
    df["xp_scraped"] = (
        pd.to_numeric(df["xP"], errors="coerce") if "xP" in df.columns else pd.NA
    )
    df["xp_scraped_leak_risk"] = True

    prior = _prior_season_lookup(df)
    df = df.merge(prior, on=["season", "player_code"], how="left")
    df["is_new_to_fpl"] = df["prior_minutes"].isna().astype(int)
    for col in (
        "prior_games",
        "prior_minutes",
        "prior_points",
        "prior_xg",
        "prior_xa",
        "prior_defcon_hits",
        "prior_starts",
        "prior_ppg",
        "prior_minutes_pg",
        "prior_xg90",
        "prior_defcon_rate",
    ):
        if col in df.columns:
            df[col] = df[col].fillna(0)

    players_all = pd.concat(player_frames, ignore_index=True)
    df = join_setpiece_orders(df, players_all)
    df = shift_setpiece_orders_to_prior_season(df)

    df = add_lags(df)
    df = apply_prior_season_gw1_lags(df)
    df["was_home"] = (
        df["was_home"].astype(int) if df["was_home"].dtype != int else df["was_home"]
    )
    df = attach_opponent_xgc(df, teams=teams)
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    banned = {
        "total_points",
        "minutes",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "bonus",
        "bps",
        "starts",
        "expected_goals",
        "expected_assists",
        "expected_goal_involvements",
        "expected_goals_conceded",
        "ict_index",
        "influence",
        "creativity",
        "threat",
        "clearances_blocks_interceptions",
        "recoveries",
        "tackles",
        "defensive_contribution",
        "yellow_cards",
        "red_cards",
        "own_goals",
        "penalties_saved",
        "penalties_missed",
        "team_h_score",
        "team_a_score",
        "xP",
        "xp_scraped",
        "defcon_count",
        "defcon_hit",
        "played",
        "started",
        "transfers_balance",
        "transfers_in",
        "transfers_out",
        "selected",
        "modified",
    }
    numeric_ok = []
    prefixes = ("_l1", "_r3", "_r5")
    static = {
        "was_home",
        "fdr",
        "value",
        "gw_in_season",
        "is_new_to_fpl",
        "prior_games",
        "prior_minutes",
        "prior_points",
        "prior_xg",
        "prior_xa",
        "prior_defcon_hits",
        "prior_starts",
        "prior_ppg",
        "prior_minutes_pg",
        "prior_xg90",
        "prior_defcon_rate",
        "penalties_order",
        "corners_and_indirect_freekicks_order",
        "direct_freekicks_order",
        *OPP_XGC_COLS,
    }
    for col in df.columns:
        if col in banned:
            continue
        if col in static or col.endswith(prefixes):
            if pd.api.types.is_numeric_dtype(df[col]):
                numeric_ok.append(col)
    return sorted(set(numeric_ok))


def save_panel(df: pd.DataFrame) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROCESSED / "panel.parquet", index=False)
    feat = feature_columns(df)
    (PROCESSED / "feature_columns.txt").write_text("\n".join(feat), encoding="utf-8")
