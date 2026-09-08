"""Build the living fplbench board (HF Space x0me/fplbench-board).

Regenerates the Space's static index.html from live data, preserving the
dark-pitch visual identity of the original hand-made GW1 board:

- header: current/next GW + a deadline countdown (deadline ISO embedded,
  small inline JS ticks it down),
- pitch view of the CURRENT applied team (entry picks; falls back to the
  latest GW whose picks are available and labels which GW is shown),
- team performance table (same data as scripts/track_team.py),
- model scoreboard (per-GW MAE rows parsed from RESULTS.md),
- one responsive provisional data preview for every official FPL club,
- footer links (GitHub repo, HF dataset, official team page).

Everything is rendered server-side in Python; the only JS on the page is the
countdown ticker. Output: outputs/board/index.html,
outputs/board/teams/<slug>/index.html, and outputs/board/README.md (upload with
scripts/publish_space.py).

Usage:
  python scripts/build_board.py
  python scripts/build_board.py --out outputs/board --results RESULTS.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import posixpath
import re
import sys
import unicodedata
from html.parser import HTMLParser
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
PORTFOLIO_URL = "https://github.com/PascalAI2024/portfolio"
RESULTS_URL = f"{GITHUB_URL}/blob/main/RESULTS.md"
DEFAULT_OUT = ROOT / "outputs" / "board"
DEFAULT_RESULTS = ROOT / "RESULTS.md"

POS_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# Vertical placement per XI row, % of pitch height (GK at the bottom).
ROW_Y = {"GK": 84, "DEF": 64, "MID": 39, "FWD": 16}

SPACE_README = """\
---
title: "fplbench — live benchmark"
emoji: "⚽"
colorFrom: green
colorTo: yellow
sdk: static
app_file: index.html
license: other
fullWidth: true
header: mini
pinned: false
short_description: "Leakage-safe FPL forecasts, frozen then scored in public."
datasets:
  - x0me/fplbench
tags:
  - fantasy-premier-league
  - football
  - machine-learning
  - forecasting
  - tabular
  - time-series
thumbnail: https://raw.githubusercontent.com/PascalAI2024/fplbench/main/docs/img/social.png
---

The public operating surface for **fplbench**: a leakage-safe Fantasy Premier
League model whose forecast is committed before the deadline, entered as a
real team, and scored after each officially verified gameweek.

- [Explore the dataset](https://huggingface.co/datasets/x0me/fplbench)
- [Inspect the code and frozen forecasts](https://github.com/PascalAI2024/fplbench)
- [Read the public score record](https://github.com/PascalAI2024/fplbench/blob/main/RESULTS.md)
- [View the model's official FPL team](https://fantasy.premierleague.com/entry/4770634/history)
- Browse the current official club previews from the board's club navigation.

The board is regenerated from public FPL data by
[`scripts/build_board.py`](https://github.com/PascalAI2024/fplbench/blob/main/scripts/build_board.py).
Live and post-match-review values remain visibly provisional. Model scores are
published only when FPL marks the gameweek both `finished` and `data_checked`.
"""


# ---------------------------------------------------------------- live data


def fetch_bootstrap() -> dict:
    return _get_json(f"{API}/bootstrap-static/")


def fetch_fixtures() -> list[dict[str, Any]]:
    """Current official fixture list; fail soft for preview-only team pages."""
    try:
        payload = _get_json(f"{API}/fixtures/")
    except requests.RequestException:
        return []
    return payload if isinstance(payload, list) else []


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


def team_slug(team: dict[str, Any]) -> str:
    """Stable, URL-safe season slug derived from the official team name."""
    raw = str(team.get("name") or team.get("short_name") or team.get("id") or "team")
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or f"team-{int(team.get('id') or 0)}"


def official_teams(bootstrap: dict) -> list[dict[str, Any]]:
    """Official clubs in deterministic display order with unique stable slugs."""
    teams = sorted(
        (dict(team) for team in bootstrap.get("teams") or []),
        key=lambda team: (str(team.get("name") or "").casefold(), int(team.get("id") or 0)),
    )
    seen: dict[str, int] = {}
    for team in teams:
        base = team_slug(team)
        seen[base] = seen.get(base, 0) + 1
        team["slug"] = base if seen[base] == 1 else f"{base}-{int(team.get('id') or seen[base])}"
    return teams


def club_nav_html(teams: list[dict[str, Any]], *, from_team_page: bool = False) -> str:
    """Links to every generated club preview from the board or a club page."""
    links = []
    for team in teams:
        slug = str(team["slug"])
        href = f"../{slug}/index.html" if from_team_page else f"teams/{slug}/index.html"
        links.append(
            f'<a class="club-link" href="{href}">'
            f'{html.escape(str(team.get("short_name") or team.get("name") or slug))}</a>'
        )
    return "".join(links)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = {key: value or "" for key, value in attrs}
        self.links.append(values)


def page_links(page: str) -> list[dict[str, str]]:
    parser = _LinkParser()
    parser.feed(page)
    return parser.links


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
    roles = []
    if p["captain"]:
        roles.append("triple captain" if p.get("multiplier") == 3 else "captain")
    elif p["vice"]:
        roles.append("vice captain")
    role_text = f", {', '.join(roles)}" if roles else ""
    minute_text = "minutes unavailable" if minutes is None else f"{minutes} minutes"
    aria = html.escape(
        f"{p['name']}, {pts} points, {p['club']}, {minute_text}{role_text}",
        quote=True,
    )
    return (
        f'<div class="{cls}" role="img" aria-label="{aria}" '
        f'style="left:{x:.1f}%;top:{y:.1f}%">'
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
        return '<p class="note">No public team record is available yet.</p>'
    body = []
    for r in sorted(team_rows, key=lambda x: x["gw"]):
        status = r.get("status") or ("live" if r["live"] else "final")
        gw = f"{r['gw']} ({status})" if status != "final" else str(r["gw"])
        vs = r["vs_avg"]
        vs_cell = "—" if vs is None else (f"+{vs}" if vs > 0 else str(vs))
        rank = r["overall_rank"]
        body.append(
            "<tr>"
            f'<th scope="row">{html.escape(gw)}</th>'
            f"<td>{'—' if r['points'] is None else r['points']}</td>"
            f"<td>{'—' if r['average'] is None else r['average']}</td>"
            f"<td>{vs_cell}</td>"
            f"<td>{'—' if rank is None else format(rank, ',')}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll" role="region" '
        'aria-label="Team performance table" tabindex="0">'
        '<table><caption class="sr-only">Official team points and rank by gameweek; '
        'rows marked live or review are provisional.</caption><thead><tr>'
        '<th scope="col">GW</th><th scope="col">pts</th><th scope="col">avg</th>'
        '<th scope="col">vs avg</th><th scope="col">rank</th></tr></thead><tbody>'
        + "".join(body)
        + "</tbody></table></div>"
    )


def _fmt(v: Any) -> str:
    import math

    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.4f}"


def mae_table_html(mae_rows: dict[int, dict]) -> str:
    if not mae_rows:
        return '<p class="note">No officially verified gameweek has been scored yet.</p>'
    body = []
    for gw in sorted(mae_rows):
        m = mae_rows[gw]
        body.append(
            "<tr>"
            f'<th scope="row">{gw}</th><td>{m["n_common"]}</td>'
            f"<td>{_fmt(m['mae_model'])}</td><td>{_fmt(m['mae_ep_next'])}</td>"
            f"<td>{m['n_played']}</td>"
            f"<td>{_fmt(m['mae_model_played'])}</td>"
            f"<td>{_fmt(m['mae_ep_next_played'])}</td>"
            "</tr>"
        )
    return (
        '<div class="table-scroll" role="region" '
        'aria-label="Model accuracy table" tabindex="0">'
        '<table><caption class="sr-only">Mean absolute error by officially verified '
        'gameweek; lower is better.</caption><thead><tr>'
        '<th scope="col">GW</th><th scope="col">n_common</th>'
        '<th scope="col">mae_model</th><th scope="col">mae_ep_next</th>'
        '<th scope="col">n_played</th><th scope="col">mae_model_played</th>'
        '<th scope="col">mae_ep_next_played</th></tr></thead><tbody>'
        + "".join(body)
        + "</tbody></table></div>"
    )


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="fplbench freezes Fantasy Premier League forecasts before the deadline, runs the team, and scores the model in public.">
<meta name="theme-color" content="#07140d">
<title>fplbench board</title>
<style>
  html {{ color-scheme: dark; background: #030705; }}
  html, body {{ margin: 0; padding: 0; background: #030705; color: #e8f6ec; }}
  body {{
    font-family: "Segoe UI", "Helvetica Neue", ui-sans-serif, system-ui, sans-serif;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    overflow-x: hidden;
  }}
  #board {{
    --chip-w: 112px;
    --chip-h: 78px;
    width: min(100%, 1280px);
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
  .sr-only {{
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }}
  .topbar {{
    min-height: 72px;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 18px;
    padding: 12px 20px;
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
  .live-pill {{
    display: inline-flex;
    margin-top: 5px;
    padding: 3px 6px;
    border: 1px solid rgba(125,255,195,0.3);
    border-radius: 999px;
    color: #7dffc3;
    font-size: 8px;
    letter-spacing: 0.12em;
  }}
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
  .stage {{
    flex: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 338px;
    min-height: 0;
  }}
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
    min-height: 0;
    aspect-ratio: 1050 / 680;
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
    width: var(--chip-w);
    height: var(--chip-h);
    margin: calc(var(--chip-h) / -2) 0 0 calc(var(--chip-w) / -2);
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
  .dugout-title {{
    position: absolute;
    left: 12px;
    top: 8px;
    margin: 0;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #c8b27a;
  }}
  #bench-chips {{ position: absolute; inset: 22px 8px 8px 8px; }}
  #panel {{
    min-width: 0;
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
    font-weight: 600;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #86a38c;
    margin: 10px 0 0;
  }}
  .kicker:first-child {{ margin-top: 0; }}
  .eyebrow {{
    color: #7dffc3;
    font-size: 9px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
  }}
  #panel h2 {{
    max-width: 13ch;
    margin: 5px 0 4px;
    color: #f3fff4;
    font-size: clamp(22px, 2.2vw, 31px);
    line-height: 1.03;
    letter-spacing: -0.035em;
  }}
  .panel-intro {{
    margin: 6px 0 10px;
    color: #9db3a3;
    font-size: 12px;
    line-height: 1.5;
  }}
  .actions {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 7px;
    margin: 4px 0 10px;
  }}
  .action {{
    display: flex;
    min-height: 36px;
    align-items: center;
    justify-content: center;
    padding: 8px 10px;
    border: 1px solid rgba(125,255,195,0.24);
    border-radius: 8px;
    background: rgba(125,255,195,0.06);
    color: #b8ffcf;
    font-size: 11px;
    font-weight: 650;
    text-align: center;
    text-decoration: none;
  }}
  .action:hover, .action:focus-visible {{
    border-color: rgba(223,243,106,0.75);
    color: #dff36a;
    outline: 2px solid #dff36a;
    outline-offset: 2px;
  }}
  .legend {{
    display: grid;
    gap: 5px;
    margin: 8px 0 2px;
    color: #8fa395;
    font-size: 10px;
    line-height: 1.35;
  }}
  .legend span::before {{
    content: "";
    display: inline-block;
    width: 7px;
    height: 7px;
    margin-right: 7px;
    border: 1px solid #7dffc3;
    border-radius: 50%;
  }}
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
  .table-scroll {{
    width: 100%;
    overflow-x: auto;
    overscroll-behavior-inline: contain;
    scrollbar-color: #466552 transparent;
  }}
  .table-scroll:focus-visible {{
    outline: 1px solid #7dffc3;
    outline-offset: 3px;
  }}
  .tables {{
    padding: 4px 18px 14px;
    border-top: 1px solid rgba(180,220,180,0.12);
    background: linear-gradient(180deg, rgba(0,0,0,0.25), transparent);
  }}
  .clubs {{
    padding: 8px 18px 18px;
    border-top: 1px solid rgba(180,220,180,0.12);
  }}
  .club-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
    gap: 7px;
    margin-top: 10px;
  }}
  .club-link {{
    display: flex;
    min-height: 34px;
    align-items: center;
    justify-content: center;
    padding: 7px;
    border: 1px solid rgba(125,255,195,0.18);
    border-radius: 8px;
    color: #b8ffcf;
    background: rgba(125,255,195,0.04);
    font-size: 10px;
    letter-spacing: 0.05em;
    text-decoration: none;
  }}
  .club-link:hover, .club-link:focus-visible {{
    color: #dff36a;
    border-color: rgba(223,243,106,0.75);
    outline: 2px solid #dff36a;
    outline-offset: 2px;
  }}
  .note {{
    font-size: 11px;
    line-height: 1.45;
    color: #7f9486;
    margin: 12px 0 0;
  }}
  footer {{
    display: flex;
    flex-wrap: wrap;
    gap: 22px;
    padding: 12px 20px 16px;
    border-top: 1px solid rgba(180,220,180,0.12);
    font-size: 12px;
  }}
  footer a {{ color: #9dceaa; text-decoration: none; }}
  footer a:hover, footer a:focus-visible {{ color: #dff36a; }}
  footer a:focus-visible {{ outline: 2px solid #dff36a; outline-offset: 3px; }}
  footer .generated {{ margin-left: auto; color: #7f9486; }}
  @media (max-width: 900px) {{
    .stage {{ grid-template-columns: minmax(0, 1fr); }}
    .pitch {{ aspect-ratio: 1.32; }}
    #panel {{
      border-top: 1px solid rgba(180,220,180,0.12);
      border-left: 0;
    }}
    #panel h2 {{ max-width: none; }}
  }}
  @media (max-width: 600px) {{
    #board {{
      --chip-w: clamp(48px, 15.5vw, 58px);
      --chip-h: 56px;
      min-height: 100vh;
    }}
    .topbar {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 11px 9px;
      padding: 14px 16px 16px;
    }}
    .brand {{ grid-column: 1 / -1; min-width: 0; }}
    .stat {{ min-width: 0; }}
    .stat em {{ font-size: 8px; letter-spacing: 0.1em; }}
    .stat strong {{ font-size: 14px; overflow-wrap: anywhere; }}
    .field-col {{ padding: 10px 12px 12px; gap: 9px; }}
    .pitch {{
      aspect-ratio: 0.78;
      border-radius: 13px;
    }}
    .story {{
      top: 8px;
      left: 10px;
      max-width: calc(100% - 20px);
      font-size: 9px;
      letter-spacing: 0.04em;
    }}
    .chip {{
      padding: 6px 3px 4px 21px;
      border-radius: 8px;
    }}
    .chip .nm {{ font-size: 9px; }}
    .chip .pts {{ margin-top: 2px; font-size: 16px; }}
    .chip .club {{ display: none; }}
    .ring {{ left: 3px; top: 18px; width: 18px; height: 18px; }}
    .arm {{ right: 2px; top: 2px; transform: scale(0.82); transform-origin: top right; }}
    .dugout {{ height: 102px; flex-basis: 102px; }}
    #bench-chips {{ inset: 22px 2px 4px; }}
    #panel {{ padding: 18px 16px 20px; }}
    .actions {{ margin-bottom: 14px; }}
    .tables {{ padding: 7px 16px 16px; }}
    .clubs {{ padding: 8px 16px 18px; }}
    .club-grid {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    footer {{ gap: 10px 16px; padding: 14px 16px 18px; }}
    footer a {{ flex: 1 1 145px; }}
    footer .generated {{ flex: 1 0 100%; margin-left: 0; }}
  }}
  @media (max-width: 360px) {{
    .topbar {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .actions {{ grid-template-columns: 1fr; }}
  }}
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
<main id="board">
  <h1 class="sr-only">fplbench live Fantasy Premier League benchmark</h1>
  <header class="topbar">
    <div class="brand">fplbench<b>board</b><span class="live-pill">GW{shown_gw} {score_status}</span></div>
    <div class="stat"><em>Showing</em><strong>GW{shown_gw}</strong></div>
    <div class="stat lime"><em>{deadline_label}</em><strong id="countdown">—</strong></div>
    <div class="stat gold"><em>Captain</em><strong>{captain}</strong></div>
    <div class="stat"><em>GW pts</em><strong>{gw_pts}</strong></div>
    <div class="stat"><em>Total pts</em><strong>{total_pts}</strong></div>
    <div class="stat"><em>Overall rank</em><strong>{rank}</strong></div>
  </header>
  <div class="stage">
    <div class="field-col">
      <h2 id="pitch-heading" class="sr-only">Current official team formation</h2>
      <div class="pitch" aria-labelledby="pitch-heading">
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
        <h3 class="dugout-title">Bench</h3>
        <div id="bench-chips">{bench_chips}</div>
      </div>
    </div>
    <aside id="panel" aria-labelledby="panel-heading">
      <div class="eyebrow">open model · public record</div>
      <h2 id="panel-heading">Frozen before deadline. Scored after verification.</h2>
      <p class="panel-intro">The same forecast ranks the public squad and becomes the weekly benchmark artifact. {state_note}</p>
      <nav class="actions" aria-label="Project links">
        <a class="action" href="{dataset_url}" target="_blank" rel="noopener noreferrer">Explore data</a>
        <a class="action" href="{github_url}" target="_blank" rel="noopener noreferrer">Inspect code</a>
        <a class="action" href="{results_url}" target="_blank" rel="noopener noreferrer">Read results</a>
        <a class="action" href="{team_url}" target="_blank" rel="noopener noreferrer">Official team</a>
      </nav>
      <div class="kicker">team performance</div>
      {team_table}
      <div class="legend" aria-label="Pitch legend">
        <span>Rings show minutes recorded this gameweek.</span>
        <span>C, TC, and V mark captain roles.</span>
        <span>Live and review values remain provisional.</span>
      </div>
    </aside>
  </div>
  <section class="tables" aria-labelledby="model-heading">
    <h2 id="model-heading" class="kicker">model scoreboard — e_points_final MAE vs FPL ep_next (2026/27)</h2>
    {mae_table}
    <p class="note">A model row is published only after FPL marks the gameweek both finished and data-checked. Lower MAE is better.</p>
  </section>
  <section class="clubs" aria-labelledby="clubs-heading">
    <h2 id="clubs-heading" class="kicker">club previews — current official FPL data</h2>
    <p class="note">One responsive preview per official club. Live and review values remain provisional and are not model scores.</p>
    <nav class="club-grid" aria-label="Club preview pages">{club_nav}</nav>
  </section>
  <footer>
    <a href="{github_url}" target="_blank" rel="noopener noreferrer">GitHub: PascalAI2024/fplbench</a>
    <a href="{dataset_url}" target="_blank" rel="noopener noreferrer">HF dataset: x0me/fplbench</a>
    <a href="{portfolio_url}" target="_blank" rel="noopener noreferrer">More work: PascalAI2024/portfolio</a>
    <a href="{team_url}" target="_blank" rel="noopener noreferrer">Official team page (entry {entry_id})</a>
    <time class="generated" datetime="{generated_iso}">refreshed {generated}</time>
  </footer>
  <div class="scan"></div>
</main>
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


TEAM_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Current Fantasy Premier League club data preview for {team_name}.">
<meta name="theme-color" content="#07140d">
<title>{team_name} · fplbench club preview</title>
<style>
  html {{ color-scheme: dark; background: #030705; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; background: #030705; color: #e8f6ec; font-family: "Segoe UI", system-ui, sans-serif; }}
  .shell {{ width: min(100%, 1100px); margin: 0 auto; min-height: 100vh; padding: 24px; background: radial-gradient(800px 360px at 10% 0, rgba(80,160,90,.2), transparent 60%), #07140d; }}
  .back, .club-link {{ color: #b8ffcf; text-decoration: none; }}
  .back:hover, .back:focus-visible, .club-link:hover, .club-link:focus-visible {{ color: #dff36a; outline: 2px solid #dff36a; outline-offset: 3px; }}
  header {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: end; padding: 24px 0; border-bottom: 1px solid rgba(180,220,180,.15); }}
  .eyebrow, .label {{ color: #86a38c; font-size: 10px; letter-spacing: .18em; text-transform: uppercase; }}
  h1 {{ margin: 7px 0 0; font-size: clamp(32px, 7vw, 64px); line-height: .95; letter-spacing: -.045em; }}
  .status {{ align-self: start; padding: 7px 10px; border: 1px solid rgba(240,193,75,.45); border-radius: 999px; color: #f0c14b; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; }}
  .notice {{ margin: 18px 0; padding: 14px 16px; border-left: 3px solid #f0c14b; background: rgba(240,193,75,.08); color: #d8cfb4; line-height: 1.5; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }}
  .metric {{ min-height: 90px; padding: 14px; border: 1px solid rgba(180,220,180,.12); border-radius: 12px; background: rgba(6,16,11,.78); }}
  .metric strong {{ display: block; margin-top: 7px; color: #f4ffe8; font-size: 20px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
  h2 {{ margin: 28px 0 10px; font-size: 13px; letter-spacing: .16em; text-transform: uppercase; color: #9dceaa; }}
  .table-scroll {{ overflow-x: auto; border: 1px solid rgba(180,220,180,.12); border-radius: 12px; }}
  .table-scroll:focus-visible {{ outline: 2px solid #dff36a; outline-offset: 3px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }}
  th, td {{ padding: 10px; text-align: right; border-top: 1px solid rgba(180,220,180,.1); white-space: nowrap; }}
  thead th {{ border-top: 0; color: #7f9a86; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; }}
  th:first-child, td:first-child {{ text-align: left; }}
  .player {{ color: #f4ffe8; font-weight: 650; }}
  .club-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr)); gap: 7px; margin: 12px 0 24px; }}
  .club-link {{ display: flex; min-height: 34px; align-items: center; justify-content: center; padding: 7px; border: 1px solid rgba(125,255,195,.18); border-radius: 8px; background: rgba(125,255,195,.04); font-size: 10px; }}
  footer {{ display: flex; flex-wrap: wrap; gap: 16px; padding-top: 18px; border-top: 1px solid rgba(180,220,180,.12); color: #7f9486; font-size: 11px; }}
  footer time {{ margin-left: auto; }}
  @media (max-width: 720px) {{
    .shell {{ padding: 18px 14px; }}
    header {{ grid-template-columns: 1fr; align-items: start; }}
    .status {{ justify-self: start; }}
    .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .club-grid {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    footer time {{ flex-basis: 100%; margin-left: 0; }}
  }}
  @media (max-width: 380px) {{ .metrics {{ grid-template-columns: 1fr; }} .club-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
</style>
</head>
<body>
<main class="shell" data-team-id="{team_id}" data-team-slug="{team_slug}">
  <a class="back" href="../../index.html">← Main benchmark board</a>
  <header>
    <div><div class="eyebrow">fplbench · official club data preview</div><h1>{team_name}</h1></div>
    <div class="status">GW{preview_gw} {preview_status}</div>
  </header>
  <p class="notice"><strong>Preview, not a model score.</strong> {preview_notice}</p>
  <section class="metrics" aria-label="Club preview summary">
    <div class="metric" data-field="short-name"><span class="label">Club code</span><strong>{short_name}</strong></div>
    <div class="metric" data-field="player-count"><span class="label">Listed players</span><strong>{player_count}</strong></div>
    <div class="metric" data-field="average-cost"><span class="label">Average price</span><strong>{average_cost}</strong></div>
    <div class="metric" data-field="next-fixture"><span class="label">Next fixture</span><strong>{next_fixture}</strong></div>
  </section>
  <section aria-labelledby="roster-heading">
    <h2 id="roster-heading">Current FPL roster · {roster_value_status}</h2>
    <div class="table-scroll" role="region" aria-label="{team_name} player table" tabindex="0">
      <table><thead><tr><th scope="col">Player</th><th scope="col">Pos</th><th scope="col">Price</th><th scope="col">Season pts</th><th scope="col">GW pts</th><th scope="col">Minutes</th><th scope="col">Selected</th><th scope="col">Status</th></tr></thead><tbody>{roster_rows}</tbody></table>
    </div>
  </section>
  <section aria-labelledby="club-nav-heading"><h2 id="club-nav-heading">All club previews</h2><nav class="club-grid" aria-label="All club preview pages">{club_nav}</nav></section>
  <footer><a class="back" href="{github_url}" target="_blank" rel="noopener noreferrer">Source code</a><a class="back" href="{dataset_url}" target="_blank" rel="noopener noreferrer">Dataset</a><time datetime="{generated_iso}">refreshed {generated}</time></footer>
</main>
</body>
</html>
"""


def _event_status(bootstrap: dict, gw: int) -> str:
    event = next(
        (item for item in bootstrap.get("events") or [] if int(item.get("id") or -1) == gw),
        {},
    )
    return "verified" if event.get("finished") and event.get("data_checked") else "provisional preview"


def _next_fixture_text(
    team: dict[str, Any], teams: list[dict[str, Any]], fixtures: list[dict[str, Any]]
) -> str:
    team_id = int(team.get("id") or 0)
    names = {int(item.get("id") or 0): str(item.get("short_name") or item.get("name") or "—") for item in teams}
    candidates = [
        fixture
        for fixture in fixtures
        if not fixture.get("finished")
        and team_id in (int(fixture.get("team_h") or 0), int(fixture.get("team_a") or 0))
    ]
    if not candidates:
        return "—"
    fixture = min(
        candidates,
        key=lambda item: (
            str(item.get("kickoff_time") or "9999"),
            int(item.get("id") or 0),
        ),
    )
    home = int(fixture.get("team_h") or 0) == team_id
    opponent = int(fixture.get("team_a") if home else fixture.get("team_h") or 0)
    return f"{'vs' if home else '@'} {names.get(opponent, '—')}"


def _roster_rows(
    team_id: int, bootstrap: dict, live: dict[int, dict[str, Any]]
) -> tuple[str, int, str]:
    players = [
        dict(player)
        for player in bootstrap.get("elements") or []
        if int(player.get("team") or 0) == team_id
    ]
    players.sort(
        key=lambda player: (
            int(player.get("element_type") or 9),
            -int(player.get("total_points") or 0),
            str(player.get("web_name") or "").casefold(),
        )
    )
    rows = []
    for player in players:
        player_id = int(player.get("id") or 0)
        stats = live.get(player_id) or {}
        availability = str(player.get("status") or "a").upper()
        rows.append(
            "<tr>"
            f'<th class="player" scope="row">{html.escape(str(player.get("web_name") or f"#{player_id}"))}</th>'
            f'<td>{POS_BY_TYPE.get(int(player.get("element_type") or 0), "—")}</td>'
            f'<td>£{float(player.get("now_cost") or 0) / 10:.1f}m</td>'
            f'<td>{int(player.get("total_points") or 0)}</td>'
            f'<td>{"—" if stats.get("points") is None else stats.get("points")}</td>'
            f'<td>{"—" if stats.get("minutes") is None else stats.get("minutes")}</td>'
            f'<td>{html.escape(str(player.get("selected_by_percent") or "—"))}%</td>'
            f'<td>{html.escape(availability)}</td>'
            "</tr>"
        )
    costs = [float(player.get("now_cost") or 0) / 10 for player in players]
    average_cost = "—" if not costs else f"£{sum(costs) / len(costs):.1f}m"
    return "".join(rows), len(players), average_cost


def build_team_page(
    team: dict[str, Any],
    teams: list[dict[str, Any]],
    bootstrap: dict,
    fixtures: list[dict[str, Any]],
    preview_gw: int,
    live: dict[int, dict[str, Any]],
    generated_at: dt.datetime,
) -> str:
    team_id = int(team.get("id") or 0)
    roster_rows, player_count, average_cost = _roster_rows(team_id, bootstrap, live)
    event_status = _event_status(bootstrap, preview_gw)
    if event_status == "verified":
        preview_notice = (
            f"GW{preview_gw} points and minutes are final; roster, price, availability, "
            "and fixture metadata reflect the latest public FPL snapshot."
        )
        roster_value_status = f"verified GW{preview_gw} points"
    else:
        preview_notice = (
            "Current and review-period values can change until FPL marks the "
            "gameweek both finished and data-checked."
        )
        roster_value_status = f"provisional GW{preview_gw} values"
    page = TEAM_PAGE.format(
        team_id=team_id,
        team_slug=html.escape(str(team["slug"]), quote=True),
        team_name=html.escape(str(team.get("name") or team["slug"])),
        short_name=html.escape(str(team.get("short_name") or "—")),
        preview_gw=preview_gw,
        preview_status=html.escape(event_status),
        preview_notice=html.escape(preview_notice),
        roster_value_status=html.escape(roster_value_status),
        player_count=player_count,
        average_cost=average_cost,
        next_fixture=html.escape(_next_fixture_text(team, teams, fixtures)),
        roster_rows=roster_rows,
        club_nav=club_nav_html(teams, from_team_page=True),
        github_url=GITHUB_URL,
        dataset_url=DATASET_URL,
        generated=generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        generated_iso=generated_at.isoformat(),
    )
    validate_team_page(page, team)
    return page


def validate_page(page: str) -> None:
    """Fail closed when a generated board loses its public-surface contract."""
    required = (
        '<main id="board">',
        '<h1 class="sr-only">',
        'id="countdown"',
        'class="table-scroll"',
        '@media (max-width: 600px)',
        ':focus-visible',
        PORTFOLIO_URL,
        'aria-label="Club preview pages"',
    )
    missing = [token for token in required if token not in page]
    if missing:
        raise ValueError(f"generated board is missing required tokens: {missing}")
    if page.count("<h1") != 1:
        raise ValueError("generated board must contain exactly one h1")
    for link in page_links(page):
        href = link.get("href", "")
        if href.startswith(("https://", "http://")) and (
            link.get("target") != "_blank"
            or link.get("rel") != "noopener noreferrer"
        ):
            raise ValueError("every external board link must escape the Space iframe safely")
    if "width: 1280px" in page:
        raise ValueError("generated board contains the retired fixed desktop width")


def validate_team_page(page: str, team: dict[str, Any]) -> None:
    required = (
        '<main class="shell"',
        f'data-team-id="{int(team.get("id") or 0)}"',
        f'data-team-slug="{team["slug"]}"',
        "Preview, not a model score.",
        'data-field="short-name"',
        'data-field="player-count"',
        'data-field="average-cost"',
        'data-field="next-fixture"',
        'id="roster-heading"',
        'aria-label="All club preview pages"',
        '@media (max-width: 720px)',
    )
    missing = [token for token in required if token not in page]
    if missing:
        raise ValueError(f"generated club page is missing required tokens: {missing}")
    if page.count("<h1") != 1:
        raise ValueError("generated club page must contain exactly one h1")
    for link in page_links(page):
        href = link.get("href", "")
        if href.startswith(("https://", "http://")) and (
            link.get("target") != "_blank"
            or link.get("rel") != "noopener noreferrer"
        ):
            raise ValueError("every external club-page link must escape the Space iframe safely")


def _resolved_local_link(source: Path, href: str) -> str | None:
    if not href or href.startswith(("https://", "http://", "mailto:", "#")):
        return None
    clean = href.split("#", 1)[0].split("?", 1)[0]
    if not clean:
        return None
    resolved = posixpath.normpath(posixpath.join(source.parent.as_posix(), clean))
    if resolved.endswith("/"):
        resolved += "index.html"
    return resolved


def validate_site(site: dict[Path, str], teams: list[dict[str, Any]]) -> None:
    """Validate exact page inventory and every generated local navigation link."""
    expected = {Path("index.html"), *(Path("teams") / str(team["slug"]) / "index.html" for team in teams)}
    if set(site) != expected:
        missing = sorted(str(path) for path in expected - set(site))
        extra = sorted(str(path) for path in set(site) - expected)
        raise ValueError(f"generated site page inventory mismatch: missing={missing}, extra={extra}")
    if len(site) != len(teams) + 1:
        raise ValueError("generated site must contain one index plus exactly one page per club")
    available = {path.as_posix() for path in site}
    broken: list[str] = []
    for source, page in site.items():
        for link in page_links(page):
            resolved = _resolved_local_link(source, link.get("href", ""))
            if resolved is not None and resolved not in available:
                broken.append(f"{source.as_posix()} -> {resolved}")
    if broken:
        raise ValueError(f"generated site has broken local links: {broken}")
    index = site[Path("index.html")]
    for team in teams:
        expected_href = f'teams/{team["slug"]}/index.html'
        if f'href="{expected_href}"' not in index:
            raise ValueError(f"board index is missing club link: {expected_href}")
        validate_team_page(site[Path(expected_href)], team)


def build_page(results_path: Path, *, bootstrap: dict | None = None) -> str:
    bootstrap = bootstrap or fetch_bootstrap()
    teams = official_teams(bootstrap)
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

    shown_event = next(
        (
            event
            for event in bootstrap.get("events") or []
            if int(event.get("id", -1)) == shown_gw
        ),
        {},
    )
    if shown_event.get("finished") and shown_event.get("data_checked"):
        score_status = "verified"
        state_note = f"GW{shown_gw} is officially data-checked."
    elif shown_event.get("finished"):
        score_status = "under review"
        state_note = (
            f"GW{shown_gw} is finished but still under official review; "
            "points and rank remain provisional."
        )
    else:
        score_status = "provisional"
        state_note = f"GW{shown_gw} is live; points and rank remain provisional."

    generated_at = dt.datetime.now(dt.timezone.utc)
    page = PAGE.format(
        shown_gw=shown_gw,
        score_status=html.escape(score_status),
        state_note=html.escape(state_note),
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
        portfolio_url=PORTFOLIO_URL,
        results_url=RESULTS_URL,
        team_url=TEAM_URL,
        club_nav=club_nav_html(teams),
        entry_id=ENTRY_ID,
        generated=generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        generated_iso=generated_at.isoformat(),
    )
    validate_page(page)
    return page


def build_site(results_path: Path) -> dict[Path, str]:
    """Build the board index and exactly one preview page per official club."""
    bootstrap = fetch_bootstrap()
    teams = official_teams(bootstrap)
    if not teams:
        raise SystemExit("official bootstrap contains no teams")
    ctx = gw_context(bootstrap)
    events = bootstrap.get("events") or []
    preview_gw = ctx.get("current_gw") or ctx.get("next_gw")
    if preview_gw is None:
        ids = [int(event.get("id") or 0) for event in events if event.get("id")]
        preview_gw = max(ids) if ids else 0
    live = fetch_live_points(int(preview_gw)) if preview_gw else {}
    fixtures = fetch_fixtures()
    generated_at = dt.datetime.now(dt.timezone.utc)
    site: dict[Path, str] = {Path("index.html"): build_page(results_path, bootstrap=bootstrap)}
    for team in teams:
        relative = Path("teams") / str(team["slug"]) / "index.html"
        site[relative] = build_team_page(
            team,
            teams,
            bootstrap,
            fixtures,
            int(preview_gw),
            live,
            generated_at,
        )
    validate_site(site, teams)
    return site


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Build the fplbench board Space files")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = p.parse_args(argv)

    site = build_site(args.results)
    args.out.mkdir(parents=True, exist_ok=True)
    readme = args.out / "README.md"
    for relative, page in site.items():
        destination = args.out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(page, encoding="utf-8")
    readme.write_text(SPACE_README, encoding="utf-8")
    print(f"wrote {len(site)} HTML pages to {args.out}")
    print(f"wrote {readme}")


if __name__ == "__main__":
    main()
