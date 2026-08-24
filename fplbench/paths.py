from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
VAASTAV = DATA_RAW / "vaastav"
LIVE = DATA_RAW / "live"
PROCESSED = ROOT / "data" / "processed"
HF_EXPORT = PROCESSED / "hf"
MODELS = ROOT / "outputs" / "models"
PREDS = ROOT / "outputs" / "predictions"

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
LIVE_SEASON = "2026-27"

# Official FPL DefCon thresholds (still in force for 2026/27).
DEFCON_DEF_THRESHOLD = 10  # CBIT
DEFCON_OUTFIELD_THRESHOLD = 12  # CBIT + recoveries

VAASTAV_REVISION = "c2add969e11ec19002a091f8aa60164c9a255854"
VAASTAV_RAW = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/"
    f"{VAASTAV_REVISION}"
)
FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"
