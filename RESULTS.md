# Live scoring results

Published `e_points_final` MAE vs FPL `ep_next` after each gameweek is both
finished and data-checked (common finite mask). `e_points_final` is the frozen
pre-deadline forecast used to rank the squad: minutes-gated points plus expected
DefCon.

Until an official gameweek is verified, this table has no scores.
`scripts/score_gw.py` writes them from official FPL actuals. No invented numbers.

| GW | n_common | mae_model | mae_ep_next | n_played | mae_model_played | mae_ep_next_played |
|---|---|---|---|---|---|---|

## Team — The Leakage-Safe XI (entry 4770634)

The model's own squad in the official FPL game — [live team page](https://fantasy.premierleague.com/entry/4770634/history). Rewritten from the official API on every post-GW run. Rows remain marked live or review until FPL sets both `finished` and `data_checked`.

| GW | pts | GW avg | vs avg | captain | overall rank | total pts |
|---|---|---|---|---|---|---|
| 1 (live) | 53 | 50 | +3 | Haaland | 3,482,299 | 53 |
