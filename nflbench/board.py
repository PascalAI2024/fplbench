"""Small deterministic HTML evidence board for the NFLBench sample."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd


def render_sample_board(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    metrics: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    joined = forecasts.merge(
        actuals[["player_id", "fantasy_points", "played"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    rows = []
    for row in joined.itertuples(index=False):
        status = "Played" if int(row.played) else "DNP (0 retained)"
        rows.append(
            "<tr>"
            f"<td data-label=\"Player\">{escape(str(row.player_name))}</td>"
            f"<td data-label=\"Position\">{escape(str(row.position))}</td>"
            f"<td data-label=\"Matchup\">{escape(str(row.team))} vs {escape(str(row.opponent))}</td>"
            f"<td data-label=\"EWMA4\">{float(row.forecast_ewma4):.2f}</td>"
            f"<td data-label=\"Position median\">{float(row.forecast_position_median):.2f}</td>"
            f"<td data-label=\"Actual\">{float(row.fantasy_points):.2f}</td>"
            f"<td data-label=\"Status\">{status}</td>"
            "</tr>"
        )

    artifact_hash = escape(manifest["artifacts"]["forecasts.csv"]["sha256"])
    cutoff = escape(manifest["cutoff_at"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NFLBench sample evidence board</title>
  <style>
    :root {{ color-scheme: dark; --bg:#08111f; --panel:#111e31; --line:#29405f; --ink:#edf4ff; --muted:#a9bbd4; --accent:#5dd6a8; --warn:#ffd479; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(160deg,#08111f,#10213a); color:var(--ink); font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
    main {{ width:min(1120px,calc(100% - 32px)); margin:32px auto 56px; }}
    header,section {{ background:rgba(17,30,49,.96); border:1px solid var(--line); border-radius:16px; padding:24px; margin-bottom:18px; box-shadow:0 16px 42px rgba(0,0,0,.22); }}
    .eyebrow {{ color:var(--accent); font-weight:800; letter-spacing:.12em; text-transform:uppercase; font-size:.78rem; }}
    h1 {{ margin:.3rem 0 .5rem; font-size:clamp(2rem,6vw,3.4rem); line-height:1.04; }}
    h2 {{ margin:0 0 14px; font-size:1.35rem; }}
    p {{ color:var(--muted); max-width:78ch; }}
    .warning {{ color:var(--warn); font-weight:750; }}
    .metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-top:18px; }}
    .metric {{ background:#0b1728; border:1px solid var(--line); border-radius:12px; padding:14px; }}
    .metric span {{ display:block; color:var(--muted); font-size:.82rem; }}
    .metric strong {{ display:block; font-size:1.55rem; margin-top:3px; }}
    .table-wrap {{ overflow-x:auto; }}
    table {{ width:100%; border-collapse:collapse; min-width:780px; }}
    th,td {{ padding:12px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
    th:first-child,td:first-child,th:nth-child(3),td:nth-child(3),th:last-child,td:last-child {{ text-align:left; }}
    th {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; }}
    code {{ overflow-wrap:anywhere; color:var(--accent); }}
    @media (max-width:700px) {{
      main {{ width:min(100% - 20px,1120px); margin-top:10px; }}
      header,section {{ padding:18px; border-radius:12px; }}
      table {{ min-width:0; }}
      thead {{ position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }}
      tbody {{ display:grid; gap:12px; }}
      tbody tr {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 16px; padding:12px; background:#0b1728; border:1px solid var(--line); border-radius:10px; }}
      tbody td {{ display:flex; justify-content:space-between; gap:12px; padding:5px 0; border:0; text-align:right !important; white-space:normal; }}
      tbody td::before {{ content:attr(data-label); color:var(--muted); font-size:.74rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; text-align:left; }}
      tbody td:first-child {{ grid-column:1/-1; padding-bottom:9px; margin-bottom:3px; border-bottom:1px solid var(--line); font-weight:800; }}
      tbody td:last-child {{ grid-column:1/-1; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">NFLBench feasibility evidence</div>
    <h1>Week {int(metrics['week'])} sample board</h1>
    <p class="warning">Synthetic deterministic reconstruction. Not live, not published, and not a claim of model performance.</p>
    <p>Forecasts were frozen at <strong>{cutoff}</strong>. Every frozen player remains in the denominator; a later DNP scores zero.</p>
    <div class="metrics" aria-label="Sample score summary">
      <div class="metric"><span>Frozen players</span><strong>{int(metrics['n_frozen'])}</strong></div>
      <div class="metric"><span>DNP retained</span><strong>{int(metrics['n_dnp'])}</strong></div>
      <div class="metric"><span>EWMA4 MAE</span><strong>{float(metrics['mae_ewma4']):.3f}</strong></div>
      <div class="metric"><span>Position median MAE</span><strong>{float(metrics['mae_position_median']):.3f}</strong></div>
    </div>
  </header>
  <section>
    <h2>Frozen forecasts and realized PPR</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Player</th><th>Pos</th><th>Matchup</th><th>EWMA4</th><th>Pos median</th><th>Actual</th><th>Status</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </section>
  <section>
    <h2>Integrity proof</h2>
    <p>Forecast artifact SHA-256:</p>
    <code>{artifact_hash}</code>
    <p>The sample builder validates point-in-time timestamps, rejects same-week outcomes, uses fixed scoring weights, sorts canonical rows, and hashes exact CSV bytes.</p>
  </section>
</main>
</body>
</html>
"""
