#!/bin/bash
# Fair Line daily job. Runs inside GitHub Actions, from the repo root.
#   site_job.sh open   make the fixed work folders, install what the models need, unlock yesterday's books
#   site_job.sh run    run the day (kind comes from the relay step: midday, close, or FORCE=build), rebuild the app, lock the books
# The books (bets, audit, priced lines) are stored encrypted with RELAY_PASS because they hold sportsbook prices.
set -e
R=$(pwd); P=/home/claude/props; ENC="$R/state/state.tar.gz.enc"
OSSL="openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass env:RELAY_PASS"
[ -n "$RELAY_PASS" ] || { echo "RELAY_PASS is not set"; exit 1; }
if [ "$1" = open ]; then
  [ -w /home/claude ] || { sudo mkdir -p /home/claude && sudo chown -R "$(id -u):$(id -g)" /home/claude; }
  mkdir -p $P/src $P/data $P/out/priced $P/out/lines $P/out/news
  [ "$R/pipeline" -ef $P/src ] || cp -r "$R/pipeline/." $P/src/
  [ -n "$SKIP_PIP" ] || python3 -m pip install -q numpy scipy pandas pyarrow
  if [ -f "$ENC" ]; then $OSSL -d -in "$ENC" | tar -C $P -xzf - && echo "books unlocked"; else echo "no saved books yet: starting empty"; fi
  exit 0
fi
KIND=$(cat /tmp/relay_kind 2>/dev/null || echo none); [ -n "$FORCE" ] && KIND=$FORCE
D=$(TZ=America/New_York date +%F); cd $P/src; NOTE=""
case "$KIND" in
  early|midday|build)
    if [ "$KIND" = midday ]; then for LG in NBA NFL; do L=$P/out/lines/${LG}_$D.txt; N=$P/out/news/${LG}_$D.txt
      if [ -f "$L" ]; then python3 daily.py news $D $LG "$([ -f "$N" ] && echo "$N" || echo -)" "$L"; fi; done; fi
    bash run.sh
    [ "$KIND" = early ] && NOTE="Morning refresh. Lines and picks come with the late morning run."
    node check.js | head -2 | python3 -c "import sys,re; v=[float(x) for x in re.findall(r'rel diff ([0-9.e+-]+)', sys.stdin.read())]; print('engine check', v); sys.exit(0 if v and max(v) < 1e-2 else 1)"
    if [ "$KIND" = midday ]; then for LG in NBA NFL; do L=$P/out/lines/${LG}_$D.txt; T=$P/out/lines/${LG}_${D}_today.txt
      if [ -f "$L" ] && python3 daily.py today $D "$L" "$T" && grep -q '^hardrockbet|' "$T"; then python3 daily.py lines $D $LG "$T"; python3 daily.py pick $D $LG
      else NOTE="$NOTE $LG: no Hard Rock lines for games today."; fi; done; fi ;;
  close)
    for LG in NBA NFL; do for F in $P/out/lines/${LG}_${D}_close*.txt; do
      if [ -f "$F" ]; then python3 daily.py close $D $LG "$(TZ=America/New_York date '+%-I:%M %p ET'), relay" "$F" || true; fi; done; done ;;
  *) echo "nothing to build ($KIND)"; exit 0 ;;
esac
python3 build.py; python3 site.py
mkdir -p "$R/docs" "$R/state"; cp -r $P/site/docs/. "$R/docs/"
python3 daily.py report > "$R/state/report.txt" 2>/dev/null || true
python3 daily.py summary "$D" "$KIND" "$NOTE" > "$R/state/summary.json"
find $P/out/priced -name '*.json' -mtime +21 -delete; find $P/out/lines $P/out/news -name '*.txt' -mtime +6 -delete
tar -C $P --exclude='out/index.html' -czf - out | $OSSL -salt -out "$ENC"
echo "built $KIND for $D:"; cat "$R/state/summary.json"
