"""Republish the x0me/fplbench dataset card as a living scoreboard.

Fetches the current card from the Hub (preserving its frontmatter and dataset
description), rebuilds the "## Live scoreboard (2026/27)" section from
RESULTS.md (model MAE) and the official FPL API (team performance), and
uploads the card back to the Hub.

The HF token is read from the HF_TOKEN environment variable ONLY and is never
printed or logged.

Usage:
  HF_TOKEN=... python scripts/publish_hf_card.py
  python scripts/publish_hf_card.py --dry-run   # build + print, no upload
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from track_team import (  # noqa: E402
    ENTRY_ID,
    TEAM_NAME,
    TEAM_URL,
    build_team_rows,
    team_table_md,
)

from fplbench.score import split_results_md  # noqa: E402

REPO_ID = "x0me/fplbench"
CARD_RAW_URL = f"https://huggingface.co/datasets/{REPO_ID}/raw/main/README.md"
GITHUB_URL = "https://github.com/PascalAI2024/fplbench"
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
SCOREBOARD_HEADING = "## Live scoreboard (2026/27)"
DEFAULT_RESULTS = ROOT / "RESULTS.md"

MAE_COLS = (
    "GW",
    "n_common",
    "mae_model",
    "mae_ep_next",
    "n_played",
    "mae_model_played",
    "mae_ep_next_played",
)


def fetch_current_card() -> str:
    r = requests.get(CARD_RAW_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter incl. both --- fences, body). No frontmatter → ("", text)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[: i + 1]), "\n".join(lines[i + 1 :])
    return "", text


def strip_scoreboard(body: str) -> str:
    """Remove an existing scoreboard section (idempotent republish)."""
    lines = body.splitlines()
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip().startswith("## Live scoreboard")
        ),
        None,
    )
    if start is None:
        return body
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    return "\n".join(lines[:start]).rstrip() + "\n\n" + "\n".join(lines[end:]).lstrip("\n")


def _fmt(v: float) -> str:
    import math

    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.4f}"


def mae_table_md(rows: dict[int, dict]) -> str:
    header = "| " + " | ".join(MAE_COLS) + " |"
    sep = "|" + "|".join("---" for _ in MAE_COLS) + "|"
    out = [header, sep]
    for gw in sorted(rows):
        m = rows[gw]
        out.append(
            "| "
            + " | ".join(
                [
                    str(gw),
                    str(m["n_common"]),
                    _fmt(m["mae_model"]),
                    _fmt(m["mae_ep_next"]),
                    str(m["n_played"]),
                    _fmt(m["mae_model_played"]),
                    _fmt(m["mae_ep_next_played"]),
                ]
            )
            + " |"
        )
    return "\n".join(out)


def build_scoreboard(results_path: Path) -> str:
    _, mae_rows, _ = split_results_md(
        results_path.read_text(encoding="utf-8") if results_path.exists() else ""
    )
    team_rows = build_team_rows()

    parts = [SCOREBOARD_HEADING, ""]
    parts.append(
        "Updated weekly by the [fplbench post-GW workflow]"
        f"({GITHUB_URL}/blob/main/.github/workflows/fplbench.yml) "
        "from official FPL actuals. No invented numbers."
    )
    parts += ["", "### Model accuracy — MAE vs FPL `ep_next`", ""]
    if mae_rows:
        parts.append(mae_table_md(mae_rows))
    else:
        parts.append(
            "No finished gameweek scored yet — the first row lands after GW1."
        )
    parts += ["", f"### Team — {TEAM_NAME} (entry {ENTRY_ID})", ""]
    if team_rows:
        parts.append(team_table_md(team_rows))
    else:
        parts.append("No gameweek data yet.")
    parts += [
        "",
        f"- Code + weekly self-scoring: {GITHUB_URL}",
        f"- The team, live in the official FPL game: {TEAM_URL}",
        "",
        f"_Last refreshed: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
    ]
    return "\n".join(parts)


def insert_scoreboard(body: str, section: str) -> str:
    """Insert the scoreboard before the first `## ` heading (after the intro)."""
    lines = body.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    if idx is None:
        return body.rstrip() + "\n\n" + section + "\n"
    before = "\n".join(lines[:idx]).rstrip()
    after = "\n".join(lines[idx:])
    return before + "\n\n" + section + "\n\n" + after


def build_card(results_path: Path) -> str:
    current = fetch_current_card()
    frontmatter, body = split_frontmatter(current)
    body = strip_scoreboard(body)
    card = insert_scoreboard(body, build_scoreboard(results_path))
    if frontmatter:
        card = frontmatter + "\n" + card
    if not card.endswith("\n"):
        card += "\n"
    return card


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Publish the living HF dataset card")
    p.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    p.add_argument("--dry-run", action="store_true", help="build + print, no upload")
    args = p.parse_args(argv)

    card = build_card(args.results)
    if args.dry_run:
        print(card)
        print(f"-- dry run: {len(card)} chars, not uploaded --")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN environment variable is required")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.upload_file(
        path_or_fileobj=card.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="scoreboard: refresh live model + team tables",
    )
    print(f"uploaded dataset card ({len(card)} chars) -> https://huggingface.co/datasets/{REPO_ID}")


if __name__ == "__main__":
    main()
