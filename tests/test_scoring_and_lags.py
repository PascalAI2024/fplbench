import numpy as np
import pandas as pd

from fplbench.form import last_played_window, player_end_of_season_row
from fplbench.panel import add_lags, apply_prior_season_gw1_lags, feature_columns
from fplbench.predict import fill_scoring_feature_nans
from fplbench.scoring import defcon_count, defcon_hit
from fplbench.tabfm_head import stratified_context_indices


def test_defcon_defender_threshold():
    pos = pd.Series(["DEF", "DEF"])
    cbit = pd.Series([10, 9])
    rec = pd.Series([0, 20])
    hits = defcon_hit(pos, cbit, rec)
    assert list(hits) == [1.0, 0.0]
    assert list(defcon_count(pos, cbit, rec)) == [10, 9]


def test_defcon_midfielder_uses_recoveries():
    pos = pd.Series(["MID", "MID", "FWD"])
    cbit = pd.Series([8, 8, 4])
    rec = pd.Series([4, 3, 8])
    hits = defcon_hit(pos, cbit, rec)
    assert list(hits) == [1.0, 0.0, 1.0]


def test_goalkeepers_never_hit():
    pos = pd.Series(["GK"])
    assert defcon_hit(pos, pd.Series([40]), pd.Series([40])).iloc[0] == 0.0


def test_lags_do_not_include_current_gw():
    df = pd.DataFrame(
        {
            "season": ["2024-25"] * 3,
            "player_code": ["1", "1", "1"],
            "GW": [1, 2, 3],
            "minutes": [90, 10, 45],
            "total_points": [6, 1, 2],
            "position": ["DEF"] * 3,
        }
    )
    out = add_lags(df)
    assert pd.isna(out.loc[out["GW"].eq(1), "minutes_l1"].iloc[0])
    assert out.loc[out["GW"].eq(2), "minutes_l1"].iloc[0] == 90
    assert out.loc[out["GW"].eq(3), "minutes_l1"].iloc[0] == 10
    assert out.loc[out["GW"].eq(3), "minutes_r3"].iloc[0] == 50


def test_feature_list_excludes_same_gw_and_xp():
    df = pd.DataFrame(
        {
            "season": ["2024-25", "2024-25"],
            "player_code": ["1", "1"],
            "GW": [1, 2],
            "minutes": [90, 80],
            "total_points": [6, 2],
            "xP": [4.0, 3.0],
            "xp_scraped": [4.0, 3.0],
            "minutes_l1": [None, 90],
            "total_points_l1": [None, 6],
            "was_home": [1, 0],
            "fdr": [2, 4],
            "value": [50, 50],
            "gw_in_season": [1, 2],
            "is_new_to_fpl": [0, 0],
            "prior_ppg": [4.0, 4.0],
        }
    )
    feats = feature_columns(df)
    assert "minutes" not in feats
    assert "total_points" not in feats
    assert "xP" not in feats
    assert "xp_scraped" not in feats
    assert "minutes_l1" in feats
    assert "was_home" in feats


def test_end_of_season_form_ignores_trailing_blank():
    df = pd.DataFrame(
        {
            "player_code": ["223094"] * 4,
            "GW": [35, 36, 37, 38],
            "minutes": [90, 90, 90, 0],
            "starts": [1, 1, 1, 0],
            "total_points": [7, 11, 9, 0],
            "expected_goals": [0.8, 1.2, 1.0, 0.0],
            "expected_assists": [0.1, 0.1, 0.0, 0.0],
            "defcon_hit": [0, 0, 0, 0],
        }
    )
    window = last_played_window(df, 5)
    assert list(window["GW"]) == [35, 36, 37]
    rec = player_end_of_season_row(df)
    assert rec["minutes_l1"] == 90
    assert rec["total_points_l1"] == 9
    assert rec["starts_l1"] == 1
    assert rec["prior_games"] == 3


def test_stratified_context_keeps_haulers():
    minutes = pd.Series([0] * 400 + [90] * 80 + [90] * 20)
    points = pd.Series([0] * 400 + [2] * 80 + [8] * 20)
    idx = stratified_context_indices(minutes, points, n=100, seed=0)
    haulers = ((minutes.iloc[idx] > 0) & (points.iloc[idx] >= 5)).sum()
    assert haulers >= 10


def test_gw1_lags_use_prior_season_end_of_form():
    rows = []
    for gw, mins, pts in [(36, 90, 8), (37, 90, 6), (38, 90, 10)]:
        rows.append(
            {
                "season": "2023-24",
                "player_code": "p1",
                "GW": gw,
                "minutes": mins,
                "total_points": pts,
                "starts": 1,
                "position": "MID",
            }
        )
    rows.append(
        {
            "season": "2024-25",
            "player_code": "p1",
            "GW": 1,
            "minutes": 90,
            "total_points": 2,
            "starts": 1,
            "position": "MID",
        }
    )
    df = pd.DataFrame(rows)
    out = apply_prior_season_gw1_lags(add_lags(df))
    gw1 = out[out["GW"].eq(1)].iloc[0]
    assert gw1["minutes_l1"] == 90
    assert gw1["total_points_l1"] == 10
    assert gw1["total_points_r3"] == (8 + 6 + 10) / 3


def test_fill_scoring_feature_nans_zeros_prior_and_features():
    feats = ["prior_ppg", "minutes_l1", "was_home", "fdr"]
    df = pd.DataFrame(
        {
            "player_code": ["a", "b"],
            "prior_ppg": [4.0, np.nan],
            "prior_minutes": [np.nan, np.nan],
            "minutes_l1": [np.nan, 90.0],
            "was_home": [1, np.nan],
            "fdr": [np.nan, 3],
            "name": ["x", "y"],
        }
    )
    out = fill_scoring_feature_nans(df, feats)
    for col in feats + ["prior_minutes"]:
        assert out[col].isna().sum() == 0
    assert out.loc[1, "prior_ppg"] == 0.0
    assert out.loc[0, "minutes_l1"] == 0.0
    assert out.loc[0, "prior_minutes"] == 0.0
