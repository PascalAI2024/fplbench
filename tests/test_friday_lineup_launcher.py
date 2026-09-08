import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_noninteractive_lineup_launcher_enables_chrome_tools() -> None:
    launcher = (ROOT / "scripts" / "friday_lineup.cmd").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "friday_lineup_runner.ps1").read_text(encoding="utf-8")

    assert "friday_lineup_runner.ps1" in launcher
    assert '"--chrome"' in runner
    assert '"--permission-mode", "auto"' in runner
    assert "--dangerously-skip-permissions" not in launcher
    assert "--dangerously-skip-permissions" not in runner


# The runner is a Windows operator-machine launcher; Linux CI has no
# powershell.exe. The text-contract test above still runs everywhere.
@pytest.mark.skipif(
    shutil.which("powershell.exe") is None,
    reason="powershell.exe unavailable (non-Windows runner)",
)
def test_runner_rejects_false_success_when_agent_reports_failure(tmp_path: Path) -> None:
    fake_claude = tmp_path / "fake-claude.cmd"
    fake_claude.write_text(
        "@echo off\r\necho FPLBENCH_RUN_STATUS=FAILED\r\nexit /b 0\r\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "friday_lineup_runner.ps1"),
            "-ClaudeExe",
            str(fake_claude),
            "-PromptPath",
            str(ROOT / "scripts" / "friday_lineup.prompt.md"),
            "-OutputDir",
            str(tmp_path / "outputs"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "FPLBENCH_RUN_STATUS=FAILED" in (
        tmp_path / "outputs" / "friday_lineup_last_run.log"
    ).read_text(encoding="utf-8-sig")
