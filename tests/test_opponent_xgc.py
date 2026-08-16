"""Leak-safe opponent rolling xGC: GW t must not see GW t xGC."""

from __future__ import annotations

import pandas as pd

from fplbench.opponent import (
    OPP_XGC_COLS,
    attach_live_opponent_xgc,
    attach_opponent_xgc,
    next_gw_team_xgc,
    team_gw_xgc,
)
from fplbench.panel import feature_columns


def _row(
    *,
    team: str,
    gw: int,
    xgc: float,
    was_home: int,
    opponent: str,
    position: str = "GK",
    minutes: float = 90,
    name: str = "k",
    season: str = "2024-25",
) -> dict:
    return {
        "season": season,
        "team": team,
        "GW": gw,
        "position": position,
        "minutes": minutes,
        "expected_goals_conceded": xgc,
        "was_home": was_home,
        "opponent_team": opponent,
        "name": name,
    }


def _ab_panel() -> pd.DataFrame:
    """A faces B every GW. B xGC = 10, 20, 30, 40. B home in 1,3 away in 2,4."""
    rows = []
    b_xgc = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    b_home = {1: 1, 2: 0, 3: 1, 4: 0}
    for gw in (1, 2, 3, 4):
        rows.append(
            _row(
                team="A",
                gw=gw,
                xgc=1.0,
                was_home=1 - b_home[gw],
                opponent="B",
                name="a_gk",
            )
        )
        rows.append(
            _row(
                team="B",
                gw=gw,
                xgc=b_xgc[gw],
                was_home=b_home[gw],
                opponent="A",
                name="b_gk",
            )
        )
    return pd.DataFrame(rows)


def test_gw3_does_not_see_gw3_xgc():
    out = attach_opponent_xgc(_ab_panel())
    a3 = out[(out["team"].eq("A")) & (out["GW"].eq(3))].iloc[0]
    # B completed GWs 1–2 only: (10 + 20) / 2
    assert a3["opp_xgc_r5"] == 15.0
    assert a3["opp_xgc_r5"] != 20.0
    assert a3["opp_xgc_r5"] != 30.0
    # B home < GW3: GW1 only. B away < GW3: GW2 only.
    assert a3["opp_xgc_r5_home"] == 10.0
    assert a3["opp_xgc_r5_away"] == 20.0


def test_first_gw_is_zero():
    out = attach_opponent_xgc(_ab_panel())
    a1 = out[(out["team"].eq("A")) & (out["GW"].eq(1))].iloc[0]
    assert a1["opp_xgc_r5"] == 0.0
    assert a1["opp_xgc_r5_home"] == 0.0
    assert a1["opp_xgc_r5_away"] == 0.0


def test_gk_preferred_over_outfield():
    df = pd.DataFrame(
        [
            _row(team="B", gw=1, xgc=9.0, was_home=1, opponent="A", position="GK"),
            _row(
                team="B",
                gw=1,
                xgc=0.1,
                was_home=1,
                opponent="A",
                position="DEF",
                name="outfield",
            ),
            _row(team="A", gw=2, xgc=1.0, was_home=0, opponent="B"),
            _row(team="B", gw=2, xgc=1.0, was_home=0, opponent="A"),
        ]
    )
    tg = team_gw_xgc(df)
    b1 = tg[(tg["team"].eq("B")) & (tg["GW"].eq(1))].iloc[0]
    assert b1["xgc"] == 9.0
    out = attach_opponent_xgc(df)
    a2 = out[(out["team"].eq("A")) & (out["GW"].eq(2))].iloc[0]
    assert a2["opp_xgc_r5"] == 9.0


def test_fallback_all_players_when_no_gk():
    df = pd.DataFrame(
        [
            _row(
                team="B",
                gw=1,
                xgc=2.0,
                was_home=1,
                opponent="A",
                position="DEF",
                minutes=90,
                name="d1",
            ),
            _row(
                team="B",
                gw=1,
                xgc=4.0,
                was_home=1,
                opponent="A",
                position="MID",
                minutes=90,
                name="m1",
            ),
            _row(team="A", gw=2, xgc=0.0, was_home=0, opponent="B"),
            _row(
                team="B",
                gw=2,
                xgc=0.0,
                was_home=0,
                opponent="A",
                position="DEF",
                name="d2",
            ),
        ]
    )
    tg = team_gw_xgc(df)
    b1 = tg[(tg["team"].eq("B")) & (tg["GW"].eq(1))].iloc[0]
    assert b1["xgc"] == 3.0


def test_gkp_counts_as_keeper():
    df = pd.DataFrame(
        [
            _row(team="B", gw=1, xgc=5.0, was_home=1, opponent="A", position="GKP"),
            _row(
                team="B",
                gw=1,
                xgc=1.0,
                was_home=1,
                opponent="A",
                position="DEF",
                name="d",
            ),
            _row(team="A", gw=2, xgc=0.0, was_home=0, opponent="B"),
            _row(team="B", gw=2, xgc=0.0, was_home=0, opponent="A"),
        ]
    )
    tg = team_gw_xgc(df)
    assert tg[(tg["team"].eq("B")) & (tg["GW"].eq(1))]["xgc"].iloc[0] == 5.0


def test_next_gw_includes_last_completed():
    tg = team_gw_xgc(_ab_panel())
    nxt = next_gw_team_xgc(tg)
    b = nxt[nxt["team"].eq("B")].iloc[0]
    assert b["xgc_r5"] == 25.0  # (10+20+30+40)/4
    assert b["xgc_r5_home"] == 20.0  # (10+30)/2
    assert b["xgc_r5_away"] == 30.0  # (20+40)/2


def test_live_helper_uses_end_of_prior_season():
    panel = _ab_panel()
    live = pd.DataFrame({"opponent_name": ["B", "Nobody"]})
    out = attach_live_opponent_xgc(live, panel, "2024-25")
    assert out.loc[0, "opp_xgc_r5"] == 25.0
    assert out.loc[0, "opp_xgc_r5_home"] == 20.0
    assert out.loc[0, "opp_xgc_r5_away"] == 30.0
    assert out.loc[1, "opp_xgc_r5"] == 0.0


def test_feature_columns_includes_opp_xgc():
    df = pd.DataFrame(
        {
            "was_home": [1],
            "fdr": [2],
            "value": [50],
            "gw_in_season": [1],
            "opp_xgc_r5": [1.2],
            "opp_xgc_r5_home": [0.8],
            "opp_xgc_r5_away": [1.1],
        }
    )
    feats = feature_columns(df)
    for col in OPP_XGC_COLS:
        assert col in feats


def test_id_map_via_teams():
    df = pd.DataFrame(
        [
            _row(team="A", gw=1, xgc=1.0, was_home=1, opponent=2),
            _row(team="B", gw=1, xgc=8.0, was_home=0, opponent=1),
            _row(team="A", gw=2, xgc=1.0, was_home=0, opponent=2),
            _row(team="B", gw=2, xgc=4.0, was_home=1, opponent=1),
        ]
    )
    teams = pd.DataFrame(
        {
            "season": ["2024-25", "2024-25"],
            "id": [1, 2],
            "name": ["A", "B"],
        }
    )
    out = attach_opponent_xgc(df, teams=teams)
    a2 = out[(out["team"].eq("A")) & (out["GW"].eq(2))].iloc[0]
    assert a2["opp_xgc_r5"] == 8.0
