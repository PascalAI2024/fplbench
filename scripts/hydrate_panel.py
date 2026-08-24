"""Hydrate panel.parquet from one immutable, manifest-verified HF revision."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fplbench.export_hf import FIXTURE_KEY, validate_split  # noqa: E402
from fplbench.paths import PROCESSED  # noqa: E402

REPO_ID = "x0me/fplbench"
HF_RESOLVE = f"https://huggingface.co/datasets/{REPO_ID}/resolve"
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _get(url: str) -> bytes:
    response = requests.get(url, headers=HEADERS, timeout=300)
    response.raise_for_status()
    return response.content


def main() -> None:
    requested = os.environ.get("FPLBENCH_HF_REVISION")
    revision = requested or HfApi().repo_info(REPO_ID, repo_type="dataset").sha
    if not revision:
        raise SystemExit("could not resolve an immutable HF dataset revision")
    base = f"{HF_RESOLVE}/{revision}"
    manifest = json.loads(_get(f"{base}/manifest.json"))
    if manifest.get("format_version") != 1:
        raise SystemExit("unsupported or missing dataset manifest version")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    frames = []
    split_meta = manifest.get("splits") or {}
    for split in ("train", "validation"):
        meta = split_meta.get(split) or {}
        name = meta.get("file")
        if name != f"{split}.parquet":
            raise SystemExit(f"manifest has an invalid {split} filename")
        content = _get(f"{base}/{name}")
        if _sha256_bytes(content) != meta.get("sha256"):
            raise SystemExit(f"{split} SHA-256 does not match manifest")
        dest = PROCESSED / f"hf_{name}"
        dest.write_bytes(content)
        frame = pd.read_parquet(dest)
        if len(frame) != int(meta.get("rows", -1)):
            raise SystemExit(f"{split} row count does not match manifest")
        if list(frame.columns) != manifest.get("columns"):
            raise SystemExit(f"{split} schema does not match manifest")
        validate_split(frame, split)
        frames.append(frame)
        print(f"{split}: {len(frame):,} verified rows")

    panel = pd.concat(frames, ignore_index=True)
    if panel.duplicated(FIXTURE_KEY).any():
        raise SystemExit("hydrated panel contains duplicate fixture keys")
    out = PROCESSED / "panel.parquet"
    panel.to_parquet(out, index=False)
    seasons = sorted(panel["season"].unique())
    print(f"panel.parquet: {len(panel):,} rows, seasons={seasons}, revision={revision}")


if __name__ == "__main__":
    main()
