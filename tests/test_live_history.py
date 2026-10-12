"""Synthetic offline regressions for live season/GW/time and coverage boundaries."""

import hashlib
import json

import pandas as pd
import pytest

from fplbench import ingest, predict
from fplbench.live_history import (
    HISTORY_SOURCE,
    LiveHistoryError,
    current_form_features,
    forecast_cutoff,
    load_current_history,
    load_live_snapshot,
    previous_season,
    prior_panel_before,
)
from fplbench.paths import FPL_BOOTSTRAP, FPL_FIXTURES

SEASON = "2026-27"
AS_OF = "2026-10-09T23:00:00Z"
CAPTURED = "2026-10-09T22:59:00Z"
FEATURES = [
    "minutes_l1",
    "minutes_r3",
    "minutes_r5",
    "starts_l1",
    "total_points_r3",
    "prior_minutes",
    "prior_games",
    "opp_xgc_r5",
    "fdr",
    "was_home",
    "value",
]


def bundle(tmp_path, *, gw=6):
    bootstrap = {
        "teams": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "events": [
            {"id": 1, "deadline_time": "2026-08-15T10:00:00Z", "finished": True},
            {"id": gw, "is_next": True, "deadline_time": "2026-10-10T10:00:00Z"},
        ],
        "elements": [
            {
                "id": 101,
                "code": 1001,
                "element_type": 3,
                "team": 1,
                "minutes": 135,
                "starts": 1,
                "total_points": 10,
                "now_cost": 60,
                "web_name": "One",
                "status": "a",
                "chance_of_playing_next_round": None,
            },
            {
                "id": 102,
                "code": 1002,
                "element_type": 1,
                "team": 2,
                "minutes": 90,
                "starts": 1,
                "total_points": 2,
                "now_cost": 45,
                "web_name": "Two",
                "status": "a",
                "chance_of_playing_next_round": None,
            },
        ],
    }
    fixtures = [
        {
            "id": fid,
            "event": event,
            "kickoff_time": time,
            "finished": finished,
            "finished_provisional": finished,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 2,
            "team_a_difficulty": 3,
        }
        for fid, event, time, finished in [
            (11, 1, "2026-08-15T12:00:00Z", True),
            (12, 2, "2026-08-22T12:00:00Z", True),
            (15, 5, "2026-09-19T12:00:00Z", True),
            (16, gw, "2026-10-10T12:00:00Z", False),
        ]
    ]
    history = pd.DataFrame(
        [
            {
                "element": element,
                "fixture": fid,
                "round": event,
                "kickoff_time": time,
                "minutes": minutes,
                "starts": starts,
                "total_points": points,
                "was_home": element == 101,
                "expected_goals_conceded": 1.0,
                "clearances_blocks_interceptions": 2,
                "recoveries": 3,
            }
            for element, fid, event, time, minutes, starts, points in [
                (101, 11, 1, fixtures[0]["kickoff_time"], 90, 1, 8),
                (101, 12, 2, fixtures[1]["kickoff_time"], 45, 0, 2),
                (101, 15, 5, fixtures[2]["kickoff_time"], 0, 0, 0),
                (102, 11, 1, fixtures[0]["kickoff_time"], 90, 1, 2),
            ]
        ]
    )
    for name, value in [("bootstrap.json", bootstrap), ("fixtures.json", fixtures)]:
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    snapshot = {
        "format_version": 1,
        "season": SEASON,
        "captured_at_utc": CAPTURED,
        "bootstrap_source": FPL_BOOTSTRAP,
        "fixtures_source": FPL_FIXTURES,
        "bootstrap_sha256": hashlib.sha256(
            (tmp_path / "bootstrap.json").read_bytes()
        ).hexdigest(),
        "fixtures_sha256": hashlib.sha256(
            (tmp_path / "fixtures.json").read_bytes()
        ).hexdigest(),
    }
    (tmp_path / "snapshot_manifest.json").write_text(json.dumps(snapshot))
    manifest = {
        "format_version": 1,
        "season": SEASON,
        "captured_at_utc": CAPTURED,
        "source": HISTORY_SOURCE,
        "covered_element_ids": [101, 102],
        "bootstrap_sha256": snapshot["bootstrap_sha256"],
        "fixtures_sha256": snapshot["fixtures_sha256"],
    }
    write_history(tmp_path, history, manifest)
    return bootstrap, pd.DataFrame(fixtures), snapshot, history, manifest


def write_history(path, history, manifest, *, record_counts=True):
    history.to_csv(path / "history.csv", index=False)
    manifest["history_sha256"] = hashlib.sha256(
        (path / "history.csv").read_bytes()
    ).hexdigest()
    if record_counts:
        counts = history.groupby("element").size().to_dict()
        manifest["history_rows_by_element"] = {
            str(i): int(counts.get(i, 0)) for i in manifest["covered_element_ids"]
        }
    (path / "history_manifest.json").write_text(json.dumps(manifest))


def load(path, data, feats=FEATURES):
    boot, fx, snapshot, _, _ = data
    return load_current_history(path, boot, fx, snapshot, SEASON, 6, AS_OF, feats)


def test_midseason_lags_match_training_and_include_recorded_zero_minutes(tmp_path):
    data = bundle(tmp_path)
    history, report = load(tmp_path, data)
    form = current_form_features(
        history, ["1001", "1002", "new"], 6, SEASON, FEATURES
    ).set_index("player_code")
    assert form.loc["1001", "minutes_l1"] == 0
    assert form.loc["1001", "minutes_r3"] == 45
    assert form.loc["1001", "starts_l1"] == 0
    assert form.loc["new", "minutes_r5"] == 0
    assert report["rows"] == 4


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("season", "2025-26", "season/source"),
        ("captured_at_utc", "2026-10-10T12:00:00Z", "future-dated"),
        ("captured_at_utc", "2026-10-07T12:00:00Z", "stale"),
        ("covered_element_ids", [101], "every current element"),
        ("bootstrap_sha256", "0" * 64, "bound"),
        ("source", "https://untrusted.example/history", "season/source"),
    ],
)
def test_history_provenance_failures(tmp_path, field, value, match):
    data = bundle(tmp_path)
    data[4][field] = value
    write_history(tmp_path, data[3], data[4])
    with pytest.raises(LiveHistoryError, match=match):
        load(tmp_path, data)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("round", 2, "fixture/gameweek"),
        ("kickoff_time", "2026-08-16T12:00:00Z", "fixture/kickoff"),
        ("minutes", None, "missing/nonfinite minutes"),
        ("element", 999, "unknown current"),
        ("fixture", 999, "unknown fixtures"),
    ],
)
def test_row_alignment_and_missing_data(tmp_path, field, value, match):
    data = bundle(tmp_path)
    data[3].loc[0, field] = value
    write_history(tmp_path, data[3], data[4])
    with pytest.raises(LiveHistoryError, match=match):
        load(tmp_path, data)


def test_missing_feature_field_is_not_zero_filled(tmp_path):
    data = bundle(tmp_path)
    with pytest.raises(LiveHistoryError, match="missing scoring fields.*assists"):
        load(tmp_path, data, FEATURES + ["assists_r5"])


def test_partial_history_not_accepted_even_with_complete_covered_ids(tmp_path):
    data = bundle(tmp_path)
    write_history(tmp_path, data[3].iloc[1:], data[4])
    with pytest.raises(LiveHistoryError, match="coverage mismatch for minutes"):
        load(tmp_path, data)


def test_omitted_zero_minute_row_is_detected_by_response_count(tmp_path):
    data = bundle(tmp_path)
    write_history(
        tmp_path, data[3].loc[~data[3].fixture.eq(15)], data[4], record_counts=False
    )
    with pytest.raises(LiveHistoryError, match="row-count coverage mismatch"):
        load(tmp_path, data)


def test_verified_empty_history_is_cold_start_without_last_season_lags(tmp_path):
    data = bundle(tmp_path)
    for player in data[0]["elements"]:
        player.update(minutes=0, starts=0, total_points=0)
    write_history(tmp_path, data[3].iloc[:0], data[4])
    history, report = load(tmp_path, data)
    form = current_form_features(history, ["1001", "1002"], 6, SEASON, FEATURES)
    assert form.minutes_l1.eq(0).all() and form.starts_l1.eq(0).all()
    assert report["covered_elements"] == 2


def test_stable_player_code_alignment_cannot_be_reassigned(tmp_path):
    data = bundle(tmp_path)
    data[3]["player_code"] = [1002, 1001, 1001, 1002]
    write_history(tmp_path, data[3], data[4])
    with pytest.raises(LiveHistoryError, match="stable-code alignment mismatch"):
        load(tmp_path, data)


def test_target_or_later_gw_cannot_enter_rolling_form(tmp_path):
    data = bundle(tmp_path)
    future = data[3].iloc[[0]].copy()
    future.loc[:, "fixture"] = 16
    future.loc[:, "round"] = 6
    future.loc[:, "kickoff_time"] = "2026-10-10T12:00:00Z"
    future.loc[:, "minutes"] = 9000
    write_history(tmp_path, pd.concat([data[3], future]), data[4])
    history, report = load(tmp_path, data)
    assert report["excluded_inadmissible_rows"] == 1
    assert history.minutes.sum() == 225
    with pytest.raises(LiveHistoryError, match="target-gameweek"):
        current_form_features(history.assign(GW=6), ["1001"], 6, SEASON, FEATURES)
    with pytest.raises(LiveHistoryError, match="season"):
        current_form_features(
            history.assign(season="2025-26"), ["1001"], 6, SEASON, FEATURES
        )


@pytest.mark.parametrize("change", ["unfinished", "not_final", "kickoff_after_capture"])
def test_prior_round_not_known_completed_is_excluded_and_fails_coverage(
    tmp_path, change
):
    data = bundle(tmp_path)
    if change == "unfinished":
        data[1].loc[0, "finished"] = False
    elif change == "not_final":
        data[1].loc[0, "finished_provisional"] = False
    else:
        data[1].loc[0, "kickoff_time"] = "2026-10-10T00:00:00Z"
        data[3].loc[data[3].fixture.eq(11), "kickoff_time"] = "2026-10-10T00:00:00Z"
        write_history(tmp_path, data[3], data[4])
    with pytest.raises(LiveHistoryError, match="coverage mismatch"):
        load(tmp_path, data)


def test_exact_duplicates_removed_but_conflicts_rejected(tmp_path):
    data = bundle(tmp_path)
    write_history(tmp_path, pd.concat([data[3], data[3].iloc[[0]]]), data[4])
    history, _ = load(tmp_path, data)
    assert len(history) == 4
    conflicting = data[3].iloc[[0]].assign(total_points=99)
    write_history(tmp_path, pd.concat([data[3], conflicting]), data[4])
    with pytest.raises(LiveHistoryError, match="conflicting duplicate"):
        load(tmp_path, data)


def test_history_hash_checked_before_use(tmp_path):
    data = bundle(tmp_path)
    with (tmp_path / "history.csv").open("a") as f:
        f.write("\n")
    with pytest.raises(LiveHistoryError, match="SHA-256 mismatch"):
        load(tmp_path, data)


def test_missing_bundle_has_exact_actionable_file_name(tmp_path):
    data = bundle(tmp_path)
    (tmp_path / "history_manifest.json").unlink()
    with pytest.raises(LiveHistoryError, match="missing history_manifest.json"):
        load(tmp_path, data)


@pytest.mark.parametrize("as_of", ["2026-10-10T10:00:00Z", "2026-10-11T10:00:00Z"])
def test_deadline_boundary_is_closed(tmp_path, as_of):
    data = bundle(tmp_path)
    with pytest.raises(LiveHistoryError, match="deadline has passed"):
        forecast_cutoff(data[0], 6, as_of)


def test_timezone_required_and_immediate_prior_season_only():
    assert previous_season("2026-27") == "2025-26"
    panel = pd.DataFrame(
        {
            "season": ["2024-25", "2025-26", "2026-27"],
            "kickoff_time": [
                "2025-05-01T12:00:00Z",
                "2026-05-01T12:00:00Z",
                "2027-05-01T12:00:00Z",
            ],
            "player_code": ["one"] * 3,
            "GW": [38] * 3,
            "minutes": [90] * 3,
            "total_points": [100, 10, 9999],
        }
    )
    prior = prior_panel_before(panel, SEASON, AS_OF)
    assert prior.total_points.tolist() == [10]
    with pytest.raises(LiveHistoryError, match="timezone-aware"):
        prior_panel_before(panel, SEASON, "2026-10-09")
    with pytest.raises(LiveHistoryError, match="at or after cutoff"):
        prior_panel_before(panel, SEASON, "2026-04-01T00:00:00Z")


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("hash", "SHA-256"),
        ("future", "future-dated"),
        ("stale", "older"),
        ("season_calendar", "calendar"),
    ],
)
def test_live_metadata_snapshot_boundaries(tmp_path, mutation, match):
    data = bundle(tmp_path)
    snapshot = data[2]
    if mutation == "hash":
        snapshot["fixtures_sha256"] = "0" * 64
    elif mutation == "future":
        snapshot["captured_at_utc"] = "2026-10-10T00:00:00Z"
    elif mutation == "stale":
        snapshot["captured_at_utc"] = "2026-10-08T00:00:00Z"
    else:
        data[0]["events"][0]["deadline_time"] = "2027-08-15T10:00:00Z"
        (tmp_path / "bootstrap.json").write_text(json.dumps(data[0]))
        snapshot["bootstrap_sha256"] = hashlib.sha256(
            (tmp_path / "bootstrap.json").read_bytes()
        ).hexdigest()
    (tmp_path / "snapshot_manifest.json").write_text(json.dumps(snapshot))
    with pytest.raises(LiveHistoryError, match=match):
        load_live_snapshot(tmp_path, SEASON, AS_OF)


def test_live_ingest_records_hashes_without_requesting_histories(tmp_path, monkeypatch):
    data = bundle(tmp_path)
    calls = []

    def get(url):
        calls.append(url)
        return json.dumps(
            data[0] if url == FPL_BOOTSTRAP else data[1].to_dict("records")
        ).encode()

    monkeypatch.setattr(ingest, "LIVE", tmp_path)
    monkeypatch.setattr(ingest, "_get", get)
    ingest.download_live()
    recorded = json.loads((tmp_path / "snapshot_manifest.json").read_text())
    assert calls == [FPL_BOOTSTRAP, FPL_FIXTURES]
    assert (
        recorded["bootstrap_sha256"]
        == hashlib.sha256((tmp_path / "bootstrap.json").read_bytes()).hexdigest()
    )


def test_live_history_acquisition_covers_every_element_and_binds_snapshot(
    tmp_path, monkeypatch
):
    data = bundle(tmp_path)
    by_element = {
        101: data[3].loc[data[3].element.eq(101)].drop(columns="element"),
        102: data[3].iloc[:0].drop(columns="element"),
    }
    calls = []

    def get(url):
        calls.append(url)
        element_id = int(url.rstrip("/").rsplit("/", 1)[-1])
        return json.dumps(
            {"history": by_element[element_id].to_dict("records")}
        ).encode()

    monkeypatch.setattr(ingest, "_get", get)
    result = ingest.download_live_history(tmp_path, max_workers=1, as_of=AS_OF)

    assert calls == [f"{HISTORY_SOURCE}101/", f"{HISTORY_SOURCE}102/"]
    assert result == {
        "history": tmp_path / "history.csv",
        "manifest": tmp_path / "history_manifest.json",
    }
    history = pd.read_csv(result["history"])
    manifest = json.loads(result["manifest"].read_text())
    assert history.element.tolist() == [101, 101, 101]
    assert manifest["covered_element_ids"] == [101, 102]
    assert manifest["history_rows_by_element"] == {"101": 3, "102": 0}
    assert manifest["bootstrap_sha256"] == data[2]["bootstrap_sha256"]
    assert manifest["fixtures_sha256"] == data[2]["fixtures_sha256"]
    assert manifest["source"] == HISTORY_SOURCE
    assert manifest["history_sha256"] == hashlib.sha256(
        result["history"].read_bytes()
    ).hexdigest()


def test_live_history_acquisition_failure_preserves_existing_bundle(
    tmp_path, monkeypatch
):
    bundle(tmp_path)
    history_before = (tmp_path / "history.csv").read_bytes()
    manifest_before = (tmp_path / "history_manifest.json").read_bytes()

    def get(url):
        if url.endswith("101/"):
            return b'{"history": []}'
        return b'{"history_past": []}'

    monkeypatch.setattr(ingest, "_get", get)
    with pytest.raises(LiveHistoryError, match="element 102"):
        ingest.download_live_history(tmp_path, max_workers=1, as_of=AS_OF)
    assert (tmp_path / "history.csv").read_bytes() == history_before
    assert (tmp_path / "history_manifest.json").read_bytes() == manifest_before
    assert not list(tmp_path.glob(".history*.tmp"))


def test_predict_live_orders_snapshot_history_and_inference(tmp_path, monkeypatch):
    from scripts import predict_live

    calls = []
    monkeypatch.setattr(predict_live, "PREDS", tmp_path)
    monkeypatch.setattr(
        predict_live, "download_live", lambda: calls.append("snapshot")
    )
    monkeypatch.setattr(
        predict_live, "download_live_history", lambda: calls.append("history")
    )

    def run_prediction():
        calls.append("predict")
        return pd.DataFrame({"id": [101]})

    monkeypatch.setattr(predict_live, "predict_next_gw", run_prediction)
    predict_live.main([])
    assert calls == ["snapshot", "history", "predict"]


def test_prepare_uses_current_form_and_priors_separately(tmp_path, monkeypatch):
    bundle(tmp_path)
    model_dir = tmp_path / "models"
    processed = tmp_path / "processed"
    model_dir.mkdir()
    processed.mkdir()
    (model_dir / "feature_columns.txt").write_text("\n".join(FEATURES))
    prior = pd.DataFrame(
        {
            "season": ["2025-26", "2025-26"],
            "player_code": ["1001", "1002"],
            "GW": [38, 38],
            "kickoff_time": ["2026-05-01T12:00:00Z"] * 2,
            "minutes": [90, 90],
            "starts": [1, 1],
            "total_points": [99, 5],
            "team": ["A", "B"],
            "position": ["MID", "GK"],
            "was_home": [1, 0],
            "expected_goals_conceded": [9, 9],
        }
    )
    prior.to_parquet(processed / "panel.parquet")
    monkeypatch.setattr(predict, "LIVE", tmp_path)
    monkeypatch.setattr(predict, "MODELS", model_dir)
    monkeypatch.setattr(predict, "PROCESSED", processed)
    monkeypatch.setattr(
        predict,
        "load_season_players",
        lambda season: pd.DataFrame({"code": [1001, 1002]}),
    )
    merged, _, _, gw = predict._prepare_live_merged(as_of=AS_OF)
    one = merged.set_index("id").loc[101]
    assert gw == 6 and set(merged.event) == {6}
    assert one.minutes_l1 == 0 and one.minutes_r3 == 45
    assert one.prior_minutes == 90 and one.prior_points == 99
    assert one.opp_xgc_r5 == 1.0
    (tmp_path / "history_manifest.json").unlink()
    with pytest.raises(LiveHistoryError, match="history_manifest.json"):
        predict._prepare_live_merged(as_of=AS_OF)


def test_prepare_gw1_preserves_known_prior_cold_start_without_history(
    tmp_path, monkeypatch
):
    data = bundle(tmp_path)
    (tmp_path / "history_manifest.json").unlink()
    data[0]["events"] = [
        {"id": 1, "is_next": True, "deadline_time": "2026-08-15T10:00:00Z"}
    ]
    fixture = data[1].loc[data[1].id.eq(16)].copy()
    fixture.loc[:, "event"] = 1
    fixture.loc[:, "kickoff_time"] = "2026-08-15T12:00:00Z"
    for name, value in [
        ("bootstrap.json", data[0]),
        ("fixtures.json", fixture.to_dict("records")),
    ]:
        (tmp_path / name).write_text(json.dumps(value))
    data[2].update(
        captured_at_utc="2026-08-14T22:59:00Z",
        bootstrap_sha256=hashlib.sha256(
            (tmp_path / "bootstrap.json").read_bytes()
        ).hexdigest(),
        fixtures_sha256=hashlib.sha256(
            (tmp_path / "fixtures.json").read_bytes()
        ).hexdigest(),
    )
    (tmp_path / "snapshot_manifest.json").write_text(json.dumps(data[2]))
    model_dir, processed = tmp_path / "models", tmp_path / "processed"
    model_dir.mkdir()
    processed.mkdir()
    (model_dir / "feature_columns.txt").write_text("\n".join(FEATURES))
    panel = pd.DataFrame(
        {
            "season": ["2025-26"] * 2,
            "player_code": ["1001", "1002"],
            "GW": [38] * 2,
            "kickoff_time": ["2026-05-01T12:00:00Z"] * 2,
            "minutes": [90, 90],
            "starts": [1, 1],
            "total_points": [99, 5],
            "team": ["A", "B"],
            "position": ["MID", "GK"],
            "was_home": [1, 0],
            "expected_goals_conceded": [9, 9],
        }
    )
    panel.to_parquet(processed / "panel.parquet")
    monkeypatch.setattr(predict, "LIVE", tmp_path)
    monkeypatch.setattr(predict, "MODELS", model_dir)
    monkeypatch.setattr(predict, "PROCESSED", processed)
    monkeypatch.setattr(
        predict,
        "load_season_players",
        lambda season: pd.DataFrame({"code": [1001, 1002]}),
    )
    merged, _, _, gw = predict._prepare_live_merged(as_of="2026-08-14T23:00:00Z")
    one = merged.set_index("id").loc[101]
    assert gw == 1 and one.minutes_l1 == 90 and one.total_points_r3 == 99
    assert one.opp_xgc_r5 == 9
