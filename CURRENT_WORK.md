# fplbench — current work

## October 10, 2026: GW6 forecast, saved team, and portable solver

The current-season repair is now materialized as a deterministic GW6 forecast.
The public forecast contains 667 unique players, targets event 6 before its
2026-10-10 10:00 UTC deadline, and has SHA-256
`37a81e7b5756a8fd7e7c631abea3ef08128e0aaa967c15637a7b77abdd9cfca2`.
Its validated official-history input covered all 667 current players across
3,216 GW1–5 fixture rows. Those raw history inputs and authenticated receipts
remain private; only the forecast and a sanitized progress record are public.

**Observed saved state:** two free transfers were saved and read back before
the deadline: Enzo to Rogers and Milenković to Schuster, for zero points. No
chip was used, no free transfers remained, and the bank remained £0.2m. The
saved 3-4-3 is Kinsky; Tarkowski, Schuster, Diop; Rogers (C), B.Fernandes (V),
Szoboszlai, Anderson; Haaland, Evanilson, Calvert-Lewin. Bench order: Pickford,
Groß, Konsa, Aina.

**Model projection, not an observation:** the saved team projects to 55.292
points versus 50.701 for holding, a projected gain of 4.592. GW6 is unplayed
and unscored; actual points remain absent until FPL marks the event both
`finished` and `data_checked`.

The optimizer now uses the native CBC executable on `PATH` through three
`pulp.COIN_CMD` calls. Homebrew CBC 2.10.13 on arm64 passed its solver smoke
test; the source repair suite recorded 170 passed and 1 skipped. CI installs
the same system solver explicitly, and [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md)
documents a portable Apple Silicon setup without signing or security changes.
The final publication suite, including the sanitized-progress binding test,
passes 171 tests with 1 skip.

The first Linux CI replay exposed PuLP 4.0's removal of the deprecated
`LpVariable.dicts` and integer `LpStatus` interfaces. Variable creation and
status handling now use the compatible problem APIs, and each `COIN_CMD`
receives the exact native `cbc` path instead of accepting a package-bundled
default. The full 171-pass suite succeeds against both PuLP 3.3.2 and 4.0.0.

The existing GitHub deadline workflow remains the public-data scheduler. This
update did not create another automation: the historical one-occurrence Codex
deadline routine described below must be reused or explicitly replaced in its
own owning task, never duplicated. Experiment rules remain model-selected free
transfers, no points hits, and no chip unless separately authorized.

## October 10, 2026: isolated current-season feature correction

Owner: delegated Codex task `2026-10-08/task-2`; source branch
`codex/current-season-features` in its isolated `engine-fix` checkout. Base
`fae0a9f81fe9da6258c6bc1667cd29b71bae7ccb`. The original Windows checkout and
the frozen planner-validation packet are preserved read-only. This is a new
source correction, not a reconstruction of the unavailable reviewed repair ZIP.

The live predictor previously joined 2025/26 end-of-season rolling form for
every GW. It now restricts that cold start to GW1. Later player/opponent form
uses validated current-season fixture history and the same lag implementation
as training. Previous-season aggregate priors and set-piece orders remain
separate. Metadata, season, target-GW, fixture date/completion, response row
counts, cumulative coverage, and deadline boundaries are checked before model
inference. No player-history downloader, credential flow, publication, or live
team action was added.

Full final local suite: 169 passed. Changed-file Ruff checks and Git whitespace
checks pass. The source correction is tested; current-season forecasting is
blocked by missing input data.
Fresh official bootstrap and fixture metadata captured October 10 at
00:04:14 UTC resolve GW6 and 667 elements. Read-only preparation against the
existing 139,029-row local panel stops at `missing history_manifest.json`;
the panel contains only 2021/22 through 2025/26. No current-season forecast was
generated. Exact new required bundle files, raw fields, provenance, and cutoff
rules are in the task's `engine-fix-input-audit.json` and the README.

Next acceptance check: materialize a previously authorized official history
bundle, verify complete current-season coverage and cutoff provenance, then
generate and independently evaluate a fresh forecast. Its predictive error
and calibration remain unmeasured. Do not use this source-only correction or
the old under-review forecasts for live transfers. Existing no-hit/no-chip and
model-only experiment rules remain intact.

Preservation boundary: all new source/data/evidence stays inside this task's
isolated checkout and final frozen handoff. Parent should pass the immutable
receipt to preservation owner `01a122f8-eded-7454-ad7e-9e39c5b5a0d1`; no original
FPL files should be snapshotted as changed by this correction. No remote backup
or Mac replay is implied by local commits or archives.

Updated September 18, 2026. Repo: `projects/fplbench/main` (moved here in the
2026-09-07 workspace reorg, out of the retired `dev\fplbench`). Origin:
https://github.com/PascalAI2024/fplbench.

## Verified state

### September 25: bench order from simulated autosubs (branch `bench-subs`)

Before this, the bench was "backup GK, then outfield by `e_points_final`" in
three places (`squad._order_bench`, `plan_transfers.format_plan`, prompt step
6), and the planner's JSON carried no bench at all. The bench has scored 9, 17,
14, 25 and 16 points this season, so its order is not cosmetic.

`fplbench/bench.py` now scores all six outfield orders against 4,000 seeded
scenarios under FPL's real autosub rules (pitch order, first bench player who
played, formation bands, GK-only-for-GK). P(plays) comes from projected minutes
through a curve measured on the 2025-26 holdout (even an 88-minute projection
misses 3% of games), capped by FPL's chance-of-playing flag. A sub is valued at
his points when he plays, so a rotation risk with a high ceiling can move ahead
of a nailed low scorer; players ruled out go last. `TransferPlan.bench_ids`,
the planner's JSON `bench`, and prompt step 6 now carry that order. The
transfer ILP's `BENCH_WEIGHT` is unchanged. 128 tests pass (12 new); mutation
checked both ways (always-naive order and no play-probability floor each turn
one test red).

GW6 (deadline **2026-10-10 10:00 UTC**) preview on the Sept 25 CI forecast,
approximate selling prices, 2 free transfers inferred from public history:
Calvert-Lewin -> Thiago, B.Fernandes -> Bruno G., +3.88 net. XI Pickford;
Konsa, Tarkowski, Aina; Szoboszlai (C), Bruno G. (V), Enzo, Anderson; Haaland,
Thiago, Evanilson. Bench Kinsky, Gross, Diop, Milenkovic (injured, back
Oct 11). Nothing was submitted to FPL. The forecast refreshes daily until the
deadline, so this is provisional.

Injuries are now a hard constraint in the transfer ILP: a player who is injured,
suspended or flagged below 75% never starts and cannot be bought. If injuries
leave no legal fit XI, holding is priced at zero, so the planner has to make a
transfer. `min_transfers` prices options the solver would not pick on its own.
On 2026-09-25 only Milenkovic (hamstring, back Oct 11) was flagged among the 15.
International-break news had nothing on the others. GW6 options (net of hits,
against holding): 1 FT +1.81, 2 FT +3.88, 3 transfers (one -4 hit, which sells
Milenkovic) +1.48. A dead bench slot is not worth a hit.

Stale: HF `HF_TOKEN` expires 2026-10-08, two days before the GW6 deadline, so
the final pre-deadline publish will fail without a rotation.

### September 18: Codex deadline routine replaces Claude scheduled jobs

User narrowed the repair to creating a routine using their Chrome. Created and
read back active Codex heartbeat `fplbench-deadline-routine` in
task `01a0b615-3f94-7753-96da-0eb9bd509080`. The user explicitly REJECTED two-hour
polling: run ONCE per gameweek, 90 minutes before its official deadline. The next
occurrence is October 10 at 04:30 America/New_York (08:30 UTC), for GW6's verified
10:00 UTC deadline. It reschedules the same routine to one occurrence 90 minutes
before the following official event, respecting DST. No regular Codex polling.
The routine dispatches the existing pre-deadline GitHub workflow to calculate and
commit predictions and publish the Hugging Face board before managing the team.
It checks existing post-GW scoring/publication and may dispatch a missing verified
results refresh once. Existing post-match GitHub schedules remain active.
GitHub/Hugging Face publication was explicitly requested; the user's Kaggle
reference needs a destination clarification before any Kaggle upload.
Model-selected free transfers and lineup only, stopping 20 minutes before the
deadline. No chips or points hits. Authenticated UI reload verification
is required before recording success. New blockers and missed deadlines must alert;
unchanged/non-actionable checks stay quiet. No private browser API calls or tokens.

All three legacy Windows FPLBench tasks are verified Disabled. Their XML backups
are in `C:/Users/pasca/dev/_archive/fplbench/2026-09-18/scheduler/`.
The heartbeat configuration was verified on disk and through automation view;
an unattended authenticated save has NOT yet been demonstrated. Chrome is reachable
but FPL was signed out; its login tab was left open for the user. No team change,
code repair, push or publication was performed during routine setup. Existing dirty
work is preserved. Shared continuation: `projects/fplbench/2026-09-18-deadline-routine.md`.

GW5 deadline was missed (2026-09-18 17:30 UTC). The Thursday run lacked the GW5
forecast at 16:06 UTC; forecast commit `deeb549` arrived at 18:55 UTC. Friday's
07:35 Eastern Claude run failed on expired OAuth and 11:50 exited abnormally.
Public GW5 picks match the saved September 10 squad/XI/C/VC/bench, with zero
GW5 transfers. Friday workflow `35377430602` failed building the board on FPL
503 responses, while Thursday's GW5 board remains online. Known miss already
reported to the user: do not repeatedly alert about GW5.

Next acceptance: user signs into FPL in Chrome; routine must prove authenticated
read and, when a matching future forecast is available in the action window,
verify saved state after the update. This entry supersedes the older claims below
that the legacy tasks are Ready or unattended team management is proven.

### September 10: GW4 deadline preparation

**Live update completed after the user explicitly instructed execution now.**
The signed-in official FPL UI showed entry 4770634, 3 free transfers, zero bank,
and actual selling prices. Applied the model's three free transfers:
Trafford to Pickford, Van Hecke to Konsa, Gakpo to Enzo. Confirmation showed
0 points cost; bank after was GBP 0.2m. Saved the model XI and verified all
15 positions by reloading the authenticated team page. Captain B.Fernandes;
vice Enzo; bench Kinsky, Aina, Diop, Gross. No chip used. Projected gain 4.671.
Evidence `outputs/gw4-live-verified.json`; duplicate guard recorded in
`outputs/friday_lineup_log.md` against forecast `5bae1a7` and its SHA256.
The earlier browser hold and authentication blocker below are now resolved.
Completion work item: `fplbench-gw4-live-update-20260910`.

- Official next deadline is **Saturday September 12, 12:30 UTC / 08:30 Eastern**.
  Friday September 11 is preparation day, with local tasks Ready at 07:35 and
  11:50 Eastern. Thursday's 12:05 run correctly skipped at 44.4 hours out;
  it did not authenticate or change the team.
- Remote `origin/main` advanced to `5bae1a7` with the committed GW4 forecast:
  655 unique player IDs, finite `e_points_final`, event 4, all 15 public GW3
  squad members covered. Forecast SHA256:
  `3da4140a9808fcfd80e992ad68c4e127d4c8be90b5adeb5ebcd5ee9029bff23b`.
  Local untracked GW4 CSV and all earlier output folders are preserved; no pull.
- Repaired the planner used by the scheduled tasks: remaining free transfers
  are `max(0, limit - made)`, not the whole weekly limit. Zero stays zero;
  invalid/missing allowance data and active chips fail closed. The scheduled
  prompt independently checks the remaining allowance before a transfer.
  **116 tests passed**, including exhausted allowance and prior-transfer cases.
  These safety changes are local and not yet committed or pushed.
- Today's prediction workflow failed only at HF publishing: its OAuth token
  had expired. Replaced GitHub `HF_TOKEN` using the existing validated `x0me`
  login, valid until **2026-10-08T02:32:51Z**. This repairs current publishing;
  it does not provide permanent token renewal. No secret entered project files.
  Verification run: https://github.com/PascalAI2024/fplbench/actions/runs/34535612666.
  Run succeeded; all 21 published HTML pages passed immutable readback. Public
  root matches Space revision `c794ba87cded01a1d7ed94ff9f6d5df7877d330c`,
  apart from Hugging Face's injected runtime metadata script.
  Pre-deadline runs can refresh GW4; forecasts become immutable after deadline.
- No live transfers, lineup changes or chips were submitted. Chrome is running,
  but there is no existing FPL tab. Read-only sign-in preflight is pending the
  user's release of the earlier Windows foreground hold. The 36-hour action
  window begins September 10 at 20:30 Eastern.
- Evidence: `outputs/gw4-readiness.json`. Jarvis owner `fplbench-deadline-prep`,
  work item `fplbench-gw4-prep-20260910` in `fplbench-live-operations`.
  Next acceptance: FPL sign-in preflight and Friday authenticated GET-after-POST
  verification, or a precise failure requiring user action.

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
- Runner now `Set-Location`s to the repo root. Task Scheduler starts in
  system32 and the rewritten `.cmd` had dropped the old `cd /d`, leaving the
  prompt's relative git and artifact reads unanchored.
- `tests/test_fpl_api_retry.py` pins all four retry paths. Verified by
  mutation: forcing `MAX_ATTEMPTS = 1` turns two of them red.

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
5. GW4 is the first week transfers are in scope. Check the log names the
   transfer applied and its `expected_gain`, and that the authenticated
   re-GET confirmed the squad actually changed.

**Dry run passed 2026-09-08 02:21Z.** `Start-ScheduledTask 'fplbench lineup thu'`
exercised the whole chain from the new path: task -> `friday_lineup.cmd` ->
`friday_lineup_runner.ps1` -> `claude.exe --chrome` -> prompt. The gate read GW4
at 106.1h out, correctly skipped, wrote to `outputs/friday_lineup_log.md` in the
right directory, emitted `SUCCESS_NOOP`, and the runner exited 0. No FPL side
effects.

**The GW2 browser failure is addressed but not yet proven.** Those runs failed
because the Claude-in-Chrome tools were absent from the scheduled session; the
runner now passes `--chrome` to `claude.exe`, and the three tasks run as
`Interactive` under `pasca` (not session 0, so the extension bridge can reach
the desktop Chrome). What the dry run could not exercise is the authenticated
browser step itself, because the gate skipped before reaching it. Friday is the
first real test. If Chrome is not running and logged into FPL at 11:35Z, step 3
still fails by design and the XI needs setting by hand.

## Transfers are now the model's job too (2026-09-08)

`fplbench/transfers.py` + `scripts/plan_transfers.py`, wired into the weekly
prompt. The squad had been frozen on the GW1 picks all season, so "the model's
team" was not true of the 15, only aspirationally of the 11.

The ILP solves squad, XI and captain jointly against expected starting XI
points net of the 4-point hit, using real selling prices from the
authenticated my-team endpoint. Preview mode approximates prices from
`now_cost` and refuses to be submitted.

Live gate before any transfer POST: `expected_gain > 0`, at most 2 transfers,
non-approximate prices, and every out/in checked against the authenticated
squad. A failed transfer POST is never retried.

**Model's GW4 opinion** (local preview board, not the committed forecast):
transfer Gakpo out for Enzo (+2.86 net), and three lineup changes — bench Aina,
Diop, Gross for Van Hecke, Calvert-Lewin, Evanilson. Captain B.Fernandes.
Worth noting: the model wanted to bench Gakpo in GW3 too, and he returned 11.
Selling him now is the same call again — conviction or blind spot, one week
does not say which.

## The automation has never applied a lineup

Checked 2026-09-08. Across the whole log history there is **zero**
`SUCCESS_CHANGED` — five entries total: one skip (no board yet), two `FAILED`
(browser tools absent, GW2), and two gate-skips (2026-08-30 and tonight's dry
run).

- GW1 -> GW2 the team **did** change (XI, captain, vice, bench order), but both
  automated attempts failed that week, so it was applied by hand.
- GW2 -> GW3 **nothing changed at all** — identical XI, captain, vice and bench
  order. The scheduled tasks last fired 2026-08-28, so no run acted for GW3;
  FPL simply carried the GW2 lineup forward.

Counting the cost of that miss, on GW3 the model's board wanted three swaps:
bench Aina (3.31), Milenkovic (3.47), Gakpo (2.76); start Van Hecke (3.62),
Calvert-Lewin (3.55), Evanilson (4.09), for +1.727 expected.

Actual GW3 returns: out 1 + 7 + 11 = 19, in 8 + 1 + 2 = 11. **The model's
lineup would have scored 8 points worse.** It wanted to bench Gakpo, who was
the squad's top scorer that week at 11.

That is one gameweek and proves nothing on its own, but it does mean the
current evidence does not show lineup automation beating leaving the squad
alone. The forecast head is strong (it beats FPL's `ep_next` on MAE); picking
an XI from 15 owned players is a much narrower and noisier decision. Get one
verified run, then judge it over several weeks before trusting it — and do not
treat a failed Friday as a known loss.

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
