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


def test_target_event_excludes_unfinished_old_fixture_and_future_dgw():
    fixtures = pd.DataFrame(
        [
            {
                "event": event,
                "kickoff_time": f"2026-10-{day:02d}T12:00:00Z",
                "finished": False,
                "team_h": 1,
                "team_a": opponent,
                "team_h_difficulty": 2,
                "team_a_difficulty": 3,
            }
            for event, day, opponent in [(4, 1, 2), (5, 10, 2), (6, 17, 2), (6, 18, 3)]
        ]
    )
    out = _next_fixtures(
        pd.DataFrame({"team": [1, 2, 3]}), fixtures, _teams(), target_event=5
    )
    assert set(out.event) == {5}
    assert set(out.team) == {1, 2}


def test_blank_target_team_does_not_receive_a_later_event():
    fixtures = pd.DataFrame(
        [
            {
                "event": 5,
                "kickoff_time": "2026-10-10T12:00:00Z",
                "finished": False,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 2,
                "team_a_difficulty": 3,
            },
            {
                "event": 6,
                "kickoff_time": "2026-10-17T12:00:00Z",
                "finished": False,
                "team_h": 1,
                "team_a": 3,
                "team_h_difficulty": 2,
                "team_a_difficulty": 3,
            },
        ]
    )
    out = _next_fixtures(
        pd.DataFrame({"team": [1, 2, 3]}), fixtures, _teams(), target_event=5
    )
    assert 3 not in set(out.team)
