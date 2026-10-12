# fplbench — current work

## October 10, 2026: official live-history acquisition repair

Manual pre-deadline run
[`38038374950`](https://github.com/PascalAI2024/fplbench/actions/runs/38038374950)
on `a7e8376` downloaded the historical panel and raw season files and trained
the models successfully, then failed during live inference at 08:35 UTC with
`LiveHistoryError: missing history_manifest.json`. Prediction commit and board
publication were correctly skipped. The root cause was an orchestration gap:
the strict mid-season validator required a current-season official history
bundle, but neither the workflow nor `scripts/predict_live.py` acquired it.

The live loop now downloads one exact bootstrap/fixture snapshot, retrieves the
public official `element-summary` history for every current element with bounded
parallelism and transient retries, writes original per-element row counts, and
binds the resulting CSV to the snapshot hashes in `history_manifest.json`.
Acquisition is all-or-nothing: malformed or incomplete responses do not replace
an existing bundle, and the manifest is published last. Inference retains all
existing season, cutoff, fixture-completion, stable-code, cumulative-coverage,
and feature-field checks; no fallback was introduced.
The acquisition/provenance regressions pass 48 focused tests; the complete
local suite passes 174 tests with 1 skip. Python compilation and Git whitespace
checks also pass.

The GW6 deadline passed at 10:00 UTC, so this repair must not replay the
pre-deadline job retrospectively. The already committed 667-player forecast and
sanitized board remain frozen and unscored with SHA-256
`37a81e7b5756a8fd7e7c631abea3ef08128e0aaa967c15637a7b77abdd9cfca2`.
No team action, credential flow, new automation, or raw-history publication is
part of this repair.

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
inference. At this source-correction stage no player-history downloader,
credential flow, publication, or live team action was added; the acquisition
gap was subsequently closed by the workflow repair above.

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

## October 10, 08:37 UTC: GW6 routine — team verified; fresh pipeline blocked

The overnight remote release supersedes the stale model blockers below. Fetched
origin/main without pulling: `a7e8376780c4196898f94653bc0b4ae290b3f94f`.
GW6 committed forecast SHA256 `37a81e7b5756a8fd7e7c631abea3ef08128e0aaa967c15637a7b77abdd9cfca2`
has 667 unique IDs, all finite e_points_final, only event 6, and all 15 owned players.
Existing Chrome confirmed entry 4770634 and all 15 positions, Rogers captain,
B.Fernandes vice, bench Pickford/Groß/Konsa/Aina, £0.2m bank, 0 free transfers,
and no active chip. The existing overnight saved state matches the committed
model progress receipt. No transfer, chip or lineup save was repeated.

Authorized pre-deadline run 38038374950 FAILED at Live ingest + predict:
`LiveHistoryError: missing history_manifest.json`. No prediction commit or
publication occurred in this run. This routine is BLOCKED, not success/no-op.
Required repair: supply and validate the current-season history manifest/data in
the Actions runner before prediction. Prior Actions HF OAuth failure remains
untested by this run because publication was never reached. No credentials changed.
Run: https://github.com/PascalAI2024/fplbench/actions/runs/38038374950

Public HF Space revision `162e8342cb9c1d4d5f05bb87f5607bd0feafe389` is RUNNING;
root shows matching GW6 forecast hash and unscored saved-team observation.
GitHub RESULTS and HF dataset card/board show completed GW1–5 results; GW5
MAE 1.3062 vs baseline 1.1560 and team 52 vs average 48. No post-GW recovery
needed, and no unfinished GW6 score published.

Same automation rescheduled with supported automation_update for GW7 deadline
2026-10-17 10:00 UTC: next run 08:30 UTC / 04:30 America/New_York (EDT).
Read-only scheduler verification: ACTIVE, next_run_at 1792225800000.
No duplicate routine or polling. Evidence: `.evidence/2026-10-10/gw6-routine-receipt.json`
and `.evidence/2026-10-10/pre-deadline-run.json`.
Shared continuation: `projects/fplbench/2026-09-18-deadline-routine.md`.
Jarvis item: `fplbench-live-operations/fplbench-gw6-deadline-20261010`.
Preserved prior dirty CURRENT_WORK.md; no local pull/reset/commit/push.

## October 9, 19:46 UTC: current completion reconciliation

Supersedes the earlier scheduler blocker below: an external supported update
has corrected the same `fplbench-deadline-routine`. Actual local scheduler state
is ACTIVE, next_run_at `1791621000000`, October 10 at 08:30 UTC / 04:30 EDT;
updated_at `1791533815267`. No runs have occurred yet. The official Premier League
GW6 essentials notice, published October 9, verifies the deadline at 11:00 BST
on October 10 = 10:00 UTC. The saved schedule is exactly 90 minutes before it.
Source: https://www.premierleague.com/en/news/4729192/everything-you-need-for-gameweek-6-of-fpl-with-the-latest-tips-and-advice
No scheduler/config/database edits or duplicate automations were made by this
reconciliation; the delegated automation tool still reports local-thread-only.

GitHub was checked directly through the existing Windows gh CLI: main remains
5f12c30b9ffdf69b008f3a5a833a9d42e6619a9d; the only remote branch is main; all-state
PR list is empty. Last run remains failed 37840825721, only Build + publish failed.
Therefore the cloud engine repair is not visible in the repository/PR/CI state.
Cloud owner reported 163 tests passed, 1 skipped and independent review clear,
but the exact repair artifact/test receipt is not present in this desktop task.
No patch publication or previously denied 667-player collection was retried.
No credential handling, new access, or team changes occurred.

HF Space remains RUNNING at d37c4cb9497f557584779d8b370e1c2926463c2d, serving the
Oct 8 snapshot with its under-review notice. Current public root matches the
preserved artifact after removing only HF's injected runtime metadata. The prior
receipt proves all 21 immutable/public pages matched. This completes snapshot
publication recovery and now schedule timing correction; it does not complete
model repair release, validated forecast refresh, or unattended HF Actions auth.
Latest receipt:
`C:/Users/pasca/Documents/Codex/2026-10-08/task-2/fplbench-status-reconciliation-2026-10-09.json`.

## October 8: desktop auth/publication and routine verification

Desktop HF CLI 1.27.0 is installed. Supported `hf auth whoami` refreshed the
existing `oauth-x0me` login, returning `x0me`; current OAuth expiry is
2026-11-07T21:11:24Z. Explicit target write access to `x0me/fplbench-board`
passed. No token value was printed, and no credential was manually copied or
reconfigured. GitHub Actions uses a separate `HF_TOKEN`, last updated
2026-09-10T22:05:01Z; it still requires approval-gated replacement.

Run 37840825721 failed only board publication with OAuth expiry after training,
ingest/predict, and commit succeeded. Existing GW6 snapshot is source
`5f12c30b9ffdf69b008f3a5a833a9d42e6619a9d` (667 unique IDs, finite predictions).
A desktop publication recovery built that exact source in an isolated task
workspace, then atomically published all 21 HTML pages at Space revision
`d37c4cb9497f557584779d8b370e1c2926463c2d`. All 21 immutable readbacks and all
21 public pages match the candidate (public pages except only HF's injected
runtime metadata script). Every page explicitly identifies the Oct 8 snapshot
and warns that current-player-history checks remain pending; this is NOT
acceptance of the model repair and must not drive team changes. No training,
package changes, GitHub workflow dispatch, or source-code edits were performed.

The actual local scheduler DB says `fplbench-deadline-routine` ACTIVE but
`next_run_at = 2026-10-10T04:30:00Z`, four hours earlier than the intended
08:30 UTC / 04:30 America/New_York. `last_run_at` is null and no run history
exists. The target thread 01a0b615-3f94-7753-96da-0eb9bd509080 DOES exist locally,
is unarchived, and has a current local catalog entry; the cloud lookup's
not-found result does not prove it is missing. Supported automation view/update
was unavailable in this delegated caller context (local-thread-only error).
No routine configuration or scheduler DB was changed. All three legacy FPLBench
Windows tasks remain Disabled. Official GW6 deadline freshly verified as
2026-10-10T10:00:00Z; GW7 is 2026-10-17T10:00:00Z.

Authenticated Chrome FPL UI was read only: entry 4770634, The Leakage-Safe XI,
GW6, 2 free transfers, bank GBP 0.2m, no current-GW transfers. Saved XI still
starts injured Milenkovic (0% next-round chance, hamstring, expected back Oct 11)
and newly doubtful Konsa (75%, unspecified injury). Captain B.Fernandes,
vice Enzo, bench Kinsky/Aina/Diop/Gross. No transfers, substitutions, chips,
hits, or team saves. FPL tab restored to its original my-team page; Upwork tabs
and browser account context were untouched.

Evidence and secure recovery helper:
`C:/Users/pasca/Documents/Codex/2026-10-08/task-2/publication-receipt.json`,
`fpl-authenticated-observations.json`, `routine-observations.json`, and
`replace_hf_token_after_approval.py` in the same directory. The helper has NOT
run. Exact remaining approvals/actions: replace only repo Actions HF_TOKEN
with existing refreshed x0me credential via encrypted stdin after human approval;
correct and read back the existing routine's scheduler time via supported local
Codex automation controls; accept current-player-history engine repair before
using a new forecast for the team. Shared vault-note access and an attempted
parent progress message were rejected by automatic approval review; local
findings are returned through the delegated final response.

Latest scope clarification (21:25 UTC): leave GitHub HF_TOKEN unchanged; do not
copy CLI credentials into GitHub secrets, generate grants, or change access.
The earlier approval-gated helper is now explicitly disabled and was never run.
Fresh target write-access check and public root readback still confirm x0me and
Space revision d37c4cb; GitHub main is still 5f12c30. The routine scheduler and
saved authenticated squad are unchanged. Updated read-only evidence:
`C:/Users/pasca/Documents/Codex/2026-10-08/task-2/latest-access-publication-state.json`.

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
are retained in the private scheduler archive.
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
The signed-in official FPL UI for the privately configured entry showed 3 free transfers, zero bank,
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

The Leakage-Safe XI: 53 / 102 / 51 = **206 points**, overall
rank 1,658,210. Zero transfers all season — by design, transfers are never
applied automatically.

## Changed this session (2026-09-08)

Pushed to `main`, CI green (run 34179506259).

- `add785b` — retry/backoff on transient FPL API errors. A single 503 from
  `/entry/<private-id>/history/` killed the whole 2026-09-04 pre-deadline run.
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
`scripts\friday_lineup.cmd` from the repository root.

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

### 2026-10-09 20:00 UTC desktop readback

- Existing default Hugging Face authentication still identifies x0me; write access to x0me/fplbench-board verified. No credential value read into output, copied, or reconfigured. Space is RUNNING at d37c4cb9497f557584779d8b370e1c2926463c2d, with public root HTTP 200 matching the 21-page publication receipt and review notice preserved. Published forecast source remains 5f12c30b9ffdf69b008f3a5a833a9d42e6619a9d.
- A new scheduled GitHub run 37983571521 started 2026-10-09 19:55:58 UTC, trained/ingested/predicted/committed successfully, then failed Build + publish Space board. Failed-log classification confirms OAuth expired without printing raw logs. HF_TOKEN metadata remains unchanged since 2026-09-10T22:05:01Z. Latest main is now 9d1733936fb07793067db6a8dd28a5f5f30b5f39 (19:57:33 UTC); compare with 5f12c30 shows only outputs/predictions/gw6_2026-27.csv changed. No repair code publication visible.
- Existing deadline routine fplbench-deadline-routine was found externally corrected: ACTIVE, next_run_at 1791621000000 = 2026-10-10 08:30 UTC = 04:30 EDT, updated_at 1791533815267 = 2026-10-09 08:16:55.267 UTC. This desktop task made no successful scheduler update and no TOML/DB edits; actual external actor is unrecorded. This Saturday schedule does not fulfil today's Friday catch-up.
- Exact Library metadata resolved: fplbench-20261008-reviewed-engine.zip, libfile_7a7e73d549d48191b59e18d11fb8fc7a, file_0000000050ac82308a8b251be4afca41, 2,320,051 bytes, created 2026-10-08T22:02:44.981817Z. No bytes materialized or local exact copy found. Historical /workspace/shared/fplbench-maintenance-20261008 no longer exists per parent. Contained patch SHA256 must match cfdcc7425ba6bf3e25d4e2ada3a117bb943151ecf9805df6fb8c19b2dee70948; ZIP hash is not assumed to equal patch hash. No denied route retried.
- Fresh official PL news dated 9 October says Milenkovic will miss Crystal Palace (bruised bone), Konsa sustained injury on international duty (selection risk, not proven multi-week absence), and Haaland is fit for Anfield. Source: https://www.premierleague.com/en/news/4730320 . Milenkovic was starting in the last authenticated GW6 snapshot from 8 October. Fresh public GW5 picks match the 15 owned IDs, but public GW5 bench differs from the last authenticated GW6 bench; public history cannot establish today's saved GW6 lineup.
- Current authenticated GW6 UI not reverified: CUA controls not exposed and Upwork builder owns interactive Chrome. No browser tabs/context touched, team changes, transfers, paid runs, chips/hits, credential changes, or engine edits. Friday lineup/bench/captain model review remains blocked pending a permitted exact repair copy, reviewed engine publication/data validation, and coordinated authenticated read-only browser access.
- Evidence in C:\Users\pasca\Documents\Codex\2026-10-08\task-2: final-auth-publication-readback.json; latest-ci-failure-receipt.json; schedule-correction-attribution.json; repair-packet-availability.json; friday-team-review-final.json; publication-receipt.json.

### 2026-10-09 23:31 UTC: ongoing management authority and GW6 decision packet

Latest parent delegation carries Pascal's explicit ongoing FPLBench and actual-team management through end-of-year review: improve and evaluate the bench experiment and maximize score. No spend, paid competitions, credential/access changes or prior-denied download bypass. Existing deadline routine is retained; no duplicate schedule or regular polling was created.

Parent's Mac normal-browser read at 23:20 UTC verified today's unchanged fifteen, Bruno captain/Enzo vice, Kinsky-Aina-Diop-Gross bench, 2 FT, GBP 0.2m bank, GBP 100.1m squad value and no active chip. This Windows task did not independently browse it. Mac is currently unauthorized and Windows normal Chrome controls unavailable; no team save occurred.

Fresh official public bootstrap and GW6 fixtures were read at 23:25 UTC, limited saved evidence to the owned fifteen and a named candidate shortlist; no element-summary/history bulk collection. Milenkovic is 0% with knee injury/unknown return, Konsa 75%, Gross healthy with 450 minutes and 47 points. Hall GBP 5.3m, Saka GBP 9.6m; current clubs checked. PL Scout dated October 9 selects Saka captain/Haaland vice and highlights Gross, Hall and Tarkowski. Sources: https://www.premierleague.com/en/news/4730172 and https://www.premierleague.com/en/news/4730320 . Exact deadline 2026-10-10 10:00 UTC; existing stop-before-save cutoff 09:40 UTC.

Actual existing automation TOML still requires 'Use the existing model planner for all decisions; no personal football judgment', positive-gain free moves only, zero points hit, no chips, actual rendered-UI selling prices, accepted matching forecast/publication, and authenticated reload verification. No policy or scheduler changes were made. Broader management authority is recorded without silently discarding these experiment constraints.

Prepared candidate for the validated model to evaluate: Milenkovic (471) -> Lewis Hall (449), Bruno (426) -> Saka (12), using two verified FT at zero hit cost, no chip. Proposed 3-5-2: Pickford; Tarkowski/Hall/Diop; Saka(C)/Gross/Szoboszlai/Anderson/Enzo; Haaland(VC)/Evanilson. Provisional bench Kinsky/Konsa/Calvert-Lewin/Aina; executable bench must come from the existing autosub simulator. Squad 2/5/5/3, XI 1/3/5/2, fifteen unique players and maximum three per club verified. Current combined purchases GBP 14.9m; actual sale proceeds must be at least GBP 14.7m given GBP 0.2m bank. Indicative remaining bank GBP 2.6m uses Oct 8 displayed sale values (5.4 and 11.9), not fresh selling-price approval. Compare against Hall plus Barnes replacing Enzo, and the optimized zero-transfer baseline. No expected gain was invented and no candidate was represented as model-approved.

GitHub rechecked at 23:28 UTC: only main at 9d1733936fb07793067db6a8dd28a5f5f30b5f39, no PRs; latest scheduled run 37983571521 remains failed. Latest commit modifies only GW6 prediction CSV, so reviewed engine repair remains absent remotely. No permitted exact repair bytes were available here and no denied download/materialization route was retried.

Exact execution dependency: restore authorized normal Mac browser or normal Windows Chrome; clear the accepted-model/forecast gate through existing permitted routes; run existing planner with actual current UI selling prices and verify positive gain, zero hit, no chip; re-read saved squad/FT/prices/deadline; save only selected plan before 09:40 UTC, reload and verify every squad/position/captain/vice/bank change. Parent can coordinate Mac execution on reconnection under already delegated management authority. Year-end audit will retain frozen forecasts, actual results, bench/autosub outcomes, transfers, costs and failures separately from successful saves.

Evidence in C:/Users/pasca/Documents/Codex/2026-10-08/task-2: gw6-management-decision-audit.json; gw6-fresh-official-metadata.json; gw6-latest-engine-publication-state.json. No FPL, browser, credential, engine-source or remote-repository writes occurred.
