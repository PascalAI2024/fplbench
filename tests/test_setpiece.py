"""Leak-safe prior-season set-piece order join/shift (no shipped MAE)."""

from __future__ import annotations

import pandas as pd

from fplbench.ingest import SETPIECE_ORDER_COLS
from fplbench.panel import (
    attach_prior_season_setpiece_orders,
    feature_columns,
    join_setpiece_orders,
    shift_setpiece_orders_to_prior_season,
)


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    players = pd.DataFrame(
        {
            "season": ["2023-24", "2024-25", "2024-25"],
            "element": [1, 1, 2],
            "code": ["p1", "p1", "p2"],
            "penalties_order": [1, 3, 1],
            "corners_and_indirect_freekicks_order": [2, 5, 4],
            "direct_freekicks_order": [3, 6, 2],
        }
    )
    panel = pd.DataFrame(
        {
            "season": ["2023-24", "2023-24", "2024-25", "2024-25", "2024-25"],
            "element": [1, 1, 1, 1, 2],
            "player_code": ["p1", "p1", "p1", "p1", "p2"],
            "GW": [1, 2, 1, 2, 1],
            "was_home": [1, 0, 1, 0, 1],
            "fdr": [2, 3, 2, 4, 3],
            "value": [80, 80, 85, 85, 50],
            "gw_in_season": [1, 2, 1, 2, 1],
        }
    )
    return panel, players


def test_join_keeps_same_season_snapshot():
    panel, players = _fixture()
    joined = join_setpiece_orders(panel, players)
    s1 = joined[joined["season"].eq("2023-24")]
    s2 = joined[joined["season"].eq("2024-25") & joined["player_code"].eq("p1")]
    assert (s1["penalties_order"] == 1).all()
    assert (s2["penalties_order"] == 3).all()


def test_shift_uses_prior_season_not_end_of_season_snapshot():
    panel, players = _fixture()
    out = shift_setpiece_orders_to_prior_season(join_setpiece_orders(panel, players))
    s2 = out[out["season"].eq("2024-25") & out["player_code"].eq("p1")]
    assert len(s2) == 2
    assert (s2["penalties_order"] == 1).all()
    assert (s2["corners_and_indirect_freekicks_order"] == 2).all()
    assert (s2["direct_freekicks_order"] == 3).all()
    assert not (s2["penalties_order"] == 3).any()


def test_first_season_and_new_player_are_zero():
    panel, players = _fixture()
    out = shift_setpiece_orders_to_prior_season(join_setpiece_orders(panel, players))
    s1 = out[out["season"].eq("2023-24")]
    newbie = out[out["player_code"].eq("p2")]
    for col in SETPIECE_ORDER_COLS:
        assert (s1[col] == 0).all()
        assert (newbie[col] == 0).all()


def test_feature_columns_includes_setpiece_orders():
    panel, players = _fixture()
    out = shift_setpiece_orders_to_prior_season(join_setpiece_orders(panel, players))
    feats = feature_columns(out)
    for col in SETPIECE_ORDER_COLS:
        assert col in feats


def test_attach_prior_season_orders_by_player_code():
    live = pd.DataFrame({"player_code": ["p1", "p_new"]})
    prior = pd.DataFrame(
        {
            "code": ["p1"],
            "penalties_order": [1],
            "corners_and_indirect_freekicks_order": [2],
            "direct_freekicks_order": [3],
        }
    )
    out = attach_prior_season_setpiece_orders(live, prior)
    row = out[out["player_code"].eq("p1")].iloc[0]
    assert row["penalties_order"] == 1
    assert row["corners_and_indirect_freekicks_order"] == 2
    assert row["direct_freekicks_order"] == 3
    newbie = out[out["player_code"].eq("p_new")].iloc[0]
    for col in SETPIECE_ORDER_COLS:
        assert newbie[col] == 0
