"""Download vaastav season dumps and the live FPL API snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from fplbench.paths import (
    FPL_BOOTSTRAP,
    FPL_FIXTURES,
    LIVE,
    SEASONS,
    VAASTAV,
    VAASTAV_RAW,
)

HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}

# End-of-season snapshot columns on vaastav players_raw (2021-22 … 2025-26).
# Never treat these as known mid-season; panel/live use prior-season values.
SETPIECE_ORDER_COLS = (
    "penalties_order",
    "corners_and_indirect_freekicks_order",
    "direct_freekicks_order",
)


def _get(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.content


def download_vaastav(seasons: tuple[str, ...] = SEASONS) -> list[Path]:
    VAASTAV.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    files = {
        "merged_gw.csv": "gws/merged_gw.csv",
        "players_raw.csv": "players_raw.csv",
        "fixtures.csv": "fixtures.csv",
        "teams.csv": "teams.csv",
    }
    for season in seasons:
        dest = VAASTAV / season
        dest.mkdir(parents=True, exist_ok=True)
        for local_name, remote in files.items():
            url = f"{VAASTAV_RAW}/data/{season}/{remote}"
            path = dest / local_name
            path.write_bytes(_get(url))
            written.append(path)
    return written


def download_live() -> dict[str, Path]:
    LIVE.mkdir(parents=True, exist_ok=True)
    bootstrap = json.loads(_get(FPL_BOOTSTRAP))
    fixtures = json.loads(_get(FPL_FIXTURES))
    boot_path = LIVE / "bootstrap.json"
    fix_path = LIVE / "fixtures.json"
    boot_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    fix_path.write_text(json.dumps(fixtures), encoding="utf-8")
    pd.DataFrame(bootstrap["elements"]).to_csv(LIVE / "elements.csv", index=False)
    pd.DataFrame(bootstrap["teams"]).to_csv(LIVE / "teams.csv", index=False)
    pd.DataFrame(bootstrap["events"]).to_csv(LIVE / "events.csv", index=False)
    pd.DataFrame(fixtures).to_csv(LIVE / "fixtures.csv", index=False)
    return {"bootstrap": boot_path, "fixtures": fix_path}


def load_season_merged(season: str) -> pd.DataFrame:
    df = pd.read_csv(VAASTAV / season / "merged_gw.csv")
    df["season"] = season
    return df


def load_season_players(season: str) -> pd.DataFrame:
    raw = pd.read_csv(VAASTAV / season / "players_raw.csv")
    keep = [
        c
        for c in (
            "id",
            "code",
            "web_name",
            "first_name",
            "second_name",
            "element_type",
            "team",
            *SETPIECE_ORDER_COLS,
        )
        if c in raw.columns
    ]
    out = raw[keep].copy()
    out = out.rename(columns={"id": "element"})
    out["season"] = season
    for col in SETPIECE_ORDER_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_season_fixtures(season: str) -> pd.DataFrame:
    fx = pd.read_csv(VAASTAV / season / "fixtures.csv")
    fx["season"] = season
    return fx


def load_season_teams(season: str) -> pd.DataFrame:
    raw = pd.read_csv(VAASTAV / season / "teams.csv")
    keep = [c for c in ("id", "name", "short_name") if c in raw.columns]
    out = raw[keep].copy()
    out["season"] = season
    return out
