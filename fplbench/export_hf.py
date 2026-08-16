"""Write a Hugging Face-ready export with a dataset card."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from fplbench.panel import feature_columns
from fplbench.paths import HF_EXPORT, PROCESSED

CARD = """---
language:
  - en
pretty_name: fplbench player-gameweek panel
license: other
task_categories:
  - tabular-regression
  - tabular-classification
tags:
  - football
  - fantasy-premier-league
  - sports
  - time-series
size_categories:
  - 100K<n<1M
---

# fplbench — leakage-safe Fantasy Premier League panel

One row per player per Premier League gameweek. Built so you can train a model
without accidentally using the same gameweek's result as a feature.

This folder is a **local** Hugging Face-style export (not published on the Hub yet).

## Load with `datasets`

Path-based load from a clone of this repo (adjust the root if needed):

```python
from datasets import load_dataset

ds = load_dataset(
    "parquet",
    data_files={
        "train": "data/processed/hf/train.parquet",
        "validation": "data/processed/hf/validation.parquet",
    },
)
# ds["train"], ds["validation"]
```

From this directory:

```python
from datasets import load_dataset

ds = load_dataset(
    "parquet",
    data_files={"train": "train.parquet", "validation": "validation.parquet"},
)
```

Feature names used by the bundled LightGBM heads are listed in `features.txt`
(same set as `data/processed/feature_columns.txt`).

## Train / validation / live seasons

| split | seasons | in this export? | intended use |
|-------|---------|-----------------|--------------|
| train | 2021-22, 2022-23, 2023-24, 2024-25 | yes → `train.parquet` | fit minutes + points heads |
| validation | 2025-26 | yes → `validation.parquet` | held-out season; first full DefCon year |
| live | 2026-27 | **no** | scored weekly from the official FPL API |

Live season rows are never written here. Use the live predictor / API ingest instead.

## Leakage rule

**Do not use unshifted `xP` / `xp_scraped` as a feature.**

- Every performance statistic used as a **feature** is shifted by one gameweek
  inside `(season, player_code)`.
- Columns ending `_l1`, `_r3`, `_r5` (plus a small set of static priors / context
  columns) are the only form features.
- `xp_scraped` is the vaastav `xP` column, copied from FPL `ep_this` **after**
  the gameweek. Treat it as a contaminated baseline label/comparator only —
  never as a model input.

See [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League).

## Targets

- `minutes`
- `total_points`
- `defcon_hit` — 1 if the official 2025/26–2026/27 threshold is met
  (DEF: CBIT ≥ 10; MID/FWD: CBIT + recoveries ≥ 12; GK: 0)

## Caveats

### In-sample `pred_defcon` (GW ≤ 28)

The DefCon classifier is fit on 2025-26 **GW ≤ 28**. When you look at
validation predictions (`outputs/predictions/val_2025-26.csv`), `pred_defcon`
on those early gameweeks is **in-sample** — the model saw those rows during
training. **Holdout DefCon metrics must use GW > 28 only.**

### Double gameweeks (DGW)

The live predictor raises `NotImplementedError` when a team has two or more
unfinished fixtures in the same event (double gameweek). DGW is not supported
yet; single-fixture events only.

## Sources

- Historical rows: [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League) (cite if you use this)
- Labels follow official FPL scoring. Underlying player data is owned by the Premier League / its data providers.
- This export is for research and personal modelling. It is not an official Premier League product.

## Recommended citation

Vaastav Anand, FPL Historical Dataset, https://github.com/vaastav/Fantasy-Premier-League
"""


def export_hf(panel_path: Path | None = None) -> Path:
    panel_path = panel_path or (PROCESSED / "panel.parquet")
    df = pd.read_parquet(panel_path)
    HF_EXPORT.mkdir(parents=True, exist_ok=True)
    train = df[df["season"].isin(["2021-22", "2022-23", "2023-24", "2024-25"])]
    val = df[df["season"].eq("2025-26")]
    train.to_parquet(HF_EXPORT / "train.parquet", index=False)
    val.to_parquet(HF_EXPORT / "validation.parquet", index=False)
    (HF_EXPORT / "README.md").write_text(CARD, encoding="utf-8")
    (HF_EXPORT / "features.txt").write_text("\n".join(feature_columns(df)), encoding="utf-8")
    return HF_EXPORT
