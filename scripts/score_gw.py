"""Score a finished GW: join predictions to FPL event-live actuals, update RESULTS.md.

Usage:
  python scripts/score_gw.py --gw 1 --preds outputs/predictions/gw1_2026-27.csv
  python scripts/score_gw.py          # auto: score the latest FINISHED GW's gw*.csv
  python scripts/score_gw.py --help
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.paths import PREDS
from fplbench.score import score_gameweek, upsert_results_md

HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
EVENT_LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"
BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
DEFAULT_RESULTS = ROOT / "RESULTS.md"
_GW_IN_NAME = re.compile(r"gw(\d+)", re.IGNORECASE)


def fetch_bootstrap_events() -> list[dict]:
    r = requests.get(BOOTSTRAP, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json().get("events") or []


def latest_finished_event(events: list[dict]) -> int | None:
    finished = [int(e["id"]) for e in events if e.get("finished")]
    return max(finished) if finished else None


def fetch_event_live(gw: int) -> pd.DataFrame:
    """Fetch element stats for a finished gameweek from the official FPL API."""
    url = EVENT_LIVE.format(gw=int(gw))
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    elements = r.json().get("elements") or []
    rows = []
    for el in elements:
        stats = el.get("stats") or {}
        rows.append(
            {
                "id": el["id"],
                "total_points": stats.get("total_points"),
                "minutes": stats.get("minutes"),
            }
        )
    return pd.DataFrame(rows)


def load_actuals(gw: int, actuals_path: Path | None) -> pd.DataFrame:
    if actuals_path is not None:
        df = pd.read_csv(actuals_path)
        if "id" not in df.columns or "total_points" not in df.columns:
            raise SystemExit("actuals CSV must include id and total_points columns")
        return df
    return fetch_event_live(gw)


def _gw_from_path(path: Path) -> int | None:
    m = _GW_IN_NAME.search(path.name)
    return int(m.group(1)) if m else None


def resolve_gw_and_preds(gw: int | None, preds: Path | None) -> tuple[int, Path]:
    """Resolve GW number and predictions CSV for CLI / cron defaults."""
    if preds is not None:
        path = preds if preds.is_absolute() else ROOT / preds
        if not path.is_file():
            raise SystemExit(f"predictions not found: {path}")
        if gw is not None:
            return int(gw), path
        parsed = _gw_from_path(path)
        if parsed is None:
            raise SystemExit(
                f"--gw required when predictions filename has no gwN: {path.name}"
            )
        return parsed, path

    candidates = sorted(PREDS.glob("gw*.csv"), key=lambda p: p.stat().st_mtime)
    # Prefer non-validation boards (val_*.csv is not gw-prefixed).
    if not candidates:
        raise SystemExit(
            f"no predictions under {PREDS} — pass --preds explicitly"
        )
    if gw is not None:
        match = PREDS / f"gw{int(gw)}_*.csv"
        hits = sorted(PREDS.glob(f"gw{int(gw)}_*.csv"))
        if not hits:
            raise SystemExit(f"no predictions matching {match}")
        return int(gw), hits[-1]

    path = candidates[-1]
    parsed = _gw_from_path(path)
    if parsed is None:
        raise SystemExit(f"could not parse GW from {path.name}; pass --gw")
    return parsed, path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Post-GW model vs ep_next MAE scoring")
    p.add_argument(
        "--gw",
        type=int,
        default=None,
        help="gameweek number (default: parse from --preds or latest gw*.csv)",
    )
    p.add_argument(
        "--preds",
        type=Path,
        default=None,
        help="predictions CSV path (default: latest outputs/predictions/gw*.csv)",
    )
    p.add_argument(
        "--actuals",
        type=Path,
        default=None,
        help="optional actuals CSV (offline); default = FPL event-live API",
    )
    p.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"RESULTS.md path (default: {DEFAULT_RESULTS})",
    )
    args = p.parse_args(argv)

    # Online mode (no --actuals): guard on the official finished flag so a
    # Tuesday run during an unfinished GW is a clean no-op, not a red X.
    events: list[dict] | None = None
    gw_arg = args.gw
    if args.actuals is None:
        events = fetch_bootstrap_events()
        if gw_arg is None and args.preds is None:
            latest = latest_finished_event(events)
            if latest is None:
                print("No finished gameweek yet — skipping scoring")
                return
            gw_arg = latest

    gw, preds_path = resolve_gw_and_preds(gw_arg, args.preds)

    if events is not None:
        ev = next((e for e in events if int(e.get("id", -1)) == int(gw)), None)
        if ev is None:
            raise SystemExit(f"GW {gw} not found in bootstrap events")
        if not ev.get("finished"):
            print(f"GW {gw} not finished — skipping scoring")
            return
    preds = pd.read_csv(preds_path)
    actuals = load_actuals(gw, args.actuals)
    metrics = score_gameweek(preds, actuals)
    upsert_results_md(args.results, gw, metrics)

    print(
        f"GW{gw} n_common={metrics['n_common']} "
        f"mae_model={metrics['mae_model']:.4f} mae_ep_next={metrics['mae_ep_next']:.4f} "
        f"n_played={metrics['n_played']} "
        f"mae_model_played={metrics['mae_model_played']:.4f} "
        f"mae_ep_next_played={metrics['mae_ep_next_played']:.4f}"
    )
    print(f"preds={preds_path}")
    print(f"wrote {args.results}")


if __name__ == "__main__":
    main()
