"""Shared end-of-season form / lag features for panel GW1 and live scoring."""

from __future__ import annotations

import pandas as pd

FORM_COLS = (
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
)


def last_played_window(group: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Last n appearances with minutes > 0. Trailing blanks are not form."""
    g = group.sort_values("GW")
    played = g[pd.to_numeric(g["minutes"], errors="coerce").fillna(0) > 0]
    if played.empty:
        return g.tail(0)
    return played.tail(n)


def player_end_of_season_row(group: pd.DataFrame) -> dict:
    g = group.sort_values("GW")
    all_played = g[pd.to_numeric(g["minutes"], errors="coerce").fillna(0) > 0]
    played = last_played_window(g, 5)
    rec: dict = {"player_code": str(g["player_code"].iloc[0])}
    rec["prior_games"] = int(len(all_played))
    rec["prior_minutes"] = pd.to_numeric(g["minutes"], errors="coerce").fillna(0).sum()
    rec["prior_points"] = (
        pd.to_numeric(g["total_points"], errors="coerce").fillna(0).sum()
    )
    rec["prior_xg"] = (
        pd.to_numeric(g["expected_goals"], errors="coerce").fillna(0).sum()
        if "expected_goals" in g
        else 0.0
    )
    rec["prior_xa"] = (
        pd.to_numeric(g["expected_assists"], errors="coerce").fillna(0).sum()
        if "expected_assists" in g
        else 0.0
    )
    rec["prior_defcon_hits"] = (
        pd.to_numeric(g["defcon_hit"], errors="coerce").fillna(0).sum()
        if "defcon_hit" in g
        else 0.0
    )
    rec["prior_starts"] = (
        pd.to_numeric(g["starts"], errors="coerce").fillna(0).sum()
        if "starts" in g
        else 0.0
    )
    games = max(int(rec["prior_games"]), 1)
    rec["prior_ppg"] = rec["prior_points"] / games if rec["prior_games"] else 0.0
    rec["prior_minutes_pg"] = (
        pd.to_numeric(all_played["minutes"], errors="coerce").mean()
        if not all_played.empty
        else 0.0
    )
    rec["prior_xg90"] = rec["prior_xg"] / max(rec["prior_minutes"], 1) * 90
    rec["prior_defcon_rate"] = (
        rec["prior_defcon_hits"] / games if rec["prior_games"] else 0.0
    )
    window = played if not played.empty else g.tail(5)
    for src_col in FORM_COLS:
        if src_col not in g.columns:
            continue
        s = pd.to_numeric(window[src_col], errors="coerce")
        rec[f"{src_col}_l1"] = s.iloc[-1] if len(s) else 0.0
        rec[f"{src_col}_r3"] = s.tail(3).mean() if len(s) else 0.0
        rec[f"{src_col}_r5"] = s.tail(5).mean() if len(s) else 0.0
    return rec
