"""Render the GW1 pitch-board HTML from shipped artifacts (T wow)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.wow import build_wow_payload, write_wow  # noqa: E402

DEFAULT_PREDS = ROOT / "outputs" / "predictions" / "gw1_2026-27.csv"
DEFAULT_SQUAD = ROOT / "outputs" / "squad_gw1.md"
DEFAULT_METRICS = ROOT / "outputs" / "models" / "val_metrics.json"
DEFAULT_OUT = ROOT / "docs" / "wow" / "gw1_pitch.html"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="GW1 pitch board from shipped squad + preds")
    p.add_argument(
        "--preds",
        type=Path,
        default=DEFAULT_PREDS,
        help=f"predictions CSV (default: {DEFAULT_PREDS})",
    )
    p.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD,
        help=f"squad markdown (default: {DEFAULT_SQUAD})",
    )
    p.add_argument(
        "--metrics",
        type=Path,
        default=DEFAULT_METRICS,
        help=f"val metrics JSON (default: {DEFAULT_METRICS})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output HTML (default: {DEFAULT_OUT})",
    )
    args = p.parse_args(argv)

    for label, path in (
        ("predictions", args.preds),
        ("squad", args.squad),
        ("metrics", args.metrics),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")

    payload = build_wow_payload(args.preds, args.squad, args.metrics)
    out = write_wow(args.preds, args.squad, args.metrics, args.out)
    print(
        f"wrote {out} captain={payload['captain']} "
        f"cost=£{payload['cost_m']:.1f}m mae_decomposed={payload['mae_decomposed']}"
    )


if __name__ == "__main__":
    main()
