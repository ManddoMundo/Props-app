# Fair Line Lab Scripts — Higher-Resolution Tracking & Snap Features

**Zero production files touched.** None of these scripts modify `nba.py`, `nfl.py`, `daily.py`, `engine.js`, `CHANGELOG.md`, or `RUNBOOK.md`. They are strictly standalone walk-forward research tests matching `shot_bt.py`.

## 1. NBA Potential Assists & Rebound Chances (`pt_pull.py` + `pt_bt.py`)
Tests whether decomposing NBA assists and rebounds into tracking volume × steadied conversion (`potential_assists/min × ast/potential_ast` and `reb_chances/min × reb/reb_chances`) beats box-score rates out-of-sample across BOTH 2025–26 and 2026–27.

```bash
cd /home/claude/props/src
# Step 1: Test 3 dates first to confirm stats.nba.com responds from this environment
python3 pt_pull.py 2027 --limit 3
# If stats.nba.com succeeds, pull all three seasons (resumable; saves every 10 dates)
python3 pt_pull.py 2025 2026 2027
# Step 2: Run the walk-forward backtest (fits on 2024-25 only, scores on 2025-26 & 2026-27)
python3 pt_bt.py
```
*(If `stats.nba.com` blocks cloud IPs with 403/timeout, run `pt_pull.py` on a residential machine and copy `nba_pt_2025..2027.parquet` into `/home/claude/props/data/`.)*

## 2. NFL Offensive Snap Share × Targets Per Snap (`nfl_snap_bt.py`)
Tests decomposing receiver target share into fast-memory snap share (`HL=3`) × slow-memory target rate per snap (`HL=10`) using the `nfl_snaps_20*.csv` files `run.sh` already downloads.

```bash
cd /home/claude/props/src
python3 nfl_snap_bt.py
```
**Preliminary run on your 2023–26 CSVs (`w_snap=0.50`):**
- 2025 (`n=2,754`): `rec` `-0.09%`, `rec_yds` `-0.10%`, **TE `rec_yds` `-0.88%` (96% better)**
- 2026 (`n=1,578`): `rec` `-0.79%` (99% better), `rec_yds` `-0.72%` (100% better), **TE `rec_yds` `-1.14%` (100% better)**
- Re-run in Claude with `nfl_players.parquet` present so it uses exact `gsis_id` joins instead of name matching.
