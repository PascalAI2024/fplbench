"""Unit tests for FPL squad ILP (tiny synthetic pool)."""

from __future__ import annotations

import pandas as pd
import pytest

from fplbench.squad import (
    BUDGET_TENTHS,
    eligible_mask,
    filter_eligible,
    pick_squad,
    verify_squad,
)


def _row(
    i: int,
    name: str,
    pos: str,
    club: str,
    cost: int,
    pts: float,
    status: str = "a",
    chance=None,
) -> dict:
    return {
        "id": i,
        "web_name": name,
        "position": pos,
        "team_name": club,
        "now_cost": cost,
        "e_points_final": pts,
        "status": status,
        "chance_of_playing_next_round": chance,
    }


def _tiny_pool() -> pd.DataFrame:
    """Enough players for a legal 15 with known optimum-friendly costs."""
    rows = []
    n = 1
    # 3 GK — prefer high pts cheap
    for name, club, cost, pts in [
        ("GK_A", "ClubA", 40, 4.0),
        ("GK_B", "ClubB", 45, 3.5),
        ("GK_C", "ClubC", 50, 1.0),
    ]:
        rows.append(_row(n, name, "GK", club, cost, pts))
        n += 1
    # 7 DEF
    for i, (club, cost, pts) in enumerate(
        [
            ("ClubA", 40, 5.0),
            ("ClubB", 45, 4.5),
            ("ClubC", 40, 4.0),
            ("ClubD", 50, 3.5),
            ("ClubE", 45, 3.0),
            ("ClubF", 55, 2.0),
            ("ClubG", 60, 0.5),
        ]
    ):
        rows.append(_row(n, f"DEF_{i}", "DEF", club, cost, pts))
        n += 1
    # 7 MID
    for i, (club, cost, pts) in enumerate(
        [
            ("ClubA", 100, 6.0),
            ("ClubB", 90, 5.5),
            ("ClubC", 80, 5.0),
            ("ClubD", 70, 4.0),
            ("ClubE", 65, 3.5),
            ("ClubF", 60, 2.0),
            ("ClubG", 50, 0.5),
        ]
    ):
        rows.append(_row(n, f"MID_{i}", "MID", club, cost, pts))
        n += 1
    # 5 FWD
    for i, (club, cost, pts) in enumerate(
        [
            ("ClubD", 120, 7.0),
            ("ClubE", 100, 6.0),
            ("ClubF", 75, 4.0),
            ("ClubG", 70, 2.0),
            ("ClubC", 65, 1.0),
        ]
    ):
        rows.append(_row(n, f"FWD_{i}", "FWD", club, cost, pts))
        n += 1
    # Injured zero-chance should be dropped even with huge points
    rows.append(_row(n, "HurtStar", "MID", "ClubA", 40, 99.0, status="i", chance=0.0))
    n += 1
    # Doubtful with non-zero chance stays eligible
    rows.append(_row(n, "Doubtful", "DEF", "ClubG", 40, 0.1, status="d", chance=75.0))
    return pd.DataFrame(rows)


def test_eligible_excludes_zero_chance_non_available():
    df = _tiny_pool()
    elig = filter_eligible(df)
    assert "HurtStar" not in set(elig["web_name"])
    assert "Doubtful" in set(elig["web_name"])
    assert eligible_mask(df).sum() == len(df) - 1


def test_pick_squad_respects_constraints():
    result = pick_squad(_tiny_pool())
    errors = verify_squad(result)
    assert errors == []
    assert len(result.squad) == 15
    assert result.total_cost_tenths <= BUDGET_TENTHS
    counts = result.squad["position"].value_counts().to_dict()
    assert counts == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert int(result.squad["team_name"].value_counts().max()) <= 3
    assert result.captain_name == result.squad.loc[
        result.squad["e_points_final"].idxmax(), "web_name"
    ]
    assert "HurtStar" not in set(result.squad["web_name"])


def test_pick_squad_infeasible_raises():
    # Only one GK — cannot fill 2
    df = _tiny_pool()
    df = df[df["position"] != "GK"].copy()
    df = pd.concat(
        [df, pd.DataFrame([_row(999, "OnlyGK", "GK", "ClubA", 40, 1.0)])],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="not enough eligible GK"):
        pick_squad(df)
