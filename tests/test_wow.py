"""Tests for the GW pitch-board payload and HTML (no mocked wow)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from fplbench.wow import (
    build_wow_payload,
    load_metrics,
    parse_squad_md,
    render_wow_html,
    write_wow,
)

ROOT = Path(__file__).resolve().parents[1]
SHIPPED_PREDS = ROOT / "outputs" / "predictions" / "gw1_2026-27.csv"
SHIPPED_SQUAD = ROOT / "outputs" / "squad_gw1.md"
SHIPPED_METRICS = ROOT / "outputs" / "models" / "val_metrics.json"
_HAVE_SHIPPED = all(p.is_file() for p in (SHIPPED_PREDS, SHIPPED_SQUAD, SHIPPED_METRICS))


def _mini_md(*, alpha_e: str = "5.000", beta_e: str = "4.200", gamma_e: str = "3.145") -> str:
    return (
        "# Squad — TEST\n\n"
        "**Total cost:** £20.0m (200 tenths / 1000)\n"
        "**Total e_points_final (3):** 12.345\n"
        "**Captain:** Alpha (e_points_final=5.000)\n\n"
        "## Starting XI\n\n"
        "| Pos | Player | Club | Cost | e_points_final |\n"
        "|-----|--------|------|-----:|---------------:|\n"
        f"| MID | Alpha (C) | ClubA | £10.0m | {alpha_e} |\n"
        f"| FWD | Beta | ClubB | £6.0m | {beta_e} |\n\n"
        "## Bench\n\n"
        "| Pos | Player | Club | Cost | e_points_final |\n"
        "|-----|--------|------|-----:|---------------:|\n"
        f"| DEF | Gamma | ClubC | £4.0m | {gamma_e} |\n"
    )


def _mini_csv(path: Path, *, gamma_e: float = 3.145) -> Path:
    df = pd.DataFrame(
        [
            {
                "web_name": "Alpha",
                "position": "MID",
                "team_name": "ClubA",
                "opponent_name": "ClubZ",
                "now_cost": 100,
                "pred_minutes": 90.0,
                "pred_defcon": 0.01,
                "pred_points": 5.2,
                "pred_points_decomposed": 5.0,
                "e_points_final": 5.0002,
                "e_points_p90": 6.4,
                "ep_next": 4.0,
                "selected_by_percent": 12.0,
            },
            {
                "web_name": "Beta",
                "position": "FWD",
                "team_name": "ClubB",
                "opponent_name": "ClubY",
                "now_cost": 60,
                "pred_minutes": 75.0,
                "pred_defcon": 0.0,
                "pred_points": 5.04,
                "pred_points_decomposed": 4.2,
                "e_points_final": 4.2,
                "e_points_p90": 5.1,
                "ep_next": 3.1,
                "selected_by_percent": 8.0,
            },
            {
                "web_name": "Gamma",
                "position": "DEF",
                "team_name": "ClubC",
                "opponent_name": "ClubX",
                "now_cost": 40,
                "pred_minutes": 62.0,
                "pred_defcon": 0.1,
                "pred_points": 4.5,
                "pred_points_decomposed": 3.1,
                "e_points_final": gamma_e,
                "e_points_p90": gamma_e + 0.8,
                "ep_next": 1.0,
                "selected_by_percent": 1.5,
            },
        ]
    )
    path.write_text(df.to_csv(index=False), encoding="utf-8")
    return path


def _mini_metrics(path: Path, mae: float = 0.4321) -> Path:
    path.write_text(
        json.dumps(
            {
                "n_common": 12,
                "mae_decomposed": mae,
                "published_points": "pred_points_decomposed",
                "defcon_auc": 0.75,
            }
        ),
        encoding="utf-8",
    )
    return path


def _mini_bundle(tmp_path: Path, *, gamma_e: float = 3.145):
    preds = _mini_csv(tmp_path / "preds.csv", gamma_e=gamma_e)
    squad = tmp_path / "squad.md"
    squad.write_text(_mini_md(), encoding="utf-8")
    metrics = _mini_metrics(tmp_path / "metrics.json")
    return preds, squad, metrics


def test_fixture_join_and_header_fields(tmp_path: Path):
    preds, squad, metrics = _mini_bundle(tmp_path)
    parsed = parse_squad_md(squad.read_text(encoding="utf-8"))
    loaded = load_metrics(metrics)
    payload = build_wow_payload(preds, squad, metrics)

    assert parsed["xi_names"] == ["Alpha", "Beta"]
    assert parsed["bench_names"] == ["Gamma"]
    assert " (C)" not in "".join(parsed["xi_names"])
    assert payload["captain"] == parsed["captain"]
    assert payload["cost_m"] == parsed["cost_m"]
    assert payload["total_e_points"] == parsed["total_e_points"]
    assert payload["mae_decomposed"] == loaded["mae_decomposed"]
    assert payload["n_common"] == loaded["n_common"]
    assert [p["web_name"] for p in payload["xi"]] == parsed["xi_names"]
    assert [p["web_name"] for p in payload["bench"]] == parsed["bench_names"]
    assert payload["formula"] == "e_points_final = pred_points_decomposed + 2 * pred_defcon"


def test_epoints_mismatch_raises(tmp_path: Path):
    preds, squad, metrics = _mini_bundle(tmp_path, gamma_e=9.999)
    with pytest.raises(ValueError, match="mismatch"):
        build_wow_payload(preds, squad, metrics)


def test_missing_player_raises(tmp_path: Path):
    preds, squad, metrics = _mini_bundle(tmp_path)
    df = pd.read_csv(preds)
    df = df[df["web_name"] != "Gamma"]
    df.to_csv(preds, index=False)
    with pytest.raises(ValueError, match="not found"):
        build_wow_payload(preds, squad, metrics)


def test_render_html_is_inline_and_shows_copied_numbers(tmp_path: Path):
    preds, squad, metrics = _mini_bundle(tmp_path)
    payload = build_wow_payload(preds, squad, metrics)
    html = render_wow_html(payload)
    assert payload["captain"] in html
    assert f"£{payload['cost_m']:.1f}m" in html
    assert f"{payload['mae_decomposed']:.4f}" in html
    assert "module.exports" not in html
    assert "require(" not in html
    assert 'type="module"' not in html
    assert "window.FPLBENCH_WOW" in html
    assert "window.FPLBENCH_WOW_DATA" in html
    assert 'id="board"' in html


def test_write_wow_roundtrip(tmp_path: Path):
    preds, squad, metrics = _mini_bundle(tmp_path)
    out = tmp_path / "wow.html"
    path = write_wow(preds, squad, metrics, out)
    assert path == out
    text = out.read_text(encoding="utf-8")
    parsed = parse_squad_md(squad.read_text(encoding="utf-8"))
    assert parsed["captain"] in text


@pytest.mark.skipif(not _HAVE_SHIPPED, reason="shipped artifacts missing")
def test_payload_matches_shipped_sources():
    parsed = parse_squad_md(SHIPPED_SQUAD.read_text(encoding="utf-8"))
    metrics = load_metrics(SHIPPED_METRICS)
    payload = build_wow_payload(SHIPPED_PREDS, SHIPPED_SQUAD, SHIPPED_METRICS)

    assert payload["captain"] == parsed["captain"]
    assert payload["cost_m"] == parsed["cost_m"]
    assert payload["total_e_points"] == parsed["total_e_points"]
    assert payload["mae_decomposed"] == metrics["mae_decomposed"]
    assert payload["n_common"] == metrics["n_common"]
    assert payload["published_points"] == metrics["published_points"]
    assert payload["defcon_auc"] == metrics["defcon_auc"]
    assert [p["web_name"] for p in payload["xi"]] == parsed["xi_names"]
    assert [p["web_name"] for p in payload["bench"]] == parsed["bench_names"]
    assert len(payload["xi"]) + len(payload["bench"]) == len(parsed["xi_names"]) + len(
        parsed["bench_names"]
    )

    html = render_wow_html(payload)
    assert payload["captain"] in html
    assert f"£{payload['cost_m']:.1f}m" in html
    assert f"{payload['mae_decomposed']:.4f}" in html
    assert "module.exports" not in html
    assert "require(" not in html
    assert 'id="board"' in html
    assert "1280px" in html
    assert "800px" in html
    for col in (
        "pred_points",
        "pred_minutes",
        "pred_defcon",
        "pred_points_decomposed",
        "e_points_final",
        "e_points_p90",
        "ep_next",
    ):
        assert col in payload["xi"][0]
        assert col in html
