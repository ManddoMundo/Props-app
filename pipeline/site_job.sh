#!/bin/bash
# Fair Line daily job (v4.2). Runs inside GitHub Actions, from the repo root.
#   site_job.sh open   make the fixed work folders, install what the models need, unlock yesterday's books
#   site_job.sh run    run the day (kind comes from the relay step: early, midday, evening, close, lineups, or FORCE=build), rebuild the app, lock the books
# The books (bets, audit, priced lines) are stored encrypted with RELAY_PASS because they hold sportsbook prices.
set -eo pipefail
R=$(pwd); P=/home/claude/props; ENC="$R/state/state.tar.gz.enc"
OSSL="openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass env:RELAY_PASS"
[ -n "$RELAY_PASS" ] || { echo "RELAY_PASS is not set"; exit 1; }
if [ "$1" = open ]; then
  [ -w /home/claude ] || { sudo mkdir -p /home/claude && sudo chown -R "$(id -u):$(id -g)" /home/claude; }
  mkdir -p $P/src $P/data $P/out/priced $P/out/lines $P/out/news $P/out/lineups $P/out/games $P/out/poly $P/out/sharps
  [ "$R/pipeline" -ef $P/src ] || cp -r "$R/pipeline/." $P/src/
  [ -n "$SKIP_PIP" ] || python3 -m pip install -q numpy scipy pandas pyarrow
  if [ -f "$ENC" ]; then $OSSL -d -in "$ENC" | tar -C $P -xzf - && echo "books unlocked"; else echo "no saved books yet: starting empty"; fi
  exit 0
fi
KIND=$(cat /tmp/relay_kind 2>/dev/null || echo none); [ -n "$FORCE" ] && KIND=$FORCE
D=$(TZ=America/New_York date +%F); cd $P/src; NOTE=""
case "$KIND" in
  early|midday|build)
    # v3.19: lineup news from today's injury report on every run, lines or not (NFL news used to wait for a game day's lines)
    for LG in NBA NFL; do L=$P/out/lines/${LG}_$D.txt; N=$P/out/news/${LG}_$D.txt; [ "$KIND" = midday ] || L=/nonexistent
      if [ -f "$L" ] || [ -f "$N" ]; then python3 daily.py news $D $LG "$([ -f "$N" ] && echo "$N" || echo -)" $([ -f "$L" ] && echo "$L"); fi; done
    bash run.sh
    [ "$KIND" = early ] && NOTE="Morning refresh. Lines and picks come with the late morning run."
    node check.js > /tmp/check_job.log && head -2 /tmp/check_job.log | python3 -c "import sys,re; v=[float(x) for x in re.findall(r'rel diff ([0-9.e+-]+)', sys.stdin.read())]; print('engine check', v); sys.exit(0 if v and max(v) < 1e-2 else 1)"
    if [ "$KIND" = midday ]; then for LG in NBA NFL; do L=$P/out/lines/${LG}_$D.txt; T=$P/out/lines/${LG}_${D}_today.txt
      if [ -f "$L" ] && python3 daily.py today $D "$L" "$T" && grep -qE '^(hardrockbet|draftkings|fanduel|betmgm|williamhill_us|betrivers|fanatics)\|' "$T"; then python3 daily.py lines $D $LG "$T"; python3 daily.py pick $D $LG; python3 daily.py confident $D $LG "$T" || echo "CONFIDENT LANE FAILED for $LG"
      else NOTE="$NOTE $LG: no Hard Rock lines for games today."; fi; done
      python3 daily.py fill $D || echo "FILL STEP FAILED"
      python3 games.py && python3 daily.py gpicks $D log || echo "GAME PICKS STEP FAILED"
      # v4.2 game price lane (shadow, bounded wall-clock timeout so a stalled external API can never kill the daily job)
      timeout 180 python3 sharps.py pull $D || echo "POLYMARKET STEP FAILED"
      timeout 60 python3 gline.py log $D || echo "GAME PRICE LANE FAILED"; fi ;;
  evening)      # v3.17: about 6 PM. Fresh injuries into the model, closing numbers for the midday bets, then a second look under the same rules
    for LG in NBA NFL; do L=$P/out/lines/${LG}_${D}_pm.txt; N=$P/out/news/${LG}_$D.txt
      if [ -f "$L" ] || [ -f "$N" ]; then python3 daily.py news $D $LG "$([ -f "$N" ] && echo "$N" || echo -)" $([ -f "$L" ] && echo "$L"); fi; done
    bash run.sh
    node check.js > /tmp/check_job.log && head -2 /tmp/check_job.log | python3 -c "import sys,re; v=[float(x) for x in re.findall(r'rel diff ([0-9.e+-]+)', sys.stdin.read())]; print('engine check', v); sys.exit(0 if v and max(v) < 1e-2 else 1)"
    # v3.37: a ticket on a player now ruled out is voided here, before the second look, so its slot goes to the next side that clears the bar
    for LG in NBA NFL; do python3 daily.py scratch $D $LG || echo "SCRATCH STEP FAILED for $LG"; done
    for LG in NBA NFL; do L=$P/out/lines/${LG}_${D}_pm.txt; T=$P/out/lines/${LG}_${D}_pm_today.txt
      if [ -f "$L" ]; then python3 daily.py close $D $LG "$(TZ=America/New_York date '+%-I:%M %p ET'), evening" "$L" || true; fi
      if [ -f "$L" ] && python3 daily.py today $D "$L" "$T" && grep -qE '^(hardrockbet|draftkings|fanduel|betmgm|williamhill_us|betrivers|fanatics)\|' "$T"; then FL_RUN=pm python3 daily.py lines $D $LG "$T" && python3 daily.py evening $D $LG || echo "EVENING PASS FAILED for $LG"
      else NOTE="$NOTE $LG: no evening Hard Rock lines for games still to come."; fi; done
    python3 games.py || echo "GAME MODEL STEP FAILED"
    timeout 180 python3 sharps.py pull $D || echo "POLYMARKET STEP FAILED"
    timeout 60 python3 gline.py close $D || echo "GAME PRICE LANE FAILED" ;;       # v4.2: bounded closing numbers
  close|lineups)
    # v3.24/v3.39: close (Sunday ~12:30 PM) and lineups (~6:40 and ~9:15 PM): fresh injuries, NBA starting lineups, late prices.
    fresh(){ [ -f "$1" ] && [ -n "$(find "$1" -mmin -25)" ]; }
    for LG in NBA NFL; do for F in $P/out/lines/${LG}_${D}_close*.txt; do
      if [ -f "$F" ]; then python3 daily.py close $D $LG "$(TZ=America/New_York date '+%-I:%M %p ET'), relay" "$F" || true; fi; done; done
    for LG in NBA NFL; do N=$P/out/news/${LG}_$D.txt; F=$P/out/lines/${LG}_${D}_late.txt; L=$P/out/lines/${LG}_${D}_pm.txt; [ -f "$L" ] || L=$P/out/lines/${LG}_$D.txt
      if [ -f "$N" ]; then if fresh "$F"; then python3 daily.py news $D $LG "$N" "$F"; else FL_NEWS=late python3 daily.py news $D $LG "$N" $([ -f "$L" ] && echo "$L"); fi; fi; done
    bash run.sh
    node check.js > /tmp/check_job.log && head -2 /tmp/check_job.log | python3 -c "import sys,re; v=[float(x) for x in re.findall(r'rel diff ([0-9.e+-]+)', sys.stdin.read())]; print('engine check', v); sys.exit(0 if v and max(v) < 1e-2 else 1)"
    for LG in NBA NFL; do python3 daily.py scratch $D $LG || echo "SCRATCH STEP FAILED for $LG"; done
    for LG in NBA NFL; do F=$P/out/lines/${LG}_${D}_late.txt; L=$P/out/lines/${LG}_${D}_pm.txt; [ -f "$L" ] || L=$P/out/lines/${LG}_$D.txt; T=$P/out/lines/${LG}_${D}_late_today.txt
      if fresh "$F"; then
        python3 daily.py close $D $LG "$(TZ=America/New_York date '+%-I:%M %p ET'), late" "$F" || true
        if python3 daily.py today $D "$F" "$T" && grep -qE '^(hardrockbet|draftkings|fanduel|betmgm|williamhill_us|betrivers|fanatics)\|' "$T"; then FL_RUN=late python3 daily.py lines $D $LG "$T" && python3 daily.py evening $D $LG late || echo "LATE PASS FAILED for $LG"; fi
      elif [ -f "$L" ] && python3 daily.py today $D "$L" "$T" && grep -qE '^(hardrockbet|draftkings|fanduel|betmgm|williamhill_us|betrivers|fanatics)\|' "$T"; then FL_RUN=late python3 daily.py lines $D $LG "$T" || echo "LATE PRICING FAILED for $LG"; fi; done
    # v4.2: capture real pre-kickoff Sunday NFL closes (12:30 PM) and late NBA pre-tip closes (6:40 / 9:15 PM) + final Polymarket trades
    timeout 180 python3 sharps.py pull $D || echo "POLYMARKET STEP FAILED"
    timeout 60 python3 gline.py close $D || echo "GAME PRICE LANE CLOSE FAILED" ;;
  *) echo "nothing to build ($KIND)"; exit 0 ;;
esac
python3 build.py; python3 site.py
mkdir -p "$R/docs" "$R/state"; cp -r $P/site/docs/. "$R/docs/"
python3 daily.py report > "$R/state/report.txt" 2>/dev/null || true
python3 daily.py summary "$D" "$KIND" "$NOTE" > "$R/state/summary.json"
# v4.2: append game price lane & wallet board reports (stderr printed to job log, never fatal) and update summary counts
{ timeout 60 python3 gline.py report; timeout 60 python3 sharps.py report; } >> "$R/state/report.txt" || echo "GAME PRICE REPORT FAILED"
timeout 60 python3 gline.py summary "$R/state/summary.json" || echo "GAME PRICE SUMMARY FAILED"
# v4.2: prune all daily state files including out/poly and out/sharps/<date>.json so encrypted state stays bounded
find $P/out/priced -name '*.json' -mtime +21 -delete 2>/dev/null || true
find $P/out/lines $P/out/news $P/out/lineups -name '*.txt' -mtime +6 -delete 2>/dev/null || true
find $P/out/games -name '*.txt' -mtime +30 -delete 2>/dev/null || true
find $P/out/poly -name '*.txt' -mtime +14 -delete 2>/dev/null || true
find $P/out/sharps -maxdepth 1 -name '20*.json' -mtime +14 -delete 2>/dev/null || true
# v4.2: atomic encrypted state write (never truncates $ENC in-place)
tar -C $P --exclude='out/index.html' -czf - out | $OSSL -salt -out "$ENC.tmp" && mv "$ENC.tmp" "$ENC"
echo "built $KIND for $D:"; cat "$R/state/summary.json"
