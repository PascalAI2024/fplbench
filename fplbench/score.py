"""Post-GW self-scoring: model vs ep_next on a common finite mask."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TABLE_COLS = (
    "GW",
    "n_common",
    "mae_model",
    "mae_ep_next",
    "n_played",
    "mae_model_played",
    "mae_ep_next_played",
)

# Kept across score_gw upserts. Do not invent GW scores here.
DEFAULT_PREAMBLE = (
    "# Live scoring results\n"
    "\n"
    "Model MAE vs FPL `ep_next` after each finished gameweek (common finite mask).\n"
    "\n"
    "The first data row lands after GW1. Until then this table has no scores — "
    "`scripts/score_gw.py` writes them from official FPL actuals. No invented numbers."
)


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float(np.mean(np.abs(y_true - y_pred)))


def score_gameweek(pred_df: pd.DataFrame, actuals_df: pd.DataFrame) -> dict[str, Any]:
    """Join predictions to actuals and compute MAE on a common finite mask.

    Common mask: pred_points, ep_next, and actual total_points are all finite.
    Played-only: common mask and minutes > 0.
    """
    pred = pred_df.copy()
    act = actuals_df.copy()
    for frame, col in ((pred, "id"), (act, "id")):
        if col not in frame.columns:
            raise KeyError(f"missing join key {col!r}")
    for col in ("pred_points", "ep_next"):
        if col not in pred.columns:
            raise KeyError(f"predictions missing {col!r}")
    if "total_points" not in act.columns:
        raise KeyError("actuals missing 'total_points'")

    pred["id"] = pd.to_numeric(pred["id"], errors="coerce")
    act["id"] = pd.to_numeric(act["id"], errors="coerce")
    keep_act = ["id", "total_points"] + (
        ["minutes"] if "minutes" in act.columns else []
    )
    merged = pred.merge(act[keep_act].drop_duplicates("id"), on="id", how="inner")

    y = pd.to_numeric(merged["total_points"], errors="coerce")
    p_model = pd.to_numeric(merged["pred_points"], errors="coerce")
    p_ep = pd.to_numeric(merged["ep_next"], errors="coerce")
    common = (
        y.notna()
        & p_model.notna()
        & p_ep.notna()
        & np.isfinite(y)
        & np.isfinite(p_model)
        & np.isfinite(p_ep)
    )

    y_c = y.loc[common].to_numpy(dtype=float)
    m_c = p_model.loc[common].to_numpy(dtype=float)
    e_c = p_ep.loc[common].to_numpy(dtype=float)

    if "minutes" in merged.columns:
        minutes = pd.to_numeric(merged["minutes"], errors="coerce").fillna(0)
        played = common & (minutes > 0)
    else:
        played = common & False

    y_p = y.loc[played].to_numpy(dtype=float)
    m_p = p_model.loc[played].to_numpy(dtype=float)
    e_p = p_ep.loc[played].to_numpy(dtype=float)

    return {
        "n_common": int(common.sum()),
        "mae_model": _mae(y_c, m_c),
        "mae_ep_next": _mae(y_c, e_c),
        "n_played": int(played.sum()),
        "mae_model_played": _mae(y_p, m_p),
        "mae_ep_next_played": _mae(y_p, e_p),
    }


def _fmt_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return ""
        return f"{float(v):.4f}"
    return str(v)


def _row_line(gw: int, metrics: dict[str, Any]) -> str:
    cells = [
        str(int(gw)),
        str(int(metrics["n_common"])),
        _fmt_cell(metrics["mae_model"]),
        _fmt_cell(metrics["mae_ep_next"]),
        str(int(metrics["n_played"])),
        _fmt_cell(metrics["mae_model_played"]),
        _fmt_cell(metrics["mae_ep_next_played"]),
    ]
    return "| " + " | ".join(cells) + " |"


def parse_results_table(text: str) -> dict[int, dict[str, Any]]:
    """Parse GW metric rows from a RESULTS.md body."""
    out: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if not parts or parts[0].lower() == "gw" or set(parts[0]) <= {"-", ":"}:
            continue
        try:
            gw = int(parts[0])
        except ValueError:
            continue
        if len(parts) < 7:
            continue

        def _num(x: str) -> float:
            if x == "":
                return float("nan")
            return float(x)

        out[gw] = {
            "n_common": int(parts[1]) if parts[1] else 0,
            "mae_model": _num(parts[2]),
            "mae_ep_next": _num(parts[3]),
            "n_played": int(parts[4]) if parts[4] else 0,
            "mae_model_played": _num(parts[5]),
            "mae_ep_next_played": _num(parts[6]),
        }
    return out


def _table_header_index(lines: list[str]) -> int | None:
    """Index of the `| GW | …` header, or None if the table is missing."""
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if parts and parts[0].lower() == "gw":
            return i
    return None


def _extract_preamble(text: str) -> str:
    """Keep everything above the results table so score_gw does not wipe notes."""
    lines = text.splitlines()
    idx = _table_header_index(lines)
    if idx is None:
        body = text.strip()
        return body if body else DEFAULT_PREAMBLE
    preamble = "\n".join(lines[:idx]).rstrip()
    return preamble if preamble else DEFAULT_PREAMBLE


def upsert_results_md(path: Path | str, gw: int, metrics: dict[str, Any]) -> None:
    """Write or replace one GW row in RESULTS.md (idempotent).

    Existing text above the table (the preamble) is preserved. A missing file
    gets DEFAULT_PREAMBLE, including the 'first data row lands after GW1' note.
    """
    path = Path(path)
    existing: dict[int, dict[str, Any]] = {}
    preamble = DEFAULT_PREAMBLE
    if path.exists():
        text = path.read_text(encoding="utf-8")
        existing = parse_results_table(text)
        preamble = _extract_preamble(text)
    existing[int(gw)] = {
        "n_common": int(metrics["n_common"]),
        "mae_model": metrics["mae_model"],
        "mae_ep_next": metrics["mae_ep_next"],
        "n_played": int(metrics["n_played"]),
        "mae_model_played": metrics["mae_model_played"],
        "mae_ep_next_played": metrics["mae_ep_next_played"],
    }

    header = "| " + " | ".join(TABLE_COLS) + " |"
    sep = "|" + "|".join("---" for _ in TABLE_COLS) + "|"
    lines = [preamble.rstrip(), "", header, sep]
    for g in sorted(existing):
        lines.append(_row_line(g, existing[g]))
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
