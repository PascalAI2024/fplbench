"""Native external solver selection shared by every optimizer."""

from __future__ import annotations

import shutil

import pulp


def native_cbc_path() -> str:
    """Return CBC from PATH and fail clearly instead of using a bundled binary."""
    path = shutil.which("cbc")
    if path is None:
        raise RuntimeError(
            "CBC executable not found on PATH; install `cbc` on macOS or "
            "`coinor-cbc` on Ubuntu"
        )
    return path


def solve_status_label(result: object) -> str:
    """Normalize PuLP 3 integer and PuLP 4 structured solve statuses."""
    status = getattr(result, "status", result)
    name = getattr(status, "name", None)
    if name:
        return str(name)
    labels = getattr(pulp, "LpStatus", {})
    return str(labels.get(status, status))
