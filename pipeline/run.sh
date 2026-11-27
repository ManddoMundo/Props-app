#!/bin/bash
# Refresh all data, refit both models, rebuild the data blob, grade open desk bets.
# Layout is fixed: /home/claude/props/{src,data,out}. Run from anywhere: bash /home/claude/props/src/run.sh
set -eo pipefail
mkdir -p /home/claude/props/data /home/claude/props/out/priced /home/claude/props/out/lines
cd /home/claude/props/data
if [ -z "$SKIP_DL" ]; then      # SKIP_DL=1 bash run.sh reruns the models on the files already here (used after lineup news lands)
B=https://github.com/nflverse/nflverse-data/releases/download
S=https://github.com/sportsdataverse/sportsdataverse-data/releases/download
get(){ curl -sfL -m 180 -o "$1.tmp" "$2" && mv "$1.tmp" "$1" || { echo "DOWNLOAD FAILED: $2"; exit 1; }; }
for y in 2023 2024 2025 2026; do get nfl_pw_$y.csv $B/stats_player/stats_player_week_$y.csv; done
get nfl_games.csv https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
# snap counts (who actually played). Not fatal: without them grading falls back to the stats file alone.
curl -sfL -m 180 -o nfl_snaps_2026.csv.tmp $B/snap_counts/snap_counts_2026.csv && mv nfl_snaps_2026.csv.tmp nfl_snaps_2026.csv || echo "snap counts not available"
# v3.16: past seasons' snap counts, once (they no longer change). nfl.py adds the games a player was on the field with no stat line.
for y in 2023 2024 2025; do [ -s nfl_snaps_$y.csv ] || { curl -sfL -m 180 -o nfl_snaps_$y.csv.tmp $B/snap_counts/snap_counts_$y.csv && mv nfl_snaps_$y.csv.tmp nfl_snaps_$y.csv || echo "snap counts $y not available"; }; done
# research room files (matchup sheets). Not fatal: a file that fails to download keeps its last copy.
soft(){ curl -sfL -m 240 -o "$1.tmp" "$2" && mv "$1.tmp" "$1" || { rm -f "$1.tmp"; echo "research file not refreshed: $1"; }; }
soft nfl_play_by_play_2026.parquet $B/pbp/play_by_play_2026.parquet
soft nfl_ftn_charting_2026.parquet $B/ftn_charting/ftn_charting_2026.parquet
for k in def rush pass; do soft nfl_advstats_week_${k}_2026.parquet $B/pfr_advstats/advstats_week_${k}_2026.parquet; done
soft nfl_players.parquet $B/players/players.parquet
soft nfl_roster_weekly_2026.parquet $B/weekly_rosters/roster_weekly_2026.parquet
soft nfl_injuries_2026.parquet $B/injuries/injuries_2026.parquet
soft nfl_depth_charts_2026.parquet $B/depth_charts/depth_charts_2026.parquet
# nfelo (open-source NFL model): opening and closing lines since 2009 and its own line, for the Games tab. Not fatal.
soft nfelo_games.csv https://raw.githubusercontent.com/greerreNFL/nfelo/main/output_data/nfelo_games.csv
for y in 2025 2026 2027; do get nba_pb_$y.parquet $S/espn_nba_player_boxscores/player_box_$y.parquet; done
get nba_sched_2027.parquet $S/espn_nba_schedules/nba_schedule_2027.parquet
fi
python3 -c "import pyarrow" 2>/dev/null || pip install --break-system-packages -q pyarrow
cd /home/claude/props/src
echo "== NFL =="; python3 nfl.py > /tmp/nfl.log && tail -n 14 /tmp/nfl.log
echo "== NBA =="; python3 nba.py > /tmp/nba.log && tail -n 22 /tmp/nba.log
python3 build_data.py
node check.js > /tmp/check.log && head -2 /tmp/check.log      # JS engine must match Python: worst rel diff should be under 1e-2
python3 daily.py grade
# research room sheets. Not fatal: if this fails the page keeps the last research/nfl.json.
{ [ -f research_nfl.py ] && python3 research_nfl.py; } || echo "RESEARCH STEP FAILED: the Research tab keeps its last file"
# stress test history: teammates with and without each regular. Not fatal: the page then shows no history.
python3 ww.py || echo "WITH/WITHOUT STEP FAILED: the stress test shows no history"
# trends by split for the Research room. Not fatal: the Splits sheet keeps its last file.
python3 splits.py || echo "SPLITS STEP FAILED: the Splits sheet keeps its last file"
# NBA matchup sheets for the Research room. Not fatal.
python3 nba_match.py || echo "NBA MATCHUP STEP FAILED: the sheet keeps its last file"
# game picks: team ratings, win chances and spread picks for both leagues, then grade any finished picks. Not fatal.
python3 nba_lines.py || echo "NBA LINES STEP FAILED: the NBA track record uses the lines already on file"
python3 weather.py || echo "WEATHER STEP FAILED: no wind notes on the Games tab"
python3 injuries.py || echo "INJURY STEP FAILED: no injury notes on the Games tab"
python3 games.py || echo "GAME MODEL STEP FAILED: the Games tab keeps its last file"
python3 daily.py gpicks "$(TZ=America/New_York date +%F)" grade || true
# v4.2 the game price lane: bounded grading + Polymarket wallet scoring. Never fatal.
timeout 60 python3 gline.py grade || echo "GAME PRICE LANE GRADE FAILED"
timeout 60 python3 sharps.py score || echo "POLYMARKET SCORE FAILED"
# v3.20 the game simulator: grade yesterday's logged props, then play every game on the slate 10,000 times. Not fatal: the Sim tab keeps its last file.
python3 sim.py grade || echo "SIM GRADE STEP FAILED"
python3 sim.py || echo "SIM STEP FAILED: the Sim tab keeps its last file"
python3 daily.py audit > /home/claude/props/out/audit.txt && head -14 /home/claude/props/out/audit.txt
# v3.44 the shadow book: grade every side that cleared the test, picked or not. Tracking only, never fatal.
python3 daily.py shadow || echo "SHADOW STEP FAILED: the shadow book keeps its last file"
python3 - <<'PY'
import json; D=json.load(open('/home/claude/props/out/data.json'))
for lg in ('NBA','NFL'):
    L=D[lg]; print(lg,'slate',L['label'],'| data through',L['data_through'],'| games',[(g['day'],g['time'],g['away']+'@'+g['home']) for g in L['games']][:16])
PY
