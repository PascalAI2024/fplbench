"""Track the model's live FPL team ("The Leakage-Safe XI", entry 4770634).

Rewrites the `## Team — …` section of RESULTS.md from the official FPL API:
per-GW points vs the global average, captain, overall rank, and running total.
Idempotent — the whole section is rebuilt on every run. Only finished
gameweeks are listed, plus the current one marked "(live)".

Usage:
  python scripts/track_team.py
  python scripts/track_team.py --results RESULTS.md --entry 4770634
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENTRY_ID = 4770634
TEAM_NAME = "The Leakage-Safe XI"
TEAM_URL = f"https://fantasy.premierleague.com/entry/{ENTRY_ID}/history"
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
API = "https://fantasy.premierleague.com/api"
DEFAULT_RESULTS = ROOT / "RESULTS.md"

SECTION_HEADING = f"## Team — {TEAM_NAME} (entry {ENTRY_ID})"
TEAM_TABLE_COLS = (
    "GW",
    "pts",
    "GW avg",
    "vs avg",
    "captain",
    "overall rank",
    "total pts",
)


def _get_json(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def _captain(entry_id: int, gw: int, names: dict[int, str]) -> str:
    """Captain's web_name for one GW; em dash if picks are unavailable."""
    try:
        picks = _get_json(f"{API}/entry/{entry_id}/event/{gw}/picks/")
    except requests.RequestException:
        return "—"
    for pick in picks.get("picks") or []:
        if pick.get("is_captain"):
            name = names.get(int(pick["element"]), f"#{pick['element']}")
            if int(pick.get("multiplier") or 0) == 3:
                name += " (TC)"
            return name
    return "—"


def build_team_rows(entry_id: int = ENTRY_ID) -> list[dict[str, Any]]:
    """One row per finished GW (plus the current live one) from the FPL API."""
    bootstrap = _get_json(f"{API}/bootstrap-static/")
    events = {int(e["id"]): e for e in bootstrap.get("events") or []}
    names = {int(e["id"]): e["web_name"] for e in bootstrap.get("elements") or []}
    history = _get_json(f"{API}/entry/{entry_id}/history/")

    rows: list[dict[str, Any]] = []
    for h in history.get("current") or []:
        gw = int(h["event"])
        ev = events.get(gw)
        if ev is None:
            continue
        finished = bool(ev.get("finished"))
        live = not finished and bool(ev.get("is_current"))
        if not finished and not live:
            continue
        avg = ev.get("average_entry_score")
        pts = h.get("points")
        rows.append(
            {
                "gw": gw,
                "live": live,
                "points": pts,
                "average": avg,
                "vs_avg": (pts - avg) if pts is not None and avg is not None else None,
                "captain": _captain(entry_id, gw, names),
                "overall_rank": h.get("overall_rank"),
                "total_points": h.get("total_points"),
            }
        )
    return rows


def team_table_md(rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(TEAM_TABLE_COLS) + " |"
    sep = "|" + "|".join("---" for _ in TEAM_TABLE_COLS) + "|"
    lines = [header, sep]
    for r in sorted(rows, key=lambda x: x["gw"]):
        gw_cell = f"{r['gw']} (live)" if r["live"] else str(r["gw"])
        vs = r["vs_avg"]
        vs_cell = "" if vs is None else (f"+{vs}" if vs > 0 else str(vs))
        rank = r["overall_rank"]
        rank_cell = f"{rank:,}" if rank is not None else ""
        cells = [
            gw_cell,
            "" if r["points"] is None else str(r["points"]),
            "" if r["average"] is None else str(r["average"]),
            vs_cell,
            r["captain"],
            rank_cell,
            "" if r["total_points"] is None else str(r["total_points"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_section(rows: list[dict[str, Any]]) -> str:
    blurb = (
        f"The model's own squad in the official FPL game — "
        f"[live team page]({TEAM_URL}). Rewritten from the official API on "
        f"every post-GW run; the current gameweek is marked (live) until it "
        f"finishes."
    )
    if not rows:
        body = "No gameweek data yet — the first row lands once GW1 kicks off."
    else:
        body = team_table_md(rows)
    return f"{SECTION_HEADING}\n\n{blurb}\n\n{body}"


def upsert_team_section(path: Path, section: str) -> None:
    """Replace (or append) the team section; the rest of the file is untouched."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith(SECTION_HEADING)),
        None,
    )
    if start is None:
        new = text.rstrip() + "\n\n" + section + "\n" if text.strip() else section + "\n"
    else:
        end = start + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        kept_after = "\n".join(lines[end:]).strip()
        before = "\n".join(lines[:start]).rstrip()
        parts = [p for p in (before, section, kept_after) if p]
        new = "\n\n".join(parts) + "\n"
    path.write_text(new, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=f"Track {TEAM_NAME} in RESULTS.md")
    p.add_argument("--entry", type=int, default=ENTRY_ID, help="FPL entry id")
    p.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"RESULTS.md path (default: {DEFAULT_RESULTS})",
    )
    args = p.parse_args(argv)

    rows = build_team_rows(args.entry)
    section = render_section(rows)
    upsert_team_section(args.results, section)
    print(f"{len(rows)} gameweek row(s) for entry {args.entry}")
    print(section)
    print(f"wrote {args.results}")


if __name__ == "__main__":
    main()
