# Changelog

## 2026-11-17 v3.4 build 1: market grades and hit rates on every market
- New pipeline step books.py (run from build.py, never fatal) reads the newest full lines pull and keeps every book's quote on every prop, not only the ones Hard Rock posts. Each quote is turned into the number it implies on the model's own curve; the books other than Hard Rock are combined by their middle into a consensus, and every over and under at every book is priced against it. Written to out/books.json and embedded as DATA.books. Display only: the desk's picks are untouched.
- Research gets a Market grades sheet (both leagues; the NBA picker now has two sheets). One card per prop: Hard Rock's grade A to F for its better side against the other books, Hard Rock's price, what the books imply, the middle line, the best over and best under across all books, an Off market stamp when Hard Rock's line is out of step, and a chip for every book with the best over in green and the best under in blue. Sort by best at Hard Rock, worst, or off market; filter by market and game.
- Hit rates now cover every market any book quotes: the line is Hard Rock's where it has one, otherwise the middle line across the other books. A new Grid view lays every player against every market (last ten over the line, green to red), grouped by game; tap a cell for the memo.

## 2026-11-17 v3.3 stress test: sideline figure, player cards, history check (asked for by Armanddo)
- The stress test header has a player on the sideline in the chosen club's colours, wearing the number of the last man you switched. Healthy, he dribbles (NBA) or jogs in place (NFL). Sit someone and he turns his ankle: the foot rolls, an alarm pops, he sits down holding the ankle and the ball rolls away, with a pulse at the joint. He stays down until the lineup is whole; switch the player back in and he springs up.
- The table is now player cards: jersey, name, tags (sat by you, back in, questionable, missed last game), an In/Out switch, a minutes bar (targets plus carries for NFL) showing the base as a ghost under the new number, and stat tiles that roll to their new values with the change marked up or down. Cards that move glow green; a sat player's card goes dashed and drops to the bottom, and the cards slide to their new places rather than jumping.
- A panel for each change: how many minutes (or targets and carries) he leaves, a share bar of where the desk sends them, and the names with the amounts.
- Under it, "When it actually happened": every teammate's per-game change in the games he really missed over the last two seasons for this club (NBA: minutes, points, rebounds, assists; NFL: targets, carries, receiving and rushing yards), with games with and without, and a stamp next to the desk's own shift: history agrees, history says more, history says less, or thin sample.
- New pipeline step ww.py builds that history each run and scores the engine against it. Today's numbers: NBA, across 1,126 teammate pairs, the desk's minute shifts miss what happened by 3.06 a game against 3.41 for assuming nothing changes, point the right way 84% of the time on clear moves, and get the average size right (+2.4 against +2.2 actual); the weak spot is which teammate takes the biggest share (correlation 0.10). NFL, 280 pairs: carries go the right way 80% of the time but the desk hands out about half what backups actually got (+0.33 against +0.65 a game); target shifts are no better than assuming no change. The page says this under the cards. Nothing here changes the projections or the desk's picks.

## 2026-11-17 v3.2 research picker and coaches (asked for by Armanddo)
- The ten-tile grid took too much room. The research sheets now sit in one row: back and forward arrows either side of a picker that reads "Sheet 03 of 10" with the sheet's name. Tapping it opens a sheet listing all ten, grouped Players and Teams, each with a line on what it covers. A strip under the row shows where you are; tap a segment to jump. The name slides in from the side you moved toward.
- NBA: the one-button picker is gone, since hit rates is the only NBA sheet for now. A single line says matchup sheets are coming in a later build.
- The drifting balls are gone from the Board and Research headers.
- The Research header has a coach working the play, drawn like the desk anchors: on the NFL side a coach in a headset and cap with his call sheet, pointing at the X's and O's; on the NBA side a coach in a suit with a marker at the clipboard. He points, nods and talks on a loop. The header is the same size as before.

## 2026-11-17 v3.1.1 research fixes (reported by Armanddo)
- The film room tool picker was one long pill that cut off "Touchdowns" on the phone. It is now a numbered grid of tiles, two across on the phone and five across on wide screens, and the pill glides across rows and columns.
- The drifting balls in the NFL research and board headers were round and read as basketballs. They are now footballs: a long brown oval at an angle with white laces.

## 2026-11-17 v3.1 research: face-off, fixture tickets, role cards (asked for by Armanddo)
- The fixture panel is a face-off: away and home halves in club colours with a slanted seam, big club codes and nicknames, each side's implied points rolling up, an @ medallion with the kickoff, and a tug of war bar that splits the total by implied points (when both clubs wear the same colour, the home side takes its second colour). Favourite, total, week and stats-through sit underneath. The halves slide in from their own sides.
- The game dropdown is now a strip of fixture tickets grouped by week, each with both clubs' colour swatches; the chosen ticket lifts and the strip glides it to the middle.
- Role matchups are player cards, not a table: jersey with number, role tag, games and snap share, and a matchup gauge (Soft spot, Leans soft, Even, Leans tough, Locked down) showing how far this defense is from the league for his role. Under that, one tile per stat with his average large and what the defense allows with its rank. Each side has a band in its club colours.
- Every player named in the other research sheets now wears his jersey, as on the Board.
- All research switches (lens, period, side, columns) are sliding pills.

## 2026-11-17 v3.0 spotlight, flip cards, watch list, drifting balls (from a reference video Armanddo sent)
- Spotlight on the Board: the top seven picks of the current filters as a fan of jersey cards. The chosen one stands upright in the middle, its neighbours shrink and tilt away; tap a card or swipe to bring another forward, and the panel floods to his club's colours in a ripple from the card. His name sets large with the line and grade, and his pick number sits behind as a giant outlined numeral. Tapping the centre card opens his memo. It refans when a filter changes.
- Flip: every pick card has a flip control. The card turns over to its label: projection, fair line, book line, edge, rating, the reason in a sentence and the last ten games as marks. Flip again to turn it back.
- Watch list: a + on every pick card (and a Watch button in the Spotlight) drops the player's jersey into one of three slots in a tray at the bottom of the screen; the tray glows in the last player's colours. Tap a slot to open his memo, the x to take him off. A fourth is refused with a shake. Saved on the device only. Tracking only: no combined odds. Shown on the Board and Research. To remove the feature, set WATCH_ON to false in the page source.
- A few basketballs or footballs drift in the Board and Research mastheads at different speeds as the page scrolls.
- The pre-3.0 page source is kept as a fallback should any of this need reverting.

## 2026-11-17 v2.9 the film room console on Research (asked for by Armanddo after 2.8)
- Research opens with the Film room panel, in the same build as the Board's War room: a live dot, one line on what the room is for, and the sheets as a sliding pill rail (Role matchups, Hit rates, Touchdowns... on the NFL side). The NBA side says plainly that its matchup sheets are next on the build list.
- Hit rates get their own console: four scoreboard counters (On the tape, Running hot: over in 7+ of the last 10, Ice cold: 3 or fewer, Desk agrees: the streak and the desk lean the same way), a market pill rail, a Hottest first / Coldest first pill, and the game picker. Counters roll from what they last showed to the new count on every change, and the pills slide from where they were even though the sheet repaints.
- On a change the list deals in from the top and each row's hit marks punch in left to right.
- The NFL game picker on the matchup sheets matches the pill style.

## 2026-11-17 v2.8 the war room console on the Board (Armanddo's note: the counts and filters looked messy)
- The loose stats line and the four boxy filters are one panel now, the War room. Four scoreboard counters (On the slate, Scouted, Lines in, On the board) roll up from zero on arrival, and On the board rolls to its new count whenever a filter changes.
- Market is a pill rail (All, PTS, REB, AST...) and sort is a three-way pill (Best grade, Biggest number, A to Z). The dark pill slides between choices and stretches toward the new one before pulling its back edge in. The game picker and search sit on one line; the search box types out names from the top of the board until you tap it.
- A filter change no longer rebuilds the page. Only the list repaints, dealing the new order in from the top, and the draft board in the masthead refills with the new top picks.
- Plainer, fuller wording: the "none is rated yet" hint is now a "Mock board" note that says when grades arrive and how to grade a prop yourself; an empty search says what to try.

## 2026-11-17 v2.7 smooth pick to memo (from Armanddo's screen recording of 2.6)
- His recording showed the 2.6 morph stuttering on the Duo, with the header and side rail vanishing while it ran. It used view transitions, which make Safari snapshot the whole page. Replaced with a hand-built container transform: one stand-in card in the club's colours grows from the row to the memo (bottom sheet on a phone) while the jersey flies and spins into the memo header, then the memo fades in under it. Nothing else on the page is touched, so the header and rail stay put. Closing runs it in reverse into the row. About 0.44 seconds open and 0.36 closing.
- The header no longer tucks away while a memo is open.

## 2026-11-17 v2.6 tighter mastheads, rail gap, a pick that grows into its memo (Armanddo's notes on 2.5)
- Draft boards made smaller: tighter cells and header on the NBA board (15 picks wide, 8 on a phone), a slimmer On the clock panel and 6 strips on the NFL board (4 on a phone).
- Desk masthead on a phone: the anchors now sit in front of the video wall instead of below it, which removes the dead space.
- On a phone with a side status strip, the page now keeps a 16 pixel gap from the rail instead of running into it.
- Tapping a pick on the Board: the card itself grows into the credit memo (a container transform). The row's card, jersey and name travel into place, the jersey spins as it flies, and the memo's contents fade in crisp, never stretched. Closing shrinks the memo back into its row when that row is on screen. Falls back to the old slide where the browser has no view transitions, and with reduced motion.

## 2026-11-17 v2.5 anchors at the desk, real draft night boards (Armanddo's notes on 2.4)
- The desk now has its two anchors in suits behind a curved desk with PLAY BY PLAY and ANALYST nameplates. They take turns talking: the play by play man gestures while he talks, then the analyst (glasses, cue card) answers, each turning toward the other. ON AIR light kept.
- NBA board rebuilt after the arena video board on draft night: a red and blue header bar (Fair Line, Draft night, the year, Round 1), then columns of picks, each a white pick number, a club-coloured team tag and the player's surname, filled in column by column like the board lighting up. It shows the actual top 15 on the board right now (10 on a phone).
- NFL board rebuilt after draft night: an On the clock panel in the top pick's club colours with a 10 minute pick timer counting down (the real round 1 clock), beside the Round 1 list of strips: pick number, club stripe, name, position and market.
- Before lines arrive the boards say "Mock board" or "Mock draft, by projection"; once rated, "Round 1" and "The pick is in".
- The lottery cards and the flipping NBA rows from 2.4 are gone.

## 2026-11-17 v2.4 broadcast desk, draft night board, NBA clipboard (asked for by Armanddo; display only)
- The desk is a broadcast set: a video wall that powers on panel by panel, an ON AIR light that flickers on and keeps breathing, and the curved anchor desk rising in front. Ticket titles slide in like lower thirds, and the results crawl has a blinking LIVE light.
- The big board is draft night. NFL: a wall of club-coloured name strips slotting in, with empty slots left for later picks. NBA: lottery cards flip from 5 down to 1. Rows read "Pick 1, Pick 2..." and, sorted by rating, are grouped into rounds by rating. NFL rows slide in like strips; NBA rows flip in, and the top three reveal last, lottery style.
- Research on the NBA side is a coach's dry-erase clipboard: half court in marker, a pick and roll that draws itself (dribble off the screen, the roll to the rim, the pass). The NFL side keeps the blueprint.
- No league logos or network branding.

## 2026-11-17 v2.3.1 side rail fix (reported by Armanddo on the Duo, unfolded)
- On his phone the side rail and the paper grain stopped about a screen down and the rail broke apart. Both were pinned to the screen, a kind of layer Safari can leave stranded after a fold. Both are now drawn along the whole page instead, and the ball sticks in view as it rides down. Could not be reproduced in the test browser (not Safari), so this is a fix for the most likely cause.

## 2026-11-17 v2.3 data strip, side rail, slower fold (asked for by Armanddo; display only)
- The data line under the letterhead is now a ticket strip with labelled parts: Slate, Stats through, Updated (and a red Stale part when the page has missed its refresh). No more cut-off text. It re-deals on a league change.
- On a phone with a status strip down the side (iPhone Duo), that strip is now a rail of hardwood or turf, faded out behind the clock, with a ball that travels down as you scroll. It takes its width from the phone's own side inset, so other phones never see it.
- Fold animation slowed so it reads: the covers now carry the awning, hold a beat, then swing open over about 1.35 seconds with a lit seam at the hinge. Closing takes about 0.8 seconds.

## 2026-11-17 v2.2.1 morning refresh (asked for by Armanddo)
- New run at about 7:10 AM Eastern: grades last night's bets, refreshes projections, research and injury reports, and rebuilds the app, so it is current when he wakes. It spends no credits.
- Lines and picks stay with the late morning run (about 11:20 AM): most books post NBA player props mid morning, and the injury report firms up by then, so picking at 7 AM would mean fewer props and staler news.

## 2026-11-17 v2.2 Duo fixes and the market rail (asked for by Armanddo; display only)
- iPhone Duo: the credit memo's Close button sat under the phone's side status strip. On phone sheets Close is now on the left, the memo head keeps clear of the right inset, and the picker sheets do the same.
- League switch scene: on his recording the second scene opened already at the score and shut at once. The scene started on the tap while Safari was still holding the old screen. It now starts when the page change is ready (with a 1.5 second fallback).
- Markets in the credit memo are a rail of small tote tiles. Each shows its own projection (PTS 8.8, REB 4.1) and the chosen one lights up, lifts and flickers on like a tube. The rail glides the lit tile to the middle.

## 2026-11-17 v2.1 the daily run moves into GitHub; the standalone app updates itself (asked for by Armanddo)
- New `site_job.sh` and workflow `lines.yml`: the GitHub job now unlocks the books, pulls lines, runs the models, picks, rebuilds the Fair Line app in `docs/` and locks the books again. The books are stored encrypted. Dry run here end to end: engine check 0.0014 and 0.0002, 433 KB of state, app built.
- New `daily.py today` (only games that tip today are priced, so a Saturday pull cannot bet Sunday's games a day early), `mirror` (the Claude daily run copies GitHub's books instead of picking) and `summary`.
- Bug found by the dry run and fixed in `nfl.py` and `engine.js`: with no active players on a side the share maths returned NaN and check.js failed. It would have stopped the next daily run. Both engines floor the sum; check passes.
- Pick policy unchanged. GitHub becomes the only runner that picks once `state/summary.json` exists in the repo.

## 2026-11-16 v2.0 Fair Line: name, logo, row motion, standalone package (asked for by Armanddo; display only)
- The app is now called Fair Line (page title, letterhead, fold covers). The artifact slug and the pipeline are unchanged.
- Logo in the app's own materials: the awning, ledger paper, the fat-face letters F and L, and the red stamp as the marker on a dashed line between them. Files in `icons/`.
- Player rows answer the pointer in club colours: a colour wash sweeps in, the stripe widens, the jersey tilts and the number pops. Rows, ledger entries and pass cards rise in as they scroll into view (scroll-driven, only where the browser supports it, off with reduced motion).
- The data line turns red and says how many days it has gone without a refresh once the page is more than 40 hours old.
- New `site.py` wraps the built page as a standalone web app (manifest, home screen icon, full screen) in `site/docs` for GitHub Pages. First copy is a snapshot uploaded by hand. A daily build inside GitHub is the next step; until then the Claude artifact is the live copy.

## 2026-11-16 v1.9 jerseys, smoother credit memo, fold animation (asked for by Armanddo; display only)
- Every player row on the Board and in Hit rates now carries a jersey in his club's colours with his number, a club tag, and a colour stripe down the row edge. NFL rows get a football jersey, NBA rows a vest. The credit memo opens with the same jersey, larger. Club logos are trademarks and are not drawn.
- `build.py` adds jersey numbers to the page data (NFL from the weekly roster file, NBA from the box scores). Display only and not fatal: a player with no number shows his position.
- Credit memo: on a phone it is now a sheet that rises from the bottom over a dimmed page and can be dragged down by its head or closed by tapping outside. Changing market slides the new numbers in from the side that market sits on. The line marker glides to its new place, and the rating stamp lands again whenever the verdict changes.
- Fold: when the page width jumps between phone and tablet size in one step, as a folding phone does, two covers swing apart from the hinge (or swing shut). It watches the width because Safari's posture and viewport-segment features are still behind flags.
- Checked in a browser at desktop, dark and phone widths, including a simulated unfold and fold: no script errors, no sideways scroll.

## 2026-11-16 v1.8 arcade letterhead, tucking header, sheet drag (asked for by Armanddo; display only)
- League switch now plays a two second 80s arcade scene on a small screen in the letterhead: a pixel basketball arcs into a hoop (SWISH! +3) for the NBA, a pixel football tumbles through the uprights (IT'S GOOD! +3) for the NFL. Stepped motion at about 18 frames a second, a ghost trail, a 1UP score that ticks to 000300, and the screen switches on and off like a tube. Behind the whole letterhead the floor scrolls by in chunks at low strength and a scan line runs across.
- It plays only on a league change, never on load, restarts cleanly if the switch is hit again mid-scene, and is skipped entirely with reduced motion. The data line it covers fades out for the scene and back in after.
- Phone: the letterhead tucks away while reading down and returns on the first scroll up, leaving the tabs in reach. Checked: tabs sit 4px from the top when tucked.
- Picker sheets can be dragged down by the head to dismiss. Research keeps the chosen sheet's chip centred in its rail. Ledger rows give a small press response.
- One new font, Press Start 2P, for the arcade text.
- Checked in a browser frame by frame at desktop (light and dark) and phone widths: no script errors, no sideways scroll.

## 2026-11-16 v1.7 rooms, league switch, pickers (asked for by Armanddo; display only)
- Each tab is now its own room with a sign over the door and its own way of arriving: an awning that unrolls over the desk, a chalkboard for the board with the title chalked on, a blueprint with a play that draws itself for research, hazard tape and a gauge whose needle swings for the stress test, a ruled notebook written by hand for your book, a certificate with a seal pressed on for the model audit. Section headings are ruled in the room's colour.
- Tabs are coloured file dividers with an icon each. One raised divider slides to the tab picked and takes its colour.
- League switch: a ball on a track. Hardwood and a basketball that bounces in for the NBA, turf with yard lines and a football that spirals in for the NFL. A strip of the same floor runs across the top of the page, and on a league change the new sheet opens out from the switch.
- Every dropdown now opens as a slip in the page's own paper (a bottom sheet on a phone, a small menu on a wide screen) instead of the phone's system menu. The `<select>` elements are still in the page and still fire `change`, so no handler changed. Keyboard: arrows, Home, End, Enter, Escape.
- One new font, Caveat, for the notebook title. Reduced motion still switches every animation off.
- Checked in a browser at desktop, dark and phone widths: no script errors, no sideways scroll. A hidden select on Your book was forcing the page wide on phones; fixed.
- No change to the model, the pick policy or any bet.

## 2026-11-16 v1.6 lines relay (asked for by Armanddo; pick policy unchanged)
- New key and a GitHub repo from Armanddo. Built a relay: one GitHub Actions workflow (`relay_lines.yml`, script in `relay_pull.py`) that pulls lines from seven books and the ESPN injury feed on a schedule and saves them encrypted in the repo. New `daily.py relay <date>` downloads and decrypts them into `out/lines` and `out/news` in the formats the desk already reads.
- Tested here against a stand-in for the API built from today's real lines: the relay file decrypted to the same 509 quotes as the file typed by hand, the quarterback naming and injury table read correctly, a duplicate alternate line was dropped, an unknown book key falls back to four books, and a missing secret or small plan degrades without spending credits. Not yet run on GitHub: that needs the workflow file and two secrets added to the repo.
- `parse()` now reads anytime touchdown rows (line and no price are empty). Rows in other markets with no under price are still dropped, as before.
- Guard so the relay cannot widen the bets on its own: `CFG["pick_markets"]` lists the six markets the desk has always picked from (points, rebounds, assists, receiving, rushing and passing yards). Checked on today's priced sides: the same 2 NBA sides and 0 NFL sides are eligible before and after. New markets are priced and graded, shown as ON TRIAL in the pass list, and need 200 graded sides before the weekly review may add them.
- Daily run now tries the relay first and falls back to WebFetch per league.

## 2026-11-16 v1.5 research room (asked for by Armanddo; no model or policy change)
- New Research tab. NFL sheets for any game this week and next: role matchups (his average against what the defense allows that role, with rank), touchdowns, first touchdown, red zone, run lanes (left, middle, right), team share by half and quarter, a 32 team board for offense and defense, tendencies, and trenches (line against front, top pass rushers, what each defender has allowed in coverage).
- Hit rates for both leagues: last five and last ten against the line on file, his record against tonight's opponent, and the desk's own chance beside it. Uses the lines the daily pull already has, so it costs no credits.
- New `research_nfl.py` writes `out/research/nfl.json` (384 KB, 432 players, 14 games), published as `research/nfl.json` and fetched by the page on demand. `run.sh` downloads seven more nflverse files and runs it. Both are soft steps.
- Checked against a reference app's screens for the same week: Flowers 8.0 targets and a 30.3% share, Ravens allowing wide receivers 12.11 catches and 172.56 yards, Henry's run mix 46/13/41, Ravens 3.0 red zone trips a game, Henry anytime TD in 6 of 9. All matched.
- Fixed while building: the snap file labels some running backs HB, which left the Bengals with no backs and skewed what their opponents were shown to allow. Positions now come from the stat file.
- The pick policy, the pricing and the two open bets were not touched. Research is display only.
- Not built: hit rates across all markets and alternate lines, trends by split, market grades (need a paid odds plan and a relay), alignment and receiver against cornerback sheets (no consumer source this season).

## 2026-11-16 v1.4 case files, closing line tracking, redesign (asked for by Armanddo)
- Why the model reads low, found: for the 499 graded lines the live projections matched a clean replay exactly, and those players played 7.7% more minutes than projected (29.5 against 27.4). All top-seven rotation players together were within 2%. So it is selection, not a bug: a book only quotes a player it expects to play a full night. Centring on the market (v1.3) is the right correction and stays.
- NBA lineup with news: rotation now fills to 236 team minutes (ROT_T_NEWS) when lineup news is on, 250 when it is not. The model was calibrated on the players who actually played, whose minutes add to 240 (2025-26) and 244 (2026-27) a game; 250 trimmed everyone about 3%. No historical injury reports exist to backtest this, so it rests on matching the calibration conditions.
- Tested and rejected: back to back rest and home or away. Factors fitted on 2025-26 moved the 2026-27 average miss from 5.2157 to 5.2155 points, 1.9607 to 1.9604 rebounds, 1.5173 to 1.5177 assists. Not worth a parameter.
- Case files: every bet now carries `why` (thesis, what each book quoted, the chance by source, model build, last ten, who is out by team, matchup, the math, what beats it). Each day carries `passed`: the closest calls and the test each failed. Built by `daily.py explain`, called from `pick`. News now records who is out by team (`out_team`).
- Closing line value: new `daily.py close`. First reading, pulled 6:25 PM ET on 11-16 (2 credits): Dybantsa Over 5.5 reb +100 closed +100, market fair 46.7%, CLV -6.5%, market moved 0.9 points against. Suggs Over 2.5 reb -160 closed -150, fair 56.5%, CLV -8.2%, market moved 3.3 points against. Both are model plays, so a negative reading against the fair price is expected unless the market comes around; the average over many bets is what counts.
- Page: new type (Ultra, Besley, Sometype Mono, Doto), a tote board for the record with flip cells and a results tape, tickets that open into the case file with two dot plots and a last-ten chart, a pass list, result stamps on the ledger, page turns between tabs, a sliding memo, and standing orders on the Model tab. Board chance column now shows the desk's chance when a book line is present. Motion respects reduced motion.
- Tonight's two bets were not changed. Their case files and closing lines were added to them.

## 2026-11-16 v1.3 market check, lineup news, lean fix (model and policy change, asked for by Armanddo)
Why: 1,138 graded sides showed the v1.2 model was not beating the book. Hit rate sat near 50 to 55% at every edge level, and it had a lean: it called Unders 55.6% likely and they hit 49.2%. 22 of 25 desk bets were Unders.
- Lineup news (new `daily.py news`, read by nba.py and nfl.py): ESPN injury report plus the books. Listed out sits, quoted by a book plays, questionable is priced but never picked, the book's passing yards market names the NFL quarterback (a quarterback new to the team is brought in with his own history).
- NBA rotation fill (ROT_T = 250): the live lineup was everyone in the last box score, sometimes 12 to 14 players, which squeezed starters' minutes. Now filled by minutes to a 250 team total. Walk-forward test over 2,978 team games, players projected 20+ minutes: minutes bias +0.20 to 0.00 (2025-26) and +0.13 to -0.04 (2026-27); points avg miss 5.163 to 5.154 and 5.216 to 5.182; minutes avg miss 4.64 to 4.59 and 4.64 to 4.57.
- Market check: odds are pulled from Hard Rock plus DraftKings, FanDuel and BetMGM at the same credit cost. Each book's line is turned into the projection it implies; the median of the other three is the market view.
- Pricing mean = market + w x (centred model - market). Centring puts the model's slate average on the market's, market by market, so a general lean cannot create bets. w is relearned each run from the audit (tonight: NBA pts 0.29, reb 0.46, ast 0.41; NFL rec 0.29, rush 0.11, pass 0.23), pulled toward 0.25.
- Evidence, each day held out in turn on the 565 graded lines: Brier 0.2599 for v1.2 probabilities, 0.2509 anchored and centred (a coin flip is 0.2500). Honest reading: this removes false confidence and the lean. It does not show an edge against Hard Rock's own line. Any real edge now has to come from Hard Rock being out of line with the other books, or from the model being right about one player by more than it is about the rest.
- Policy: a pick needs 2+ other books quoting the prop (min_books), the old max_edge hold now applies to the centred model on its own view (edgec), questionable players are never picked. Thresholds for edge, odds, history and minutes are unchanged. No quota for Overs or Unders.
- Desk log: the five picks logged at 1:30 PM by v1.2 (Pritchard, Tatum, Boozer, Henry, Tre Harris) are kept in history marked replaced and not counted; v1.3 repicked the card before tip. The 1:30 PM lines are kept as desk/lines/*_2026-11-16_first.txt.
- One extra odds pull today (about 15 credits over the daily cap) to get the other books.
- Page: desk odds use the anchored mean and say so, new flags for questionable and QB change, hold when the model alone is far from the market.
- run.sh: `SKIP_DL=1` reruns the models without downloading; audit printout no longer throws a broken pipe.
- Not done yet: NBA back to back and home and away, defense by position, NFL weather and snap share, closing line tracking.

## 2026-11-16 v1.2.2 grading fix (no model or policy change)
- NFL: a player who played but recorded no stats was graded as did not play. The weekly stats file leaves out anyone without a stat line, so the grader voided the bet. Elijah Higgins (ARI, 11-15, Under 19.5 rec yds) played 24 offensive snaps with no targets and was voided when the Under had won. Armanddo caught it.
- Grading now also reads the nflverse snap counts (data/nfl_snaps_2026.csv, downloaded in run.sh, not fatal if missing). No stat line plus snaps in that game means a real zero and the bet stands. A bet is voided only when the game is in the snap counts and the player has no snaps. Without the snap file it falls back to the old rule.
- Before: 9-9, -0.37 units, Higgins void. After: 10-9, +0.50 units, Higgins won with 0 yards. No other bet changed.
- Audit: 12 sides (6 players with zero yards on 11-12 and 11-15) were being skipped and are now graded, 1126 to 1138 sides. They were all Under wins, so the audit had been slightly unfair to Unders on low volume players.

## 2026-11-13 v1.2.1 grading fix (no model or policy change)
- NFL bets and audit sides are now settled straight from the weekly stats file (data/nfl_pw_2026.csv) instead of the page data. The page data only carries players whose team still has a game left in the current week, so the two Thursday Week 10 bets (WAS @ NYG) sat open with the box score already available, and a team on bye the following week would have had its bets voided even though the player played.
- A bet is voided only when that game's stats are in the file and the player has no line in them. If the file cannot be read, grading falls back to the old page-log path.
- Before: 2 NFL bets open, 0 NFL sides audited. After: both graded (Okonkwo 24 rec yds, McCarthy 34 rush yds), NFL sides from 11-12 enter the audit.
- Known and not changed: NBA grading still reads the page data, which covers teams with a game in the next three slate days. A team with a longer gap could have a bet voided wrongly. Same fix pattern applies.

## 2026-11-11 v1.2 design
- Page restyled: ledger paper by day, odds chalkboard by night, typewritten figures, stamped ratings, ticket stubs for desk bets. Styling only lives in index.src.html.
- Board and memo now put any side with an edge above 12 points on HOLD instead of rating it, matching the desk rule (CFG max_edge in daily.py and MAX_EDGE in index.src.html must stay equal).

## 2026-11-11 v1.1 (same day as launch)
- NBA: cut shrinkage toward position averages (rate prior 150 to 15 pseudo-minutes, minutes prior 0.6 to 0.05 pseudo-games). First comparison against Hard Rock lines showed stars projected far too low. Held-out bias for 20+ point projections went from +3.2 to +0.8 points, average points miss 4.96 to 4.85.
- Both leagues: added a slope correction per market, fit in the backtest (y = a + b x projection). NBA 20+ point bias now +0.3. NFL pass TD slope 0.80 pulls down inflated TD projections.
- Added the desk: daily.py (price book lines, log up to 3 best bets per league per day at 1 unit, grade, audit), Desk record tab, bankroll $25 with a $0.50 unit.
- Pick policy v1: edge between 3 and 12 points, confidence adjusted EV at least 2.5%, odds between -160 and +150, at least 8 games of history, NBA projected minutes at least 20, max 2 picks per game, 1 per player.

## 2026-11-11 v1.0
- Launch. NFL: team volume x share x efficiency. NBA: minutes x per-minute rate inside team totals. Negative binomial pricing.
