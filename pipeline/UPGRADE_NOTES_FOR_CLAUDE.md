# Fair Line v3.52 Upgrade Package — Handoff for Claude

Drop these files into `/home/claude/props/src/` (keeping the lab scripts in `src/` or `lab/`), then run the verification and backtest commands below before publishing.

## 1. Included Files & What Changed

| File | Type | What Changed |
| :--- | :--- | :--- |
| **`common.py`** | Drop-in | Added `pid_str()` to canonically normalize NBA `athlete_id` (`str(float(x))`) so parquet schema changes (`int64` vs `float64`) never break joins or grading. |
| **`daily.py`** | Drop-in | 1) Leave-one-out, sharp-weighted (`mk_w`), power-devigged consensus in `price_all()` (`use_loo_cons=True`, `use_power_devig=True`).<br>2) `calib()` now filters to post-v1.3 market-checked rows and fits `w` via regularized **binary log-loss** at the line (`cal_w_n0=250`, `cal_w_max=0.45`, `use_logloss_calib=True`).<br>3) `cmd_confident()` directly power-devigs alternate rungs when `>= conf_books` other books quote the exact same rung (`direct_alt=True`) instead of extrapolating into the NB tail.<br>4) Direct NBA parquet grading (`nba_box()` / `nba_actual()`) so 4+ day schedule gaps never drop or mis-void NBA tickets.<br>5) `cmd_audit()` now filters `priced/*.json` to midday files only (no `_pm`/`_late` leakage).<br>6) Added a **Hard Rock–only** shadow lane (`hr_only`) in `cmd_shadow()` / `shadow_report()` for Florida execution visibility.<br>7) `fill_live=False` routes `cmd_fill()` 1%–3% leans into `shadow.json["leans"]` instead of live `history.json`. |
| **`books.py`** | Drop-in | Normalized whole-number lines for pushes (`ov / (ov + un)`) and switched implied means to `power_fair()`. |
| **`build_data.py`** | Drop-in | Replaced hardcoded `"built": "2026-11-11"` with live UTC timestamp. |
| **`apply_ui_fixes.py`** | Patch script | Safely patches `simtab.css` (removes stray `}` and duplicated v3.42 `.sm-leg` block; fixes `.sm-leg.on .tk` → `.sm-leg.on .slp`), syncs league-aware `HOLD_EDGE` (`NBA: 0.25, NFL: 0.12`) in `index.src.html`, and wires `pid_str()` into `nba.py`. |
| **`test_fairline.py`** | Unit tests | Verifies `pid_str`, `power_fair`, whole-line push normalization, `implied_mean` round-trip, leave-one-out weighted consensus, and `eligible()` guards. |
| **`nba_vegas_bt.py`** | Lab backtest | Walk-forward test of adding Vegas implied team total + blowout minutes adjustment (`out/nba_lines.jsonl`) into `nba.py`. |
| **`nfl_pos_bt.py`** | Lab backtest | Walk-forward test of positional-bucket share renormalization (RB room / WR-TE-RB rooms) in `nfl.py`. |

## 2. Commands for Claude to Run

```bash
cd /home/claude/props/src

# 1. Apply the safe in-place UI & ID patches (also delete duplicate rest_out_bt_2.py if present)
python3 apply_ui_fixes.py /home/claude/props/src

# 2. Run the unit test suite
python3 test_fairline.py

# 3. Run the pipeline dry check and verify Python <-> JS parity
SKIP_DL=1 bash run.sh
node check.js | head -2

# 4. Run the two walk-forward lab backtests before modifying nba.py / nfl.py / engine.js
python3 nba_vegas_bt.py
python3 nfl_pos_bt.py
```

## 3. Policy & Rollback Notes
- Every pricing upgrade in `daily.py` is behind a single `CFG` toggle (`use_power_devig`, `use_loo_cons`, `use_logloss_calib`, `fill_live`) so you can replay historical lines before/after or revert any single change cleanly.
- Do **not** merge `nba_vegas_bt.py` or `nfl_pos_bt.py` into `nba.py`/`nfl.py`/`engine.js` until the walk-forward test shows an out-of-sample gain in both test folds, per `RUNBOOK.md`.
