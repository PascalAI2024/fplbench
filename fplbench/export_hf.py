"""Write the verified Hugging Face dataset export and integrity manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from fplbench.panel import LAG_COLS, feature_columns
from fplbench.paths import HF_EXPORT, PROCESSED, ROOT, VAASTAV_REVISION

CARD_TEMPLATE = ROOT / "docs" / "huggingface" / "DATASET_CARD.md"
FIXTURE_KEY = ["season", "GW", "player_code", "fixture"]
EVENT_KEY = ["season", "GW", "player_code"]
SPLIT_SEASONS = {
    "train": ("2021-22", "2022-23", "2023-24", "2024-25"),
    "validation": ("2025-26",),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_split(df: pd.DataFrame, split: str) -> None:
    """Reject empty, duplicate, or same-GW-lag-inconsistent exports."""
    if df.empty:
        raise ValueError(f"{split} split is empty")
    missing = [column for column in FIXTURE_KEY if column not in df.columns]
    if missing:
        raise ValueError(f"{split} split is missing fixture keys: {missing}")
    duplicates = int(df.duplicated(FIXTURE_KEY).sum())
    if duplicates:
        raise ValueError(f"{split} split has {duplicates} duplicate fixture keys")

    same_event = df[df.duplicated(EVENT_KEY, keep=False)]
    lag_columns = [
        f"{column}_{window}"
        for column in LAG_COLS
        for window in ("l1", "r3", "r5")
        if f"{column}_{window}" in df.columns
    ]
    if not same_event.empty and lag_columns:
        conflicts = (
            same_event.groupby(EVENT_KEY, dropna=False)[lag_columns]
            .nunique(dropna=False)
            .gt(1)
        )
        if conflicts.to_numpy().any():
            count = int(conflicts.any(axis=1).sum())
            raise ValueError(
                f"{split} split has {count} same-GW groups with divergent form lags"
            )


def export_hf(panel_path: Path | None = None) -> Path:
    panel_path = panel_path or (PROCESSED / "panel.parquet")
    panel = pd.read_parquet(panel_path)
    HF_EXPORT.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "format_version": 1,
        "historical_source_revision": VAASTAV_REVISION,
        "row_grain": "player-fixture observation within an FPL gameweek",
        "lag_contract": (
            "All fixtures in one player-gameweek receive the same form lags, "
            "computed before that gameweek's first fixture."
        ),
        "columns": list(panel.columns),
        "column_count": int(len(panel.columns)),
        "splits": {},
    }
    split_manifest: dict[str, object] = {}
    for split, seasons in SPLIT_SEASONS.items():
        frame = panel[panel["season"].isin(seasons)].copy()
        validate_split(frame, split)
        path = HF_EXPORT / f"{split}.parquet"
        frame.to_parquet(path, index=False)
        split_manifest[split] = {
            "file": path.name,
            "rows": int(len(frame)),
            "seasons": list(seasons),
            "sha256": _sha256(path),
        }

    features = feature_columns(panel)
    features_path = HF_EXPORT / "features.txt"
    features_path.write_text("\n".join(features) + "\n", encoding="utf-8")
    manifest["feature_count"] = len(features)
    manifest["features_sha256"] = _sha256(features_path)
    manifest["splits"] = split_manifest

    manifest_path = HF_EXPORT / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (HF_EXPORT / "README.md").write_text(
        CARD_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return HF_EXPORT
