# Portable macOS setup

fplbench uses PuLP's `COIN_CMD` interface so optimization runs the CBC binary
on `PATH`. This avoids PuLP's bundled binary, which can be the wrong
architecture on Apple Silicon.

## Install

```bash
brew install python@3.12 cbc
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

No signing, quarantine, or macOS security changes are required. Do not disable
Gatekeeper to make an incompatible bundled solver run.

## Verify the native solver

```bash
command -v cbc
file "$(command -v cbc)"
cbc -stop
python - <<'PY'
import pulp

solver = pulp.COIN_CMD(msg=False)
path = solver.available()
assert path, "CBC is not available on PATH"
print(path)
PY
```

On Apple Silicon, `file` should report an `arm64` or universal executable.
Homebrew normally links it as `/opt/homebrew/bin/cbc`.

## Verify the project

```bash
python -m compileall -q fplbench scripts tests
python -m pytest -q
python scripts/pick_squad.py
```

The unit suite uses synthetic fixtures and does not require credentials. A
live mid-season forecast additionally requires the project's validated local
official-history bundle. That raw bundle is intentionally not published and
the predictor fails closed when it is absent or does not match the bound
bootstrap and fixture snapshots.

On Ubuntu, install `coinor-cbc` with the system package manager before running
the same Python commands. Other platforms are supported when a native `cbc`
executable is available on `PATH`.

## Troubleshooting

- If PuLP reports that it cannot execute CBC, confirm `command -v cbc` works in
  the same shell that launches Python.
- If `file` reports `x86_64` on an Apple Silicon-only machine, install the
  native Homebrew package instead of changing macOS security settings.
- The project deliberately does not fall back to `PULP_CBC_CMD`; that fallback
  could silently select PuLP's incompatible bundled executable.
