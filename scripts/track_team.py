"""Track the model's live FPL team ("The Leakage-Safe XI").

Rewrites the `## Team — …` section of RESULTS.md from the official FPL API:
per-GW points vs the global average, captain, overall rank, and running total.
Idempotent — the whole section is rebuilt on every run. Verified gameweeks
are final; live and post-match-review rows are labeled provisional.

Usage:
  FPLBENCH_ENTRY_ID=<private-id> python scripts/track_team.py
  python scripts/track_team.py --results RESULTS.md --entry <private-id>
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEAM_NAME = "The Leakage-Safe XI"
ENTRY_ENV = "FPLBENCH_ENTRY_ID"
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
API = "https://fantasy.premierleague.com/api"
DEFAULT_RESULTS = ROOT / "RESULTS.md"

SECTION_HEADING = f"## Team — {TEAM_NAME}"
TEAM_TABLE_COLS = (
    "GW",
    "pts",
    "GW avg",
    "vs avg",
    "captain",
    "overall rank",
    "total pts",
)


# The FPL API returns 429/5xx around deadlines and final whistles, when the
# scheduled runs happen to fire. A single 503 used to fail the whole board
# build (2026-09-04), so transient statuses are retried with backoff.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE = 2.0


def configured_entry_id() -> int | None:
    """Return the private runtime entry id without embedding it in public source."""
    raw = os.environ.get(ENTRY_ENV, "").strip()
    if not raw:
        return None
    try:
        entry_id = int(raw)
    except ValueError as exc:
        raise ValueError(f"{ENTRY_ENV} must be a positive integer") from exc
    if entry_id <= 0:
        raise ValueError(f"{ENTRY_ENV} must be a positive integer")
    return entry_id


def _get_json(url: str) -> dict:
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
                last = requests.HTTPError(f"{r.status_code} {r.reason} for {url}", response=r)
            else:
                r.raise_for_status()
                return r.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            if attempt == MAX_ATTEMPTS - 1:
                raise
        delay = BACKOFF_BASE**attempt + random.uniform(0, 0.5)
        print(f"fpl api retry {attempt + 1}/{MAX_ATTEMPTS - 1} in {delay:.1f}s: {last}", file=sys.stderr)
        time.sleep(delay)
    raise last if last else RuntimeError(f"unreachable: {url}")


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


def build_team_rows(entry_id: int | None = None) -> list[dict[str, Any]]:
    """One row per visible GW, with explicit live/review/final status."""
    entry_id = entry_id or configured_entry_id()
    if entry_id is None:
        raise ValueError(f"pass entry_id or set {ENTRY_ENV}")
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
        data_checked = bool(ev.get("data_checked"))
        current = bool(ev.get("is_current"))
        if not finished and not current:
            continue
        final = finished and data_checked
        status = "final" if final else ("review" if finished else "live")
        avg = ev.get("average_entry_score")
        pts = h.get("points")
        rows.append(
            {
                "gw": gw,
                "live": status != "final",
                "status": status,
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
        status = r.get("status") or ("live" if r["live"] else "final")
        gw_cell = f"{r['gw']} ({status})" if status != "final" else str(r["gw"])
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
        "The model's own squad in the official FPL game. Rewritten from the "
        "official API using a privately supplied entry identifier on every "
        "post-GW run. Public outputs omit that identifier. Rows remain marked "
        "live or review until FPL sets both `finished` and `data_checked`."
    )
    if not rows:
        body = "No public team record is available yet."
    else:
        body = team_table_md(rows)
    return f"{SECTION_HEADING}\n\n{blurb}\n\n{body}"


def parse_team_rows(text: str) -> list[dict[str, Any]]:
    """Parse the sanitized public team table without needing the private id."""
    lines = text.splitlines()
    heading = next(
        (i for i, line in enumerate(lines) if line.strip().startswith(SECTION_HEADING)),
        None,
    )
    if heading is None:
        return []
    header = next(
        (
            i
            for i in range(heading + 1, len(lines))
            if lines[i].strip().casefold().startswith("| gw | pts | gw avg |")
        ),
        None,
    )
    if header is None:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[header + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != len(TEAM_TABLE_COLS):
            continue
        match = re.fullmatch(r"(\d+)(?:\s+\((live|review|final)\))?", cells[0])
        if not match:
            continue
        status = match.group(2) or "final"

        def integer(value: str) -> int | None:
            value = value.replace(",", "").strip()
            return int(value) if value else None

        rows.append(
            {
                "gw": int(match.group(1)),
                "live": status != "final",
                "status": status,
                "points": integer(cells[1]),
                "average": integer(cells[2]),
                "vs_avg": integer(cells[3].lstrip("+")),
                "captain": cells[4] or "—",
                "overall_rank": integer(cells[5]),
                "total_points": integer(cells[6]),
            }
        )
    return rows


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
    p.add_argument(
        "--entry",
        type=int,
        default=configured_entry_id(),
        help=f"private FPL entry id (or set {ENTRY_ENV})",
    )
    p.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"RESULTS.md path (default: {DEFAULT_RESULTS})",
    )
    args = p.parse_args(argv)

    if args.entry is None:
        p.error(f"--entry or {ENTRY_ENV} is required")

    rows = build_team_rows(args.entry)
    section = render_section(rows)
    upsert_team_section(args.results, section)
    print(f"{len(rows)} gameweek row(s)")
    print(section)
    print(f"wrote {args.results}")


if __name__ == "__main__":
    main()
