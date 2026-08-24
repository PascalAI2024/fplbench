---
language:
  - en
pretty_name: "fplbench — Leakage-Safe Fantasy Premier League Panel"
license: other
source_datasets:
  - extended
task_categories:
  - tabular-regression
  - tabular-classification
tags:
  - football
  - fantasy-premier-league
  - sports
  - time-series
  - tabular
  - datasets
  - pandas
  - polars
  - sports-analytics
size_categories:
  - 100K<n<1M
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.parquet
      - split: validation
        path: validation.parquet
---

<p align="center">
  <a href="https://huggingface.co/spaces/x0me/fplbench-board">
    <img src="https://raw.githubusercontent.com/PascalAI2024/fplbench/main/docs/img/social.png" alt="Dated preview of the fplbench Fantasy Premier League benchmark board" width="960">
  </a>
</p>

<p align="center"><sub>Dated board preview. Open the board for current provisional values.</sub></p>

# fplbench

**Leakage-aware Fantasy Premier League player-fixture data, reproducible
LightGBM forecasts, and a public post-gameweek scoring record.**

[Load the dataset](#load-it-in-one-line) ·
[Open the live board](https://huggingface.co/spaces/x0me/fplbench-board) ·
[Inspect frozen forecasts](https://github.com/PascalAI2024/fplbench/tree/main/outputs/predictions) ·
[Read the results](https://github.com/PascalAI2024/fplbench/blob/main/RESULTS.md) ·
[Inspect the code](https://github.com/PascalAI2024/fplbench) ·
[View the official team](https://fantasy.premierleague.com/entry/4770634/history)

## Load it in one line

```bash
pip install -U datasets
```

```python
from datasets import load_dataset

ds = load_dataset("x0me/fplbench")
train = ds["train"]
validation = ds["validation"]
```

## Why this dataset exists

Fantasy-football models are unusually easy to evaluate badly. A same-gameweek
statistic can leak the result, a lineup can be revised after the deadline, and
a single holdout number can quietly become a marketing claim.

fplbench publishes a stricter record:

- **deadline-safe features** — form statistics are shifted within player and
  season before training;
- **frozen live forecasts** — the committed pre-deadline file is the artifact
  scored later;
- **minutes + points + DefCon** — separate heads model whether a player plays,
  expected points, and the current Defensive Contribution rule;
- **public accountability** — the model's team, weekly score, code, and
  limitations remain linked.

<!-- LIVE_SCOREBOARD:START -->
## Live record — generated when the card is published

The publishing workflow replaces this block with the current model and team
record from official FPL data.
<!-- LIVE_SCOREBOARD:END -->

The repository contains two Parquet splits:

| Split | Rows | Seasons | Intended use |
| --- | ---: | --- | --- |
| `train` | 109,282 | 2021-22 through 2024-25 | Fit minutes, points, and supporting heads |
| `validation` | 29,747 | 2025-26 | Held-out season and first full DefCon season |

The export contains **139,029 rows and 165 columns**. Live 2026-27 data is not
a third split; it is fetched and scored by the public weekly workflow.

## Row and target contract

Each row represents one player-fixture observation within an FPL gameweek.
Double gameweeks therefore contain two rows for a player. Important targets
include:

- `minutes`
- `total_points`
- `defcon_hit` — whether the official positional threshold was met

Model features use lagged or rolling forms such as `_l1`, `_r3`, and `_r5`,
plus a small set of static priors and fixture context. The exact bundled model
feature list is published in `features.txt`.

## Leakage contract

**Never use unshifted `xP` / `xp_scraped` as a model feature.**

The vaastav `xP` column reflects FPL's `ep_this` after the gameweek. It is kept
only as a contaminated comparator. Every performance feature used for fitting
is shifted inside `(season, player_code)`. Both fixtures in a double gameweek
receive the same lag values that were known before the first fixture; fixture
two cannot observe fixture one's result. `manifest.json` records the fixture
key, schema, row counts, and file hashes.

The live score grades the committed `e_points_final` forecast:

```text
pred_points_decomposed = pred_points * clip(pred_minutes / 90, 0, 1)
e_points_final         = pred_points_decomposed + 2 * pred_defcon
```

## Reproducible benchmark evidence

The corrected 2025-26 common-mask comparison contains 29,417 rows. These are
first-party historical holdout results, not independent validation:

| Measure | MAE | Boundary |
| --- | ---: | --- |
| Published base-points score (`pred_points_decomposed`) | **0.8764** | Held-out season |
| Rolling last-five baseline | 1.0534 | Same finite-row mask |
| Scraped post-match `xP` comparator | 1.0683 | Comparator only; never a feature |

DefCon holdout interpretation is restricted to gameweeks after the classifier
training window. The full evidence, masks, charts, and current caveats are in
the [GitHub repository](https://github.com/PascalAI2024/fplbench).

## Known limitations

- GW1 is a cold start with no current-season form.
- The DefCon classifier currently has one historical rules season.
- Historical double-gameweek lags are protected; live double-gameweek
  prediction still fails closed with `NotImplementedError`.
- TabFM appears only as a research comparison under its non-commercial
  license. The public operating path uses LightGBM.
- Public live results are first-party experimental evidence, not independent
  validation or betting advice.

GW1 provenance is explicit: the current file is byte-identical to the
[original pre-deadline artifact](https://github.com/PascalAI2024/fplbench/commit/4b970a812deb997d32e48f9e48d9520b6a5ab901).
Git history also preserves a post-deadline overwrite and the
[explicit restoration](https://github.com/PascalAI2024/fplbench/commit/2981de109ce7b57f8ccc75ed1c011eb16886fc3a).

## Sources and use

- Historical panel: [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
- Live fixtures, prices, availability, expected points, and actuals: official
  FPL API
- Scoring rules and underlying player data remain owned by the Premier League
  and its data providers.

This export is for research and personal modelling. It is not an official
Premier League product.

## Citation

Please cite the upstream historical source when using the panel:

> Vaastav Anand, *FPL Historical Dataset*,
> https://github.com/vaastav/Fantasy-Premier-League

For the benchmark implementation and live record, link
[`PascalAI2024/fplbench`](https://github.com/PascalAI2024/fplbench).
