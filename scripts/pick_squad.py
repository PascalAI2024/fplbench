"""Pick a legal 15-man FPL squad from a predictions CSV (T22)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.squad import (  # noqa: E402
    format_squad_md,
    pick_squad_from_csv,
    result_to_dict,
    verify_squad,
)

DEFAULT_PREDS = ROOT / "outputs" / "predictions" / "gw1_2026-27.csv"
DEFAULT_OUT = ROOT / "outputs" / "squad_gw1.md"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="ILP 15-man FPL squad from predictions CSV")
    p.add_argument(
        "--preds",
        type=Path,
        default=DEFAULT_PREDS,
        help=f"predictions CSV (default: {DEFAULT_PREDS})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output markdown (default: {DEFAULT_OUT})",
    )
    p.add_argument(
        "--event-label",
        default="GW1 2026/27",
        help="label for the markdown title",
    )
    args = p.parse_args(argv)

    if not args.preds.is_file():
        raise SystemExit(f"predictions not found: {args.preds}")

    result = pick_squad_from_csv(args.preds)
    errors = verify_squad(result)
    if errors:
        raise SystemExit("illegal squad: " + "; ".join(errors))

    md = format_squad_md(result, event_label=args.event_label)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")

    info = result_to_dict(result)
    print(f"wrote {args.out}")
    print(f"captain={info['captain']} cost=£{info['cost_m']:.1f}m "
          f"e_points={info['e_points_final']:.3f}")
    print("XI:", ", ".join(info["xi"]))
    print("Bench:", ", ".join(info["bench"]))
    print("15:", ", ".join(info["names"]))


if __name__ == "__main__":
    main()
