"""Pre-deadline live ingest + predict (CI / cron entrypoint).

Usage:
  python scripts/predict_live.py
  python scripts/predict_live.py --help

Equivalent one-liner:
  python -c "from fplbench.ingest import download_live; from fplbench.predict import predict_next_gw; download_live(); predict_next_gw()"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.ingest import download_live
from fplbench.paths import PREDS
from fplbench.predict import predict_next_gw


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Download live FPL snapshot and write outputs/predictions/*.csv"
    )
    p.parse_args(argv)

    print("download_live …")
    download_live()
    print("predict_next_gw …")
    preds = predict_next_gw()
    written = sorted(PREDS.glob("*.csv"))
    print(f"rows={len(preds):,} files={[str(x.relative_to(ROOT)) for x in written]}")
    print(preds.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
