"""Unit tests for next-fixture selection (no network)."""

import pandas as pd
import pytest

from fplbench.predict import _next_fixtures


def _teams() -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})


def test_two_fixtures_same_event_raises():
    """Synthetic DGW: one team, two unfinished fixtures in the same event."""
    fixtures = pd.DataFrame(
        {
            "event": [5, 5],
            "kickoff_time": ["2026-09-01T12:00:00Z", "2026-09-01T19:00:00Z"],
            "finished": [False, False],
            "team_h": [1, 1],
            "team_a": [2, 3],
            "team_h_difficulty": [2, 3],
            "team_a_difficulty": [4, 3],
        }
    )
    elements = pd.DataFrame({"team": [1, 2, 3]})
    with pytest.raises(NotImplementedError, match="team=1 event=5"):
        _next_fixtures(elements, fixtures, _teams())


def test_next_fixtures_picks_earliest_event_per_team():
    fixtures = pd.DataFrame(
        {
            "event": [1, 2],
            "kickoff_time": ["2026-08-15T14:00:00Z", "2026-08-22T14:00:00Z"],
            "finished": [False, False],
            "team_h": [1, 1],
            "team_a": [2, 3],
            "team_h_difficulty": [2, 3],
            "team_a_difficulty": [4, 2],
        }
    )
    elements = pd.DataFrame({"team": [1, 2, 3]})
    out = _next_fixtures(elements, fixtures, _teams())
    assert set(out["team"]) == {1, 2, 3}
    assert int(out.loc[out["team"].eq(1), "event"].iloc[0]) == 1
    assert int(out.loc[out["team"].eq(1), "opponent"].iloc[0]) == 2
