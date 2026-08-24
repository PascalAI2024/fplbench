"""Build the living fplbench board (HF Space x0me/fplbench-board).

Regenerates the Space's static index.html from live data, preserving the
dark-pitch visual identity of the original hand-made GW1 board:

- header: current/next GW + a deadline countdown (deadline ISO embedded,
  small inline JS ticks it down),
- pitch view of the CURRENT applied team (entry picks; falls back to the
  latest GW whose picks are available and labels which GW is shown),
- team performance table (same data as scripts/track_team.py),
- model scoreboard (per-GW MAE rows parsed from RESULTS.md),
- footer links (GitHub repo, HF dataset, official team page).

Everything is rendered server-side in Python; the only JS on the page is the
countdown ticker. Output: outputs/board/index.html + outputs/board/README.md
(upload with scripts/publish_space.py).

Usage:
  python scripts/build_board.py
  python scripts/build_board.py --out outputs/board --results RESULTS.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from track_team import (  # noqa: E402
    API,
    ENTRY_ID,
    TEAM_NAME,
    TEAM_URL,
    _get_json,
    build_team_rows,
)

from fplbench.score import split_results_md  # noqa: E402

GITHUB_URL = "https://github.com/PascalAI2024/fplbench"
DATASET_URL = "https://huggingface.co/datasets/x0me/fplbench"
DEFAULT_OUT = ROOT / "outputs" / "board"
DEFAULT_RESULTS = ROOT / "RESULTS.md"

POS_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# Vertical placement per XI row, % of pitch height (GK at the bottom).
ROW_Y = {"GK": 84, "DEF": 64, "MID": 39, "FWD": 16}

SPACE_README = """\
---
title: fplbench board
emoji: "⚽"
colorFrom: green
colorTo: purple
sdk: static
pinned: false
---

Living board for the fplbench model — regenerated from live FPL data by
[scripts/build_board.py](https://github.com/PascalAI2024/fplbench/blob/main/scripts/build_board.py)
on every fplbench workflow run.

- Dataset: https://huggingface.co/datasets/x0me/fplbench
- Code + weekly self-scoring: https://github.com/PascalAI2024/fplbench
- The model's team in the official FPL game: https://fantasy.premierleague.com/entry/4770634/history
"""


# ---------------------------------------------------------------- live data


def fetch_bootstrap() -> dict:
    return _get_json(f"{API}/bootstrap-static/")


def gw_context(bootstrap: dict) -> dict[str, Any]:
    """Current/next GW ids and the next deadline (ISO) from bootstrap events."""
    events = bootstrap.get("events") or []
    current = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)
    finished = [int(e["id"]) for e in events if e.get("finished")]
    return {
        "current_gw": int(current["id"]) if current else None,
        "next_gw": int(nxt["id"]) if nxt else None,
        "next_deadline": (nxt or {}).get("deadline_time"),
        "finished_gws": sorted(finished, reverse=True),
    }


def fetch_picks(entry_id: int, ctx: dict[str, Any]) -> tuple[int, dict] | None:
    """Picks for the latest available GW.

    The next GW's picks 404 before its deadline, so try next → current →
    finished GWs descending, and report which GW actually answered.
    """
    candidates: list[int] = []
    for gw in [ctx.get("next_gw"), ctx.get("current_gw"), *ctx.get("finished_gws", [])]:
        if gw is not None and gw not in candidates:
            candidates.append(int(gw))
    for gw in candidates:
        try:
            picks = _get_json(f"{API}/entry/{entry_id}/event/{gw}/picks/")
        except requests.RequestException:
            continue
        if picks.get("picks"):
            return gw, picks
    return None


def fetch_live_points(gw: int) -> dict[int, dict[str, Any]]:
    """element id -> {points, minutes} for one GW; empty when unavailable."""
    try:
        live = _get_json(f"{API}/event/{gw}/live/")
    except requests.RequestException:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for el in live.get("elements") or []:
        stats = el.get("stats") or {}
        out[int(el["id"])] = {
            "points": stats.get("total_points"),
            "minutes": stats.get("minutes"),
        }
    return out


def build_squad(bootstrap: dict, picks: dict, live: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per pick (position 1-15), enriched from bootstrap + live."""
    elements = {int(e["id"]): e for e in bootstrap.get("elements") or []}
    teams = {int(t["id"]): t for t in bootstrap.get("teams") or []}
    squad: list[dict[str, Any]] = []
    for pick in sorted(picks.get("picks") or [], key=lambda p: int(p["position"])):
        el = elements.get(int(pick["element"])) or {}
        team = teams.get(int(el.get("team") or 0)) or {}
        stats = live.get(int(pick["element"])) or {}
        squad.append(
            {
                "slot": int(pick["position"]),
                "name": el.get("web_name", f"#{pick['element']}"),
                "pos": POS_BY_TYPE.get(int(el.get("element_type") or 0), "MID"),
                "club": team.get("short_name") or team.get("name") or "",
                "captain": bool(pick.get("is_captain")),
                "vice": bool(pick.get("is_vice_captain")),
                "multiplier": int(pick.get("multiplier") or 0),
                "points": stats.get("points"),
                "minutes": stats.get("minutes"),
            }
        )
    return squad


# ---------------------------------------------------------------- rendering


def _chip(p: dict[str, Any], x: float, y: float) -> str:
    minutes = p.get("minutes")
    gate = max(0.0, min(1.0, (minutes or 0) / 90.0))
    circ = 2 * 3.141592653589793 * 10
    dash = f"{gate * circ:.2f} {circ:.2f}"
    badge = ""
    if p["captain"]:
        label = "TC" if p.get("multiplier") == 3 else "C"
        badge = f'<span class="arm">{label}</span>'
    elif p["vice"]:
        badge = '<span class="arm vice">V</span>'
    pts = "—" if p.get("points") is None else str(p["points"])
    cls = "chip" + (" cap" if p["captain"] or p["vice"] else "")
    return (
        f'<div class="{cls}" style="left:{x:.1f}%;top:{y:.1f}%">'
        '<svg class="ring" viewBox="0 0 26 26" aria-hidden="true">'
        '<circle class="bg" cx="13" cy="13" r="10"></circle>'
        f'<circle class="fg" cx="13" cy="13" r="10" stroke-dasharray="{dash}"></circle>'
        "</svg>"
        f"{badge}"
        f'<span class="nm">{html.escape(str(p["name"]))}</span>'
        f'<span class="pts">{pts}</span>'
        f'<span class="club">{html.escape(str(p["club"]))}</span>'
        "</div>"
    )


def render_chips(squad: list[dict[str, Any]]) -> tuple[str, str, str]:
    """(xi chips html, bench chips html, formation string like 4-4-2)."""
    xi = [p for p in squad if p["slot"] <= 11]
    bench = [p for p in squad if p["slot"] > 11]
    rows: dict[str, list[dict[str, Any]]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for p in xi:
        rows[p["pos"] if p["pos"] in rows else "MID"].append(p)
    pitch_parts: list[str] = []
    for pos, arr in rows.items():
        n = len(arr)
        for i, p in enumerate(arr):
            x = 50.0 if n <= 1 else 13 + (74.0 * i) / (n - 1)
            pitch_parts.append(_chip(p, x, ROW_Y[pos]))
    bench_parts: list[str] = []
    n = max(len(bench), 1)
    for i, p in enumerate(bench):
        x = 18.0 if n <= 1 else 12 + (76.0 * i) / (n - 1)
        bench_parts.append(_chip(p, x, 52.0))
    formation = "-".join(str(len(rows[k])) for k in ("DEF", "MID", "FWD"))
    return "".join(pitch_parts), "".join(bench_parts), formation


def team_table_html(team_rows: list[dict[str, Any]]) -> str:
    if not team_rows:
        return '<p class="note">No gameweek data yet — the first row lands once GW1 kicks off.</p>'
    body = []
    for r in sorted(team_rows, key=lambda x: x["gw"]):
        gw = f"{r['gw']} (live)" if r["live"] else str(r["gw"])
        vs = r["vs_avg"]
        vs_cell = "—" if vs is None else (f"+{vs}" if vs > 0 else str(vs))
        rank = r["overall_rank"]
        body.append(
            "<tr>"
            f"<td>{html.escape(gw)}</td>"
            f"<td>{'—' if r['points'] is None else r['points']}</td>"
            f"<td>{'—' if r['average'] is None else r['average']}</td>"
            f"<td>{vs_cell}</td>"
            f"<td>{'—' if rank is None else format(rank, ',')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>GW</th><th>pts</th><th>avg</th><th>vs avg</th>"
        "<th>rank</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def _fmt(v: Any) -> str:
    import math

    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.4f}"


def mae_table_html(mae_rows: dict[int, dict]) -> str:
    if not mae_rows:
        return '<p class="note">No finished gameweek scored yet — the first row lands after GW1.</p>'
    body = []
    for gw in sorted(mae_rows):
        m = mae_rows[gw]
        body.append(
            "<tr>"
            f"<td>{gw}</td><td>{m['n_common']}</td>"
            f"<td>{_fmt(m['mae_model'])}</td><td>{_fmt(m['mae_ep_next'])}</td>"
            f"<td>{m['n_played']}</td>"
            f"<td>{_fmt(m['mae_model_played'])}</td>"
            f"<td>{_fmt(m['mae_ep_next_played'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>GW</th><th>n_common</th><th>mae_model</th>"
        "<th>mae_ep_next</th><th>n_played</th><th>mae_model_played</th>"
        "<th>mae_ep_next_played</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fplbench board</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #030705; color: #e8f6ec; }}
  body {{
    font-family: "Segoe UI", "Helvetica Neue", ui-sans-serif, system-ui, sans-serif;
    min-height: 100vh;
    display: flex;
    justify-content: center;
  }}
  #board {{
    width: 1280px;
    min-height: 800px;
    box-sizing: border-box;
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background:
      radial-gradient(1200px 500px at 40% -10%, rgba(80,160,90,0.18), transparent 55%),
      radial-gradient(700px 400px at 100% 100%, rgba(180,70,90,0.12), transparent 50%),
      #07140d;
    color: #e8f6ec;
  }}
  #board * {{ box-sizing: border-box; }}
  .topbar {{
    height: 72px;
    flex: 0 0 72px;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 0 20px;
    border-bottom: 1px solid rgba(180, 220, 180, 0.12);
    background: linear-gradient(180deg, rgba(0,0,0,0.35), transparent);
  }}
  .brand {{
    letter-spacing: 0.22em;
    font-size: 11px;
    text-transform: uppercase;
    color: #9dceaa;
    min-width: 132px;
  }}
  .brand b {{ display: block; color: #f3fff4; letter-spacing: 0.28em; font-size: 13px; }}
  .stat {{
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 92px;
  }}
  .stat em {{
    font-style: normal;
    font-size: 10px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #7f9a86;
  }}
  .stat strong {{ font-size: 16px; font-variant-numeric: tabular-nums; color: #f4ffe8; }}
  .stat.gold strong {{ color: #f0c14b; }}
  .stat.lime strong {{ color: #dff36a; }}
  .stage {{ flex: 1; display: flex; min-height: 620px; }}
  .field-col {{
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    padding: 10px 12px 12px 16px;
    gap: 8px;
  }}
  .pitch {{
    position: relative;
    flex: 1;
    min-height: 460px;
    border-radius: 18px;
    overflow: hidden;
    box-shadow:
      inset 0 0 0 1px rgba(255,255,255,0.08),
      0 20px 50px rgba(0,0,0,0.45);
  }}
  .pitch svg.grass {{ position: absolute; inset: 0; width: 100%; height: 100%; display: block; }}
  #chips {{ position: absolute; inset: 0; }}
  .story {{
    position: absolute;
    left: 14px;
    top: 10px;
    z-index: 3;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(232,246,236,0.78);
    text-shadow: 0 1px 8px rgba(0,0,0,0.7);
    pointer-events: none;
  }}
  .chip {{
    position: absolute;
    width: 112px;
    height: 78px;
    margin: -39px 0 0 -56px;
    border: 1px solid rgba(210,255,210,0.16);
    background: rgba(6, 16, 11, 0.82);
    color: inherit;
    border-radius: 12px;
    padding: 7px 8px 6px 34px;
    text-align: left;
    font: inherit;
    box-shadow: 0 8px 18px rgba(0,0,0,0.35);
  }}
  .chip.cap {{ border-color: rgba(240,193,75,0.55); }}
  .chip .nm {{
    display: block;
    font-size: 12px;
    font-weight: 650;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .chip .pts {{
    display: block;
    margin-top: 2px;
    font-size: 20px;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.03em;
    color: #b8ffcf;
  }}
  .chip .club {{
    display: block;
    font-size: 10px;
    color: #8ea894;
    letter-spacing: 0.04em;
  }}
  .ring {{
    position: absolute;
    left: 6px;
    top: 14px;
    width: 26px;
    height: 26px;
  }}
  .ring circle {{ fill: none; stroke-width: 3; }}
  .ring .bg {{ stroke: rgba(255,255,255,0.12); }}
  .ring .fg {{
    stroke: #7dffc3;
    transform: rotate(-90deg);
    transform-origin: 13px 13px;
  }}
  .arm {{
    position: absolute;
    right: 6px;
    top: 6px;
    min-width: 16px;
    height: 16px;
    border-radius: 8px;
    background: #f0c14b;
    color: #211600;
    font-size: 10px;
    font-weight: 800;
    line-height: 16px;
    text-align: center;
    padding: 0 2px;
  }}
  .arm.vice {{ background: rgba(240,193,75,0.35); color: #f3e7bd; }}
  .dugout {{
    position: relative;
    height: 118px;
    flex: 0 0 118px;
    border-radius: 14px;
    background:
      repeating-linear-gradient(90deg, rgba(255,255,255,0.03) 0 18px, transparent 18px 36px),
      linear-gradient(180deg, #14110d, #0c0b09);
    border: 1px solid rgba(240,193,75,0.18);
  }}
  .dugout label {{
    position: absolute;
    left: 12px;
    top: 8px;
    font-size: 10px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #c8b27a;
  }}
  #bench-chips {{ position: absolute; inset: 22px 8px 8px 8px; }}
  #panel {{
    width: 338px;
    flex: 0 0 338px;
    padding: 16px 18px 18px;
    background: linear-gradient(180deg, rgba(8,14,12,0.96), rgba(6,10,9,0.98));
    border-left: 1px solid rgba(180,220,180,0.12);
    display: flex;
    flex-direction: column;
    min-height: 0;
    gap: 6px;
  }}
  .kicker {{
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #86a38c;
    margin-top: 10px;
  }}
  .kicker:first-child {{ margin-top: 0; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }}
  th, td {{
    padding: 7px 8px;
    text-align: right;
    border-top: 1px solid rgba(180,220,180,0.1);
    white-space: nowrap;
  }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7f9a86;
    border-top: 0;
  }}
  .tables {{
    padding: 4px 18px 14px;
    border-top: 1px solid rgba(180,220,180,0.12);
    background: linear-gradient(180deg, rgba(0,0,0,0.25), transparent);
  }}
  .note {{
    font-size: 11px;
    line-height: 1.45;
    color: #7f9486;
    margin: 12px 0 0;
  }}
  footer {{
    display: flex;
    gap: 22px;
    padding: 12px 20px 16px;
    border-top: 1px solid rgba(180,220,180,0.12);
    font-size: 12px;
  }}
  footer a {{ color: #9dceaa; text-decoration: none; }}
  footer a:hover {{ color: #dff36a; }}
  .scan {{
    pointer-events: none;
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      to bottom,
      rgba(255,255,255,0.015) 0 1px,
      transparent 1px 3px
    );
    z-index: 5;
  }}
</style>
</head>
<body>
<div id="board">
  <header class="topbar">
    <div class="brand">fplbench<b>board</b></div>
    <div class="stat"><em>Showing</em><strong>GW{shown_gw}</strong></div>
    <div class="stat lime"><em>{deadline_label}</em><strong id="countdown">—</strong></div>
    <div class="stat gold"><em>Captain</em><strong>{captain}</strong></div>
    <div class="stat"><em>GW pts</em><strong>{gw_pts}</strong></div>
    <div class="stat"><em>Total pts</em><strong>{total_pts}</strong></div>
    <div class="stat"><em>Overall rank</em><strong>{rank}</strong></div>
  </header>
  <div class="stage">
    <div class="field-col">
      <div class="pitch">
        <svg class="grass" viewBox="0 0 1050 680" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="night" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#1a4a28"/>
              <stop offset="1" stop-color="#0c2416"/>
            </linearGradient>
          </defs>
          <rect width="1050" height="680" fill="url(#night)"/>
          <g>
            <rect y="0" width="1050" height="68" fill="#143820"/>
            <rect y="136" width="1050" height="68" fill="#143820"/>
            <rect y="272" width="1050" height="68" fill="#143820"/>
            <rect y="408" width="1050" height="68" fill="#143820"/>
            <rect y="544" width="1050" height="68" fill="#143820"/>
          </g>
          <g fill="none" stroke="rgba(236,246,232,0.55)" stroke-width="3">
            <rect x="60" y="40" width="930" height="600" rx="4"/>
            <line x1="60" y1="340" x2="990" y2="340"/>
            <circle cx="525" cy="340" r="92"/>
            <circle cx="525" cy="340" r="4" fill="rgba(236,246,232,0.8)" stroke="none"/>
            <rect x="270" y="40" width="510" height="165"/>
            <rect x="365" y="40" width="320" height="72"/>
            <rect x="270" y="475" width="510" height="165"/>
            <rect x="365" y="568" width="320" height="72"/>
            <path d="M 434 205 A 92 92 0 0 0 616 205"/>
            <path d="M 434 475 A 92 92 0 0 1 616 475"/>
            <rect x="478" y="28" width="94" height="12"/>
            <rect x="478" y="640" width="94" height="12"/>
          </g>
        </svg>
        <div class="story">{formation} · {team_name} · GW{shown_gw} picks</div>
        <div id="chips">{xi_chips}</div>
      </div>
      <div class="dugout">
        <label>Bench</label>
        <div id="bench-chips">{bench_chips}</div>
      </div>
    </div>
    <aside id="panel">
      <div class="kicker">team performance</div>
      {team_table}
      <p class="note">The model's own squad in the official FPL game —
      rings show minutes played this GW, C/V mark captain and vice.
      Regenerated from the official FPL API on every fplbench run.</p>
    </aside>
  </div>
  <section class="tables">
    <div class="kicker">model scoreboard — e_points_final MAE vs FPL ep_next (2026/27)</div>
    {mae_table}
  </section>
  <footer>
    <a href="{github_url}">GitHub: PascalAI2024/fplbench</a>
    <a href="{dataset_url}">HF dataset: x0me/fplbench</a>
    <a href="{team_url}">Official team page (entry {entry_id})</a>
    <span style="margin-left:auto;color:#7f9486">generated {generated}</span>
  </footer>
  <div class="scan"></div>
</div>
<script>
(function () {{
  var deadline = {deadline_js};
  var el = document.getElementById("countdown");
  if (!deadline) {{ el.textContent = "—"; return; }}
  var t = new Date(deadline).getTime();
  function pad(n) {{ return (n < 10 ? "0" : "") + n; }}
  function tick() {{
    var ms = t - Date.now();
    if (ms <= 0) {{ el.textContent = "deadline passed"; return; }}
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600);
    var m = Math.floor((s % 3600) / 60);
    el.textContent = (d > 0 ? d + "d " : "") + pad(h) + "h " + pad(m) + "m " + pad(s % 60) + "s";
    setTimeout(tick, 1000);
  }}
  tick();
}})();
</script>
</body>
</html>
"""


def build_page(results_path: Path) -> str:
    bootstrap = fetch_bootstrap()
    ctx = gw_context(bootstrap)
    got = fetch_picks(ENTRY_ID, ctx)
    if got is None:
        raise SystemExit("no picks available for any gameweek yet")
    shown_gw, picks = got
    live = fetch_live_points(shown_gw)
    squad = build_squad(bootstrap, picks, live)
    xi_chips, bench_chips, formation = render_chips(squad)

    team_rows = build_team_rows()
    latest = max(team_rows, key=lambda r: r["gw"]) if team_rows else None
    captain = next((p["name"] for p in squad if p["captain"]), "—")
    entry_hist = picks.get("entry_history") or {}
    gw_pts = entry_hist.get("points")
    total_pts = entry_hist.get("total_points")
    rank = entry_hist.get("overall_rank") or (latest or {}).get("overall_rank")

    _, mae_rows, _ = split_results_md(
        results_path.read_text(encoding="utf-8") if results_path.exists() else ""
    )

    deadline = ctx.get("next_deadline")
    if deadline and ctx.get("next_gw") is not None:
        deadline_label = f"GW{ctx['next_gw']} deadline"
        deadline_js = f'"{deadline}"'
    else:
        deadline_label = "Next deadline"
        deadline_js = "null"

    return PAGE.format(
        shown_gw=shown_gw,
        deadline_label=html.escape(deadline_label),
        deadline_js=deadline_js,
        captain=html.escape(str(captain)),
        gw_pts="—" if gw_pts is None else gw_pts,
        total_pts="—" if total_pts is None else total_pts,
        rank="—" if rank is None else format(rank, ","),
        formation=formation,
        team_name=html.escape(TEAM_NAME),
        xi_chips=xi_chips,
        bench_chips=bench_chips,
        team_table=team_table_html(team_rows),
        mae_table=mae_table_html(mae_rows),
        github_url=GITHUB_URL,
        dataset_url=DATASET_URL,
        team_url=TEAM_URL,
        entry_id=ENTRY_ID,
        generated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Build the fplbench board Space files")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = p.parse_args(argv)

    page = build_page(args.results)
    args.out.mkdir(parents=True, exist_ok=True)
    index = args.out / "index.html"
    readme = args.out / "README.md"
    index.write_text(page, encoding="utf-8")
    readme.write_text(SPACE_README, encoding="utf-8")
    print(f"wrote {index} ({len(page)} chars)")
    print(f"wrote {readme}")


if __name__ == "__main__":
    main()
