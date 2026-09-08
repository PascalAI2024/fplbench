import json
from pathlib import Path

import pandas as pd
import pytest

from nflbench.benchmark import (
    build_baseline_forecasts,
    freeze_player_week,
    score_forecasts,
)
from nflbench.sample import FIXTURE_DIR, ROOT, build_sample
from nflbench.scoring import ppr_points


def _candidates() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_DIR / "frozen_candidates.csv")


def _history() -> pd.DataFrame:
    frame = pd.read_csv(FIXTURE_DIR / "historical_player_weeks.csv")
    frame["fantasy_points"] = ppr_points(frame)
    return frame


def test_ppr_scoring_contract():
    row = pd.DataFrame(
        {
            "passing_yards": [250],
            "passing_tds": [2],
            "interceptions": [1],
            "rushing_yards": [20],
            "rushing_tds": [0],
            "receptions": [0],
            "receiving_yards": [0],
            "receiving_tds": [0],
            "fumbles_lost": [0],
        }
    )
    assert ppr_points(row).iloc[0] == 18.0


def test_freeze_rejects_post_cutoff_record():
    candidates = _candidates()
    candidates.loc[0, "observed_at"] = "2025-09-25T00:00:01Z"
    with pytest.raises(ValueError, match="post-cutoff"):
        freeze_player_week(candidates, "2025-09-25T00:00:00Z")


def test_baseline_rejects_same_week_outcome():
    frozen = freeze_player_week(_candidates(), "2025-09-25T00:00:00Z")
    history = _history()
    leaked = history.iloc[[0]].copy()
    leaked["week"] = 5
    with pytest.raises(ValueError, match="same-week or future"):
        build_baseline_forecasts(pd.concat([history, leaked]), frozen)


def test_new_players_fall_back_to_position_median():
    frozen = freeze_player_week(_candidates(), "2025-09-25T00:00:00Z")
    forecasts = build_baseline_forecasts(_history(), frozen)
    newcomer = forecasts.set_index("player_id").loc["RB_NEW"]
    assert newcomer["history_games"] == 0
    assert newcomer["forecast_ewma4"] == newcomer["forecast_position_median"]


def test_dnp_remains_in_denominator_and_scores_zero():
    frozen = freeze_player_week(_candidates(), "2025-09-25T00:00:00Z")
    forecasts = build_baseline_forecasts(_history(), frozen)
    actuals = pd.read_csv(FIXTURE_DIR / "week5_actuals.csv")
    actuals["fantasy_points"] = ppr_points(actuals)
    metrics = score_forecasts(forecasts, actuals)
    assert metrics["n_frozen"] == 7
    assert metrics["n_played"] == 6
    assert metrics["n_dnp"] == 1
    assert "DNP actual=0" in metrics["dnp_policy"]


def test_score_fails_if_frozen_player_has_no_actual():
    frozen = freeze_player_week(_candidates(), "2025-09-25T00:00:00Z")
    forecasts = build_baseline_forecasts(_history(), frozen)
    actuals = pd.read_csv(FIXTURE_DIR / "week5_actuals.csv").iloc[:-1].copy()
    actuals["fantasy_points"] = ppr_points(actuals)
    with pytest.raises(ValueError, match="actuals missing frozen players"):
        score_forecasts(forecasts, actuals)


def test_sample_build_is_byte_deterministic(tmp_path: Path):
    first = build_sample(tmp_path / "first")
    second = build_sample(tmp_path / "second")
    assert first["forecast_sha256"] == second["forecast_sha256"]
    for name in ("forecasts.csv", "score.json", "manifest.json", "board.html"):
        assert (tmp_path / "first" / name).read_bytes() == (
            tmp_path / "second" / name
        ).read_bytes()


def test_manifest_and_board_label_research_boundaries(tmp_path: Path):
    result = build_sample(tmp_path)
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    board = Path(result["board"]).read_text(encoding="utf-8")
    sources = json.loads((ROOT / "nflbench" / "sources.json").read_text(encoding="utf-8"))
    assert manifest["integrity"]["post_cutoff_records"] == "fail closed"
    assert manifest["artifacts"]["forecasts.csv"]["rows"] == 7
    assert "Synthetic deterministic reconstruction" in board
    assert "not live" in board.lower()
    assert sources["policy"]["injury_features"] == "excluded from version 0"
    assert sources["policy"]["nfl_com_automation"].startswith("not used in version 0")
    nfl_com = next(source for source in sources["sources"] if source["id"] == "nfl_com")
    assert "not blanket permission" in nfl_com["license"]
