"""Download vaastav season dumps and the live FPL API snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from fplbench.paths import (
    FPL_BOOTSTRAP,
    FPL_FIXTURES,
    LIVE,
    LIVE_SEASON,
    SEASONS,
    VAASTAV,
    VAASTAV_RAW,
)

HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
HISTORY_WORKERS = 4
HTTP_ATTEMPTS = 4

# End-of-season snapshot columns on vaastav players_raw (2021-22 … 2025-26).
# Never treat these as known mid-season; panel/live use prior-season values.
SETPIECE_ORDER_COLS = (
    "penalties_order",
    "corners_and_indirect_freekicks_order",
    "direct_freekicks_order",
)


def _get(url: str) -> bytes:
    """GET public source bytes, retrying only transient transport/server failures."""
    for attempt in range(HTTP_ATTEMPTS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code not in {408, 429, 500, 502, 503, 504}:
                r.raise_for_status()
                return r.content
            if attempt == HTTP_ATTEMPTS - 1:
                r.raise_for_status()
        except (requests.ConnectionError, requests.Timeout):
            if attempt == HTTP_ATTEMPTS - 1:
                raise
        time.sleep(2**attempt)
    raise RuntimeError(f"exhausted retries for {url}")  # pragma: no cover


def _history_response(element_id: int) -> tuple[int, list[dict]]:
    # Local import avoids ingest -> live_history -> panel -> ingest at import time.
    from fplbench.live_history import HISTORY_SOURCE, LiveHistoryError

    url = f"{HISTORY_SOURCE}{element_id}/"
    try:
        payload = json.loads(_get(url))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveHistoryError(
            f"invalid official history response for element {element_id}"
        ) from exc
    rows = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise LiveHistoryError(
            f"invalid official history response for element {element_id}"
        )
    return element_id, rows


def download_live_history(
    directory: Path | None = None,
    *,
    max_workers: int = HISTORY_WORKERS,
    as_of=None,
) -> dict[str, Path]:
    """Acquire and atomically bind official current-season fixture histories.

    Every current bootstrap element is requested, including players whose
    official response has an empty history list. Files are not replaced until
    all responses have passed basic schema checks.
    """
    # Local import avoids ingest -> live_history -> panel -> ingest at import time.
    from fplbench.live_history import (
        HISTORY_SOURCE,
        LiveHistoryError,
        load_live_snapshot,
    )

    directory = LIVE if directory is None else Path(directory)
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    observed_at = datetime.now(UTC) if as_of is None else as_of
    bootstrap, _, snapshot = load_live_snapshot(
        directory, LIVE_SEASON, observed_at
    )
    raw_elements = bootstrap.get("elements") if isinstance(bootstrap, dict) else None
    if not isinstance(raw_elements, list):
        raise LiveHistoryError("bootstrap elements are missing")
    try:
        element_ids = sorted(int(element["id"]) for element in raw_elements)
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveHistoryError("bootstrap element ids are invalid") from exc
    if len(element_ids) != len(set(element_ids)):
        raise LiveHistoryError("bootstrap element ids are duplicated")
    if not element_ids:
        raise LiveHistoryError("bootstrap has no elements")

    responses = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for completed, response in enumerate(
            pool.map(_history_response, element_ids), start=1
        ):
            responses.append(response)
            if completed % 100 == 0 or completed == len(element_ids):
                print(
                    f"[fplbench] official histories {completed}/{len(element_ids)}"
                )
    rows: list[dict] = []
    row_counts: dict[str, int] = {}
    for element_id, history in responses:
        row_counts[str(element_id)] = len(history)
        for original in history:
            row = dict(original)
            if "element" in row:
                try:
                    aligned = int(row["element"]) == element_id
                except (TypeError, ValueError):
                    aligned = False
                if not aligned:
                    raise LiveHistoryError(
                        f"history element mismatch for element {element_id}"
                    )
            row["element"] = element_id
            rows.append(row)

    columns = ["element", *sorted({key for row in rows for key in row} - {"element"})]
    if not rows:
        columns.extend(["fixture", "round"])
    history = pd.DataFrame(rows, columns=columns)
    sort_cols = [name for name in ("element", "round", "fixture") if name in history]
    if sort_cols and not history.empty:
        history = history.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    csv_bytes = history.to_csv(index=False).encode("utf-8")
    manifest = {
        "format_version": 1,
        "season": LIVE_SEASON,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "source": HISTORY_SOURCE,
        "history_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "bootstrap_sha256": snapshot["bootstrap_sha256"],
        "fixtures_sha256": snapshot["fixtures_sha256"],
        "covered_element_ids": element_ids,
        "history_rows_by_element": row_counts,
    }
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    history_path = directory / "history.csv"
    manifest_path = directory / "history_manifest.json"
    history_tmp = directory / f".history.csv.{token}.tmp"
    manifest_tmp = directory / f".history_manifest.json.{token}.tmp"
    try:
        history_tmp.write_bytes(csv_bytes)
        manifest_tmp.write_bytes(manifest_bytes)
        os.replace(history_tmp, history_path)
        # Publish the binding manifest last: an interruption cannot make an
        # incomplete or mismatched history file pass validation.
        os.replace(manifest_tmp, manifest_path)
    finally:
        history_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
    return {"history": history_path, "manifest": manifest_path}


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
    # Bind scoring metadata to one observed snapshot; CSV mtimes are insufficient.
    manifest = {
        "format_version": 1,
        "season": LIVE_SEASON,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "bootstrap_source": FPL_BOOTSTRAP,
        "fixtures_source": FPL_FIXTURES,
        "bootstrap_sha256": hashlib.sha256(boot_path.read_bytes()).hexdigest(),
        "fixtures_sha256": hashlib.sha256(fix_path.read_bytes()).hexdigest(),
    }
    (LIVE / "snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
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
