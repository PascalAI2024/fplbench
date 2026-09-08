"""Weekly transfer selection via ILP (PuLP).

`squad.pick_squad` answers "what 15 would I buy with £100m from scratch".
That is the wrong question once a squad exists: transfers are constrained by
what is already owned, by selling prices rather than list prices, and by the
4-point hit for exceeding the free-transfer allowance.

This module answers the weekly question instead — given the owned 15, the
bank, and this gameweek's board, which transfers maximise expected *starting
XI* points net of hits. Only 11 players score, so the objective optimises the
XI and the captain jointly with squad composition; a small bench weight breaks
ties toward benches that survive autosubs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pulp

from fplbench.squad import (
    MAX_PER_CLUB,
    POS_SQUAD,
    SQUAD_SIZE,
    XI_DEF,
    XI_FWD,
    XI_MID,
    XI_SIZE,
    eligible_mask,
)

HIT_COST = 4.0
# Bench players score only via autosubs. Non-zero so the solver prefers a
# useful bench among otherwise-equal squads, small enough never to outrank a
# starter.
BENCH_WEIGHT = 0.1
MAX_FREE_TRANSFERS = 5
# A free transfer costs no points, so on tied projections the solver is
# indifferent between holding and churning. Bias it toward holding: never
# spend a transfer that gains nothing.
TRANSFER_EPSILON = 0.01


@dataclass
class TransferPlan:
    out_ids: list[int]
    in_ids: list[int]
    squad_ids: list[int]
    xi_ids: list[int]
    captain_id: int
    vice_id: int
    expected_xi_points: float
    hit_cost: float
    bank_after_tenths: int
    baseline_xi_points: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def n_transfers(self) -> int:
        return len(self.out_ids)

    @property
    def expected_gain(self) -> float:
        """Net of hits — the only number worth acting on."""
        return self.expected_xi_points - self.hit_cost - self.baseline_xi_points


def _pool(board: pd.DataFrame, owned_ids: list[int]) -> pd.DataFrame:
    """Eligible players plus every owned player.

    An injured owned player is unavailable to *buy* but must stay sellable,
    so availability filters new signings only.
    """
    df = board.dropna(subset=["e_points_final", "now_cost", "position", "team_name"])
    keep = eligible_mask(df) | df["id"].isin(owned_ids)
    out = df.loc[keep].copy()
    out["now_cost"] = out["now_cost"].astype(int)
    out["e_points_final"] = out["e_points_final"].astype(float)
    out["id"] = out["id"].astype(int)
    return out.reset_index(drop=True)


def plan_transfers(
    board: pd.DataFrame,
    owned_ids: list[int],
    *,
    selling_prices: dict[int, int],
    bank_tenths: int = 0,
    free_transfers: int = 1,
    max_transfers: int = 2,
) -> TransferPlan:
    """Best transfers for one gameweek.

    `selling_prices` maps owned player id -> tenths of a million. FPL sells at
    purchase price plus half the rise, so this must come from the authenticated
    my-team endpoint; passing `now_cost` overstates the budget for any player
    who has risen.
    """
    if len(owned_ids) != SQUAD_SIZE:
        raise ValueError(f"expected {SQUAD_SIZE} owned players, got {len(owned_ids)}")

    pool = _pool(board, owned_ids)
    missing = [i for i in owned_ids if i not in set(pool["id"])]
    if missing:
        raise ValueError(f"owned players absent from board: {missing}")

    unpriced = [i for i in owned_ids if i not in selling_prices]
    if unpriced:
        raise ValueError(f"no selling price for owned players: {unpriced}")

    free_transfers = max(0, min(int(free_transfers), MAX_FREE_TRANSFERS))
    idx = list(pool.index)
    ids = pool["id"].to_dict()
    owned = set(owned_ids)
    pts = pool["e_points_final"].to_dict()
    cost = pool["now_cost"].to_dict()
    position = pool["position"].to_dict()
    club = pool["team_name"].to_dict()

    prob = pulp.LpProblem("fpl_transfers", pulp.LpMaximize)
    squad = pulp.LpVariable.dicts("s", idx, cat=pulp.LpBinary)
    start = pulp.LpVariable.dicts("x", idx, cat=pulp.LpBinary)
    cap = pulp.LpVariable.dicts("c", idx, cat=pulp.LpBinary)
    hits = pulp.LpVariable("hits", lowBound=0, cat=pulp.LpContinuous)

    # Captain doubles, so a captained starter is counted twice.
    prob += (
        pulp.lpSum(pts[i] * start[i] for i in idx)
        + pulp.lpSum(pts[i] * cap[i] for i in idx)
        + BENCH_WEIGHT * pulp.lpSum(pts[i] * (squad[i] - start[i]) for i in idx)
        - HIT_COST * hits
        - TRANSFER_EPSILON * pulp.lpSum(1 - squad[i] for i in idx if ids[i] in owned)
    )

    prob += pulp.lpSum(squad[i] for i in idx) == SQUAD_SIZE
    prob += pulp.lpSum(start[i] for i in idx) == XI_SIZE
    prob += pulp.lpSum(cap[i] for i in idx) == 1

    for i in idx:
        prob += start[i] <= squad[i]
        prob += cap[i] <= start[i]

    for pos, n in POS_SQUAD.items():
        pos_idx = [i for i in idx if position[i] == pos]
        prob += pulp.lpSum(squad[i] for i in pos_idx) == n, f"squad_{pos}"

    gk = [i for i in idx if position[i] == "GK"]
    prob += pulp.lpSum(start[i] for i in gk) == 1, "xi_GK"
    for pos, (lo, hi) in (("DEF", XI_DEF), ("MID", XI_MID), ("FWD", XI_FWD)):
        pos_idx = [i for i in idx if position[i] == pos]
        prob += pulp.lpSum(start[i] for i in pos_idx) >= lo, f"xi_{pos}_min"
        prob += pulp.lpSum(start[i] for i in pos_idx) <= hi, f"xi_{pos}_max"

    for name in pool["team_name"].unique():
        club_idx = [i for i in idx if club[i] == name]
        prob += pulp.lpSum(squad[i] for i in club_idx) <= MAX_PER_CLUB, f"club_{name}"

    owned_idx = [i for i in idx if ids[i] in owned]
    new_idx = [i for i in idx if ids[i] not in owned]

    # Each player sold frees his selling price; each bought costs list price.
    proceeds = pulp.lpSum(selling_prices[ids[i]] * (1 - squad[i]) for i in owned_idx)
    spend = pulp.lpSum(cost[i] * squad[i] for i in new_idx)
    prob += spend <= bank_tenths + proceeds, "budget"

    n_transfers = pulp.lpSum(1 - squad[i] for i in owned_idx)
    prob += n_transfers <= max_transfers, "max_transfers"
    prob += hits >= n_transfers - free_transfers, "hits_def"

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"transfer ILP failed: {pulp.LpStatus[status]}")

    chosen = {ids[i] for i in idx if pulp.value(squad[i]) > 0.5}
    xi = [ids[i] for i in idx if pulp.value(start[i]) > 0.5]
    captain = next(ids[i] for i in idx if pulp.value(cap[i]) > 0.5)
    vice = max((i for i in xi if i != captain), key=lambda i: _pts_by_id(pool, i))

    out_ids = sorted(owned - chosen)
    in_ids = sorted(chosen - owned)
    sold = sum(selling_prices[i] for i in out_ids)
    bought = sum(int(pool.loc[pool["id"] == i, "now_cost"].iloc[0]) for i in in_ids)

    return TransferPlan(
        out_ids=out_ids,
        in_ids=in_ids,
        squad_ids=sorted(chosen),
        xi_ids=xi,
        captain_id=captain,
        vice_id=vice,
        expected_xi_points=sum(_pts_by_id(pool, i) for i in xi)
        + _pts_by_id(pool, captain),
        hit_cost=HIT_COST * max(0, len(out_ids) - free_transfers),
        bank_after_tenths=bank_tenths + sold - bought,
    )


def _pts_by_id(pool: pd.DataFrame, player_id: int) -> float:
    return float(pool.loc[pool["id"] == player_id, "e_points_final"].iloc[0])


def baseline_plan(board: pd.DataFrame, owned_ids: list[int]) -> TransferPlan:
    """Best XI with no transfers — what doing nothing is worth."""
    return plan_transfers(
        board,
        owned_ids,
        selling_prices={i: 0 for i in owned_ids},
        bank_tenths=0,
        free_transfers=0,
        max_transfers=0,
    )


def plan_with_baseline(
    board: pd.DataFrame,
    owned_ids: list[int],
    *,
    selling_prices: dict[int, int],
    bank_tenths: int = 0,
    free_transfers: int = 1,
    max_transfers: int = 2,
) -> TransferPlan:
    """`plan_transfers` with `expected_gain` measured against doing nothing."""
    base = baseline_plan(board, owned_ids)
    plan = plan_transfers(
        board,
        owned_ids,
        selling_prices=selling_prices,
        bank_tenths=bank_tenths,
        free_transfers=free_transfers,
        max_transfers=max_transfers,
    )
    plan.baseline_xi_points = base.expected_xi_points
    if plan.expected_gain <= 0 and plan.out_ids:
        plan.notes.append(
            "best transfer does not beat holding after hits; roll the transfer"
        )
    return plan


def sanity_check(plan: TransferPlan, selling_prices: dict[int, int]) -> list[str]:
    """Hard invariants worth failing a live run over."""
    errors: list[str] = []
    if len(plan.squad_ids) != SQUAD_SIZE:
        errors.append(f"squad is {len(plan.squad_ids)}, expected {SQUAD_SIZE}")
    if len(plan.xi_ids) != XI_SIZE:
        errors.append(f"XI is {len(plan.xi_ids)}, expected {XI_SIZE}")
    if plan.bank_after_tenths < 0:
        errors.append(f"bank would go negative: {plan.bank_after_tenths}")
    if plan.captain_id not in plan.xi_ids:
        errors.append("captain is not in the XI")
    if plan.vice_id == plan.captain_id:
        errors.append("vice-captain is the captain")
    if len(plan.out_ids) != len(plan.in_ids):
        errors.append("transfers in and out are unbalanced")
    if set(plan.out_ids) & set(plan.squad_ids):
        errors.append("a player is both sold and retained")
    unpriced = [i for i in plan.out_ids if i not in selling_prices]
    if unpriced:
        errors.append(f"sold players without a selling price: {unpriced}")
    return errors
