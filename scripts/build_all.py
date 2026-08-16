"""Download → panel → train → live predict → HF export."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.export_hf import export_hf
from fplbench.ingest import download_live, download_vaastav
from fplbench.panel import build_panel, save_panel
from fplbench.paths import PROCESSED
from fplbench.predict import predict_next_gw
from fplbench.train import train


def main() -> None:
    print("1/5 download vaastav + live API")
    download_vaastav()
    download_live()
    print("2/5 build panel")
    panel = build_panel()
    save_panel(panel)
    print(f"   rows={len(panel):,} seasons={sorted(panel['season'].unique())}")
    print("3/5 train")
    metrics = train()
    print(json.dumps(metrics, indent=2))
    print("4/5 predict GW1")
    preds = predict_next_gw()
    print(preds.head(15).to_string(index=False))
    print("5/5 export HF folder")
    export_hf()
    print(f"done → {PROCESSED}")


if __name__ == "__main__":
    main()
