"""Transfer ILP constraints. Every assertion here guards something that
costs real squad value if it breaks in a live run."""

from __future__ import annotations

import pandas as pd
import pytest

from fplbench.transfers import (
    HIT_COST,
    TransferPlan,
    baseline_plan,
    plan_transfers,
    plan_with_baseline,
    sanity_check,
)

POS_PLAN = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _board(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "status": "a",
                "chance_of_playing_next_round": 100.0,
                "now_cost": 50,
                "team_name": f"club{r['id'] % 12}",
                **r,
            }
            for r in rows
        ]
    )


def _squad_rows(start_id: int, points: float, **kw) -> list[dict]:
    """One legal 15 with uniform points, ids start_id..start_id+14."""
    return [
        {"id": start_id + n, "web_name": f"p{start_id + n}", "position": pos,
         "e_points_final": points, **kw}
        for n, pos in enumerate(POS_PLAN)
    ]


def _owned_and_market(owned_pts: float = 2.0) -> tuple[pd.DataFrame, list[int]]:
    """15 owned on `owned_pts`, plus a same-shape market priced identically."""
    owned = _squad_rows(1, owned_pts)
    market = _squad_rows(101, 2.0)
    return _board(owned + market), [r["id"] for r in owned]


def test_zero_transfers_when_market_is_no_better() -> None:
    board, owned = _owned_and_market(owned_pts=2.0)
    plan = plan_transfers(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert plan.n_transfers == 0
    assert sorted(plan.squad_ids) == sorted(owned)


def test_takes_the_free_transfer_when_it_gains() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 9.0  # a much better GK
    plan = plan_with_baseline(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert plan.n_transfers == 1
    assert plan.in_ids == [101]
    assert plan.expected_gain > 0


def test_respects_max_transfers() -> None:
    board, owned = _owned_and_market()
    for pid in (103, 104, 108, 109):
        board.loc[board["id"] == pid, "e_points_final"] = 9.0
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        free_transfers=5,
        max_transfers=2,
    )
    assert plan.n_transfers == 2


def test_refuses_a_hit_that_does_not_pay_for_itself() -> None:
    """A second transfer worth less than 4 points must not be taken."""
    board, owned = _owned_and_market()
    board.loc[board["id"] == 103, "e_points_final"] = 9.0
    board.loc[board["id"] == 108, "e_points_final"] = 2.5  # +0.5, hit costs 4
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        free_transfers=1,
        max_transfers=2,
    )
    assert plan.n_transfers == 1
    assert plan.in_ids == [103]
    assert plan.hit_cost == 0.0


def test_takes_a_hit_when_it_clearly_pays() -> None:
    board, owned = _owned_and_market()
    # 103 is a DEF and 108 a MID, so both actually start and both score.
    board.loc[board["id"] == 103, "e_points_final"] = 20.0
    board.loc[board["id"] == 108, "e_points_final"] = 20.0
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        free_transfers=1,
        max_transfers=2,
    )
    assert plan.n_transfers == 2
    assert plan.hit_cost == HIT_COST


def test_cannot_outspend_the_bank() -> None:
    """A better player who costs more than proceeds plus bank is unreachable."""
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 50.0
    board.loc[board["id"] == 101, "now_cost"] = 130
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        bank_tenths=0,
        free_transfers=1,
    )
    assert 101 not in plan.squad_ids
    assert plan.bank_after_tenths >= 0


def test_bank_makes_the_same_player_affordable() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 50.0
    board.loc[board["id"] == 101, "now_cost"] = 130
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        bank_tenths=80,
        free_transfers=1,
    )
    assert 101 in plan.squad_ids


def test_selling_price_not_list_price_sets_the_budget() -> None:
    """Owned players who fell in value fund less than now_cost suggests."""
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 50.0
    board.loc[board["id"] == 101, "now_cost"] = 55
    cheap = {i: 50 for i in owned}
    cheap[1] = 40  # the GK we would sell is only worth 4.0m
    plan = plan_transfers(
        board, owned, selling_prices=cheap, bank_tenths=0, free_transfers=1
    )
    assert 101 not in plan.squad_ids


def test_enforces_three_per_club() -> None:
    board, owned = _owned_and_market()
    # Two owned DEFs already at the club, three more on offer and scoring
    # heavily: the solver wants all five and may hold at most three.
    board.loc[board["id"].isin([3, 4]), "team_name"] = "stacked"
    board.loc[board["id"].isin([103, 104, 105]), "team_name"] = "stacked"
    board.loc[board["id"].isin([103, 104, 105]), "e_points_final"] = 30.0
    plan = plan_transfers(
        board,
        owned,
        selling_prices={i: 50 for i in owned},
        free_transfers=5,
        max_transfers=3,
    )
    clubs = board.set_index("id")["team_name"].to_dict()
    counts: dict[str, int] = {}
    for pid in plan.squad_ids:
        counts[clubs[pid]] = counts.get(clubs[pid], 0) + 1
    assert max(counts.values()) <= 3


def test_injured_owned_player_can_still_be_sold() -> None:
    """Availability filters new signings, never the sellable squad."""
    board, owned = _owned_and_market()
    board.loc[board["id"] == 1, "status"] = "i"
    board.loc[board["id"] == 1, "chance_of_playing_next_round"] = 0.0
    board.loc[board["id"] == 1, "e_points_final"] = 0.0
    board.loc[board["id"] == 101, "e_points_final"] = 9.0
    plan = plan_transfers(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert plan.out_ids == [1]


def test_will_not_buy_an_unavailable_player() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 50.0
    board.loc[board["id"] == 101, "status"] = "i"
    board.loc[board["id"] == 101, "chance_of_playing_next_round"] = 0.0
    plan = plan_transfers(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert 101 not in plan.squad_ids


def test_baseline_makes_no_transfers() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 99.0
    base = baseline_plan(board, owned)
    assert base.n_transfers == 0
    assert sorted(base.squad_ids) == sorted(owned)


def test_rolls_the_transfer_when_nothing_beats_holding() -> None:
    board, owned = _owned_and_market()
    plan = plan_with_baseline(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert plan.expected_gain <= 0.0001


def test_captain_and_vice_are_distinct_starters() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 3, "e_points_final"] = 12.0
    board.loc[board["id"] == 4, "e_points_final"] = 11.0
    plan = plan_transfers(
        board, owned, selling_prices={i: 50 for i in owned}, free_transfers=1
    )
    assert plan.captain_id in plan.xi_ids
    assert plan.vice_id in plan.xi_ids
    assert plan.captain_id != plan.vice_id


def test_rejects_a_squad_that_is_not_fifteen() -> None:
    board, owned = _owned_and_market()
    with pytest.raises(ValueError, match="expected 15 owned"):
        plan_transfers(board, owned[:14], selling_prices={i: 50 for i in owned})


def test_rejects_missing_selling_price() -> None:
    board, owned = _owned_and_market()
    with pytest.raises(ValueError, match="no selling price"):
        plan_transfers(board, owned, selling_prices={i: 50 for i in owned[:-1]})


def test_sanity_check_catches_a_corrupt_plan() -> None:
    bad = TransferPlan(
        out_ids=[1, 2],
        in_ids=[101],
        squad_ids=[1],
        xi_ids=[1],
        captain_id=999,
        vice_id=999,
        expected_xi_points=0.0,
        hit_cost=0.0,
        bank_after_tenths=-5,
    )
    errors = sanity_check(bad, {1: 50, 2: 50})
    joined = " ".join(errors)
    assert "squad is 1" in joined
    assert "XI is 1" in joined
    assert "bank would go negative" in joined
    assert "captain is not in the XI" in joined
    assert "unbalanced" in joined


def test_sanity_check_passes_a_real_plan() -> None:
    board, owned = _owned_and_market()
    board.loc[board["id"] == 101, "e_points_final"] = 9.0
    sell = {i: 50 for i in owned}
    plan = plan_transfers(board, owned, selling_prices=sell, free_transfers=1)
    assert sanity_check(plan, sell) == []
