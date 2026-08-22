"""Upload the generated board to the HF Space x0me/fplbench-board.

Uploads outputs/board/index.html (always) and outputs/board/README.md (only
when it differs from the Space's current README, to avoid noise commits).

The HF token is read from the HF_TOKEN environment variable ONLY and is never
printed or logged.

Usage:
  python scripts/build_board.py && HF_TOKEN=... python scripts/publish_space.py
  python scripts/publish_space.py --dry-run   # report what would upload
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SPACE_ID = "x0me/fplbench-board"
SPACE_README_RAW = f"https://huggingface.co/spaces/{SPACE_ID}/raw/main/README.md"
HEADERS = {"User-Agent": "fplbench/0.1 (research; leakage-safe FPL panel)"}
DEFAULT_DIR = ROOT / "outputs" / "board"


def readme_changed(local: Path) -> bool:
    """True when the local README differs from the Space's current one."""
    try:
        r = requests.get(SPACE_README_RAW, headers=HEADERS, timeout=60)
        r.raise_for_status()
        current = r.text
    except requests.RequestException:
        return True  # can't compare — upload to be safe
    return current.strip() != local.read_text(encoding="utf-8").strip()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=f"Publish the board to {SPACE_ID}")
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="board output dir")
    p.add_argument("--dry-run", action="store_true", help="report, don't upload")
    args = p.parse_args(argv)

    index = args.dir / "index.html"
    readme = args.dir / "README.md"
    if not index.exists():
        raise SystemExit(f"{index} not found — run scripts/build_board.py first")

    uploads = [(index, "index.html")]
    if readme.exists() and readme_changed(readme):
        uploads.append((readme, "README.md"))

    if args.dry_run:
        for path, dest in uploads:
            print(f"would upload {path} -> {SPACE_ID}/{dest}")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN environment variable is required")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    for path, dest in uploads:
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=dest,
            repo_id=SPACE_ID,
            repo_type="space",
            commit_message=f"board: refresh {dest}",
        )
        print(f"uploaded {dest} -> https://huggingface.co/spaces/{SPACE_ID}")


if __name__ == "__main__":
    main()
