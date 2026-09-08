"""Public card, Space, workflow, and integrity contracts (no network)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fplbench import train
from fplbench.export_hf import validate_split
from scripts import build_board, publish_hf_card, publish_space, track_team


def _bootstrap() -> dict:
    positions = [1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 1, 2, 3, 4]
    return {
        "events": [
            {
                "id": 1,
                "is_current": True,
                "is_next": False,
                "finished": True,
                "data_checked": False,
            },
            {
                "id": 2,
                "is_current": False,
                "is_next": True,
                "finished": False,
                "data_checked": False,
                "deadline_time": "2026-08-29T10:00:00Z",
            },
        ],
        "elements": [
            {"id": index, "web_name": f"P{index}", "element_type": pos, "team": 1}
            for index, pos in enumerate(positions, start=1)
        ],
        "teams": [{"id": 1, "short_name": "TST", "name": "Test"}],
    }


def _picks() -> dict:
    return {
        "picks": [
            {
                "element": index,
                "position": index,
                "is_captain": index == 10,
                "is_vice_captain": index == 11,
                "multiplier": 2 if index == 10 else (1 if index <= 11 else 0),
            }
            for index in range(1, 16)
        ],
        "entry_history": {"points": 53, "total_points": 53, "overall_rank": 123456},
    }


def test_board_is_responsive_accessible_and_explicitly_provisional(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    bootstrap = _bootstrap()
    monkeypatch.setattr(build_board, "fetch_bootstrap", lambda: bootstrap)
    monkeypatch.setattr(build_board, "fetch_picks", lambda _entry, _ctx: (1, _picks()))
    monkeypatch.setattr(
        build_board,
        "fetch_live_points",
        lambda _gw: {index: {"points": index % 5, "minutes": 90} for index in range(1, 16)},
    )
    monkeypatch.setattr(
        build_board,
        "build_team_rows",
        lambda: [
            {
                "gw": 1,
                "live": True,
                "status": "review",
                "points": 53,
                "average": 36,
                "vs_avg": 17,
                "captain": "P10",
                "overall_rank": 123456,
                "total_points": 53,
            }
        ],
    )
    page = build_board.build_page(tmp_path / "missing-results.md")
    assert page.count("<h1") == 1
    assert '<main id="board">' in page
    assert "@media (max-width: 600px)" in page
    assert "width: 1280px" not in page
    assert "GW1 under review" in page
    assert "remain provisional" in page
    assert 'role="img"' in page
    assert '<caption class="sr-only">' in page
    assert 'scope="col"' in page
    assert ':focus-visible' in page
    assert 'aria-live="polite"' not in page
    assert build_board.PORTFOLIO_URL in page
    assert page.count("<a ") == 9
    assert page.count('target="_blank" rel="noopener noreferrer"') == 8
    assert 'href="teams/test/index.html"' in page
    for destination in (
        build_board.DATASET_URL,
        build_board.GITHUB_URL,
        build_board.RESULTS_URL,
        build_board.TEAM_URL,
        build_board.PORTFOLIO_URL,
    ):
        assert f'href="{destination}"' in page
    build_board.validate_page(page)
    with pytest.raises(ValueError, match="escape the Space iframe"):
        build_board.validate_page(
            page.replace(' target="_blank" rel="noopener noreferrer"', "", 1)
        )


def test_site_builds_exact_index_plus_twenty_club_pages_with_no_broken_links(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    bootstrap = _bootstrap()
    bootstrap["teams"] = [
        {"id": team_id, "short_name": f"T{team_id:02d}", "name": f"Team {team_id:02d}"}
        for team_id in range(1, 21)
    ]
    bootstrap["elements"] = [
        {
            "id": team_id,
            "web_name": f"Player {team_id:02d}",
            "element_type": 3,
            "team": team_id,
            "now_cost": 50 + team_id,
            "total_points": team_id,
            "selected_by_percent": "1.0",
            "status": "a",
        }
        for team_id in range(1, 21)
    ]
    monkeypatch.setattr(build_board, "fetch_bootstrap", lambda: bootstrap)
    monkeypatch.setattr(build_board, "fetch_fixtures", lambda: [])
    monkeypatch.setattr(build_board, "fetch_picks", lambda _entry, _ctx: (1, _picks()))
    monkeypatch.setattr(
        build_board,
        "fetch_live_points",
        lambda _gw: {team_id: {"points": team_id, "minutes": 90} for team_id in range(1, 21)},
    )
    monkeypatch.setattr(
        build_board,
        "build_team_rows",
        lambda: [
            {
                "gw": 1,
                "live": True,
                "status": "review",
                "points": 53,
                "average": 36,
                "vs_avg": 17,
                "captain": "Player 10",
                "overall_rank": 123456,
                "total_points": 53,
            }
        ],
    )

    site = build_board.build_site(tmp_path / "missing-results.md")
    teams = build_board.official_teams(bootstrap)
    assert len(site) == 21
    assert len([path for path in site if path.name == "index.html"]) == 21
    assert Path("index.html") in site
    assert Path("teams/team-01/index.html") in site
    assert Path("teams/team-20/index.html") in site
    build_board.validate_site(site, teams)

    for team in teams:
        page = site[Path("teams") / team["slug"] / "index.html"]
        assert f'data-team-id="{team["id"]}"' in page
        assert 'data-field="player-count"' in page
        assert "Preview, not a model score." in page
        assert "provisional GW1 values" in page
        assert "@media (max-width: 720px)" in page
        assert page.count('aria-label="All club preview pages"') == 1

    broken = dict(site)
    broken[Path("index.html")] = broken[Path("index.html")].replace(
        'teams/team-01/index.html', 'teams/missing/index.html', 1
    )
    with pytest.raises(ValueError, match="broken local links"):
        build_board.validate_site(broken, teams)


def test_verified_club_page_labels_final_gameweek_values() -> None:
    bootstrap = _bootstrap()
    bootstrap["events"][0]["data_checked"] = True
    teams = build_board.official_teams(bootstrap)
    page = build_board.build_team_page(
        teams[0],
        teams,
        bootstrap,
        [],
        1,
        {1: {"points": 3, "minutes": 90}},
        build_board.dt.datetime(2026, 9, 1, tzinfo=build_board.dt.timezone.utc),
    )
    assert "GW1 verified" in page
    assert "verified GW1 points" in page
    assert "GW1 points and minutes are final" in page
    assert "provisional GW1 values" not in page


def test_space_upload_inventory_includes_every_generated_club_page(tmp_path: Path):
    (tmp_path / "index.html").write_text("index", encoding="utf-8")
    for team_id in range(1, 21):
        page = tmp_path / "teams" / f"team-{team_id:02d}" / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text(str(team_id), encoding="utf-8")
    uploads = publish_space.generated_site_uploads(tmp_path)
    assert len(uploads) == 21
    assert uploads[0][1] == "index.html"
    assert uploads[-1][1] == "teams/team-20/index.html"


def test_dataset_card_live_block_fails_closed():
    template = "before\n<!-- LIVE_SCOREBOARD:START -->\nold\n<!-- LIVE_SCOREBOARD:END -->\nafter\n"
    card = publish_hf_card.replace_live_block(template, "new")
    assert "old" not in card
    assert "new" in card
    with pytest.raises(ValueError, match="one live block"):
        publish_hf_card.replace_live_block("no markers", "new")


def test_dataset_card_preserves_review_status():
    table = publish_hf_card.team_summary_table_md(
        [
            {
                "gw": 1,
                "live": True,
                "status": "review",
                "points": 53,
                "average": 36,
                "vs_avg": 17,
                "overall_rank": 123,
            }
        ]
    )
    assert "1 (review)" in table


def test_space_metadata_and_workflow_safety_contracts():
    assert "app_file: index.html" in build_board.SPACE_README
    assert "fullWidth: true" in build_board.SPACE_README
    assert "license: other" in build_board.SPACE_README
    metadata = build_board.SPACE_README.split("---", 2)[1]
    short_description = next(
        line.split(":", 1)[1].strip().strip('"')
        for line in metadata.splitlines()
        if line.startswith("short_description:")
    )
    assert len(short_description) <= 60
    root = Path(__file__).resolve().parents[1]
    live = (root / ".github" / "workflows" / "fplbench.yml").read_text(encoding="utf-8")
    publish = (root / ".github" / "workflows" / "publish-public-surfaces.yml").read_text(
        encoding="utf-8"
    )
    assert "github.ref == 'refs/heads/main'" in live
    assert "!cancelled()" not in live
    assert "group: fplbench-live-${{ github.ref }}" in live
    assert "permissions:\n  contents: read" in publish
    assert "group: fplbench-hf-publication" in publish
    for prohibited in ("predict_live.py", "score_gw.py", "track_team.py"):
        assert prohibited not in publish


def test_export_rejects_duplicate_fixture_keys_and_divergent_same_gw_lags():
    base = {
        "season": "2025-26",
        "GW": 1,
        "player_code": "p1",
        "fixture": 10,
        "minutes_l1": 90.0,
    }
    duplicate = pd.DataFrame([base, base])
    with pytest.raises(ValueError, match="duplicate fixture keys"):
        validate_split(duplicate, "validation")

    divergent = pd.DataFrame(
        [base, {**base, "fixture": 11, "minutes_l1": 10.0}]
    )
    with pytest.raises(ValueError, match="divergent form lags"):
        validate_split(divergent, "validation")


def test_team_rows_keep_review_state_provisional(monkeypatch: pytest.MonkeyPatch):
    bootstrap = {
        "events": [
            {
                "id": 1,
                "finished": True,
                "data_checked": False,
                "is_current": False,
                "average_entry_score": 36,
            }
        ],
        "elements": [{"id": 1, "web_name": "Captain"}],
    }
    history = {
        "current": [
            {"event": 1, "points": 53, "overall_rank": 123, "total_points": 53}
        ]
    }
    monkeypatch.setattr(
        track_team,
        "_get_json",
        lambda url: bootstrap if url.endswith("bootstrap-static/") else history,
    )
    monkeypatch.setattr(track_team, "_captain", lambda *_args: "Captain")
    rows = track_team.build_team_rows()
    assert rows[0]["status"] == "review"
    assert rows[0]["live"] is True
    assert "1 (review)" in track_team.team_table_md(rows)


def test_validation_predictions_keep_unique_fixture_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    rows = pd.DataFrame(
        [
            {
                "season": "2025-26",
                "GW": 20,
                "fixture": 100,
                "kickoff_time": "2026-01-10T12:00:00Z",
                "player_code": 1,
            },
            {
                "season": "2025-26",
                "GW": 20,
                "fixture": 101,
                "kickoff_time": "2026-01-13T19:45:00Z",
                "player_code": 1,
            },
        ]
    )
    monkeypatch.setattr(train, "PREDS", tmp_path)
    train._write_val_preds(rows)
    written = pd.read_csv(tmp_path / "val_2025-26.csv")
    assert list(written["fixture"]) == [100, 101]
    assert "kickoff_time" in written.columns

    duplicate = pd.concat([rows.iloc[[0]], rows.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate fixture keys"):
        train._write_val_preds(duplicate)
