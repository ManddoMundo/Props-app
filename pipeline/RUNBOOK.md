# Prop Underwriter runbook

Owner: Armanddo. Artifact slug: `3e7dec79-c0d0-4f7e-ac23-b04639b091aa` (title "Fair Line", formerly Prop Underwriter).
The artifact stores its own pipeline. A fresh session rebuilds everything from these files.

## Files in the artifact
- `index.html` the page (built, never edit by hand)
- `pipeline/` source: `common.py nfl.py nba.py build_data.py daily.py build.py research_nfl.py relay_pull.py site.py site_job.sh run.sh` (each stored with `.txt` added, for example `pipeline/nba.py.txt`, because the host will not serve .py or .sh) plus `engine.js check.js index.src.html RUNBOOK.md CHANGELOG.md`
- `desk/history.json` the model's bet log. This is the record of truth. Never drop or rewrite past bets.
- `desk/audit.json` every priced side that has been graded (model vs book)
- `desk/priced/<LG>_<date>.json` every side priced on a day, `desk/lines/<LG>_<date>.txt` the raw book tables, `desk/news/<LG>_<date>.txt` the raw injury tables

## Bootstrap (every scheduled run starts here)
1. Load the artifact tools with ToolSearch: `select:mcp__claude-artifacts__list_files,mcp__claude-artifacts__read_file,mcp__claude-artifacts__publish_files`.
2. `list_files(slug)`. Note the version it reports (needed as `base_version` when publishing).
3. `read_file(slug, paths=[...])` for every `pipeline/*` file, `desk/history.json`, `desk/audit.json`, and the `desk/priced/*` files from the last 14 days. With `paths` the files come back saved on disk. Copy them with `cp` (never retype them):
   - `pipeline/*` to `/home/claude/props/src/`, dropping the `.txt` suffix from the .py and .sh files (when publishing, add it back)
   - `desk/history.json` and `desk/audit.json` to `/home/claude/props/out/`
   - `desk/priced/*` to `/home/claude/props/out/priced/`
   If `paths` is refused, stop and report. Do not rebuild files from text in tool results.
4. `bash /home/claude/props/src/run.sh`. It downloads data from GitHub, refits both models, checks the JS engine against Python, grades open bets, and prints each slate.
   If a download fails or `check.js` shows a worst rel diff above 1e-2, stop, publish nothing, and report.

## Daily run: news, lines, picks, publish (v1.6: relay first)
FIRST, check who runs the day (v2.1): `curl -sfL https://raw.githubusercontent.com/ManddoMundo/Props-app/main/state/summary.json`.
- It returns JSON: GitHub is the daily runner and the ONLY one that prices lines and picks. Do not run `daily.py lines`, `pick`, `news` or the WebFetch route, even if the task prompt describes them. Mirror instead:
  1. `cd /home/claude/props/src && RELAY_PASS='<passphrase from the task prompt>' python3 daily.py mirror` (unpacks GitHub's books into `/home/claude/props/out`: history, audit, priced, lines, news, data.json, research).
  2. `python3 build.py`, then publish `index.html`, `research/nfl.json`, `research/sim_nba.json`, `research/sim_nfl.json`, `desk/history.json`, `desk/audit.json` and the newest `desk/priced` files. Never edit the mirrored books.
  3. Report from the mirrored books (`python3 daily.py report`) and from summary.json: its `date`, `picks_today`, `note`, and `version`. If `date` is not today's US Eastern date, say GitHub has not run today yet and that the standalone app updates when it does. Do not pick in its place. If `version` differs from `/home/claude/props/src/VERSION`, say an upload to GitHub is pending.
- It fails with 404: GitHub has not taken over. Use the steps below as before.
0. Relay first. A scheduled job in Armanddo's GitHub repository (`ManddoMundo/Props-app`) pulls the day's lines and injury reports late each morning and saves them encrypted. The passphrase is in the scheduled task prompt as the relay passphrase. Use it only on this command line and never write it into a file:
   `cd /home/claude/props/src && RELAY_PASS='<passphrase>' python3 daily.py relay <US Eastern date>`
   It prints the relay's last run, the credits left, and one line per file it saved: `out/lines/<LG>_<date>.txt` (seven books, every market the relay pulls, `# game:` markers already in place) and `out/news/<LG>_<date>.txt` (ESPN injury feed, all teams, in the table step 5 reads).
   - A league with a saved lines file that has Hard Rock rows: skip steps 1 to 4 for that league and spend no API credits on it. Go to step 5 with the saved files.
   - A league with games today and no saved file, or a file with no Hard Rock rows: use steps 1 to 4 (WebFetch) for that league. If the relay saved a lines file without Hard Rock rows, pass it to step 6 after the WebFetch file so the other books still serve as the market check.
   - If the command prints that nothing was saved or it cannot decrypt, use steps 1 to 4 as before and say so in the report. Do not try to repair the relay from this run.
   - The relay feeds more markets than the desk picks from. `daily.py` prices and grades all of them; edge plays and leans come only from `CFG["pick_markets"]` (NBA points, rebounds, assists; NFL receiving, rushing and passing yards). The confident lane follows the books' consensus, not the model, and is not limited to that list. Do not edit the list in a daily run. (The guard went missing from the code between v1.6 and v3.18; restored in v3.19.)
Book lines come from The Odds API and injury reports from ESPN, both through WebFetch (the shell cannot reach them). The API key is in the scheduled task prompt, not in these files. Never write the key into any file that gets published.
If the scheduled task prompt shows an older odds URL with `bookmakers=hardrockbet` only, use the four-book pattern below instead. It costs the same credits. Hard Rock is still the only book the desk bets at; the other three are the market check, and without them no side can be picked.

1. Events (free): `https://api.the-odds-api.com/v4/sports/<SPORT>/events?apiKey=KEY` with SPORT `basketball_nba` or `americanfootball_nfl`. Ask WebFetch for a table: `id | commence_time | away_team | home_team`, ids copied character for character.
2. Choose games that have not started and tip at least 40 minutes from now, on today's US Eastern date.
   - NBA: at most 4 games a day (earliest tips first). Markets `player_points`, `player_rebounds`, `player_assists`.
   - NFL: only on a day with NFL games. At most 3 games on Sunday, 1 on other days. Markets `player_reception_yds`, `player_rush_yds`, `player_pass_yds`.
   - Credit budget: one credit per market per game, whatever the number of books (up to 10 books count as one region). Stay at or under 15 credits a day. If a response says the quota is exhausted, skip lines, still refresh and publish, and report it.
3. Injury report: WebFetch `https://www.espn.com/nba/injuries` (and `https://www.espn.com/nfl/injuries` on NFL days; that page is long, so read on with the offset WebFetch gives until both teams are covered). Ask for a table `team | player | pos | est_return | status | comment` for only the teams in the chosen games. Save it to `/home/claude/props/out/news/<LG>_<date>.txt`. If the fetch fails, carry on and pass `-` as the injuries file in step 5.
4. Odds, one call per game per market (smaller tables copy more reliably, same cost): `https://api.the-odds-api.com/v4/sports/<SPORT>/events/<ID>/odds?apiKey=KEY&bookmakers=hardrockbet,draftkings,fanduel,betmgm&markets=<ONE_MARKET>&oddsFormat=american`. Ask for compact rows with no header and no spaces around the pipes: `bookmaker_key|market_key|player|line|over_price|under_price`, one row per bookmaker per player, every number copied exactly, a price left empty if missing, no commentary.
   Save the rows verbatim to `/home/claude/props/out/lines/<LG>_<date>.txt` (date is the US Eastern game date). Put a line `# game: AWAY @ HOME` before each game's rows, using the model's team codes as printed by run.sh (for example `# game: LAC @ BAL`). NFL needs that line: it is how the passing yards market names each team's quarterback.
   Sanity check: Hard Rock's line should sit close to the other books for most players. If a table looks garbled, refetch once (only if credits allow), then skip that game.
5. Lineup news, then rerun the models on it:
   `cd /home/claude/props/src && python3 daily.py news <date> <LG> ../out/news/<LG>_<date>.txt ../out/lines/<LG>_<date>.txt` for each league, then `SKIP_DL=1 bash run.sh`.
   run.sh must print `lineup news: on` for each league with news, and `check.js` must pass again (worst rel diff under 1e-2). What news does: a player listed out sits; a player the books are quoting plays (this also covers a starter back from a rest night, and beats a stale status); questionable players are priced but never picked; the book's passing line sets the NFL quarterback, even one new to the team.
6. `python3 daily.py lines <date> <LG> ../out/lines/<LG>_<date>.txt && python3 daily.py pick <date> <LG>`
   The policy in `daily.py` decides. Do not hand pick, override, or add bets. Zero picks on a day is a valid result and will be more common than before v1.3.
   `pick` also writes the case file onto each bet (`why`: what each book quoted, where the edge comes from, form, lineup, matchup, what beats it) and the day's pass list (the closest calls and the test each failed). `python3 daily.py explain <date> <LG>` rebuilds both and is safe to rerun. The text is built from the pricing numbers only. Do not edit it by hand.
7. `python3 build.py` then publish (patch mode, `base_version` from bootstrap): `index.html` from `/home/claude/props/out/index.html`, `research/nfl.json` from `/home/claude/props/out/research/nfl.json` (the Research tab fetches it; if the research step failed, leave it out and the page keeps the last one), `desk/history.json`, `desk/audit.json`, today's `desk/priced/...`, `desk/lines/...` and `desk/news/...` files.
8. Report in a few lines: yesterday's results, the running record and hit rate (`python3 daily.py report`), today's picks with line, odds, probability, and the model, market and blended projections, anything that failed.

### Closing line check (optional second run, 15 to 45 minutes before the first tip)
The number a professional is judged by. It needs its own scheduled run near tip and one credit per game and market that has an open bet.
1. For each open bet, one odds call for that game and that market only (same four books, same row format). Save the rows to `/home/claude/props/out/lines/<LG>_<date>_close.txt`.
2. `python3 daily.py close <date> <LG> "<time, for example 6:25 PM ET, 45 min before tip>" ../out/lines/<LG>_<date>_close.txt`
3. `python3 build.py` and publish `index.html`, `desk/history.json` and the close file.
It records on each bet where Hard Rock closed, the market's fair chance at the close, how far the market moved since the bet, and closing line value (a dollar at the price taken, valued at the closing fair price, minus one). `daily.py report` prints the average. Do not change the bet itself.

### How a side is priced since v1.3
- Each book's line and prices are turned into the projection they imply. The median across the other three books is the market view.
- The model is centred on the market for the slate, market by market (`centre` in daily.py), so a general lean cannot create bets.
- Pricing mean = market + w x (centred model - market). `w` is relearned every run from every graded side in audit.json (`calib`), pulled toward 0.25.
- A side can be picked only if: at least `min_books` other books quote it, blended edge is at least `min_edge`, the centred model on its own is not more than `max_edge` from the book (a gap that wide is usually news), the player is not questionable and did not miss two straight, plus the older odds, history and minutes rules.

## Weekly review
See the scheduled task prompt. Rules that always hold:
- Evidence first. A change to the projection model must hold or improve the walk-forward backtest printed by `nfl.py` / `nba.py` (average miss and calibration on held-out seasons). A change to pick policy needs the audit table (`python3 daily.py audit`) with at least 200 graded sides behind it. A week of 20 picks proves nothing by itself.
- One or two changes a week at most. Log each in `pipeline/CHANGELOG.md`: date, what changed, the before and after numbers, why.
- Python and `engine.js` must stay in step: any change to how a mean is computed goes in both, and `node check.js` must pass.
- Never change the bankroll, unit size, or past bets. Never place real bets. Never share or republish the page elsewhere.
- If anything breaks, leave the live version alone and report.

## Known limits (good places to look for improvements)
- Lineup news is read once, at run time. Anything after that is missed. A quoted player the model has no recent games for (back from a long absence) cannot be added, so his teammates' projections stay too high; the max_edge hold usually catches those.
- The model runs about 7 to 10 percent under the market on players the books price. Cause found in v1.4: those players played 7.7% more minutes than projected across 499 graded lines, while all rotation players together were projected about right. A book quote is news (the book expects a full night). Centring corrects it at pricing; the raw projections on the Board still read low for quoted players. A cleaner fix would lift quoted players' minutes inside the 240 rebalance, in both nba.py and engine.js.
- Tested and rejected in v1.4: NBA back to back and home or away factors (no gain on unseen games).
- The page is the product now: type, motion and the case file layout live in index.src.html. Fonts load from Google Fonts (Ultra, Besley, Sometype Mono, Doto). Keep motion on transform and opacity and keep the reduced motion block working.
- NBA: no rest or back to back adjustment, no home and away split, no defense by position, no pace by opponent beyond team totals.
- NFL: no weather, no snap or route share (snap counts are now downloaded: data/nfl_snaps_2026.csv), yardage curve may be too skewed for low volume players.
- No closing line tracking. It needs a second odds pull near tip, which the 15 credit budget does not cover.
- Odds pass through a summarising fetch tool. Treat any odd looking number as suspect.
- Model and book often disagree by more than is plausible. Sides with an edge above CFG max_edge are skipped on purpose: a gap that large is usually news the model lacks.

## Research room (v1.5)
- `research_nfl.py` builds `out/research/nfl.json` from free nflverse files (play-by-play, weekly stats, snap counts, weekly rosters, injuries, depth charts, FTN charting flags, Pro Football Reference advanced stats). `run.sh` downloads those files and runs the script. Both steps are soft: a failure prints a line and the page keeps its last research file. A failed research step is never a reason to hold the publish.
- The page loads `research/nfl.json` with a relative fetch when the Research tab opens in NFL. Publish it beside `index.html` at that exact path.
- Nothing in the research file feeds `nfl.py`, `nba.py` or the pick policy. It is display only. Do not use it to add, drop or change a bet.
- Hit rates on the Research tab are worked out in the page from the lines feed and each player's last ten games already in the data blob. No extra odds credits.
- Not built, and why: hit rates on every market and alternate line, trends by split and market grades need a line for every player and market (The Odds API 20K plan plus a relay that saves lines where the shell can read them). Alignment, receiver against cornerback and coverage scheme data has no source at a consumer price for the season in progress.
- Roles: receivers and tight ends by offensive snap share, backs by carries plus targets, quarterback from the depth chart, averaged over the team's last five games, active players only. The snap file labels some backs HB, so positions come from the stat file.

## Lines relay (v1.6)
- Why: the shell here cannot reach The Odds API or ESPN, and WebFetch returns tables that have to be retyped. The relay runs where both are reachable and hands back plain files.
- What: one workflow file in the repo, `.github/workflows/lines.yml`. Its source is `pipeline/relay_lines.yml.txt`, built from `pipeline/relay_pull.py` (the script is embedded in the workflow, so the repo needs only the one file). To change it, edit `relay_pull.py`, replace the copy inside the yml (the script sits between `python3 - <<'PY'` and `PY`, every line indented ten spaces), and ask Armanddo to paste the new file into the repo. A run here cannot push to GitHub.
- Secrets live in the repo's Actions secrets: `ODDS_API_KEY` and `RELAY_PASS`. Neither appears in any file. Every data file is encrypted with `RELAY_PASS` (openssl aes-256-cbc, pbkdf2, 200000 rounds), because The Odds API terms do not allow passing its data on as downloadable files and the repo has to be public for this shell to read it. `status.json` is plain and holds only times, counts, credits left and error messages.
- Schedule (US Eastern, the script checks the clock so daylight time needs no edit): late morning for the day's lines and injuries, early evening for closing lines, Sunday midday for the afternoon NFL games. Files: `data/lines/<LG>_<date>.txt.enc`, `data/lines/<LG>_<date>_close<HH>.txt.enc`, `data/news/<LG>_<date>.txt.enc`.
- Credits: one per market per game. Full tier (3000 or more credits left): NBA 8 markets, NFL 9, every game today, NFL games in the next 30 hours, the whole NFL week on Wednesday, capped at 450 a run. Lite tier (under 3000): three markets, four games, no closing pull. Under 150 left it pulls injuries only.
- Closing lines: `daily.py relay` also saves any `_close` file for the date. Feed it to `python3 daily.py close <date> <LG> "<label>" <file>` on the next run that has open bets from that date still ungraded.
- New markets are on trial. Threes, the combos, attempts, completions, catches and touchdowns are priced, shown and graded in the audit. The desk does not pick from them until the weekly review adds a market to `CFG["pick_markets"]` with at least 200 graded sides behind it.

## Page notes (v1.7)
- Dropdowns: keep writing plain `<select>` markup with an `aria-label`. The page upgrades every select it finds into its own picker (`enhance()`, run by a MutationObserver) and the select still fires `change`. Option text is split at " · " into a bold part and a small part.
- Each page starts with `mast(tab, title, sub)`. The art and entrance animation for a room live in the `.m-<tab>` CSS rules. A masthead animates only on arrival (`S.enter`), not on every repaint.
- League change uses `go(fn, 'iris')`. `main` must stay opaque and at least a screen tall, or the old league shows through while the new sheet opens.

## GitHub runs the day (v2.1)
- The repo `ManddoMundo/Props-app` holds a copy of `pipeline/`, the workflow `.github/workflows/lines.yml` (source: `pipeline/lines.yml`), the encrypted books `state/state.tar.gz.enc`, and the standalone app in `docs/` (GitHub Pages, https://manddomundo.github.io/Props-app/).
- About 7:10 AM Eastern an `early` run grades, refreshes projections and injuries and rebuilds the app with no credits and no picks.
- Each late morning the job unlocks the books, pulls lines and injuries, runs `run.sh`, prices only games that tip that day (`daily.py today`), picks, rebuilds the app with `site.py`, locks the books and commits. Evenings it records closing lines. `site_job.sh` is the whole script.
- The artifact is the authoring copy of the pipeline. A session here cannot push to GitHub. When a pipeline file changes: bump `VERSION`, publish to the artifact, and give Armanddo a zip of the changed files to drag into the repo's upload page. Until he uploads, GitHub keeps running the old version, and the daily mirror reports the mismatch.
- Weekly review: unchanged, with one addition. If it changes a pipeline file it must end its report with the list of files to upload and send them as a zip.
- 2026-11-16 fix: a team whose last game is over but whose stats are not posted yet has no active players; target and carry shares then divided zero by zero and broke check.js. Both engines now floor the sum.


## Stress test history (ww.py, v3.3)
run.sh runs `python3 ww.py` after the research step. It reads out/data.json and the box score files, and writes out/ww.json: for each regular on the slate, his teammates' per-game numbers with him in and out over the last two seasons for the same club, plus the engine's own shift for comparison and a score of the engine against history (printed in the run log). build.py embeds it as DATA.ww. It is display only: if it fails the run carries on and the stress test says there is nothing to check against.

## Market grades (books.py, v3.4)
build.py calls books.build(D) for the newest out/lines/{LG}_YYYY-MM-DD.txt under 36 hours old (not the _first or _close snapshots) and embeds the result as DATA.books. FL_LINES="NBA=path,NFL=path" overrides the file for a local test. Grades: A edge >= +2% against the other books' consensus, B >= 0, C >= -2.5%, D >= -5%, F below. If it fails, the build carries on and the Market grades sheet says no lines are on file.

## Trends by split (splits.py, v3.5)
run.sh runs `python3 splits.py` after ww.py. It writes out/research/splits_nba.json (each slate player's last 30 games across this season and last) and splits_nfl.json (last 17), with home, rest, start, season and the stats, plus each defense's rank in what it allows a game per stat and each club's last game date. site.py copies both into docs/research; the page fetches them when the sheet opens. Display only and never fatal.

## Lines pull windows (relay_pull.py, v3.5)
Scheduled GitHub runs can start late. due() now treats 6:30 to 10:45 AM Eastern as the morning refresh, and 11:00 AM to 3:30 PM (weekends to 12:45 PM) as the midday pull. If the midday pull still has not happened, run Fair Line daily by hand with mode midday.

## Confident plays (daily.py confident, v3.6)
Runs in the midday job after `pick`, on the same _today lines file, which now carries alternate ladders. Rules live in CFG (conf_*): books' fair chance >= 72% (from the other books' consensus number on the main line, through the model's curve), model alone >= 68%, Hard Rock's price no worse than fair by 1 point, odds -140 to -500, 2-point early-exit haircut on overs, 93% cap, 3+ books, NBA 24+ projected minutes, edge-lane lineup tests. Bets carry lane="confident" and keep the $0.50 unit. Candidates and reasons land in out/conf/{LG}_{date}.json. The edge lane ignores confident bets when it checks whether a day was picked.

## NBA matchup sheets (nba_match.py, v3.6)
run.sh runs it after splits.py; writes out/research/nba_match.json; site.py copies it; the page fetches it when the sheet opens. Display only.

## Stakes (v3.7)
CFG unit $25, bankroll $500 per lane. stake_units() sizes each bet (edge by rating, confident by price edge and books' chance, leans 0.25); put_stake() caps a bet at max_units and a day at day_units and writes units, unit and usd onto the bet. history() keeps legacy_unit (0.5) for bets made before v3.7; reports and the page value each bet at its own unit. `daily.py fill DATE` runs after both leagues at midday and tops the day up to min_daily with leans.

## Game picks (games.py, daily.py gpicks, v3.9)
games.py writes out/games.json: ratings, this week's NFL games and the next NBA days, each with the model margin, chance to win, the consensus spread from games/{LG}_{date}.txt (relay) or nflverse, the spread pick and its tier, plus the backtest. run.sh runs it after the research steps and then `daily.py gpicks <date> grade`; the midday job runs it after fill and then `daily.py gpicks <date> log`. Picks are logged once and never changed; grading only fills margin, tot, su, cover and ou_hit. Since v3.10 games.py also runs a points model (Pts, PTS config) for totals and projected scores, takes the best price per side across the relay's books (best()), and lists last week's (NFL) or the last two days' (NBA) finals under last. Not staked, never in history.json. A failure prints GAME PICKS STEP FAILED and the rest of the day goes on.

## NBA closing lines (nba_lines.py, v3.11)
run.sh runs it before games.py. It keeps out/nba_lines.jsonl (saved with the rest of out/ in the encrypted state) and reads only finished games it lacks from raw.githubusercontent.com/sportsdataverse/hoopR-nba-raw (the first run reads about 1,300 files, then a handful a day). A failure prints NBA LINES STEP FAILED and the game model uses the lines already on file. games.py uses the first provider ESPN lists (DraftKings) as the closing line for the NBA track record. Since v3.11 projections follow the line when there is one (pick(): proj = books); TIER_ON turns spread tiers off for the NBA.

## Opening lines, line moves, weather (v3.12)
run.sh downloads data/nfelo_games.csv (soft: a failure keeps the last copy) and runs weather.py (Open-Meteo forecast for this week's outdoor NFL games at the home club's stadium, written to out/weather.json; prints the count; a failure prints WEATHER STEP FAILED and the cards show no wind note). games.py: nfelo_file() gives openers, nfelo's line and EV; history() reads every relay pull in out/games/ for the daily path (files older than 30 days are deleted by site_job.sh); move() builds each game's mv block; moves_nfl() and moves_nba() compute the records shown in the What a move has meant card. nba_lines.py rows are version 2 (with opening numbers); older rows are read again once.


## Injuries (v3.15)
run.sh runs injuries.py after weather.py. It reads ESPN's injury pages (site.api.espn.com .../basketball/nba/injuries and .../football/nfl/injuries, no key) and needs 15+ teams; otherwise it tries the Sports Leader nightly file (github.com/WalrusQuant/sportsleader-data releases, nba_injuries/2027 and nfl_injuries/2026). The log line reads "injuries: NBA 29 teams from espn | NFL 30 teams from espn". "not refreshed" means both sources failed or were thin; the last out/injuries.json stays, and games.py ignores it once it is 36 hours old. games.py attaches g["inj"] (a, h lists; NBA ma, mh, dm, tilt) and cfg.inj (the tested record, fixed numbers from the Nov 2026 test). Display and tracking only: nothing in games.py or daily.py uses it to price or pick.

## Zero games, noon roster, NBA win chances (v3.16)
nfl.py zero_games() adds a row of zeros (zf=1) for every QB, RB, WR, TE or FB with an offensive snap and no stat line, from data/nfl_snaps_20*.csv (players matched pfr_id to gsis_id through nfl_players.parquet). NFL_ZERO=0 python3 nfl.py runs the old way for comparison (do not ship its output). nba.py ROT_T_NEWS is 246 (was 236), from a noon-roster replay of 2025-26 (script kept out of the pipeline; numbers in the CHANGELOG). games.py NBA sd is 11.8 (was 14.7).

## Evening pass (v3.17)
lines.yml crons (UTC): 27 15,16 (about 11:30 AM Eastern midday), 57 21,22 and 37 23 (about 6 PM Eastern evening). relay_pull.py due(): early 6:30 to 10:45 AM, midday 11 AM to 3:30 PM (12:45 PM weekends), evening 5:45 to 7:45 PM, Sunday close 12 to 1:45 PM. Manual run: mode evening. Evening files: lines/{LG}_{date}_pm.txt, games/{LG}_{date}_pm.txt, priced/{LG}_{date}_pm.json; news is overwritten with the newer report. site_job.sh evening: news, run.sh, engine check, daily.py close (label "evening"), today, FL_RUN=pm daily.py lines, daily.py evening, games.py. The day record gets a pm block {t, sides_priced, cleared_bar, picks, moved, compared, moves}. The workflow file lives at .github/workflows/lines.yml in the repo (pipeline/lines.yml is the copy).

## Lineup news every run (v3.19)
site_job.sh writes lineup news (daily.py news) for each league on every early, midday, build and evening run that has that day's injury report, with the lines file when there is one. nfl.py accepts news dated on a slate game day or today (Eastern). Woody Marks style doubtful/out players go inactive; questionable players carry q and are never picked.

## The Sim tab (v3.20)
- run.sh runs `python3 sim.py grade` then `python3 sim.py` after games.py. sim.py reads out/data.json, nba_check.json, nfl_check.json, games.json and the newest lines file (books.latest), plays every game still to come (NBA today and tomorrow, NFL this week) 10,000 times with simcore.py, writes out/research/sim_nba.json and sim_nfl.json, and logs every prop with a book line before tip to out/simlog.json (kept in the encrypted state; graded the next morning; trimmed after 200 days). `python3 sim.py report` prints the live record.
- Publish research/sim_nba.json and research/sim_nfl.json beside index.html, like research/nfl.json (the page fetches them when the Sim tab opens). In mirror mode they come down with GitHub's books.
- build.py pours simtab.css and simtab.js into the page at the /*__SIM_CSS__*/ and /*__SIM_JS__*/ markers in index.src.html. Edit the tab in those two files.
- Display and tracking only. daily.py never reads the sim. Its settings were fitted on 2024-25 (NBA) and 2023-24 (NFL); a change to simcore.py settings must rerun sim_bt.py and sim_bt_nfl.py (research tools, run from /home/claude/props/lab, see their headers) and hold their numbers, and update sim_bt.json. Giving it a say in pricing needs 200+ graded props in simlog.json where it beats the desk's own price, and quarterback props stay out until its QB numbers stop losing to the desk's curve.
- SIM_NOW=YYYY-MM-DDTHH:MM and SIM_LOG=path replay an earlier day locally without touching the real log. Never set them in a scheduled run.
- v3.21: simcore reads nfl_yards_lib.json (real catch and carry yards) and sim.py ships nfl_play_lib.json inside research/sim_nfl.json for the replay; both sit beside simcore.py and are rebuilt only by sim_prep_plays.py (research tool; needs nflverse play-by-play in lab/pbp). If nfl_yards_lib.json is missing, simcore falls back to the v3.20 curves.
- The quarterback restriction above is lifted as of v3.21: the sim's QB numbers beat the desk's curve on both test seasons. The 200-graded rule for any say in pricing still holds.

## Closing-line history (v3.21)
- `.github/workflows/history.yml` in the repo (source `pipeline/relay_history.yml` and `relay_history.py`). Run by hand from Actions, never on a schedule. It pulls closing player props for games already played (10 credits a market a game), stops at the cap (default 14,000) or when the account is down to the reserve (default 4,000, kept for the daily job), and skips any day already saved. Files: `data/history/<LG>_<date>.txt.enc` in the relay's format, and `history_status.json` (counts only). The plan resets on the 1st of the month: run it once early in the month for the days not yet saved.
- The test: decrypt the files to /home/claude/hist/txt with the relay passphrase on the command line only, then run close_bt.py, close_score.py, close_replay.py and close_sim.py from /home/claude/props/lab. They change nothing in the desk.

## Books (v3.22)
- daily.py CFG bet_books: the books the desk may bet. It prices every side at each one's own line and price and takes the best value. CFG hold_edge: the model-alone hold by league (NBA 0.25, NFL 0.12). Changes to either are pick-policy changes: 200+ graded sides and a CHANGELOG entry.
- The relay (relay_pull.py) pulls ten books: the seven sportsbooks plus Polymarket, Novig and Kalshi. Exchanges are display and market view only. site_job.sh prices a league when any of the seven sportsbooks has rows (it used to need Hard Rock).
- The app's book picker reads out/books.json (books.py), the same pull as the feed. books.py drops quotes whose sides add to under 1.00 or over 1.12 in implied chance.

## Starting lineups (v3.24)
- The relay's lineups run (about 6:40 PM and 9:15 PM Eastern, plus the evening pass) saves lineups/NBA_<date>.txt from nba.com and a fresh ESPN injury report; free. site_job.sh mode lineups (and close) feeds them to the model, reruns run.sh and the sim, and reprices the board (FL_RUN=late). It never picks.
- nba.py reads them with common.load_lineups (first slate day only, teams with all five listed). LINEUP_F holds the minutes factors; changing them is a model change: rerun lab lineup_bt.py and the walk-forward backtest, and keep node check.js under 1e-2.
- Run it by hand: Actions, Fair Line daily, Run workflow, mode lineups.
