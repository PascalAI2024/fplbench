"""Legal 15-man FPL squad selection via ILP (PuLP)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pulp


POS_SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
SQUAD_SIZE = 15
BUDGET_TENTHS = 1000  # £100.0m
MAX_PER_CLUB = 3

# Valid FPL formation bands for a starting XI (plus exactly 1 GK).
XI_DEF = (3, 5)
XI_MID = (2, 5)
XI_FWD = (1, 3)
XI_SIZE = 11


def eligible_mask(df: pd.DataFrame) -> pd.Series:
    """status == 'a' or chance_of_playing_next_round is not 0."""
    status_ok = df["status"].astype(str) == "a"
    chance = df["chance_of_playing_next_round"]
    # NaN != 0 is True in pandas — available players with blank chance stay in.
    chance_ok = chance != 0
    return status_ok | chance_ok


def filter_eligible(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[eligible_mask(df)].copy()
    out = out.dropna(subset=["e_points_final", "now_cost", "position", "team_name"])
    out["now_cost"] = out["now_cost"].astype(int)
    out["e_points_final"] = out["e_points_final"].astype(float)
    return out.reset_index(drop=True)


@dataclass
class SquadResult:
    squad: pd.DataFrame
    xi: pd.DataFrame
    bench: pd.DataFrame
    captain_name: str
    captain_points: float
    total_cost_tenths: int
    total_e_points: float

    @property
    def total_cost_m(self) -> float:
        return self.total_cost_tenths / 10.0


def pick_squad(df: pd.DataFrame) -> SquadResult:
    """
    Maximize sum(e_points_final) for a legal 15, then pick a legal XI
    among those 15 maximizing e_points_final. Captain = max e_points in the 15.
    """
    pool = filter_eligible(df)
    if pool.empty:
        raise ValueError("no eligible players after availability filter")

    for pos, n in POS_SQUAD.items():
        if int((pool["position"] == pos).sum()) < n:
            raise ValueError(f"not enough eligible {pos}: need {n}")

    idx = list(pool.index)
    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("p", idx, cat=pulp.LpBinary)

    prob += pulp.lpSum(pool.loc[i, "e_points_final"] * x[i] for i in idx)
    prob += pulp.lpSum(x[i] for i in idx) == SQUAD_SIZE
    prob += pulp.lpSum(pool.loc[i, "now_cost"] * x[i] for i in idx) <= BUDGET_TENTHS

    for pos, n in POS_SQUAD.items():
        pos_idx = [i for i in idx if pool.loc[i, "position"] == pos]
        prob += pulp.lpSum(x[i] for i in pos_idx) == n, f"pos_{pos}"

    for club in pool["team_name"].unique():
        club_idx = [i for i in idx if pool.loc[i, "team_name"] == club]
        prob += pulp.lpSum(x[i] for i in club_idx) <= MAX_PER_CLUB, f"club_{club}"

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"squad ILP failed: {pulp.LpStatus[status]}")

    chosen = [i for i in idx if pulp.value(x[i]) > 0.5]
    squad = _sort_by_pos(pool.loc[chosen]).reset_index(drop=True)

    xi = pick_xi(squad)
    xi_ids = set(xi["id"].tolist()) if "id" in xi.columns else set(xi.index)
    if "id" in squad.columns:
        bench = squad.loc[~squad["id"].isin(xi_ids)].copy()
    else:
        bench = squad.loc[~squad.index.isin(xi.index)].copy()

    # Bench order: GK first, then by e_points_final desc (typical FPL display).
    bench = _order_bench(bench)

    cap_row = squad.loc[squad["e_points_final"].idxmax()]
    total_cost = int(squad["now_cost"].sum())
    total_pts = float(squad["e_points_final"].sum())

    return SquadResult(
        squad=squad,
        xi=xi.reset_index(drop=True),
        bench=bench.reset_index(drop=True),
        captain_name=str(cap_row["web_name"]),
        captain_points=float(cap_row["e_points_final"]),
        total_cost_tenths=total_cost,
        total_e_points=total_pts,
    )


def pick_xi(squad: pd.DataFrame) -> pd.DataFrame:
    """Best legal XI from a 15-man squad (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD)."""
    idx = list(squad.index)
    prob = pulp.LpProblem("fpl_xi", pulp.LpMaximize)
    y = pulp.LpVariable.dicts("xi", idx, cat=pulp.LpBinary)

    prob += pulp.lpSum(squad.loc[i, "e_points_final"] * y[i] for i in idx)
    prob += pulp.lpSum(y[i] for i in idx) == XI_SIZE

    gks = [i for i in idx if squad.loc[i, "position"] == "GK"]
    defs = [i for i in idx if squad.loc[i, "position"] == "DEF"]
    mids = [i for i in idx if squad.loc[i, "position"] == "MID"]
    fwds = [i for i in idx if squad.loc[i, "position"] == "FWD"]

    prob += pulp.lpSum(y[i] for i in gks) == 1
    prob += pulp.lpSum(y[i] for i in defs) >= XI_DEF[0]
    prob += pulp.lpSum(y[i] for i in defs) <= XI_DEF[1]
    prob += pulp.lpSum(y[i] for i in mids) >= XI_MID[0]
    prob += pulp.lpSum(y[i] for i in mids) <= XI_MID[1]
    prob += pulp.lpSum(y[i] for i in fwds) >= XI_FWD[0]
    prob += pulp.lpSum(y[i] for i in fwds) <= XI_FWD[1]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"XI ILP failed: {pulp.LpStatus[status]}")

    chosen = [i for i in idx if pulp.value(y[i]) > 0.5]
    return _sort_by_pos(squad.loc[chosen])


def _sort_by_pos(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_pos_ord"] = out["position"].map(POS_ORDER)
    out = out.sort_values(["_pos_ord", "e_points_final"], ascending=[True, False])
    return out.drop(columns=["_pos_ord"])


def _order_bench(bench: pd.DataFrame) -> pd.DataFrame:
    """GK first on bench, then outfield by descending e_points_final."""
    is_gk = bench["position"] == "GK"
    gk = bench.loc[is_gk]
    out = bench.loc[~is_gk].sort_values("e_points_final", ascending=False)
    return pd.concat([gk, out], ignore_index=True)


def verify_squad(result: SquadResult) -> list[str]:
    """Return list of constraint violations (empty if legal)."""
    errors: list[str] = []
    s = result.squad
    if len(s) != SQUAD_SIZE:
        errors.append(f"squad size {len(s)} != {SQUAD_SIZE}")
    for pos, n in POS_SQUAD.items():
        c = int((s["position"] == pos).sum())
        if c != n:
            errors.append(f"{pos} count {c} != {n}")
    if result.total_cost_tenths > BUDGET_TENTHS:
        errors.append(f"cost {result.total_cost_tenths} > {BUDGET_TENTHS}")
    club_counts = s["team_name"].value_counts()
    over = club_counts[club_counts > MAX_PER_CLUB]
    if len(over):
        errors.append(f"club limit exceeded: {over.to_dict()}")
    if len(result.xi) != XI_SIZE:
        errors.append(f"XI size {len(result.xi)} != {XI_SIZE}")
    if int((result.xi["position"] == "GK").sum()) != 1:
        errors.append("XI must have exactly 1 GK")
    return errors


def _captain_points_note(result: SquadResult) -> str:
    note = f"e_points_final={result.captain_points:.3f}"
    if "e_points_p90" not in result.squad.columns:
        return note
    cap = result.squad.loc[result.squad["web_name"] == result.captain_name]
    if cap.empty:
        return note
    p90 = pd.to_numeric(cap.iloc[0]["e_points_p90"], errors="coerce")
    if pd.isna(p90):
        return note
    return f"{note}, e_points_p90={float(p90):.3f}"


def format_squad_md(result: SquadResult, *, event_label: str = "GW1 2026/27") -> str:
    """Render squad markdown report."""
    lines: list[str] = [
        f"# Squad — {event_label}",
        "",
        f"**Total cost:** £{result.total_cost_m:.1f}m "
        f"({result.total_cost_tenths} tenths / 1000)",
        f"**Total e_points_final (15):** {result.total_e_points:.3f}",
        f"**Captain:** {result.captain_name} "
        f"({_captain_points_note(result)})",
        f"**XI e_points_final:** {result.xi['e_points_final'].sum():.3f}",
        "",
        "Chips unused (no Bench Boost / Free Hit / Triple Captain / Wildcard).",
        "",
        "## Starting XI",
        "",
        "| Pos | Player | Club | Cost | e_points_final |",
        "|-----|--------|------|-----:|---------------:|",
    ]
    for _, r in result.xi.iterrows():
        cap = " (C)" if r["web_name"] == result.captain_name else ""
        lines.append(
            f"| {r['position']} | {r['web_name']}{cap} | {r['team_name']} | "
            f"£{r['now_cost'] / 10:.1f}m | {r['e_points_final']:.3f} |"
        )

    lines += [
        "",
        "## Bench",
        "",
        "| Pos | Player | Club | Cost | e_points_final |",
        "|-----|--------|------|-----:|---------------:|",
    ]
    for _, r in result.bench.iterrows():
        lines.append(
            f"| {r['position']} | {r['web_name']} | {r['team_name']} | "
            f"£{r['now_cost'] / 10:.1f}m | {r['e_points_final']:.3f} |"
        )

    lines += [
        "",
        "## Full 15 (constraint check)",
        "",
        f"- Positions: "
        + ", ".join(
            f"{pos}={int((result.squad['position'] == pos).sum())}"
            for pos in ("GK", "DEF", "MID", "FWD")
        ),
        f"- Cost tenths: {result.total_cost_tenths} ≤ {BUDGET_TENTHS}",
        f"- Max per club: {int(result.squad['team_name'].value_counts().max())} ≤ {MAX_PER_CLUB}",
        "",
        "### Club counts",
        "",
    ]
    for club, n in result.squad["team_name"].value_counts().sort_values(ascending=False).items():
        lines.append(f"- {club}: {int(n)}")

    lines.append("")
    return "\n".join(lines)


def load_predictions(path: Path | str) -> pd.DataFrame:
    return pd.read_csv(path)


def pick_squad_from_csv(path: Path | str) -> SquadResult:
    return pick_squad(load_predictions(path))


def squad_summary_lines(result: SquadResult) -> list[str]:
    """Short bullet list of the 15 for README."""
    names = []
    for _, r in _sort_by_pos(result.squad).iterrows():
        names.append(
            f"{r['web_name']} ({r['position']}, {r['team_name']}, "
            f"£{r['now_cost'] / 10:.1f}m)"
        )
    return names


def result_to_dict(result: SquadResult) -> dict[str, Any]:
    return {
        "names": result.squad["web_name"].tolist(),
        "captain": result.captain_name,
        "cost_m": result.total_cost_m,
        "cost_tenths": result.total_cost_tenths,
        "e_points_final": result.total_e_points,
        "xi": result.xi["web_name"].tolist(),
        "bench": result.bench["web_name"].tolist(),
    }
