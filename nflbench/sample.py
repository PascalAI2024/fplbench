"""Deterministic historical reconstruction used by the feasibility spike."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from nflbench.benchmark import (
    FORECAST_COLUMNS,
    build_baseline_forecasts,
    canonical_csv_bytes,
    freeze_player_week,
    score_forecasts,
    sha256_bytes,
    write_json,
)
from nflbench.board import render_sample_board
from nflbench.scoring import PPR_WEIGHTS, ppr_points


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "nflbench"


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_sample(
    output_dir: Path,
    *,
    fixture_dir: Path = FIXTURE_DIR,
) -> dict[str, Any]:
    config_path = fixture_dir / "sample_config.json"
    history_path = fixture_dir / "historical_player_weeks.csv"
    candidates_path = fixture_dir / "frozen_candidates.csv"
    actuals_path = fixture_dir / "week5_actuals.csv"
    source_manifest_path = ROOT / "nflbench" / "sources.json"

    config = json.loads(config_path.read_text(encoding="utf-8"))
    history = pd.read_csv(history_path)
    candidates = pd.read_csv(candidates_path)
    actuals = pd.read_csv(actuals_path)
    history["fantasy_points"] = ppr_points(history)
    actuals["fantasy_points"] = ppr_points(actuals)

    frozen = freeze_player_week(candidates, config["cutoff_at"])
    forecasts = build_baseline_forecasts(history, frozen)
    metrics = score_forecasts(forecasts, actuals)

    output_dir.mkdir(parents=True, exist_ok=True)
    forecast_bytes = canonical_csv_bytes(forecasts, FORECAST_COLUMNS)
    forecast_path = output_dir / "forecasts.csv"
    forecast_path.write_bytes(forecast_bytes)

    metrics_path = output_dir / "score.json"
    write_json(metrics_path, metrics)
    manifest = {
        "benchmark": "NFLBench feasibility spike",
        "sample_status": "synthetic deterministic reconstruction; not live",
        "season": config["season"],
        "week": config["week"],
        "cutoff_at": config["cutoff_at"],
        "scoring": {key: value for key, value in PPR_WEIGHTS.items()},
        "sources_manifest_sha256": _sha256_file(source_manifest_path),
        "inputs": {
            path.name: {"sha256": _sha256_file(path)}
            for path in (config_path, history_path, candidates_path, actuals_path)
        },
        "artifacts": {
            "forecasts.csv": {
                "sha256": sha256_bytes(forecast_bytes),
                "rows": int(len(forecasts)),
            },
            "score.json": {
                "sha256": _sha256_file(metrics_path),
            },
        },
        "integrity": {
            "post_cutoff_records": "fail closed",
            "same_week_outcomes": "forbidden",
            "dnp": "retained with actual=0",
            "row_order": "season, week, position, player_id",
        },
    }
    manifest_path = output_dir / "manifest.json"
    write_json(manifest_path, manifest)
    board_path = output_dir / "board.html"
    board_path.write_text(
        render_sample_board(forecasts, actuals, metrics, manifest),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "output_dir": str(output_dir),
        "forecasts": str(forecast_path),
        "score": str(metrics_path),
        "manifest": str(manifest_path),
        "board": str(board_path),
        "forecast_sha256": manifest["artifacts"]["forecasts.csv"]["sha256"],
        "metrics": metrics,
    }

