"""Atomically publish the verified dataset export and generated dataset card."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fplbench.paths import HF_EXPORT  # noqa: E402
from publish_hf_card import DEFAULT_RESULTS, REPO_ID, build_card  # noqa: E402

FILES = ("train.parquet", "validation.parquet", "features.txt", "manifest.json")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Publish verified data to {REPO_ID}")
    parser.add_argument("--dir", type=Path, default=HF_EXPORT)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--card", type=Path, help="previously verified dataset card")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    missing = [name for name in FILES if not (args.dir / name).is_file()]
    if missing:
        raise SystemExit(f"missing export files: {missing}; run fplbench.export_hf first")
    payloads = {name: (args.dir / name).read_bytes() for name in FILES}
    payloads["README.md"] = (
        args.card.read_bytes() if args.card is not None else build_card(args.results).encode("utf-8")
    )

    if args.dry_run:
        for name, content in payloads.items():
            print(f"would publish {name}: {len(content):,} bytes sha256={_sha256(content)}")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN environment variable is required")
    api = HfApi(token=token)
    parent = api.repo_info(REPO_ID, repo_type="dataset").sha
    source_sha = os.environ.get("GITHUB_SHA", "local verified build")
    commit = api.create_commit(
        repo_id=REPO_ID,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(path_in_repo=name, path_or_fileobj=content)
            for name, content in payloads.items()
        ],
        commit_message="dataset: publish leakage-safe DGW repair",
        commit_description=(
            "Atomic verified export from PascalAI2024/fplbench. "
            f"Source revision: {source_sha}. Parent: {parent}."
        ),
        parent_commit=parent,
    )

    for name, expected in payloads.items():
        downloaded = Path(
            hf_hub_download(
                repo_id=REPO_ID,
                filename=name,
                repo_type="dataset",
                revision=commit.oid,
                token=token,
            )
        ).read_bytes()
        if _sha256(downloaded) != _sha256(expected):
            raise RuntimeError(f"immutable readback mismatch for {name}")
    print(f"published and verified {len(payloads)} files -> {commit.commit_url}")


if __name__ == "__main__":
    main()
