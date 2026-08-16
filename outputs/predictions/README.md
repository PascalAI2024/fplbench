# Predictions

## `gw1_2026-27.csv`

Live 2026/27 board. Ranked by `e_points_final = pred_points + 2 * pred_defcon`.

## `val_2025-26.csv`

Per-player validation predictions for 2025-26.

**DefCon in-sample caveat:** `pred_defcon` on **GW ≤ 28** is in-sample — the
classifier was trained on those rows. Holdout DefCon metrics use **GW > 28** only.
