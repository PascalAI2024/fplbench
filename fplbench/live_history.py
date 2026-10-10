"""Validate an offline official history snapshot before mid-season scoring.

This module never downloads player histories. A missing or incomplete snapshot
is an error, not permission to substitute last season or cumulative bootstrap
statistics for fixture-level rolling form.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fplbench.panel import add_lags, deduplicate_fixture_rows
from fplbench.paths import FPL_BOOTSTRAP, FPL_FIXTURES
from fplbench.scoring import defcon_count, defcon_hit

HISTORY_SOURCE = "https://fantasy.premierleague.com/api/element-summary/"
MAX_SNAPSHOT_AGE = pd.Timedelta(hours=24)
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


class LiveHistoryError(ValueError):
    """The live inputs do not support a leakage-safe forecast."""


def utc_timestamp(value, field: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise LiveHistoryError(f"invalid {field}") from exc
    if pd.isna(result) or result.tzinfo is None:
        raise LiveHistoryError(f"{field} must be a timezone-aware timestamp")
    return result.tz_convert("UTC")


def previous_season(season: str) -> str:
    try:
        start, end = season.split("-")
        year = int(start)
        if len(start) != 4 or end != f"{(year + 1) % 100:02d}":
            raise ValueError
    except (AttributeError, ValueError) as exc:
        raise LiveHistoryError("invalid live season") from exc
    return f"{year - 1}-{year % 100:02d}"


def _read_manifest(path: Path) -> dict:
    if not path.is_file():
        raise LiveHistoryError(f"missing {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise LiveHistoryError(f"invalid {path.name}") from exc
    if not isinstance(value, dict) or value.get("format_version") != 1:
        raise LiveHistoryError(f"unsupported {path.name} format")
    return value


def _check_hash(path: Path, expected: str | None) -> None:
    if not path.is_file():
        raise LiveHistoryError(f"missing {path.name}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise LiveHistoryError(f"{path.name} SHA-256 mismatch")


def load_live_snapshot(
    directory: Path, season: str, as_of
) -> tuple[dict, pd.DataFrame, dict]:
    """Use one hashed bootstrap/fixture snapshot observed no later than as_of."""
    cutoff = utc_timestamp(as_of, "as_of")
    manifest = _read_manifest(directory / "snapshot_manifest.json")
    if manifest.get("season") != season:
        raise LiveHistoryError("live snapshot season mismatch")
    if (
        manifest.get("bootstrap_source") != FPL_BOOTSTRAP
        or manifest.get("fixtures_source") != FPL_FIXTURES
    ):
        raise LiveHistoryError("live snapshot source mismatch")
    captured = utc_timestamp(
        manifest.get("captured_at_utc"), "snapshot captured_at_utc"
    )
    if captured > cutoff or cutoff - captured > MAX_SNAPSHOT_AGE:
        raise LiveHistoryError("live snapshot is future-dated or older than 24 hours")
    _check_hash(directory / "bootstrap.json", manifest.get("bootstrap_sha256"))
    _check_hash(directory / "fixtures.json", manifest.get("fixtures_sha256"))
    bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
    first = next((e for e in bootstrap.get("events", []) if e.get("id") == 1), None)
    if first is None or utc_timestamp(
        first.get("deadline_time"), "GW1 deadline"
    ).year != int(season.split("-")[0]):
        raise LiveHistoryError(
            "bootstrap event calendar does not match configured season"
        )
    fixtures = pd.DataFrame(
        json.loads((directory / "fixtures.json").read_text(encoding="utf-8"))
    )
    return bootstrap, fixtures, manifest


def forecast_cutoff(bootstrap: dict, gw: int, as_of) -> pd.Timestamp:
    """Reject post-deadline generation instead of selecting a convenient past GW."""
    cutoff = utc_timestamp(as_of, "as_of")
    event = next(
        (e for e in bootstrap.get("events", []) if int(e.get("id", -1)) == gw), None
    )
    if event is None:
        raise LiveHistoryError(f"missing deadline for GW{gw}")
    deadline = utc_timestamp(event.get("deadline_time"), "deadline_time")
    if cutoff >= deadline:
        raise LiveHistoryError(f"GW{gw} deadline has passed; no pre-deadline forecast")
    return cutoff


def prior_panel_before(panel: pd.DataFrame, season: str, cutoff) -> pd.DataFrame:
    """Select exactly the immediately preceding season and known fixture times."""
    required = {
        "season",
        "kickoff_time",
        "player_code",
        "GW",
        "minutes",
        "total_points",
    }
    if not required <= set(panel):
        raise LiveHistoryError(
            f"historical panel missing columns: {sorted(required - set(panel))}"
        )
    prior = panel.loc[panel.season.astype(str).eq(previous_season(season))].copy()
    if prior.empty:
        raise LiveHistoryError("immediately preceding season is missing from panel")
    times = pd.to_datetime(prior.kickoff_time, utc=True, errors="coerce")
    if times.isna().any():
        raise LiveHistoryError("prior panel has unknown kickoff times")
    if (times >= utc_timestamp(cutoff, "cutoff")).any():
        raise LiveHistoryError("prior panel includes fixtures at or after cutoff")
    return prior


def _integer_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        raise LiveHistoryError(f"history missing column: {name}")
    value = pd.to_numeric(frame[name], errors="coerce")
    if value.isna().any() or not np.isfinite(value).all() or (value % 1 != 0).any():
        raise LiveHistoryError(f"history {name} must contain finite integers")
    return value.astype(int)


def load_current_history(
    directory: Path,
    bootstrap: dict,
    fixtures: pd.DataFrame,
    snapshot: dict,
    season: str,
    gw: int,
    cutoff,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, dict]:
    """Read, align and coverage-check a previously authorized official snapshot.

    CSV is official fixture-level history keyed by element, fixture and round.
    The manifest must cover every current element, including verified empty
    histories, and bind history bytes to this exact bootstrap/fixture snapshot.
    """
    manifest = _read_manifest(directory / "history_manifest.json")
    if manifest.get("season") != season or manifest.get("source") != HISTORY_SOURCE:
        raise LiveHistoryError("history season/source mismatch")
    if manifest.get("bootstrap_sha256") != snapshot.get(
        "bootstrap_sha256"
    ) or manifest.get("fixtures_sha256") != snapshot.get("fixtures_sha256"):
        raise LiveHistoryError("history is not bound to the current metadata snapshot")
    captured = utc_timestamp(manifest.get("captured_at_utc"), "history captured_at_utc")
    cutoff = utc_timestamp(cutoff, "cutoff")
    snapshot_time = utc_timestamp(
        snapshot.get("captured_at_utc"), "snapshot captured_at_utc"
    )
    if captured > cutoff or cutoff - captured > MAX_SNAPSHOT_AGE:
        raise LiveHistoryError("history capture time is future-dated or stale")
    path = directory / "history.csv"
    _check_hash(path, manifest.get("history_sha256"))
    elements = pd.DataFrame(bootstrap["elements"]).set_index(
        "id", verify_integrity=True
    )
    required_elements = {"code", "element_type", "minutes", "starts", "total_points"}
    if not required_elements <= set(elements):
        raise LiveHistoryError(
            f"bootstrap missing coverage fields: {sorted(required_elements - set(elements))}"
        )
    covered = manifest.get("covered_element_ids")
    if (
        not isinstance(covered, list)
        or len(covered) != len(set(covered))
        or set(covered) != set(elements.index)
    ):
        raise LiveHistoryError(
            "history manifest must cover every current element exactly once"
        )
    if elements.code.isna().any() or elements.code.astype(str).duplicated().any():
        raise LiveHistoryError(
            "bootstrap stable player codes are missing or duplicated"
        )
    history = pd.read_csv(path)
    for key in ["element", "fixture", "round"]:
        history[key] = _integer_column(history, key)
    if not set(history.element) <= set(elements.index):
        raise LiveHistoryError("history contains unknown current elements")
    # Response row counts catch omitted zero-minute fixtures that cumulative
    # minutes/points alone cannot detect. Counts come from the original official
    # per-element response, not a recomputation from a possibly truncated CSV.
    expected_counts = manifest.get("history_rows_by_element")
    keys = {str(i) for i in elements.index}
    if (
        not isinstance(expected_counts, dict)
        or set(expected_counts) != keys
        or any(type(v) is not int or v < 0 for v in expected_counts.values())
    ):
        raise LiveHistoryError(
            "history manifest needs original response row counts for every element"
        )
    actual_counts = (
        history.groupby("element").size().reindex(elements.index, fill_value=0)
    )
    if any(
        int(actual_counts.loc[i]) != expected_counts[str(i)] for i in elements.index
    ):
        raise LiveHistoryError("history response row-count coverage mismatch")
    if "season" in history and not history.season.astype(str).eq(season).all():
        raise LiveHistoryError("history rows cross season boundary")
    history["season"] = season
    history["GW"] = history["round"]
    expected_codes = history.element.map(elements.code.astype(str))
    if (
        "player_code" in history
        and not history.player_code.astype(str).eq(expected_codes).all()
    ):
        raise LiveHistoryError("history element/stable-code alignment mismatch")
    history["player_code"] = expected_codes
    history["position"] = history.element.map(elements.element_type.map(POS))
    if history.position.isna().any():
        raise LiveHistoryError("unknown player position")
    required_fixtures = {
        "id",
        "event",
        "kickoff_time",
        "finished",
        "finished_provisional",
        "team_h",
        "team_a",
    }
    if not required_fixtures <= set(fixtures):
        raise LiveHistoryError(
            f"fixtures missing completion fields: {sorted(required_fixtures - set(fixtures))}"
        )
    fx = fixtures.set_index("id", verify_integrity=True)
    if not set(history.fixture) <= set(fx.index):
        raise LiveHistoryError("history contains unknown fixtures")
    fixture_gw = history.fixture.map(fx.event)
    if not history.GW.eq(fixture_gw).all():
        raise LiveHistoryError("history fixture/gameweek alignment mismatch")
    if "kickoff_time" not in history:
        raise LiveHistoryError("history missing column: kickoff_time")
    times = pd.to_datetime(history.kickoff_time, utc=True, errors="coerce")
    fixture_times = pd.to_datetime(
        history.fixture.map(fx.kickoff_time), utc=True, errors="coerce"
    )
    if times.isna().any() or not times.eq(fixture_times).all():
        raise LiveHistoryError("history fixture/kickoff alignment mismatch")
    finished = history.fixture.map(fx.finished).eq(True) & history.fixture.map(
        fx.finished_provisional
    ).eq(True)
    admissible = (
        (history.GW > 0)
        & (history.GW < gw)
        & (times < min(captured, snapshot_time))
        & finished
    )
    excluded = int((~admissible).sum())
    history = history.loc[admissible].copy()
    # A later/in-progress result is excluded even when its scheduled round is earlier.
    bases = {
        c.rsplit("_", 1)[0]
        for c in feature_cols
        if c.endswith(("_l1", "_r3", "_r5")) and not c.startswith("opp_")
    }
    bases |= {
        "minutes",
        "starts",
        "total_points",
        "expected_goals_conceded",
        "clearances_blocks_interceptions",
        "recoveries",
    }
    bases -= {"defcon_count", "defcon_hit"}
    absent = bases - set(history)
    if absent:
        raise LiveHistoryError(f"history missing scoring fields: {sorted(absent)}")
    for col in bases:
        history[col] = pd.to_numeric(history[col], errors="coerce")
        missing = history[col].isna() | ~np.isfinite(history[col])
        if col in {"clearances_blocks_interceptions", "recoveries"}:
            missing &= ~history.position.eq("GK")
        if missing.any():
            raise LiveHistoryError(f"history has missing/nonfinite {col}")
    if "was_home" not in history:
        raise LiveHistoryError("history missing column: was_home")
    home = history.was_home
    if not home.isin([True, False, 0, 1]).all():
        raise LiveHistoryError("history was_home must be boolean")
    home = home.astype(bool)
    team_ids = history.fixture.map(fx.team_h).where(
        home, history.fixture.map(fx.team_a)
    )
    team_names = {t["id"]: t["name"] for t in bootstrap["teams"]}
    history["team"] = team_ids.map(team_names)
    if history.team.isna().any():
        raise LiveHistoryError("history fixture/team alignment mismatch")
    history["was_home"] = home.astype(int)
    history["defcon_count"] = defcon_count(
        history.position, history.clearances_blocks_interceptions, history.recoveries
    )
    history["defcon_hit"] = defcon_hit(
        history.position, history.clearances_blocks_interceptions, history.recoveries
    )
    try:
        history = deduplicate_fixture_rows(history)
    except ValueError as exc:
        raise LiveHistoryError(str(exc)) from exc
    # Cumulative values only validate coverage; they are never rolling features.
    totals = (
        history.groupby("element")[["minutes", "starts", "total_points"]]
        .sum()
        .reindex(elements.index, fill_value=0)
    )
    for field in ["minutes", "starts", "total_points"]:
        expected = pd.to_numeric(elements[field], errors="coerce")
        if expected.isna().any() or not totals[field].eq(expected).all():
            missing_ids = elements.index[~totals[field].eq(expected)].tolist()
            raise LiveHistoryError(
                f"history coverage mismatch for {field}: elements {missing_ids[:10]}"
            )
    report = {
        "season": season,
        "target_gw": gw,
        "cutoff_utc": cutoff.isoformat(),
        "captured_at_utc": captured.isoformat(),
        "rows": len(history),
        "excluded_inadmissible_rows": excluded,
        "covered_elements": len(covered),
        "history_sha256": manifest["history_sha256"],
        "rolling_semantics": "Same add_lags fixture-row windows as training, including recorded zero-minute fixtures; current GW never enters.",
    }
    return history, report


def current_form_features(
    history: pd.DataFrame,
    player_codes: list[str],
    gw: int,
    season: str,
    feature_cols: list[str],
) -> pd.DataFrame:
    """Append a target-GW sentinel and use the training lag implementation."""
    lag_features = [
        c
        for c in feature_cols
        if c.endswith(("_l1", "_r3", "_r5")) and not c.startswith("opp_")
    ]
    if not history.empty and (
        not history.season.eq(season).all() or not history.GW.lt(gw).all()
    ):
        raise LiveHistoryError("form source crosses season/target-gameweek boundary")
    sentinel = pd.DataFrame(
        {
            "season": season,
            "player_code": [str(c) for c in player_codes],
            "GW": gw,
            "fixture": -1,
            "_target": True,
        }
    )
    source = history.assign(_target=False)
    extended = add_lags(pd.concat([source, sentinel], ignore_index=True))
    out = extended.loc[extended._target.eq(True), ["player_code", *lag_features]].copy()
    out[lag_features] = (
        out[lag_features].apply(pd.to_numeric, errors="coerce").fillna(0)
    )
    return out
