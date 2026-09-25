"""Bench order and FPL autosub simulation."""

from __future__ import annotations

import pandas as pd
import pytest

from fplbench.bench import _autosub_points, order_bench, play_probability
from fplbench.squad import pick_squad

# 4-4-2 XI (ids 1-11) + bench GK 12 and outfield 13 (DEF), 14 (MID), 15 (FWD).
XI_PLAN = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["FWD"] * 2
BENCH_PLAN = ["GK", "DEF", "MID", "FWD"]


def _squad(
    xi_minutes: float = 90.0,
    bench: dict[int, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """15 rows; `bench` maps id -> (e_points_final, pred_minutes)."""
    bench = bench or {}
    rows = []
    for n, pos in enumerate(XI_PLAN + BENCH_PLAN, start=1):
        pts, mins = bench.get(n, (2.0, xi_minutes if n <= 11 else 90.0))
        rows.append(
            {
                "id": n,
                "web_name": f"p{n}",
                "position": pos,
                "e_points_final": pts,
                "pred_minutes": mins,
                "chance_of_playing_next_round": None,
            }
        )
    return pd.DataFrame(rows)


XI_IDS = list(range(1, 12))


def test_backup_goalkeeper_is_always_slot_one() -> None:
    squad = _squad(xi_minutes=40.0, bench={12: (0.5, 90.0), 13: (4.0, 90.0)})
    order = order_bench(squad, XI_IDS)
    assert order.ids[0] == 12
    assert sorted(order.ids) == [12, 13, 14, 15]


def test_nailed_xi_keeps_points_order() -> None:
    squad = _squad(bench={13: (1.0, 90.0), 14: (3.0, 90.0), 15: (2.0, 90.0)})
    assert order_bench(squad, XI_IDS).outfield_ids == [14, 15, 13]


def test_rotation_risk_sub_moves_up_when_he_scores_more_when_he_plays() -> None:
    # 14 projects 1.8 over 30 minutes: when he plays he is worth ~3.6, more
    # than 13's nailed 2.0. A sub who doesn't play is skipped for free, so he
    # belongs ahead of 13 even though his raw projection is lower.
    squad = _squad(
        xi_minutes=30.0,
        bench={13: (2.0, 90.0), 14: (1.8, 30.0), 15: (0.5, 90.0)},
    )
    order = order_bench(squad, XI_IDS)
    assert order.outfield_ids[0] == 14
    assert order.expected_sub_points > order.naive_sub_points


def test_injured_sub_goes_last() -> None:
    squad = _squad(xi_minutes=45.0, bench={13: (3.0, 90.0), 14: (2.0, 90.0)})
    squad.loc[squad["id"] == 13, "chance_of_playing_next_round"] = 0.0
    order = order_bench(squad, XI_IDS)
    assert order.outfield_ids[-1] == 13


def test_order_is_reproducible() -> None:
    squad = _squad(xi_minutes=50.0, bench={13: (2.1, 70.0), 14: (2.0, 40.0)})
    assert order_bench(squad, XI_IDS).ids == order_bench(squad, XI_IDS).ids


def test_rejects_a_bench_without_one_goalkeeper() -> None:
    squad = _squad()
    with pytest.raises(ValueError, match="exactly one GK"):
        order_bench(squad, list(range(2, 12)) + [13])


def test_play_probability_follows_the_holdout_curve() -> None:
    df = pd.DataFrame(
        {
            "pred_minutes": [90.0, 30.0, 1.0, 90.0],
            "chance_of_playing_next_round": [None, None, None, 25.0],
        }
    )
    # 90' tops out below certainty, 30' sits between the 22' and 38' knots,
    # a 1' cameo projection is ruled out, and a 25% flag overrides minutes.
    assert play_probability(df).tolist() == pytest.approx([0.97, 0.63, 0.0, 0.25])


def _positions() -> dict[int, str]:
    return {n: pos for n, pos in enumerate(XI_PLAN + BENCH_PLAN, start=1)}


def test_autosub_respects_the_three_defender_minimum() -> None:
    # 3-5-2: DEF 5 plays in midfield, so the XI has exactly 3 defenders.
    pos = _positions()
    pos[5] = "MID"
    played = {i: True for i in pos}
    played[2] = False  # a defender misses out
    pts = {i: float(i) for i in pos}
    # MID 14 is first on the bench but cannot replace a defender at 3 DEF.
    assert _autosub_points(XI_IDS, [14, 13, 15], 12, played, pts, pos) == 13.0


def test_autosub_skips_subs_who_did_not_play() -> None:
    pos = _positions()
    played = {i: True for i in pos}
    played[6], played[14] = False, False
    pts = {i: float(i) for i in pos}
    assert _autosub_points(XI_IDS, [14, 15, 13], 12, played, pts, pos) == 15.0


def test_only_the_backup_goalkeeper_replaces_the_goalkeeper() -> None:
    pos = _positions()
    played = {i: True for i in pos}
    played[1], played[12] = False, False
    pts = {i: float(i) for i in pos}
    assert _autosub_points(XI_IDS, [13, 14, 15], 12, played, pts, pos) == 0.0


def test_pick_squad_uses_the_simulated_bench() -> None:
    rows = []
    n = 1
    for pos, count in (("GK", 3), ("DEF", 6), ("MID", 6), ("FWD", 4)):
        for k in range(count):
            rows.append(
                {
                    "id": n,
                    "web_name": f"{pos}{k}",
                    "position": pos,
                    "team_name": f"club{n % 10}",
                    "now_cost": 45,
                    "e_points_final": 5.0 - k * 0.5,
                    "pred_minutes": 90.0,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                }
            )
            n += 1
    result = pick_squad(pd.DataFrame(rows))
    assert result.bench.iloc[0]["position"] == "GK"
    assert len(result.bench) == 4
    assert set(result.bench["id"]).isdisjoint(result.xi["id"])
