# Live scoring results

Published `e_points_final` MAE vs FPL `ep_next` after each gameweek is both
finished and data-checked (common finite mask). `e_points_final` is the frozen
pre-deadline forecast used to rank the squad: minutes-gated points plus expected
DefCon.

Until an official gameweek is verified, this table has no scores.
`scripts/score_gw.py` writes them from official FPL actuals. No invented numbers.

| GW | n_common | mae_model | mae_ep_next | n_played | mae_model_played | mae_ep_next_played |
|---|---|---|---|---|---|---|
| 1 | 587 | 1.5686 | 1.6896 | 302 | 2.4690 | 2.1318 |
| 2 | 616 | 1.3758 | 1.4672 | 308 | 2.1989 | 1.9023 |
| 3 | 652 | 1.2920 | 1.3060 | 307 | 2.2960 | 2.4264 |
| 4 | 656 | 1.2974 | 1.2398 | 307 | 2.3294 | 2.2958 |
| 5 | 659 | 1.3062 | 1.1560 | 301 | 2.4155 | 2.2209 |
| 6 | 667 | 1.0507 | 1.1675 | 315 | 2.0667 | 2.2683 |
| 7 | 667 | 1.0275 | 1.2828 | 304 | 1.9995 | 2.4855 |
| 8 | 668 | 1.0737 | 1.2969 | 303 | 2.1084 | 2.5657 |

## Team — The Leakage-Safe XI

The model's own squad in the official FPL game. Rewritten from the official API
using a privately supplied entry identifier on every post-GW run. Public outputs
omit that identifier. Rows remain marked live or review until FPL sets both
`finished` and `data_checked`.

| GW | pts | GW avg | vs avg | captain | overall rank | total pts |
|---|---|---|---|---|---|---|
| 1 | 53 | 50 | +3 | Haaland | 3,482,299 | 53 |
| 2 | 102 | 81 | +21 | B.Fernandes | 1,474,311 | 155 |
| 3 | 51 | 51 | 0 | B.Fernandes | 1,658,210 | 206 |
| 4 | 60 | 69 | -9 | B.Fernandes | 3,170,793 | 266 |
| 5 | 52 | 48 | +4 | B.Fernandes | 2,831,164 | 318 |
