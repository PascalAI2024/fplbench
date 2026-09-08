# Multisport Benchmark Expansion

## Decision memo — 30 August 2026

### Executive decision

Build **NFLBench** first: a leakage-safe, player-week PPR forecasting benchmark for quarterbacks, running backs, wide receivers, and tight ends. Freeze forecasts at T-24h before the first game of the week, retain every frozen player (including later DNPs), and score after the Thursday statistical-correction refresh.

Build **SoccerBench** second as a distinct match-level product, not as a forced copy of FPLBench. Its first target should be pre-kickoff home/draw/away probabilities and expected goals over a fixed set of competitions. OpenFootball's current CC0 fixture/result files make this unusually clean to publish.

Run a narrow **cricket licensing and fixture-provenance spike** before authorizing a public T20 benchmark. Cricsheet is technically excellent, but the inspected pages state an explicit license for the Register dataset, not clearly for the match archives.

Do not start public NBA, NHL, or Formula 1 benchmarks without written permission or separately licensed feeds. MLB is viable as a historical or annually delayed benchmark through Retrosheet, but not as the next live product.

### What was evaluated

Seven candidates were compared on data rights and source stability, pre-event freezeability, natural contest cadence, objective public scoring, engineering effort, and audience/product fit. Scores are decision aids, not empirical performance claims.

| Rank | Candidate | Decision score / 5 | Verdict |
|---:|---|---:|---|
| 1 | NFL player-week fantasy | 4.7 | GO — closest extension of FPLBench |
| 2 | Soccer match forecasting | 4.6 | GO NEXT — clean open-data product, but a different target |
| 3 | T20 cricket match forecasting | 3.6 | CONDITIONAL — resolve archive license and live provenance |
| 4 | MLB player/game forecasting | 3.4 | HISTORICAL/DELAYED — permissive archive, difficult live rights |
| 5 | NHL daily fantasy | 2.8 | HOLD — technical API access does not grant reuse rights |
| 6 | NBA daily fantasy | 2.6 | NO-GO — official terms expressly restrict fantasy/database use |
| 7 | Formula 1 fantasy | 2.5 | HOLD — rights and feed completeness are poor for public scoring |

Weights: data rights/source stability 25%; leakage control 20%; cadence 15%; scoring clarity 15%; audience/product fit 15%; engineering effort 10%.

## Why NFL is first

### Strong operating fit

NFL is the nearest analogue to the current FPLBench operating model: a recurring fantasy contest, player-level forecasts, an objective weekly score, and enough time between rounds to freeze, publish, inspect, and score artifacts. The weekly cadence is much easier to audit than the daily lineup churn in MLB, NBA, and NHL.

nflverse publishes automated data releases under CC BY 4.0. Its update schedule states that player statistics update nightly, rosters daily, schedules every five minutes, and depth charts have ISO timestamps from 2025. It also states that Thursday is the cleanest post-game scoring point after NFL corrections. The same source records the important limitation: its injury feed ended after 2024.

Sleeper's read-only API provides NFL league settings, rosters, matchups, player identity fields, practice participation, injury status, and update metadata. It is free for non-commercial use; commercial use requires a separate license. The all-player map is intended to be cached and called no more than once daily. This is useful for a public research pilot, but it is not an unconditional commercial-data grant.

### Licensing boundary

Do not scrape NFL.com to repair the injury gap. NFL.com's terms restrict use to individual, non-commercial informational purposes and prohibit systematic retrieval or database construction without consent. Official injury reports establish a clear reporting cadence and public status vocabulary, but they are reference evidence rather than an authorized ingestion feed.

The MVP should therefore use a **no-injury-feature policy** unless Sleeper's licensed fields are sufficient for the research use and their timestamp semantics pass validation. This is a cleaner benchmark than quietly importing a rights problem.

## NFLBench MVP contract

### Forecast unit and universe

- One row per season, week, player, team, opponent, and frozen snapshot.
- Positions: QB, RB, WR, and TE. Exclude kicker and team defense in version one.
- Player universe comes from the prior roster plus the last eligible, timestamped depth-chart snapshot.
- Every frozen player remains in the scored set. A player who later does not play receives zero fantasy points; the benchmark must not retrospectively delete hard cases.

### Freeze and target

- Primary track: a single immutable snapshot at least 24 hours before the first weekly kickoff.
- Later optional track: T-120 minutes for late information. It must have a separate leaderboard and artifacts.
- Target: fixed PPR scoring — passing TD 4; rushing/receiving TD 6; passing yards 1 per 25; rushing/receiving yards 1 per 10; reception 1; interception -2; lost fumble -2.
- Score only after the Thursday post-correction refresh. Record the exact nflverse release or content hash used.

### Evaluation

- Primary: mean absolute error over all frozen player-weeks, including zeros and DNPs.
- Secondary: root mean squared error, median absolute error, calibration/interval coverage when probabilistic outputs exist, and Spearman or NDCG@20 as rank diagnostics.
- Baselines: prior-four-week exponentially weighted mean and position median. Add external consensus projections only when redistribution and historical snapshot rights are explicit.
- Suggested validation: 2016-2024 training, 2025 locked validation, then a six-to-eight-week 2026 live pilot. Historical depth-chart timestamp semantics must be audited before using them in backtests.

### Leakage controls

1. Every feature row carries `observed_at`, `source_revision`, and `ingested_at`.
2. The feature join must enforce `observed_at <= cutoff_at`.
3. Same-game statistics are never available to that game's forecast; all rolling features are strictly lagged.
4. Forecast CSV, source manifest, configuration, and model revision are hashed and published before kickoff.
5. Late inactive news, corrections, depth-chart changes, and injuries never rewrite a frozen artifact.
6. Targets are computed in a separate scoring job after the correction window.
7. Identity joins fail closed on missing or ambiguous player mappings.

### Acceptance gates

- Legal/source manifest names each dataset, license, attribution requirement, cache rule, and commercial limitation.
- A synthetic time-travel test proves that post-cutoff records cannot enter a feature row.
- A DNP fixture proves that frozen players remain and score zero.
- A stat-correction fixture proves that forecasts do not change while targets can be versioned.
- A complete dry run publishes one immutable week, recomputes it from a clean checkout, and matches hashes.
- A human-readable board displays cutoff time, artifact hash, source revisions, forecasts, realized points, and baseline comparisons.

## Second product: SoccerBench

Soccer remains a strong expansion, but the clean opportunity is match forecasting rather than another player-fantasy clone. OpenFootball publishes current multi-league fixtures/results and dedicates its data/schema to the public domain. football-data.org can supplement schedules for a limited set of competitions, subject to attribution, rate, and application restrictions.

The MVP should freeze at T-24h and predict home/draw/away probabilities plus expected home and away goals. Primary scoring should be multiclass log loss; Brier score, calibration, and goal MAE or Poisson deviance are secondary. Avoid UEFA Fantasy as an operational source: UEFA's terms restrict systematic collection, database construction, scraping, and model development.

SoccerBench should have its own identity and leaderboard. Combining match-probability scores with player-fantasy MAE would produce a neat-looking number with no coherent meaning.

## Conditional option: T20 CricketBench

Cricsheet currently offers more than 22,000 ball-by-ball matches across international and club competitions, and its Register provides cross-source player identifiers under ODC Attribution 1.0. The technical corpus is excellent.

The public-license gap is material: the explicit Register license does not clearly grant reuse of the match archives. Written confirmation is needed before redistributing derived datasets or publishing a live benchmark. A separate first-party or licensed fixture/roster source is also needed.

If cleared, start with match-level T20 predictions at T-60m **before the toss**: winner probability and expected innings totals. Score winner probabilities with log loss/Brier and totals with MAE or CRPS. Exclude playing XI, toss, DLS revisions, impact-player state, and post-start corrections from the frozen track.

## Why the remaining sports are lower priority

### MLB

Retrosheet is the best permissive historical source in the field: its current site provides complete AL/NL play-by-play through 2025, and its use policy permits redistribution and commercial reuse with attribution. That supports a strong delayed or research benchmark. MLB.com's terms, however, prohibit automated collection and restrict MLB-hosted material to personal, non-commercial use. Daily probable pitchers and lineups also change close to game time. MLB should follow only with a separately licensed current feed or a clearly delayed annual release model.

### NHL

Official JSON endpoints expose schedules, rosters, box scores, and play-by-play, and NHL Fantasy Stars provides an objective daily scoring target. NHL's terms nevertheless restrict scraping, database entry, distribution, and derivative reuse. An undocumented endpoint is a technical convenience, not a license.

### NBA

NBA terms are the clearest blocker: NBA Statistics may not be used with a fantasy game or a comprehensive regularly updated database without consent. Official injury reports can update on game day, and NBA's own salary-cap fantasy formula differs from the NBA Stats glossary formula. The target is both legally and semantically less clean than NFL.

### Formula 1

Formula 1 publishes detailed fantasy rules and has a convenient weekend cadence, but its guidelines assert exclusive rights over results, timing, and statistics and prohibit text/data mining or AI use without express permission. Jolpica is non-commercial, OpenF1 is unofficial/personal-use, and neither reliably supplies every official fantasy label. Hold until rights and feed completeness are solved.

## Recommended sequence

1. **Two-week NFLBench feasibility spike:** source/license manifest, point-in-time schema, one historical freeze-and-score reconstruction, and one immutable sample board.
2. **Six-to-eight-week live NFL pilot:** no injury features, T-24h track only, public baselines, correction-aware scoring.
3. **SoccerBench prototype:** OpenFootball-only, fixed competitions, match probabilities and expected goals.
4. **Cricket diligence:** written archive-license confirmation plus live fixture/roster provenance; build only after both pass.

## Source register

### NFL

- nflverse data releases: https://github.com/nflverse/nflverse-data
- nflverse update schedule: https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
- nflreadpy documentation and licensing note: https://github.com/nflverse/nflreadpy/blob/main/docs/index.md
- Sleeper API documentation: https://docs.sleeper.com/
- NFL Football Operations important dates/injury reporting cadence: https://operations.nfl.com/calendar-events/nfl-important-dates
- NFL.com terms: https://www.nfl.com/legal/terms/
- NFL Fantasy official rules 2025: https://static.www.nfl.com/image/upload/v1745955215/league/apps/fantasy/media/rules/OfficialRules2025.pdf

### Soccer

- OpenFootball football.json: https://github.com/openfootball/football.json
- football-data.org pricing: https://www.football-data.org/pricing
- football-data.org coverage: https://www.football-data.org/coverage
- Hudl/StatsBomb open data: https://github.com/hudl/open-data
- UEFA terms: https://www.uefa.com/termsconditions/

### Cricket

- Cricsheet downloads: https://cricsheet.org/downloads/
- Cricsheet JSON format: https://cricsheet.org/format/json/
- Cricsheet Register and license: https://cricsheet.org/register/
- ICC website terms: https://www.icc-cricket.com/about/the-icc/legal-notices/website-terms-of-use

### MLB, NHL, NBA, Formula 1

- Retrosheet data-use policy: https://www.retrosheet.org/datause.html
- Retrosheet current coverage: https://www.retrosheet.org/index.html
- MLB terms: https://www.mlb.com/official-information/terms-of-use
- NHL terms: https://www.nhl.com/info/terms-of-service
- NHL Fantasy Stars: https://www.nhl.com/news/topic/fantasy/nhl-fantasy-stars-game-returns-for-2025-26-season
- NBA terms: https://www.nba.com/termsofuse
- NBA official injury reports: https://official.nba.com/nba-injury-report-2025-26-season/
- Formula 1 guidelines: https://www.formula1.com/en/information/guidelines.4EOKE9RRqevL4niTK9kWyt
- Jolpica F1 terms: https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md
- OpenF1 documentation: https://openf1.org/docs/

## Confidence and unresolved items

High confidence: relative recommendation of NFL first; viability of an OpenFootball-backed soccer match benchmark; NBA/NHL/F1 rights concerns; Retrosheet's historical usefulness.

Medium confidence: exact commercial path for an NFL product using Sleeper metadata; historic depth-chart timestamp consistency before 2025; cricket match-archive reuse rights.

Required before implementation expands beyond a research pilot: a narrow counsel review of upstream sports-data rights and marks, and written confirmation for any source whose terms do not explicitly cover the intended redistribution.
