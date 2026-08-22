# Predictions

## `gw{N}_2026-27.csv`

Live 2026/27 boards, one per gameweek (named from the GW the fixtures target).
Ranked by `e_points_final = pred_points + 2 * pred_defcon`. Committed before
each GW's deadline and never rewritten afterwards — post-GW scoring grades
exactly what was committed pre-deadline.

## `val_2025-26.csv`

Per-player validation predictions for 2025-26.

**DefCon in-sample caveat:** `pred_defcon` on **GW ≤ 28** is in-sample — the
classifier was trained on those rows. Holdout DefCon metrics use **GW > 28** only.
