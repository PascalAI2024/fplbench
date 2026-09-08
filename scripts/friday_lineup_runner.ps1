param(
    [string]$ClaudeExe = "C:\Users\pasca\.local\bin\claude.exe",
    [string]$PromptPath = "C:\Users\pasca\dev\projects\fplbench\main\scripts\friday_lineup.prompt.md",
    [string]$OutputDir = "C:\Users\pasca\dev\projects\fplbench\main\outputs",
    [string]$RepoRoot = "C:\Users\pasca\dev\projects\fplbench\main"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Task Scheduler starts us in system32. The prompt runs git and reads
# prediction artifacts by relative path, so anchor the cwd at the repo --
# the launcher .cmd did this with "cd /d" before it was rewritten.
Set-Location -LiteralPath $RepoRoot

$runTimestamp = [DateTimeOffset]::Now.ToString("o")
$lastRunPath = Join-Path $OutputDir "friday_lineup_last_run.log"
$aggregateLogPath = Join-Path $OutputDir "friday_lineup_run.log"

try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $prompt = Get-Content -Raw -LiteralPath $PromptPath
    $claudeArgs = @(
        "--chrome",
        "-p",
        "--permission-mode", "auto",
        "--no-session-persistence"
    )

    $rawOutput = $prompt | & $ClaudeExe @claudeArgs 2>&1
    $claudeExitCode = $LASTEXITCODE
    $outputText = ($rawOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
} catch {
    $claudeExitCode = 10
    $outputText = "FPLBENCH_RUN_STATUS=FAILED`nrunner_error=$($_.Exception.Message)"
}

$runRecord = "[$runTimestamp]`n$outputText`n"
Set-Content -LiteralPath $lastRunPath -Value $runRecord -Encoding UTF8
Add-Content -LiteralPath $aggregateLogPath -Value $runRecord -Encoding UTF8

if ($claudeExitCode -ne 0) {
    exit $claudeExitCode
}

$successMatches = [regex]::Matches(
    $outputText,
    '(?m)^FPLBENCH_RUN_STATUS=(SUCCESS_NOOP|SUCCESS_CHANGED)\s*$'
)
$failureMatches = [regex]::Matches(
    $outputText,
    '(?m)^FPLBENCH_RUN_STATUS=FAILED\s*$'
)

if ($successMatches.Count -ne 1 -or $failureMatches.Count -ne 0) {
    exit 2
}

exit 0
