"""Generate holdout charts for the README (MAE bars, DefCon reliability, importances).

Usage:
  python scripts/make_charts.py

Writes three PNGs under docs/img/. Rerunnable; creates the directory if needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.paths import MODELS, PREDS
from fplbench.train import DEFCON_TRAIN_GW_MAX

IMG_DIR = ROOT / "docs" / "img"
VAL_METRICS = MODELS / "val_metrics.json"
VAL_PREDS = PREDS / "val_2025-26.csv"
FEATURE_COLS = MODELS / "feature_columns.txt"
POINTS_MODEL = MODELS / "points.joblib"
MINUTES_MODEL = MODELS / "minutes.joblib"

N_RELIABILITY_BINS = 10
TOP_K_IMPORTANCES = 20


def _load_mae_bars() -> list[tuple[str, float]]:
    """Bars for holdout MAE. Never invent ep_next; use scraped xP when that is what we have."""
    metrics = json.loads(VAL_METRICS.read_text(encoding="utf-8"))
    bars: list[tuple[str, float]] = []

    published = metrics.get("published_points")
    if metrics.get("mae_decomposed") is not None and published == "pred_points_decomposed":
        bars.append(("model (decomposed)", float(metrics["mae_decomposed"])))
    elif metrics.get("mae_model") is not None:
        bars.append(("model", float(metrics["mae_model"])))

    if metrics.get("mae_last5") is not None:
        bars.append(("last5", float(metrics["mae_last5"])))

    # Live pre-deadline ep_next is not in val_metrics (historical holdout).
    if metrics.get("mae_ep_next") is not None:
        bars.append(("ep_next", float(metrics["mae_ep_next"])))
    elif metrics.get("mae_xp_scraped") is not None:
        bars.append(
            ("scraped xP (not pre-deadline ep_next)", float(metrics["mae_xp_scraped"]))
        )

    if not bars:
        raise RuntimeError(f"No MAE fields found in {VAL_METRICS}")
    return bars


def chart_mae_comparison(out: Path) -> Path:
    bars = _load_mae_bars()
    labels = [b[0].replace(" (", "\n(") for b in bars]
    values = [b[1] for b in bars]

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(labels))
    colors = ["#2563eb", "#64748b", "#94a3b8"][: len(labels)]
    ax.bar(x, values, color=colors, width=0.65, edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("MAE (total points)")
    ax.set_title("2025-26 holdout MAE comparison")
    ax.set_ylim(0, max(values) * 1.15)
    for i, v in enumerate(values):
        ax.text(i, v + max(values) * 0.02, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def chart_defcon_reliability(out: Path) -> Path:
    """10-bin reliability on 2025-26 GW>28 played outfield rows only."""
    df = pd.read_csv(VAL_PREDS)
    gw = pd.to_numeric(df["GW"], errors="coerce")
    minutes = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
    pos = df["position"].astype(str).str.upper()
    pred = pd.to_numeric(df["pred_defcon"], errors="coerce")
    y = pd.to_numeric(df["defcon_hit"], errors="coerce")

    mask = (
        (gw > DEFCON_TRAIN_GW_MAX)
        & (minutes > 0)
        & ~pos.eq("GK")
        & pred.notna()
        & y.notna()
    )
    p = pred.loc[mask].to_numpy(dtype=float)
    a = y.loc[mask].to_numpy(dtype=float)
    if len(p) < N_RELIABILITY_BINS:
        raise RuntimeError(
            f"DefCon reliability need ≥{N_RELIABILITY_BINS} rows; got {len(p)}"
        )

    # Equal-frequency bins when possible; fall back to equal-width.
    try:
        bin_ids = pd.qcut(p, q=N_RELIABILITY_BINS, labels=False, duplicates="drop")
    except ValueError:
        bin_ids = pd.cut(p, bins=N_RELIABILITY_BINS, labels=False, include_lowest=True)

    rows = []
    for b in sorted(pd.unique(bin_ids)):
        if pd.isna(b):
            continue
        m = bin_ids == b
        if not np.any(m):
            continue
        rows.append(
            {
                "mean_pred": float(np.mean(p[m])),
                "mean_actual": float(np.mean(a[m])),
                "n": int(np.sum(m)),
            }
        )
    if not rows:
        raise RuntimeError("DefCon reliability produced no bins")

    mean_pred = np.array([r["mean_pred"] for r in rows])
    mean_actual = np.array([r["mean_actual"] for r in rows])
    counts = np.array([r["n"] for r in rows])

    fig, ax = plt.subplots(figsize=(6.5, 6))
    lo = 0.0
    hi = max(1.0, float(mean_pred.max()), float(mean_actual.max()))
    ax.plot([lo, hi], [lo, hi], "--", color="#94a3b8", label="perfect calibration")
    sizes = 40 + 120 * (counts / counts.max())
    ax.scatter(mean_pred, mean_actual, s=sizes, c="#2563eb", alpha=0.85, zorder=3)
    ax.plot(mean_pred, mean_actual, color="#2563eb", linewidth=1.2, alpha=0.7)
    ax.set_xlabel("Mean predicted P(DefCon hit)")
    ax.set_ylabel("Empirical DefCon hit rate")
    ax.set_title(
        f"DefCon reliability — 2025-26 holdout GW>{DEFCON_TRAIN_GW_MAX}\n"
        f"played outfield only (n={len(p)}, {len(rows)} bins)"
    )
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper left", frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _load_model_and_names() -> tuple[object, list[str], str]:
    """Prefer points.joblib; fall back to minutes. Names from feature_columns.txt when lengths match."""
    names = [
        ln.strip()
        for ln in FEATURE_COLS.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    for path in (POINTS_MODEL, MINUTES_MODEL):
        if not path.exists():
            continue
        model = joblib.load(path)
        if not hasattr(model, "feature_importances_"):
            continue
        n_imp = len(model.feature_importances_)
        if len(names) == n_imp:
            return model, names, path.name
        if hasattr(model, "feature_name_") and model.feature_name_ and len(model.feature_name_) == n_imp:
            return model, list(model.feature_name_), path.name
        raise RuntimeError(
            f"{path.name} has {n_imp} importances but feature_columns.txt has {len(names)}"
        )
    raise RuntimeError("Neither points.joblib nor minutes.joblib has feature_importances_")


def chart_feature_importances(out: Path) -> Path:
    model, names, src = _load_model_and_names()
    imp = np.asarray(model.feature_importances_, dtype=float)
    if len(imp) != len(names):
        raise RuntimeError(
            f"importance length {len(imp)} != feature name length {len(names)}"
        )
    order = np.argsort(imp)[::-1][:TOP_K_IMPORTANCES]
    top_names = [names[i] for i in order][::-1]
    top_imp = imp[order][::-1]

    fig, ax = plt.subplots(figsize=(8, 7))
    y = np.arange(len(top_names))
    ax.barh(y, top_imp, color="#2563eb", height=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(top_names, fontsize=9)
    ax.set_xlabel("LightGBM feature importance (split counts)")
    ax.set_title(f"Top-{TOP_K_IMPORTANCES} LightGBM importances ({src})")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> int:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # Filenames match README embeds (docs/img/*).
    paths = [
        chart_mae_comparison(IMG_DIR / "mae_bar.png"),
        chart_defcon_reliability(IMG_DIR / "defcon_reliability.png"),
        chart_feature_importances(IMG_DIR / "feature_importance.png"),
    ]
    for p in paths:
        size = p.stat().st_size
        print(f"wrote {p.relative_to(ROOT)} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
