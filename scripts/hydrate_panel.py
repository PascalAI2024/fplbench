"""Rebuild data/processed/panel.parquet from the published HF dataset.

The panel is gitignored, so a fresh CI runner has no historical data. The
public dataset x0me/fplbench holds the exact same rows split by season
(train = 2021-22..2024-25, validation = 2025-26; see fplbench/export_hf.py —
row filters only, all columns preserved), so concatenating the two splits
reconstructs the panel byte-for-byte in content.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.paths import PROCESSED

HF_BASE = "https://huggingface.co/datasets/x0me/fplbench/resolve/main"
SPLITS = ("train.parquet", "validation.parquet")
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    frames = []
    for name in SPLITS:
        dest = PROCESSED / f"hf_{name}"
        r = requests.get(f"{HF_BASE}/{name}", headers=HEADERS, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
        frames.append(pd.read_parquet(dest))
        print(f"{name}: {len(frames[-1]):,} rows")
    panel = pd.concat(frames, ignore_index=True)
    out = PROCESSED / "panel.parquet"
    panel.to_parquet(out, index=False)
    seasons = sorted(panel["season"].unique())
    print(f"panel.parquet: {len(panel):,} rows, seasons={seasons}")
    if len(panel) == 0 or "2025-26" not in seasons:
        raise SystemExit("hydrated panel is empty or missing the 2025-26 season")


if __name__ == "__main__":
    main()
