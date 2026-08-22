@echo off
rem Weekly FPL auto-lineup — created 2026-08-22. Runs headless Claude with the
rem scoped prompt; requires Chrome open + logged into fantasy.premierleague.com.
cd /d C:\Users\pasca\dev\fplbench
if not exist outputs mkdir outputs
type scripts\friday_lineup.prompt.md | C:\Users\pasca\.local\bin\claude.exe -p --dangerously-skip-permissions >> outputs\friday_lineup_run.log 2>&1
