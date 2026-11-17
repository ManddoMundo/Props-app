#!/bin/bash
# Refresh all data, refit both models, rebuild the data blob, grade open desk bets.
# Layout is fixed: /home/claude/props/{src,data,out}. Run from anywhere: bash /home/claude/props/src/run.sh
set -e
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
# research room files (matchup sheets). Not fatal: a file that fails to download keeps its last copy.
soft(){ curl -sfL -m 240 -o "$1.tmp" "$2" && mv "$1.tmp" "$1" || { rm -f "$1.tmp"; echo "research file not refreshed: $1"; }; }
soft nfl_play_by_play_2026.parquet $B/pbp/play_by_play_2026.parquet
soft nfl_ftn_charting_2026.parquet $B/ftn_charting/ftn_charting_2026.parquet
for k in def rush pass; do soft nfl_advstats_week_${k}_2026.parquet $B/pfr_advstats/advstats_week_${k}_2026.parquet; done
soft nfl_players.parquet $B/players/players.parquet
soft nfl_roster_weekly_2026.parquet $B/weekly_rosters/roster_weekly_2026.parquet
soft nfl_injuries_2026.parquet $B/injuries/injuries_2026.parquet
soft nfl_depth_charts_2026.parquet $B/depth_charts/depth_charts_2026.parquet
for y in 2025 2026 2027; do get nba_pb_$y.parquet $S/espn_nba_player_boxscores/player_box_$y.parquet; done
get nba_sched_2027.parquet $S/espn_nba_schedules/nba_schedule_2027.parquet
fi
python3 -c "import pyarrow" 2>/dev/null || pip install --break-system-packages -q pyarrow
cd /home/claude/props/src
echo "== NFL =="; python3 nfl.py | tail -n 14
echo "== NBA =="; python3 nba.py | tail -n 22
python3 build_data.py
node check.js | head -2      # JS engine must match Python: worst rel diff should be under 1e-2
python3 daily.py grade
# research room sheets. Not fatal: if this fails the page keeps the last research/nfl.json.
{ [ -f research_nfl.py ] && python3 research_nfl.py; } || echo "RESEARCH STEP FAILED: the Research tab keeps its last file"
# stress test history: teammates with and without each regular. Not fatal: the page then shows no history.
python3 ww.py || echo "WITH/WITHOUT STEP FAILED: the stress test shows no history"
# trends by split for the Research room. Not fatal: the Splits sheet keeps its last file.
python3 splits.py || echo "SPLITS STEP FAILED: the Splits sheet keeps its last file"
python3 daily.py audit > /home/claude/props/out/audit.txt; head -14 /home/claude/props/out/audit.txt
python3 - <<'PY'
import json; D=json.load(open('/home/claude/props/out/data.json'))
for lg in ('NBA','NFL'):
    L=D[lg]; print(lg,'slate',L['label'],'| data through',L['data_through'],'| games',[(g['day'],g['time'],g['away']+'@'+g['home']) for g in L['games']][:16])
PY
