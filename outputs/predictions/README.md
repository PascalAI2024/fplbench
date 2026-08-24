# Predictions

## `gw{N}_2026-27.csv`

Live 2026/27 boards, one per gameweek (named from the GW the fixtures target).
Ranked by `e_points_final = pred_points_decomposed + 2 * pred_defcon`, where
`pred_points_decomposed` is minutes-gated. The operating contract commits each
board before its deadline and grades that artifact after official verification.
The freeze guard now rejects post-deadline overwrites of an existing board.

GW1 provenance is explicit: the current file is byte-identical to the original
pre-deadline commit (`4b970a8`), after a post-deadline overwrite was preserved
in Git history and explicitly restored in `2981de1`.

## `val_2025-26.csv`

Per-player validation predictions for 2025-26.

**DefCon in-sample caveat:** `pred_defcon` on **GW ≤ 28** is in-sample — the
classifier was trained on those rows. Holdout DefCon metrics use **GW > 28** only.
