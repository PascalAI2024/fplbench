"""Leak-safe opponent rolling xGC (shifted r5 + home/away split).

Team-GW xGC is the minutes-weighted mean of ``expected_goals_conceded``
on that team's GK/GKP rows (all players if no keeper minutes). Rolling
windows are shifted so GW t only sees completed GWs < t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OPP_XGC_COLS = ("opp_xgc_r5", "opp_xgc_r5_home", "opp_xgc_r5_away")
OPP_XGC_WINDOW = 5
_GK_POS = frozenset({"GK", "GKP"})


def _minutes_weighted_mean(minutes: pd.Series, values: pd.Series) -> float:
    w = pd.to_numeric(minutes, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    v = pd.to_numeric(values, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    w = np.clip(w, 0.0, None)
    if w.sum() <= 0:
        return 0.0
    return float(np.average(v, weights=w))


def resolve_opponent_team_name(
    df: pd.DataFrame, teams: pd.DataFrame | None = None
) -> pd.Series:
    """Opponent club name for each player row.

    Prefers ``opponent_team`` (merged_gw id → teams.name, or a name string).
    Falls back to the other side of the same fixture.
    """
    if "opponent_team_name" in df.columns and df["opponent_team_name"].notna().any():
        return df["opponent_team_name"]

    if "opponent_team" in df.columns:
        opp = df["opponent_team"]
        as_num = pd.to_numeric(opp, errors="coerce")
        looks_numeric = bool(len(as_num) and as_num.notna().mean() > 0.9)
        if looks_numeric and teams is not None and {"season", "id", "name"}.issubset(
            teams.columns
        ):
            lookup_src = teams.drop_duplicates(subset=["season", "id"]).copy()
            lookup_src["_id"] = pd.to_numeric(lookup_src["id"], errors="coerce")
            lookup_src["_season"] = lookup_src["season"].astype(str)
            lookup = lookup_src.dropna(subset=["_id"]).set_index(["_season", "_id"])[
                "name"
            ]
            keys = pd.MultiIndex.from_arrays(
                [df["season"].astype(str), as_num], names=["_season", "_id"]
            )
            mapped = lookup.reindex(keys)
            mapped.index = df.index
            if mapped.notna().any():
                return mapped
        if not looks_numeric:
            return opp.astype(str)

    if {"season", "fixture", "team", "was_home"}.issubset(df.columns):
        derived = _opponent_from_fixture_sides(df)
        if derived.notna().any():
            return derived

    if "opponent_team" in df.columns:
        return df["opponent_team"].astype(str)
    return pd.Series(pd.NA, index=df.index)


def _opponent_from_fixture_sides(df: pd.DataFrame) -> pd.Series:
    was_home = pd.to_numeric(df["was_home"], errors="coerce").fillna(0).astype(int)
    home = (
        df.loc[was_home.eq(1), ["season", "fixture", "team"]]
        .dropna(subset=["fixture"])
        .drop_duplicates(subset=["season", "fixture"])
        .rename(columns={"team": "_home_team"})
    )
    away = (
        df.loc[was_home.eq(0), ["season", "fixture", "team"]]
        .dropna(subset=["fixture"])
        .drop_duplicates(subset=["season", "fixture"])
        .rename(columns={"team": "_away_team"})
    )
    if home.empty and away.empty:
        return pd.Series(pd.NA, index=df.index)
    sides = home.merge(away, on=["season", "fixture"], how="outer")
    tmp = df[["season", "fixture"]].merge(sides, on=["season", "fixture"], how="left")
    tmp.index = df.index
    return tmp["_away_team"].where(was_home.eq(1), tmp["_home_team"])


def team_gw_xgc(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, team, GW): minutes-weighted team xGC."""
    work = df.copy()
    if "expected_goals_conceded" not in work.columns:
        work["expected_goals_conceded"] = 0.0
    work["minutes"] = pd.to_numeric(work["minutes"], errors="coerce").fillna(0.0)
    work["expected_goals_conceded"] = pd.to_numeric(
        work["expected_goals_conceded"], errors="coerce"
    ).fillna(0.0)
    work["GW"] = pd.to_numeric(work["GW"], errors="coerce")
    work["was_home"] = (
        pd.to_numeric(work["was_home"], errors="coerce").fillna(0).astype(int)
    )
    if "position" in work.columns:
        work["_pos"] = work["position"].astype(str).str.upper()
    else:
        work["_pos"] = ""
    work["_w"] = work["minutes"].clip(lower=0.0)
    work["_wx"] = work["_w"] * work["expected_goals_conceded"]
    keys = ["season", "team", "GW"]
    gk = work.loc[work["_pos"].isin(_GK_POS)]
    gk_agg = gk.groupby(keys, as_index=False).agg(w=("_w", "sum"), wx=("_wx", "sum"))
    all_agg = work.groupby(keys, as_index=False).agg(w=("_w", "sum"), wx=("_wx", "sum"))
    home_agg = work.groupby(keys, as_index=False)["was_home"].mean()
    home_agg["was_home"] = (home_agg["was_home"] >= 0.5).astype(int)
    out = all_agg.merge(gk_agg, on=keys, how="left", suffixes=("_all", "_gk"))
    out = out.merge(home_agg, on=keys, how="left")
    use_gk = out["w_gk"].fillna(0.0) > 0.0
    w = out["w_gk"].where(use_gk, out["w_all"])
    wx = out["wx_gk"].where(use_gk, out["wx_all"])
    out["xgc"] = np.where(pd.to_numeric(w, errors="coerce").fillna(0.0) > 0.0, wx / w, 0.0)
    out["was_home"] = out["was_home"].fillna(0).astype(int)
    return out[["season", "team", "GW", "was_home", "xgc"]]


def add_shifted_team_rolls(
    team_gw: pd.DataFrame, window: int = OPP_XGC_WINDOW
) -> pd.DataFrame:
    """Add leak-safe r5 / home-r5 / away-r5. GW t does not see GW t xGC."""
    if team_gw.empty:
        out = team_gw.copy()
        out["xgc_r5"] = pd.Series(dtype=float)
        out["xgc_r5_home"] = pd.Series(dtype=float)
        out["xgc_r5_away"] = pd.Series(dtype=float)
        return out
    frames = [
        _rolls_one_team(g, window)
        for _, g in team_gw.groupby(["season", "team"], sort=False)
    ]
    return pd.concat(frames, ignore_index=True)


def _rolls_one_team(g: pd.DataFrame, window: int) -> pd.DataFrame:
    g = g.sort_values("GW").copy()
    xgc = pd.to_numeric(g["xgc"], errors="coerce").fillna(0.0)
    g["xgc_r5"] = xgc.shift(1).rolling(window, min_periods=1).mean().fillna(0.0)
    home_hist: list[float] = []
    away_hist: list[float] = []
    home_r: list[float] = []
    away_r: list[float] = []
    homes = pd.to_numeric(g["was_home"], errors="coerce").fillna(0).astype(int)
    for val, is_home in zip(xgc.to_numpy(dtype=float), homes.to_numpy()):
        home_r.append(float(np.mean(home_hist[-window:])) if home_hist else 0.0)
        away_r.append(float(np.mean(away_hist[-window:])) if away_hist else 0.0)
        if int(is_home) == 1:
            home_hist.append(float(val))
        else:
            away_hist.append(float(val))
    g["xgc_r5_home"] = home_r
    g["xgc_r5_away"] = away_r
    return g


def next_gw_team_xgc(
    team_gw: pd.DataFrame, window: int = OPP_XGC_WINDOW
) -> pd.DataFrame:
    """Team r5 as of the GW after the last completed GW (includes last GW)."""
    if team_gw.empty:
        out = team_gw.copy()
        for col in ("xgc_r5", "xgc_r5_home", "xgc_r5_away"):
            out[col] = pd.Series(dtype=float)
        return out
    extras = (
        team_gw.groupby(["season", "team"], as_index=False)
        .agg(GW=("GW", "max"))
        .assign(was_home=0, xgc=0.0)
    )
    extras["GW"] = pd.to_numeric(extras["GW"], errors="coerce") + 1
    ext = pd.concat([team_gw, extras], ignore_index=True)
    rolled = add_shifted_team_rolls(ext, window)
    return rolled.merge(extras[["season", "team", "GW"]], on=["season", "team", "GW"])


def attach_opponent_xgc(
    df: pd.DataFrame,
    teams: pd.DataFrame | None = None,
    window: int = OPP_XGC_WINDOW,
) -> pd.DataFrame:
    """Merge shifted opponent r5 features onto player-GW rows."""
    out = df.copy()
    drop = [c for c in OPP_XGC_COLS if c in out.columns]
    if drop:
        out = out.drop(columns=drop)
    tg = team_gw_xgc(out)
    rolled = add_shifted_team_rolls(tg, window)
    out["_opp_team"] = resolve_opponent_team_name(out, teams)
    out["GW"] = pd.to_numeric(out["GW"], errors="coerce")
    right = rolled.rename(
        columns={
            "team": "_opp_team",
            "xgc_r5": "opp_xgc_r5",
            "xgc_r5_home": "opp_xgc_r5_home",
            "xgc_r5_away": "opp_xgc_r5_away",
        }
    )
    right["GW"] = pd.to_numeric(right["GW"], errors="coerce")
    out = out.merge(
        right[["season", "_opp_team", "GW", *OPP_XGC_COLS]],
        on=["season", "_opp_team", "GW"],
        how="left",
    )
    for col in OPP_XGC_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.drop(columns=["_opp_team"])


def attach_live_opponent_xgc(
    live: pd.DataFrame,
    panel: pd.DataFrame,
    prior_season: str,
    window: int = OPP_XGC_WINDOW,
    opponent_name_col: str = "opponent_name",
) -> pd.DataFrame:
    """Attach end-of-``prior_season`` opponent r5 (last 5 completed GWs)."""
    out = live.copy()
    drop = [c for c in OPP_XGC_COLS if c in out.columns]
    if drop:
        out = out.drop(columns=drop)
    src = panel[panel["season"].astype(str).eq(str(prior_season))].copy()
    if src.empty:
        for col in OPP_XGC_COLS:
            out[col] = 0.0
        return out
    nxt = next_gw_team_xgc(team_gw_xgc(src), window)
    right = nxt.rename(
        columns={
            "team": "_opp_team",
            "xgc_r5": "opp_xgc_r5",
            "xgc_r5_home": "opp_xgc_r5_home",
            "xgc_r5_away": "opp_xgc_r5_away",
        }
    )
    if opponent_name_col in out.columns:
        out["_opp_team"] = out[opponent_name_col]
    else:
        out["_opp_team"] = resolve_opponent_team_name(out)
    out = out.merge(right[["_opp_team", *OPP_XGC_COLS]], on="_opp_team", how="left")
    for col in OPP_XGC_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.drop(columns=["_opp_team"])
