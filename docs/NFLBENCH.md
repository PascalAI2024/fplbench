# NFLBench feasibility spike

NFLBench is a local research prototype for a leakage-safe NFL player-week benchmark. It is intentionally separate from the FPL package and public publication workflows.

## Contract

- Forecast unit: QB/RB/WR/TE player-week.
- Primary freeze: one immutable snapshot at least 24 hours before the first weekly kickoff.
- Target: fixed PPR (`4` passing TD, `6` rushing/receiving TD, `1/25` passing yard, `1/10` rushing/receiving yard, `1` reception, `-2` interception, `-2` lost fumble).
- Baselines: prior-four-game EWMA and prior-history position median.
- Primary metric: MAE over every frozen player, including explicit DNP rows with actual points equal to zero.
- Version 0 excludes injury features. NFL.com automation is not used in this
  feasibility slice pending a source-specific legal and operational review.
  That is a conservative scope decision, not a claim that public-page scraping
  is categorically unlawful.

## Integrity rules

1. All source rows carry `observed_at` and `source_revision`.
2. Any record observed after the cutoff fails closed.
3. Same-week and future outcomes are rejected from baseline history.
4. Missing actuals fail closed; frozen players are never silently removed.
5. Canonical forecast rows are sorted and serialized with fixed column and float formats before SHA-256 hashing.
6. The generated board labels itself synthetic and non-live.

## Build the deterministic sample

```bash
python scripts/build_nflbench_sample.py
```

Outputs land in `outputs/nflbench/sample/`:

- `forecasts.csv` — frozen baseline forecasts.
- `score.json` — reconstruction metrics.
- `manifest.json` — input and artifact hashes plus integrity policy.
- `board.html` — local evidence board.

The sample uses synthetic fixtures under `tests/fixtures/nflbench/`; it does not download or imply rights to NFL data. Source boundaries are recorded in `nflbench/sources.json`.
