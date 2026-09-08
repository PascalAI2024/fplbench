"""Weekly transfer plan for the live team.

Two modes:

  # preview — public endpoints only, selling prices approximated by now_cost
  python scripts/plan_transfers.py --preds outputs/predictions/gw4_2026-27.csv

  # live — authenticated my-team payload supplies real selling prices,
  # bank, and free-transfer count
  python scripts/plan_transfers.py --preds <board.csv> --my-team my_team.json

The live weekly run must use --my-team. Selling price is purchase price plus
half the rise, so `now_cost` overstates the budget for any player who has
gone up, and a plan built on it can be unaffordable when submitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.transfers import plan_with_baseline, sanity_check

API = "https://fantasy.premierleague.com/api"
DEFAULT_ENTRY = 4770634


def _get_json(url: str) -> dict:
    from scripts.track_team import _get_json as retrying_get

    return retrying_get(url)


def owned_from_public(entry_id: int, event: int) -> list[int]:
    """The 15 from a finished gameweek's public picks.

    Valid only while no transfer has been made since; the live run should read
    the authenticated squad instead.
    """
    picks = _get_json(f"{API}/entry/{entry_id}/event/{event}/picks/")
    return [int(p["element"]) for p in picks["picks"]]


def current_event(entry_id: int) -> int:
    return int(_get_json(f"{API}/entry/{entry_id}/")["current_event"])


def from_my_team(payload: dict) -> tuple[list[int], dict[int, int], int, int]:
    """(owned, selling_prices, bank_tenths, free_transfers) from my-team JSON."""
    picks = payload["picks"]
    owned = [int(p["element"]) for p in picks]
    selling = {int(p["element"]): int(p["selling_price"]) for p in picks}
    bank = int(payload.get("transfers", {}).get("bank", 0))
    free = int(payload.get("transfers", {}).get("limit") or 1)
    return owned, selling, bank, free


def format_plan(plan, board: pd.DataFrame, *, approximate: bool) -> str:
    names = board.set_index("id")["web_name"].to_dict()
    cost = board.set_index("id")["now_cost"].to_dict()
    team = board.set_index("id")["team_name"].to_dict()
    pts = board.set_index("id")["e_points_final"].to_dict()
    pos = board.set_index("id")["position"].to_dict()

    lines: list[str] = []
    if plan.out_ids:
        lines.append(f"TRANSFERS ({plan.n_transfers}, hit {plan.hit_cost:.0f} pts)")
        for out_id, in_id in zip(plan.out_ids, plan.in_ids, strict=True):
            lines.append(
                f"  OUT {names.get(out_id, out_id):<16} "
                f"-> IN {names.get(in_id, in_id):<16} "
                f"£{cost.get(in_id, 0) / 10:.1f}m {team.get(in_id, '')} "
                f"(e={pts.get(in_id, 0):.2f})"
            )
    else:
        lines.append("TRANSFERS: none — rolling")

    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    xi = sorted(plan.xi_ids, key=lambda i: (order.get(pos.get(i), 9), -pts.get(i, 0)))
    lines.append("")
    lines.append("XI")
    for i in xi:
        tag = ""
        if i == plan.captain_id:
            tag = " (C)"
        elif i == plan.vice_id:
            tag = " (V)"
        lines.append(
            f"  {pos.get(i, '?'):<4}{names.get(i, i):<16}{pts.get(i, 0):>6.2f}{tag}"
        )
    bench = [i for i in plan.squad_ids if i not in set(plan.xi_ids)]
    bench.sort(key=lambda i: -pts.get(i, 0))
    lines.append(
        "  BENCH: " + ", ".join(f"{names.get(i, i)} {pts.get(i, 0):.2f}" for i in bench)
    )

    lines.append("")
    lines.append(f"expected XI  : {plan.expected_xi_points:.3f} (captain doubled)")
    lines.append(f"hold instead : {plan.baseline_xi_points:.3f}")
    lines.append(f"NET GAIN     : {plan.expected_gain:+.3f} after hits")
    lines.append(f"bank after   : £{plan.bank_after_tenths / 10:.1f}m")
    for note in plan.notes:
        lines.append(f"note: {note}")
    if approximate:
        lines.append(
            "WARNING: selling prices approximated from now_cost. "
            "Do not submit this plan — rerun with --my-team."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Weekly FPL transfer plan")
    p.add_argument("--preds", type=Path, required=True, help="predictions CSV")
    p.add_argument("--entry", type=int, default=DEFAULT_ENTRY)
    p.add_argument(
        "--my-team",
        type=Path,
        help="authenticated /api/my-team/<id>/ JSON (required for a live run)",
    )
    p.add_argument(
        "--max-transfers",
        type=int,
        default=None,
        help="default: the free-transfer allowance, so a plan never costs points",
    )
    p.add_argument(
        "--free-transfers",
        type=int,
        default=1,
        help="ignored when --my-team supplies the real allowance",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = p.parse_args(argv)

    if not args.preds.is_file():
        raise SystemExit(f"predictions not found: {args.preds}")
    board = pd.read_csv(args.preds)

    if args.my_team:
        payload = json.loads(args.my_team.read_text(encoding="utf-8"))
        owned, selling, bank, free = from_my_team(payload)
        approximate = False
    else:
        owned = owned_from_public(args.entry, current_event(args.entry))
        cost = board.set_index("id")["now_cost"].to_dict()
        selling = {i: int(cost[i]) for i in owned if i in cost}
        bank, free = 0, args.free_transfers
        approximate = True

    # Free transfers cost nothing, so capping below the allowance just wastes
    # them; capping above it invites a hit on the first ever unattended run.
    max_transfers = args.max_transfers if args.max_transfers is not None else free
    plan = plan_with_baseline(
        board,
        owned,
        selling_prices=selling,
        bank_tenths=bank,
        free_transfers=free,
        max_transfers=max_transfers,
    )
    errors = sanity_check(plan, selling)
    if errors:
        print("PLAN REJECTED:", "; ".join(errors), file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "out": plan.out_ids,
                    "in": plan.in_ids,
                    "squad": plan.squad_ids,
                    "xi": plan.xi_ids,
                    "captain": plan.captain_id,
                    "vice": plan.vice_id,
                    "expected_xi_points": round(plan.expected_xi_points, 4),
                    "baseline_xi_points": round(plan.baseline_xi_points, 4),
                    "expected_gain": round(plan.expected_gain, 4),
                    "hit_cost": plan.hit_cost,
                    "bank_after_tenths": plan.bank_after_tenths,
                    "approximate_selling_prices": approximate,
                    "notes": plan.notes,
                },
                indent=2,
            )
        )
    else:
        print(format_plan(plan, board, approximate=approximate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
