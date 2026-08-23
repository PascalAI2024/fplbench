# Live scoring results

Model MAE vs FPL `ep_next` after each finished gameweek (common finite mask).

The first data row lands after GW1. Until then this table has no scores — `scripts/score_gw.py` writes them from official FPL actuals. No invented numbers.

| GW | n_common | mae_model | mae_ep_next | n_played | mae_model_played | mae_ep_next_played |
|---|---|---|---|---|---|---|

## Team — The Leakage-Safe XI (entry 4770634)

The model's own squad in the official FPL game — [live team page](https://fantasy.premierleague.com/entry/4770634/history). Rewritten from the official API on every post-GW run; the current gameweek is marked (live) until it finishes.

| GW | pts | GW avg | vs avg | captain | overall rank | total pts |
|---|---|---|---|---|---|---|
| 1 (live) | 51 | 36 | +15 | Haaland | 793,389 | 51 |
