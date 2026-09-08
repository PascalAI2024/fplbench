# fplbench — current work

Updated September 8, 2026. Repo: `projects/fplbench/main` (moved here in the
2026-09-07 workspace reorg, out of the retired `dev\fplbench`). Origin:
https://github.com/PascalAI2024/fplbench.

## Verified state

Season 2026-27 is live and the weekly loop is running unattended. GW3 is
`finished` and `data_checked`; CI scored it and pushed on 2026-09-05 and
2026-09-07.

| GW | model MAE | FPL `ep_next` | model (played) | `ep_next` (played) |
|---|---:|---:|---:|---:|
| 1 | 1.5686 | 1.6896 | 2.4690 | 2.1318 |
| 2 | 1.3758 | 1.4672 | 2.1989 | 1.9023 |
| 3 | 1.2920 | 1.3060 | 2.2960 | 2.4264 |

Model MAE improves every week so far. GW3 is the first week the model beat
FPL's own `ep_next` on the players-who-played split, which had gone against it
in GW1 and GW2.

The Leakage-Safe XI (entry 4770634): 53 / 102 / 51 = **206 points**, overall
rank 1,658,210. Zero transfers all season — by design, transfers are never
applied automatically.

## Changed this session (2026-09-08)

Pushed to `main`, CI green (run 34179506259).

- `add785b` — retry/backoff on transient FPL API errors. A single 503 from
  `/entry/4770634/history/` killed the whole 2026-09-04 pre-deadline run.
  `track_team._get_json` now retries 429/500/502/503/504 plus connection and
  timeout errors over 4 attempts with jitter; `build_board.py` already imported
  it, and `score_gw.py` now routes its two fetches through it. Same commit
  repoints the lineup launcher at the post-reorg path and finally tracks
  `friday_lineup_runner.ps1`, which `friday_lineup.cmd` invoked but which had
  never been committed.
- `d1ca5d9` — the NFLBench feasibility spike (synthetic fixtures only, no
  scraping, no publishing) plus accumulated team-board work.
- `e263e42`, `357e445` — launcher test tracked, then gated on
  `shutil.which("powershell.exe")` so Linux CI stays green while both tests
  still execute on Windows.

The three Windows scheduled tasks (`fplbench lineup thu`, `lineup fri-early`,
`Friday lineup`) were **Disabled and pointing at the dead pre-reorg path**.
Both fixed: they are Ready and now execute
`C:\Users\pasca\dev\projects\fplbench\main\scripts\friday_lineup.cmd`.

## Next acceptance check

**GW4 deadline: 2026-09-12 12:30 UTC.**

1. CI lands the GW4 board Thu 2026-09-10 15:05 UTC.
2. Thu 09-10 12:05 local correctly skips — the 36-hour gate rejects it at ~44h out.
3. Fri 09-11 07:35 local (11:35 UTC, ~25h out) is the run that should act.
4. Confirm afterwards that `outputs/friday_lineup_log.md` records a verified
   `SUCCESS_CHANGED` or `SUCCESS_NOOP`, not another `FAILED`.

**The known blocker is unresolved.** GW2 failed twice because the
Claude-in-Chrome tools were absent from the scheduled session and
chrome-devtools could not substitute. Correcting the paths does not fix that.
Unless a Chrome is left running on a dedicated profile logged into FPL with
`--remote-debugging-port`, expect step 3 to fail and set the XI manually.

## Open, not blocking

- `ruff check` reports 36 pre-existing errors across the tree (28 auto-fixable).
  CI only runs `pytest -q`, so this is not gating. Untouched — pre-existing, not
  from this session's diff.
- `outputs/board/`, `outputs/board-team-final/`, `outputs/board-team-preview/`
  (~560KB, 44 files) are regenerated publish artifacts, untracked and not in
  `.gitignore`. Candidate for a `.gitignore` entry.
- `scripts/score_gw.py` and `scripts/track_team.py` were already
  `ruff format`-dirty before this session; left alone rather than reformatting
  lines unrelated to the change.
- TimesFM 3.0 (Google, 2026-08-31) was assessed this session as a possible
  model swap. Verdict: no. Non-commercial weights block production exactly as
  TabFM's did, and the data shape is wrong — h=1, irregular cadence from blank
  and double gameweeks, zero-inflated targets, cross-sectional rather than
  autoregressive signal. The one direction worth a spike is upstream: forecast
  team-level goals for/against as a multivariate series with the fixture list as
  a known-future covariate, and feed the output to LightGBM as a feature.
