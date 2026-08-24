"""Unit tests for post-GW scoring (no network)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fplbench.score import (
    parse_results_table,
    score_gameweek,
    split_results_md,
    upsert_results_md,
)


def _preds() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            # Deliberately unrelated raw-head values: live scoring must grade
            # the exact forecast used to rank and play the team.
            "pred_points": [60.0, 20.0, 40.0, 30.0, 10.0],
            "e_points_final": [6.0, 2.0, 4.0, np.nan, 1.0],
            "ep_next": [5.0, 3.0, np.nan, 2.0, 0.0],
        }
    )


def _actuals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6],
            "total_points": [8, 0, 4, 3, 0, 10],
            "minutes": [90, 0, 75, 90, 0, 90],
        }
    )


def test_common_mask_requires_finite_pred_ep_and_actual():
    m = score_gameweek(_preds(), _actuals())
    # ids 1,2,5: all three finite (id 3 missing ep_next, id 4 missing final points)
    assert m["n_common"] == 3
    assert m["prediction_column"] == "e_points_final"
    # |8-6| + |0-2| + |0-1| = 2+2+1 = 5 / 3
    assert abs(m["mae_model"] - 5.0 / 3.0) < 1e-9
    # |8-5| + |0-3| + |0-0| = 3+3+0 = 6 / 3
    assert abs(m["mae_ep_next"] - 2.0) < 1e-9


def test_played_only_uses_minutes_gt_zero():
    m = score_gameweek(_preds(), _actuals())
    # common with minutes > 0: only id 1 (ids 2 and 5 have minutes 0)
    assert m["n_played"] == 1
    assert abs(m["mae_model_played"] - 2.0) < 1e-9  # |8-6|
    assert abs(m["mae_ep_next_played"] - 3.0) < 1e-9  # |8-5|


def test_live_score_uses_final_forecast_not_raw_points_head():
    preds = pd.DataFrame(
        {
            "id": [1],
            "pred_points": [100.0],
            "e_points_final": [7.0],
            "ep_next": [6.0],
        }
    )
    actuals = pd.DataFrame({"id": [1], "total_points": [8], "minutes": [90]})
    metrics = score_gameweek(preds, actuals)
    assert metrics["mae_model"] == 1.0
    assert metrics["mae_model_played"] == 1.0


def test_live_score_fails_closed_without_final_forecast():
    with pytest.raises(KeyError, match="e_points_final"):
        score_gameweek(_preds().drop(columns="e_points_final"), _actuals())


def test_upsert_results_idempotent(tmp_path: Path):
    path = tmp_path / "RESULTS.md"
    m1 = {
        "n_common": 10,
        "mae_model": 1.5,
        "mae_ep_next": 1.7,
        "n_played": 8,
        "mae_model_played": 1.2,
        "mae_ep_next_played": 1.4,
    }
    m2 = {
        "n_common": 12,
        "mae_model": 1.1,
        "mae_ep_next": 1.3,
        "n_played": 9,
        "mae_model_played": 0.9,
        "mae_ep_next_played": 1.0,
    }
    upsert_results_md(path, 1, m1)
    upsert_results_md(path, 2, m1)
    upsert_results_md(path, 1, m2)  # replace GW1

    text = path.read_text(encoding="utf-8")
    assert "mae_model" in text
    assert "mae_model_played" in text
    rows = parse_results_table(text)
    assert set(rows) == {1, 2}
    assert text.count("\n| 1 |") + (1 if text.startswith("| 1 |") else 0) == 1
    # only one data row for GW1
    gw1_lines = [ln for ln in text.splitlines() if ln.strip().startswith("| 1 |")]
    assert len(gw1_lines) == 1
    assert rows[1]["n_common"] == 12
    assert abs(rows[1]["mae_model"] - 1.1) < 1e-9
    assert rows[2]["n_common"] == 10


def test_upsert_preserves_gw1_note(tmp_path: Path):
    """Preamble note must survive a second score_gw-style upsert (no mocks)."""
    metrics = {
        "n_common": 10,
        "mae_model": 1.5,
        "mae_ep_next": 1.7,
        "n_played": 8,
        "mae_model_played": 1.2,
        "mae_ep_next_played": 1.4,
    }
    path = tmp_path / "RESULTS.md"
    upsert_results_md(path, 1, metrics)
    assert "first data row lands after GW1" in path.read_text(encoding="utf-8")
    upsert_results_md(path, 1, metrics)
    text = path.read_text(encoding="utf-8")
    assert "first data row lands after GW1" in text
    rows = parse_results_table(text)
    assert set(rows) == {1}
    assert rows[1]["n_common"] == 10

    custom = tmp_path / "custom.md"
    custom.write_text(
        "# Live scoring results\n\n"
        "Custom keeper: the first data row lands after GW1.\n\n"
        "| GW | n_common | mae_model | mae_ep_next | n_played | mae_model_played | mae_ep_next_played |\n"
        "|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    upsert_results_md(custom, 2, metrics)
    upsert_results_md(custom, 2, metrics)
    custom_text = custom.read_text(encoding="utf-8")
    assert "first data row lands after GW1" in custom_text
    assert "Custom keeper" in custom_text
    assert parse_results_table(custom_text)[2]["n_common"] == 10


def test_upsert_preserves_team_section_postamble(tmp_path: Path):
    """The team table below the scoring table must survive upserts unparsed."""
    metrics = {
        "n_common": 10,
        "mae_model": 1.5,
        "mae_ep_next": 1.7,
        "n_played": 8,
        "mae_model_played": 1.2,
        "mae_ep_next_played": 1.4,
    }
    team_section = (
        "## Team — The Leakage-Safe XI (entry 4770634)\n\n"
        "| GW | pts | GW avg | vs avg | captain | overall rank | total pts |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 (live) | 25 | 23 | +2 | Haaland | 3,383,283 | 25 |\n"
        "| 2 | 60 | 50 | +10 | M.Salah | 1,000,000 | 85 |"
    )
    path = tmp_path / "RESULTS.md"
    upsert_results_md(path, 1, metrics)
    path.write_text(
        path.read_text(encoding="utf-8") + "\n" + team_section + "\n",
        encoding="utf-8",
    )
    upsert_results_md(path, 2, metrics)
    upsert_results_md(path, 1, metrics)
    text = path.read_text(encoding="utf-8")
    assert "Leakage-Safe XI" in text
    assert "Haaland" in text
    # team rows must not leak into the scoring table (captain is not a metric)
    preamble, rows, postamble = split_results_md(text)
    assert set(rows) == {1, 2}
    assert "M.Salah" not in preamble
    assert "M.Salah" in postamble
    # scoring table still has exactly one GW2 row despite the team table's "| 2 |"
    assert rows[2]["n_common"] == 10
