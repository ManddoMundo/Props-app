/* ---------- v3.20 the Sim tab: every game played ten thousand times, one run played out on a court ----------
   Data: research/sim_nba.json and research/sim_nfl.json (sim.py), fetched when the tab opens.
   The replay is drawn on two canvases: the floor once (it never changes) and the players and ball every frame.
   Everything that moves is time-based (a frame at 120 Hz moves half as far as one at 60 Hz), players glide on
   critically damped springs, the ball flies on parabolas, and the loop sleeps when the court is off screen.
   Reduced motion: nothing plays by itself; Play steps through the plays with the players placed, not moving. */
const SMD = { NBA: { st: 'idle' }, NFL: { st: 'idle' } };
S.sm = { g: { NBA: null, NFL: null }, run: {}, speed: 2, mkt: 'all', slip: { NBA: [], NFL: [] }, sort: 'lean', lim: 30, open: null, bt: 'games', bq: '', bm: 'all', px: '', stack: false };
const SM_MK = { NBA: [['all', 'All'], ['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['fg3', '3PM'], ['pra', 'PRA'], ['pr', 'P+R'], ['pa', 'P+A'], ['ra', 'R+A']],
                NFL: [['all', 'All'], ['pass_yds', 'PASS YDS'], ['rush_yds', 'RUSH YDS'], ['rec_yds', 'REC YDS'], ['rec', 'REC'], ['any_td', 'ANY TD'], ['pass_att', 'ATT'], ['pass_cmp', 'CMP'], ['pass_td', 'PASS TD'], ['rush_att', 'CAR']] };
function loadSim(lg) {
  const z = SMD[lg]; if (z.st !== 'idle') return; z.st = 'load';
  fetch(`research/sim_${lg.toLowerCase()}.json`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(d => { z.st = 'ready'; z.d = d; z.bits = new Map(); }).catch(() => { z.st = 'error'; })
    .then(() => { if (S.tab === 'sim' && S.lg === lg) { refreshMain(); simAfter(true); } });
}
const smGame = lg => { const d = SMD[lg].d; if (!d || !d.games.length) return null; let g = d.games.find(x => x.id === S.sm.g[lg]); if (!g) { g = d.games[0]; S.sm.g[lg] = g.id; } return g; };
const smName = (lg, pid) => { const p = IDX[lg].byId[pid]; return p ? p.name : ''; };
const smLast = n => { const a = String(n).split(' '); return a.length > 1 ? a.slice(1).join(' ') : n; };
const smOdds = p => { const a = E.amer(Math.min(.995, Math.max(.005, p))); return a == null ? '' : odds(a); };
const SM_B64 = s => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
const SM_POP = new Uint8Array(256).map((_, i) => { let c = 0, x = i; while (x) { c += x & 1; x >>= 1; } return c; });
function smBits(lg, key, b64) { const m = SMD[lg].bits; if (!m.has(key)) m.set(key, SM_B64(b64)); return m.get(key); }
function smJoint(lg, legs) {
  if (!legs.length) return null; const us = legs.map(l => smBits(lg, l.k, l.b)), n = us[0].length * 8; let c = 0;
  for (let i = 0; i < us[0].length; i++) { let v = 255; for (let j = 0; j < us.length; j++) v &= legs[j].neg ? ~us[j][i] & 255 : us[j][i]; c += SM_POP[v]; }
  return c / n;
}
// v3.21: one slip per league, across every game on the slate. Legs from the same game are priced together from that
// game's runs (the share of runs where every one of them hit); legs from different games are multiplied, since one
// game's runs know nothing of another's
const smLegsOf = lg => S.sm.slip[lg];
const smUid = (gid, key) => gid + '#' + key;
function smSlipPrice(lg, legs) {
  const by = {}; legs.forEach(l => (by[l.g] = by[l.g] || []).push(l));
  let pj = 1, pm = 1, dec = 1, priced = 0;
  for (const gid in by) { const L = by[gid]; pj *= L.length > 1 ? smJoint(lg, L.map(l => ({ k: smUid(l.g, l.key), b: l.b, neg: l.neg }))) : L[0].p; }
  legs.forEach(l => { pm *= l.p; if (l.px != null) { dec *= E.dec(l.px); priced++; } });
  return { pj, pm, dec: priced === legs.length && legs.length ? dec : null, priced, games: Object.keys(by).length, by };
}
const smAm = dec => dec >= 2 ? Math.round((dec - 1) * 100) : Math.round(-100 / (dec - 1));

/* ---------- the page ---------- */
function simHtml() {
  const lg = S.lg, z = SMD[lg]; loadSim(lg);
  const head = mast('sim', 'Every game, ten thousand times', z.st === 'ready' ? `${z.d.runs.toLocaleString()} runs a game · simulated ${esc(z.d.asof)}` : 'Each game played out from the tip, with the players moving together');
  if (z.st === 'error') return head + `<div class="banner"><span>The simulator file did not load.</span><button class="btn ghost sm" data-sm="retry">Try again</button></div>`;
  if (z.st !== 'ready') return head + `<div class="card"><span class="lbl">Running the games</span><div class="wait"><i></i><i></i><i></i></div></div>`;
  const d = z.d, g = smGame(lg);
  if (!g) return head + `<p class="prose">No ${lg} games left on the slate to simulate. The next slate is simulated with the morning run.</p>`;
  return head + smStrip(lg, d) + smArenaHtml(lg, g) + smHowHtml(lg) + smOddsHtml(lg, g) + smPropsHtml(lg, g) + smBuildHtml(lg, d) + smScriptHtml(lg, g) + smTestHtml(lg, d) + `<div id="smTray" class="sm-tray" hidden></div>`;
}
function smStrip(lg, d) {
  const days = {}; d.games.forEach(g => (days[g.day] = days[g.day] || []).push(g));
  const dl = x => new Date(x + 'T12:00:00').toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  return `<nav class="sm-strip" aria-label="Games">${Object.keys(days).map(k => `<div class="sm-day"><span class="lbl">${dl(k)}</span><div class="sm-gs">${days[k].map(g => { const ph = g.p.home, on = g.id === S.sm.g[lg];
    return `<button class="sm-g" data-sm="g:${g.id}" aria-pressed="${on}" style="--ph:${ph};${tcol(lg, g.home).replace(/--t/g, '--h')};${tcol(lg, g.away).replace(/--t/g, '--a')}">
      <span class="sm-gt">${badge(lg, g.away, 'xs')}<b>${esc(g.away)}</b><i>@</i>${badge(lg, g.home, 'xs')}<b>${esc(g.home)}</b></span>
      <span class="sm-gm"><small>${t12(g.time)}</small><span class="sm-wbar" aria-hidden="true"><i></i></span><small>${Math.round((ph >= .5 ? ph : 1 - ph) * 100)}% ${esc(ph >= .5 ? g.home : g.away)}</small></span></button>`; }).join('')}</div></div>`).join('')}</nav>`;
}
// v3.25 replay runs: Typical (six runs near the middle, the default) and Outliers (named scenarios with how often each happened)
function smRi(g) { const v = S.sm.run[g.id]; return v != null && g.samples[v] ? v : (g.def != null && g.samples[g.def] ? g.def : Math.floor(g.samples.length / 2)); }
const smMg = (g, m) => m === 0 ? 'Tied' : `${m > 0 ? g.home : g.away} by ${Math.abs(m)}`;
const smPc = p => p < .01 ? 'under 1%' : `${Math.round(p * 100)}%`;
function smFcLine(g) {
  if (!g.mq) return '';
  const [a, , c] = g.mq, side = a > 0 ? g.home : c < 0 ? g.away : null;
  const mg = side ? `${esc(side)} by ${Math.min(Math.abs(a), Math.abs(c))} to ${Math.max(Math.abs(a), Math.abs(c))}` : `${esc(smMg(g, a))} to ${esc(smMg(g, c))}`;
  const ph = g.p.home, fav = ph >= .5 ? g.home : g.away;
  const cell = (k, v) => `<span><small>${k}</small>${v}</span>`;
  return `<div class="sm-fc">${cell('Margin, middle half', mg)}${cell('Total, middle half', `${g.tq[0]} to ${g.tq[2]}`)}${cell('Wins', `${esc(fav)} ${smPc(Math.max(ph, 1 - ph))}`)}</div>`;
}
function smRunNote(lg, g, i) {
  const s = g.samples[i]; if (!s) return '';
  const fin = `${esc(g.away)} ${s.sc[0]}, ${esc(g.home)} ${s.sc[1]}`;
  if (s.k === 'o') return `<b>${esc(s.lab)}</b> in ${smPc(s.pct)} of runs. This one: ${fin}.${s.why ? ` In those runs, ${esc(s.why.split(' · ').join('; '))}.` : ''}`;
  if (s.k === 't') return `<b>${esc(smMg(g, s.sc[1] - s.sc[0]))}</b>, ${fin}. ${smPc(s.pct)} of runs end within ${lg === 'NBA' ? 3 : 4} points of this margin.${i === g.def ? ' The most typical run on the board.' : ''}`;
  return `${fin}.`;
}
function smRunBtn(lg, g, s, i, ri) {
  const m = s.sc[1] - s.sc[0], o = s.k === 'o';
  return `<button class="sm-r${o ? ' o' : ''}${i === ri ? ' on' : ''}" data-sm="run:${i}" aria-pressed="${i === ri}" style="--m:${Math.max(-1, Math.min(1, m / (lg === 'NBA' ? 30 : 24)))}"><span class="sm-rh"><b>${s.sc[0]}-${s.sc[1]}</b>${o ? `<em>${smPc(s.pct)}</em>` : i === g.def ? '<em class="d">Middle</em>' : ''}</span><small>${esc(o ? s.lab : smMg(g, m))}</small></button>`;
}
function smRunsHtml(lg, g, ri) {
  const all = g.samples.map((s, i) => [s, i]), typ = all.filter(([s]) => s.k !== 'o'), out = all.filter(([s]) => s.k === 'o'), runs = (SMD[lg].d.runs).toLocaleString();
  const row = (lab, sub, list) => list.length ? `<div class="sm-rg"><span class="lbl">${lab}</span><small>${sub}</small></div><div class="sm-rl">${list.map(([s, i]) => smRunBtn(lg, g, s, i, ri)).join('')}</div>` : '';
  return `<div class="sm-runs">${smFcLine(g)}
      ${g.samples.some(s => s.k) ? row('Typical', `${typ.length} of ${runs}, near the middle`, typ) : row('Runs', `${typ.length} of ${runs}, ${esc(g.away)}'s best night to ${esc(g.home)}'s`, typ)}
      ${row('Outliers', 'other ways it goes', out)}
      <p class="sm-rn" id="smRn" aria-live="polite">${smRunNote(lg, g, ri)}</p></div>`;
}
function smArenaHtml(lg, g) {
  const ri = smRi(g);
  return `<section class="sm-arena lg-${lg.toLowerCase()}" id="smArena" style="${tcol(lg, g.away).replace(/--t/g, '--a')};${tcol(lg, g.home).replace(/--t/g, '--h')}">
    <div class="sm-board" aria-label="Scoreboard">
      <div class="sm-sb a"><span class="sm-tn">${badge(lg, g.away, 'm')}<b>${esc(g.away)}</b></span><b class="sm-pts" id="smA">0</b></div>
      <div class="sm-clk"><span id="smQ">${lg === 'NBA' ? 'Q1' : '1ST'}</span><b id="smT">${lg === 'NBA' ? '12:00' : '15:00'}</b></div>
      <div class="sm-sb h"><b class="sm-pts" id="smH">0</b><span class="sm-tn"><b>${esc(g.home)}</b>${badge(lg, g.home, 'm')}</span></div>
      <small class="sm-dn" id="smDn"></small>
    </div>
    <div class="sm-stage" id="smStage"><div class="sm-tilt"><canvas class="sm-floor" id="smFloor" aria-hidden="true"></canvas><canvas class="sm-live" id="smLive" role="img" aria-label="One simulated run of ${esc(g.away)} at ${esc(g.home)}, played out"></canvas></div>
      <div class="sm-stamp" id="smStamp" aria-hidden="true"></div></div>
    <div class="sm-tick" id="smTick" aria-hidden="true"></div>
    <div class="sm-ctl">
      <button class="sm-play" id="smPlay" data-sm="play" aria-label="Play"><svg viewBox="0 0 24 24" aria-hidden="true"><path class="pl" d="M8 5.5v13l11-6.5z"/><path class="pa" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg></button>
      <div class="seg sm-sp" data-seg="smsp"><span class="seg-ink"></span>${[1, 2, 4].map(v => `<button data-sm="sp:${v}" aria-pressed="${S.sm.speed === v}">${v}x</button>`).join('')}</div>
      <button class="btn ghost sm" data-sm="restart">Restart</button><button class="btn ghost sm" data-sm="final">Final</button>
      <div class="sm-prog" id="smProg" data-sm="seek" role="slider" aria-label="Game progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0"><i class="sm-pf" id="smPf"></i>${[1, 2, 3].map(q => `<b style="left:${q * 25}%"></b>`).join('')}</div>
    </div>
    ${smRunsHtml(lg, g, ri)}
    <details class="sm-box" id="smBoxD" open><summary><span class="lbl">Box score of this run, live</span></summary><div id="smBox"></div></details>
    <p class="note">One of the ${(SMD[lg].d.runs).toLocaleString()} runs, played out. The players, minutes and final numbers are that run's; the order of the plays is drawn to fit them${lg === 'NFL' ? ': downs, field position and the call on each snap follow real 2023-24 football, and every carry, catch and score is the run\'s' : ''}.</p>
  </section>`;
}
function smOddsHtml(lg, g) {
  const p = g.p, fav = p.home >= .5 ? g.home : g.away, pf = Math.max(p.home, 1 - p.home), hl = g.hist, c = hl.c, mx = Math.max(...c.slice(1, -1)), N = c.length;
  const bw = 600 / N, sl = g.spread, x0 = v => (v - hl.lo) * bw + bw / 2;
  const bars = c.map((v, i) => { const m = hl.lo + i, h = v / mx * 112; return h < .4 || i === 0 || i === N - 1 ? '' : `<rect class="${m > 0 ? 'h' : m < 0 ? 'a' : 't'}" x="${(i * bw + .6).toFixed(1)}" y="${(124 - h).toFixed(1)}" width="${(bw - 1.2).toFixed(1)}" height="${h.toFixed(1)}" style="--i:${Math.abs(m)}"/>`; }).join('');
  const tile = (k, v, s, cls) => `<div class="sm-tile${cls ? ' ' + cls : ''}"><small>${k}</small><b class="num">${v}</b>${s ? `<span>${s}</span>` : ''}</div>`;
  const ovr = p.over == null ? null : p.over;
  return `<section class="sm-odds" style="${tcol(lg, g.away).replace(/--t/g, '--a')};${tcol(lg, g.home).replace(/--t/g, '--h')}"><div class="hd"><h2>Ten thousand finishes</h2><span>${esc(g.away)} at ${esc(g.home)} · inputs from ${esc(g.src)}</span></div>
    <div class="sm-tiles">
      ${tile('Wins it', pct(pf), esc(fav) + ' · fair ' + smOdds(pf), 'w')}
      ${tile('Projected score', `${g.score[0].toFixed(0)}-${g.score[1].toFixed(0)}`, `${esc(g.away)} ${g.sq[0][0]} to ${g.sq[0][2]} · ${esc(g.home)} ${g.sq[1][0]} to ${g.sq[1][2]}`)}
      ${tile(`${esc(g.home)} covers ${sl > 0 ? '-' : '+'}${Math.abs(sl).toFixed(1)}`, pct(p.hcover), 'Spread from the same inputs, so near 50% by design')}
      ${ovr == null ? '' : tile(`Over ${g.tline}`, pct(ovr), 'Total from the same inputs')}
      ${tile(lg === 'NBA' ? 'Blowout, 20+' : 'Blowout, 17+', pct(p.blow), lg === 'NBA' ? 'Starters sit late in these' : 'The trailing side throws in these')}
      ${tile(lg === 'NBA' ? 'Close, 5 or less' : 'One score, 7 or less', pct(p.close), '')}
    </div>
    <figure class="sm-hist card"><figcaption><span class="lbl">Final margin, ${esc(g.home)} minus ${esc(g.away)}, all ${(SMD[lg].d.runs).toLocaleString()} runs</span></figcaption>
      <svg viewBox="0 -6 600 160" role="img" aria-label="Histogram of final margins. ${esc(g.home)} wins ${pct(p.home)} of runs.">
        <g class="sm-hb">${bars}</g><path class="sm-h0" d="M${x0(0)} 4V126"/><path class="sm-hs" d="M${x0(sl)} 13V126"/><text class="sm-ht" x="${x0(sl)}" y="9" text-anchor="middle">line ${esc(g.home)} ${sl > 0 ? '-' : '+'}${Math.abs(sl).toFixed(1)}</text>
        <path class="sm-hx" d="M0 125.5H600"/>${[-30, -20, -10, 0, 10, 20, 30].filter(v => v >= hl.lo && v <= -hl.lo).map(v => `<text class="sm-hl" x="${x0(v)}" y="146">${v > 0 ? '+' : ''}${v}</text>`).join('')}
        <text class="sm-hn a" x="6" y="26">${esc(g.away)} wins ${pct(1 - p.home)}</text><text class="sm-hn h" x="594" y="26" text-anchor="end">${esc(g.home)} wins ${pct(p.home)}</text></svg></figure>
    <div class="sm-gl"><span class="lbl">Add the game to a parlay</span><div class="sm-glr">${[['home', `${g.home} wins`, p.home], ['away', `${g.away} wins`, 1 - p.home], ['hcover', `${g.home} ${sl > 0 ? '-' : '+'}${Math.abs(sl).toFixed(1)}`, p.hcover], ['acover', `${g.away} ${sl > 0 ? '+' : '-'}${Math.abs(sl).toFixed(1)}`, 1 - p.hcover]]
      .concat(ovr == null ? [] : [['over', `Over ${g.tline}`, ovr], ['under', `Under ${g.tline}`, 1 - ovr]]).map(([k, t, v]) => smLegBtn(lg, g, `G|${k}`, t, v, g.legs[k], false, smGamePx(lg, g, k))).join('')}</div></div></section>`;
}
function smLegBtn(lg, g, key, label, p, b64, neg, px, cls, show) {
  const on = smLegsOf(lg).some(l => l.g === g.id && l.key === key);
  return `<button class="sm-leg${on ? ' on' : ''}${cls ? ' ' + cls : ''}" data-sm="leg" data-g="${esc(g.id)}" data-k="${esc(key)}" data-b="${b64}" data-n="${neg ? 1 : 0}" data-l="${esc(label)}" data-p="${p}"${px != null ? ` data-px="${px}"` : ''} aria-pressed="${on}"${show ? ` aria-label="${esc(label)}, ${pct(p)}"` : ''}><span>${esc(show || label)}</span><b class="num">${pct(p)}</b>${px != null ? `<em class="num">${odds(px)}</em>` : ''}<i aria-hidden="true"></i></button>`;
}
// the books' price for a game leg: the consensus moneyline, spreads and totals at the standard -110
function smGamePx(lg, g, k) { const G = ((DATA.games || {})[lg] || {}).games || [], x = G.find(y => y.id === g.id), ml = x && x.ml_mkt;
  if (k === 'home' || k === 'away') return ml && ml[k === 'home' ? 1 : 0] != null ? ml[k === 'home' ? 1 : 0] : null;
  return /book/i.test(g.src || '') ? -110 : null; }      // a spread or total from the model, not the books, has no price
function smGameLegs(lg, g) { const p = g.p, sl = g.spread, ovr = p.over;
  return [['away', `${g.away} wins`, 1 - p.home], ['home', `${g.home} wins`, p.home], ['acover', `${g.away} ${sl > 0 ? '+' : '-'}${Math.abs(sl).toFixed(1)}`, 1 - p.hcover], ['hcover', `${g.home} ${sl > 0 ? '-' : '+'}${Math.abs(sl).toFixed(1)}`, p.hcover]]
    .concat(ovr == null ? [] : [['over', `Over ${g.tline}`, ovr], ['under', `Under ${g.tline}`, 1 - ovr]]); }
function smHowHtml(lg) {      // the logic of one run, in plain words, league by league
  const N = lg === 'NBA' ? [
    ['Where it starts', 'The desk\'s own number for every player: the model, centred on the books for the slate and blended with each player\'s line at the weight the desk has learned. Players with a points line keep it; the rest of the rotation shares what is left of the books\' team total. Who plays comes from the injury report and, once the league posts them in the evening, tonight\'s starting fives: a player moved into the five gets about 21% more minutes, one moved out about 15% fewer, and the replay tips off with that five.'],
    ['1 · The game', 'Draw the final margin and total around the books\' spread and total. The spread of misses (about 14 points on the margin, 20 on the total) is what the closing line actually missed by last season.'],
    ['2 · The minutes', 'Move each player\'s minutes by how lopsided this run is: a 36-minute star plays about 13% less in a 30-point game, the end of the bench about 30% more. Add his own night-to-night swing, then keep the team to 240.'],
    ['3 · The team\'s night', 'Threes, rebounds and assists follow the team\'s points: a hot shooting night brings more threes and more assists, a cold one fewer. Fitted on 2024-25 box scores, with no shrink on threes or assists (v3.21).'],
    ['4 · Deal it out', 'Hand the team\'s threes, other points, boards and assists to the players by projection times minutes, with a random share so anyone can have a big or quiet night. A player\'s points are 3 x his threes plus his share of the rest, so the players always add up to the score.'],
    ['5 · Ten thousand times', 'Over % is the share of runs that cleared the line. A parlay is the share of runs where every leg hit, so legs that move together get credit for it.']]
  : [
    ['Where it starts', 'The desk\'s own number for every player: team volume times his share times his efficiency, centred on the books for the slate and blended with his lines at the weight the desk has learned.'],
    ['1 · The game', 'Draw the final margin and total around the books\' spread and total (the closing line misses by about 13 points either way).'],
    ['2 · The script', 'A side that ends up behind its spread throws more and runs less: about 0.5% more passes and 1% fewer carries for every point it trails by. Fitted on 2023-24.'],
    ['3 · The touches', 'Draw pass attempts and carries around the team\'s projection, deal targets by target share and carries by carry share, and each target becomes a catch at the player\'s catch rate. The starter\'s share of the dropbacks is itself uncertain: about one start in twenty he leaves early and the backup finishes.'],
    ['4 · The yards', 'Every catch and every carry is a real one from 2023-24 play-by-play (receivers, tight ends and backs each from their own), scaled to the player\'s yards per touch and to how well the offence played in that run. The quarterback\'s yards are his receivers\' yards; touchdowns follow the points.'],
    ['5 · Ten thousand times', 'Over % is the share of runs that cleared the line. A parlay is the share of runs where every leg hit, which is why a quarterback and his own receiver price far above the two legs multiplied.']];
  const weak = lg === 'NBA' ? 'Known weak spot: it is still a touch worse than the desk on threes, and teammates\' assists still compete a little.' : 'Known weak spots: catches and the run game test about level with the desk, not better. The replay is built from real plays (down, distance, field position and the call on each snap from 2023-24), and every carry, catch and touchdown in it is the run\'s.';
  return `<section class="sm-how"><details class="card"><summary><span class="lbl">How one run works</span><b>Five steps, then the same five steps 9,999 more times</b></summary>
    <ol class="sm-steps">${N.map(([t, d], i) => `<li style="--i:${i}"><b>${esc(t)}</b><p>${esc(d)}</p></li>`).join('')}</ol><p class="note">${esc(weak)} The replay above is one run drawn out play by play, starting on the run nearest the middle; Outliers holds the other ways the game breaks, each with how often it happened. The numbers below are all of the runs.</p></details></section>`;
}
function smPropRows(lg, g) {
  const rows = g.props.filter(r => S.sm.mkt === 'all' || r.mkt === S.sm.mkt);
  const lean = r => r.pk != null ? r.p - r.pk : r.pm != null ? r.p - r.pm : 0;
  rows.sort(S.sm.sort === 'lean' ? (a, b) => Math.abs(lean(b)) - Math.abs(lean(a)) : S.sm.sort === 'over' ? (a, b) => b.p - a.p : (a, b) => a.p - b.p);
  return rows;
}
function smPropsHtml(lg, g) {
  const rows = smPropRows(lg, g), anyBook = g.props.some(r => r.book);
  const mk = SM_MK[lg].filter(([k]) => k === 'all' || g.props.some(r => r.mkt === k));
  const bar = (v, cls) => v == null ? `<span class="sm-pb none">·</span>` : `<span class="sm-pb ${cls}" style="--v:${v}"><i></i><b class="num">${(v * 100).toFixed(0)}</b></span>`;
  const row = (r, i) => { const p = IDX[lg].byId[r.pid] || { name: '?', team: '', pos: '' }, team = r.t === 1 ? g.home : g.away, M = MK[lg][r.mkt] || { s: r.mkt };
    const ln = r.mkt === 'any_td' ? 'Anytime TD' : `${M.s} ${r.line}`, lv = r.pk != null ? r.p - r.pk : null, open = S.sm.open === r.pid + '|' + r.mkt;
    const st = smStat(g, r), k = `P|${r.pid}|${r.mkt}`;
    return `<li class="sm-pr${open ? ' open' : ''}" style="--i:${i};${tcol(lg, team)}">
      <button class="sm-ph" data-sm="open:${r.pid}|${r.mkt}" aria-expanded="${open}">${jersey(lg, Object.assign({}, p, { team }))}<span class="sm-pn"><b>${esc(p.name)}</b><small>${esc(team)} · ${esc(ln)}${r.book ? ` · ${esc(bookName(r.book))} ${r.o != null ? odds(r.o) : ''}${r.u != null ? '/' + odds(r.u) : ''}` : ' · sim line, no book line yet'}</small></span>
        <span class="sm-bars">${bar(r.p, 's')}${bar(r.pm, 'm')}${bar(r.pk, 'k')}</span>${lv == null ? '<span class="sm-lv"></span>' : `<span class="sm-lv ${lv >= 0 ? 'o' : 'u'}"><b>${lv >= 0 ? 'Over' : 'Under'}</b><small>${(Math.abs(lv) * 100).toFixed(1)} pts</small></span>`}</button>
      <div class="sm-pd"><div><div class="sm-pdi">${st ? smRange(st, r.line, r.mkt) : ''}<div class="sm-pl">${smPropLegs(lg, g, r, p)}</div></div></div></div></li>`; };
  return `<section class="sm-props"><div class="hd"><h2>Props, priced by the runs</h2><span>${anyBook ? 'Each line the books post, and how often the runs clear it' : 'No book lines yet for this game: sim lines at each player\'s median'}</span></div>
    <div class="sm-pf-row"><div class="seg sm-mk" data-seg="smmk"><span class="seg-ink"></span>${mk.map(([k, t]) => `<button data-sm="mk:${k}" aria-pressed="${S.sm.mkt === k}">${t}</button>`).join('')}</div>
      <div class="seg sm-so" data-seg="smso"><span class="seg-ink"></span>${[['lean', 'Biggest lean'], ['over', 'Most likely over'], ['under', 'Most likely under']].map(([k, t]) => `<button data-sm="so:${k}" aria-pressed="${S.sm.sort === k}">${t}</button>`).join('')}</div></div>
    ${(g.fit || []).filter(f => f.k < .5).map(f => `<div class="banner sm-fitnote"><span><b>${esc(f.t ? g.home : g.away)}</b>: the ${f.n} players with a points line add up to ${f.quoted.toFixed(1)} on the desk's numbers, against a team total of ${f.total.toFixed(1)} from the books. Every run has to land on a real team score, so ${esc(f.t ? g.home : g.away)}'s scorers lean under here. That is the sim siding with the team total, not a read on any one player.</span></div>`).join('')}
    <div class="sm-key"><span><i class="s"></i>Sim, over</span><span><i class="m"></i>Desk, one at a time</span><span><i class="k"></i>Books, no vig</span><span class="r">Lean = sim minus books</span></div>
    <ol class="sm-pl-list">${rows.slice(0, S.sm.lim).map(row).join('') || '<li class="prose">No props in this market.</li>'}</ol>
    ${rows.length > S.sm.lim ? `<button class="btn ghost sm sm-more" data-sm="more">Show ${Math.min(30, rows.length - S.sm.lim)} more of ${rows.length - S.sm.lim}</button>` : ''}
    <p class="note">Sim is the share of ${(SMD[lg].d.runs).toLocaleString()} runs that went over the line. Desk, one at a time is the desk's own number for that player priced on its own, the way the board prices it. Books is the no-vig chance from the books quoting the same line. Tap a prop for its range and to add it to a parlay. Display only: the desk's bets still come from its own rules.</p></section>`;
}
function smPropLegs(lg, g, r, p, cls) { const M = MK[lg][r.mkt] || { s: r.mkt }, k = `P|${r.pid}|${r.mkt}`, mini = cls === 'mini';
  return smLegBtn(lg, g, k + '|o', `${smLast(p.name)} ${r.mkt === 'any_td' ? 'scores' : 'over ' + r.line + ' ' + (M.s || '').toLowerCase()}`, r.p, r.b, false, r.book && r.o != null ? r.o : null, cls, mini ? (r.mkt === 'any_td' ? 'Scores' : 'Over ' + r.line) : null)
    + (r.mkt === 'any_td' ? '' : smLegBtn(lg, g, k + '|u', `${smLast(p.name)} under ${r.line} ${(M.s || '').toLowerCase()}`, 1 - r.p, r.b, true, r.book && r.u != null ? r.u : null, cls, mini ? 'Under ' + r.line : null)); }
const bookName = b => ({ hardrockbet: 'Hard Rock', draftkings: 'DK', fanduel: 'FD', betmgm: 'MGM', williamhill_us: 'Caesars', betrivers: 'BetRivers', fanatics: 'Fanatics' })[b] || b;
function smStat(g, r) {
  const base = r.mkt === 'any_td' ? 'td' : r.mkt; for (const T of g.teams) for (const p of T.players) if (p.id === r.pid) return p.st[base] ? { q: p.st[base] } : null; return null;
}
function smRange(st, line, mkt) {      // 10th to 90th percentile, the middle half thicker, the median ticked, the line marked
  const q = st.q, lo = Math.min(q[1], line) , hi = Math.max(q[5], line), span = Math.max(hi - lo, 1), X = v => 4 + (v - lo) / span * 92;
  return `<div class="sm-rg" aria-label="Middle 80% of runs ${q[1]} to ${q[5]}, median ${q[3]}"><span class="lbl">Middle 80% of runs</span><div class="sm-rgb"><i class="w" style="left:${X(q[1])}%;width:${X(q[5]) - X(q[1])}%"></i><i class="m" style="left:${X(q[2])}%;width:${X(q[4]) - X(q[2])}%"></i><i class="d" style="left:${X(q[3])}%"></i>${mkt === 'any_td' ? '' : `<i class="l" style="left:${X(line)}%"><b>${line}</b></i>`}</div><div class="sm-rgl num"><span>${q[1]}</span><span>median ${q[3]} · average ${q[0].toFixed(1)}</span><span>${q[5]}</span></div></div>`;
}
function smScriptHtml(lg, g) {
  const rows = [];
  g.teams.forEach((T, j) => T.players.slice(0, lg === 'NBA' ? 4 : 5).forEach(p => { const c = p.cond; if (!c) return; rows.push({ p, team: j ? g.home : g.away, c }); }));
  if (!rows.length) return '';
  const th = lg === 'NBA' ? ['Close game, within 9', 'Blowout, 20+'] : ['His side down 10+', 'His side up 10+'];
  const cell = (v, base, l) => v == null ? `<td data-l="${l}">·</td>` : `<td data-l="${l}"><b class="num">${v.toFixed(1)}</b>${base != null ? `<small class="${v >= base ? 'pos' : 'neg'}">${v >= base ? '+' : ''}${(v - base).toFixed(1)}</small>` : ''}</td>`;
  const lab = { pts: 'PTS', pass_yds: 'PASS YDS', rush_yds: 'RUSH YDS', rec_yds: 'REC YDS' };
  return `<section class="sm-script ${lg.toLowerCase()}"><div class="hd"><h2>How the script moves them</h2><span>The same runs, split by how the game went</span></div>
    <div class="card sm-st"><table class="sm-rsp"><thead><tr><th>Player</th><th>Stat</th><th>Every run</th><th>${th[0]}</th><th>${th[1]}</th>${lg === 'NBA' ? '<th>Minutes, close / blowout</th>' : ''}</tr></thead><tbody>${rows.map(r => {
      const all = r.p.st[r.c.k] ? r.p.st[r.c.k][0] : null, a = lg === 'NBA' ? r.c.close : r.c.behind, b = lg === 'NBA' ? r.c.blow : r.c.ahead;
      return `<tr style="${tcol(lg, r.team)}"><th scope="row"><span class="sm-sw"></span>${esc(r.p.name)}<small>${esc(r.team)} · ${lab[r.c.k] || r.c.k}</small></th><td class="lbl sm-stk">${lab[r.c.k] || r.c.k}</td><td data-l="Every run"><b class="num">${all == null ? '·' : all.toFixed(1)}</b></td>${cell(a, all, th[0])}${cell(b, all, th[1])}${lg === 'NBA' ? `<td class="num sm-mn" data-l="Minutes, close / blowout">${r.c.mclose.toFixed(1)}<i> / </i>${r.c.mblow.toFixed(1)}</td>` : ''}</tr>`; }).join('')}</tbody></table></div>
    <p class="note">${lg === 'NBA' ? 'In a blowout the stars sit for the fourth quarter and the bench plays it out. A player-by-player price cannot see that; the runs can, because every player in a run lives through the same game.' : 'A side that falls behind throws more and runs less, so a quarterback\'s yards climb when his side trails and a lead back\'s carries climb when it is ahead.'}</p></section>`;
}
function smTestHtml(lg, d) {
  const B = d.bt || {}, R = d.rec || {}, M = MK[lg];
  const mg = B.marg ? Object.entries(B.marg).map(([k, v]) => `<tr><th scope="row">${esc((M[k] || {}).n || k)}</th>${v.map(f => `<td class="${f[2] >= 0 ? 'pos' : 'neg'}"><b class="num">${f[2] >= 0 ? '+' : ''}${f[2].toFixed(2)}%</b><small>${esc(f[0])} · ${f[1].toLocaleString()}${f[4] != null ? ` · was ${f[4] >= 0 ? '+' : ''}${f[4].toFixed(2)}%` : ''}</small></td>`).join('')}</tr>`).join('') : '';
  const jt = B.joint ? B.joint.map(r => `<tr${/Every pair/.test(r[0]) || r[0] === 'all pairs' ? ' class="tot"' : ''}><th scope="row">${esc(r[0] === 'all pairs' ? 'Every pair tested' : r[0])}</th><td class="num" data-l="Pairs">${r[1].toLocaleString()}</td><td class="num" data-l="Actual"><b>${pct(r[2])}</b></td><td class="num" data-l="Sim">${pct(r[3])}</td><td class="num" data-l="Multiplied">${pct(r[4])}</td><td class="${r[5] >= 0 ? 'pos' : 'neg'} num" data-l="Log loss">${r[5] >= 0 ? '+' : ''}${r[5].toFixed(2)}%${r[6] != null ? `<small>was ${r[6] >= 0 ? '+' : ''}${r[6].toFixed(2)}%</small>` : ''}</td></tr>`).join('') : '';
  const rec = R.n ? `<div class="sm-rec"><span class="lbl">Live record since ${esc(R.since)}</span><p><b>${R.n.toLocaleString()}</b> graded props. Brier score, lower is better: sim <b class="num">${R.sim.brier.toFixed(4)}</b>, model alone <b class="num">${R.model.brier.toFixed(4)}</b>${R.vs_books ? `, books <b class="num">${R.vs_books.books.toFixed(4)}</b> (on the ${R.vs_books.n.toLocaleString()} with a books price)` : ''}. ${R.n < 200 ? 'Too few to judge yet: the rule is 200 graded before it can have a say.' : ''}</p></div>`
    : `<div class="sm-rec"><span class="lbl">Live record</span><p>Every prop the sim prices before tip is logged with the model's own price and the books' price, and graded the next morning. Nothing graded yet.</p></div>`;
  return `<section class="sm-test"><div class="hd"><h2>Did it earn its say?</h2><span>Tested on games it never saw</span></div>
    <div class="two w"><div class="card"><span class="lbl">One prop at a time · CRPS gain over pricing each prop alone</span><table class="sm-tt"><tbody>${mg}</tbody></table><p class="note">Plus is better. Prop by prop the sim lands about level with the desk's own curve, ${lg === 'NBA' ? 'better on points and assists, about even on rebounds, and still a touch worse on threes' : 'better on the quarterback\'s attempts, completions and yards and on receiving yards, about even on catches and the run game'}. Level is the expected result: the averages are the same model's. ${B.was ? `"Was" is v${esc(B.was)} on the same games, before the v${esc(B.ver)} fixes.` : ''}</p></div>
      <div class="card"><span class="lbl">Two legs from the same game · how often both hit</span><table class="sm-tt j sm-rsp"><thead><tr><th></th><th>Pairs</th><th>Actual</th><th>Sim</th><th>Legs multiplied</th><th>Log loss</th></tr></thead><tbody>${jt}</tbody></table><p class="note">This is where the runs earn their keep. Multiplying two legs assumes they have nothing to do with each other; ${lg === 'NBA' ? 'a scorer and his team winning, or his points and rebounds,' : 'a quarterback and his own receiver'} hit together far more often than that, and the runs see it.</p></div></div>
    ${rec}<p class="note">${esc(B.test || '')} Display and tracking only: it gets a say in the desk's prices only if the weekly review finds it beating them on 200+ graded props.</p></section>`;
}

/* ---------- v3.21 the parlay builder: every game on the slate, its lines and its props ---------- */
function smBuildHtml(lg, d) {
  return `<section class="sm-build" id="smBuild"><div class="hd"><h2>Build a parlay</h2><span>Any game on the slate, its lines and its props</span></div>
    <div class="sm-bf"><div class="seg sm-bt" data-seg="smbt"><span class="seg-ink"></span>${[['games', 'Game lines'], ['props', 'Props']].map(([k, t]) => `<button data-sm="bt:${k}" aria-pressed="${S.sm.bt === k}">${t}</button>`).join('')}</div>
      <label class="sm-bs fld"${S.sm.bt === 'games' ? ' hidden' : ''}><span class="sr">Find a player</span><input id="smBq" type="search" inputmode="search" autocomplete="off" placeholder="Find a player" value="${esc(S.sm.bq)}"></label></div>
    ${S.sm.bt === 'props' ? `<div class="seg sm-bm" data-seg="smbm"><span class="seg-ink"></span>${SM_MK[lg].filter(([k]) => k === 'all' || d.games.some(g => g.props.some(r => r.mkt === k))).map(([k, t]) => `<button data-sm="bm:${k}" aria-pressed="${S.sm.bm === k}">${t}</button>`).join('')}</div>` : ''}
    <div id="smBl" class="sm-bl">${smBuildList(lg, d)}</div>
    <p class="note">Each leg shows the share of runs it hit in and the books' price where there is one (moneylines are the consensus, spreads and totals the standard -110). Legs from one game are priced together from that game's runs; legs from different games are multiplied.</p></section>`;
}
function smBuildList(lg, d) {
  if (S.sm.bt === 'games') return `<ol class="sm-bg">${d.games.map((g, i) => `<li class="sm-bgr" style="--i:${Math.min(i, 12)};${tcol(lg, g.away).replace(/--t/g, '--a')};${tcol(lg, g.home).replace(/--t/g, '--h')}">
      <div class="sm-bgh">${badge(lg, g.away, 'xs')}<b>${esc(g.away)}</b><i>@</i>${badge(lg, g.home, 'xs')}<b>${esc(g.home)}</b><small>${t12(g.time)}</small></div>
      <div class="sm-bgl">${smGameLegs(lg, g).map(([k, t, v]) => smLegBtn(lg, g, `G|${k}`, t, v, g.legs[k], false, smGamePx(lg, g, k), 'mini', k === 'away' ? g.away + ' ML' : k === 'home' ? g.home + ' ML' : k === 'over' ? 'O ' + g.tline : k === 'under' ? 'U ' + g.tline : null)).join('')}</div></li>`).join('')}</ol>`;
  const q = S.sm.bq.trim().toLowerCase(), rows = [];
  for (const g of d.games) for (const r of g.props) { if (S.sm.bm !== 'all' && r.mkt !== S.sm.bm) continue; const p = IDX[lg].byId[r.pid]; if (!p) continue; if (q && !p.name.toLowerCase().includes(q)) continue; rows.push({ g, r, p }); }
  const lean = r => r.pk != null ? r.p - r.pk : r.pm != null ? r.p - r.pm : 0;
  rows.sort((a, b) => Math.abs(lean(b.r)) - Math.abs(lean(a.r)));
  if (!rows.length) return `<p class="prose">No props match${q ? ` "${esc(S.sm.bq)}"` : ''}.</p>`;
  return `<ol class="sm-bp">${rows.slice(0, 24).map(({ g, r, p }, i) => { const team = r.t === 1 ? g.home : g.away, opp = r.t === 1 ? g.away : g.home, M = MK[lg][r.mkt] || { s: r.mkt };
    return `<li class="sm-bpr" style="--i:${Math.min(i, 12)};${tcol(lg, team)}">${jersey(lg, Object.assign({}, p, { team }))}<span class="sm-pn"><b>${esc(p.name)}</b><small>${esc(team)} ${r.t === 1 ? 'vs' : '@'} ${esc(opp)} · ${esc(r.mkt === 'any_td' ? 'Anytime TD' : M.s + ' ' + r.line)}</small></span><span class="sm-pl">${smPropLegs(lg, g, r, p, 'mini')}</span></li>`; }).join('')}</ol>
    ${rows.length > 24 ? `<p class="note">Showing the 24 with the biggest lean of ${rows.length}. Search a name to find anyone else.</p>` : ''}`;
}
let smBqT = 0;
document.addEventListener('input', e => { if (e.target.id !== 'smBq' || S.tab !== 'sim') return; S.sm.bq = e.target.value; clearTimeout(smBqT);
  smBqT = setTimeout(() => { const el = $('#smBl'), d = SMD[S.lg].d; if (el && d) el.innerHTML = smBuildList(S.lg, d); }, 140); });
function smBuildPaint() { const sec = $('#smBuild'), d = SMD[S.lg].d; if (!sec || !d) return; const y = scrollY; sec.outerHTML = smBuildHtml(S.lg, d); window.scrollTo(0, y); document.querySelectorAll('.sm-build .seg').forEach(sg => placeSeg(sg, false)); }

/* ---------- the bet slip: a stack of tickets (v3.21) ----------
   Collapsed, the legs sit as a stack of tickets above the totals, the newest in front and two peeking behind;
   hover (or tap the stack) and they fan out into a list. A new leg slides in from below and the stack shifts back to
   make room; a removed one slides off to the side. Every move is a CSS transform that retargets from wherever it is,
   so quick taps never jump. Reduced motion: no sliding, the tickets simply appear and the stack is laid out flat. */
function smTray() {
  const t = $('#smTray'); if (!t) return; const lg = S.lg, legs = smLegsOf(lg), n = legs.length;
  document.body.classList.toggle('sm-has-tray', !!n);
  if (!n) { t.hidden = true; t.innerHTML = ''; S.sm.stack = false; return; }
  const was = t.hidden; t.hidden = false;
  if (!t.firstElementChild) t.innerHTML = `<div class="sm-slip" data-open="${S.sm.stack ? 1 : 0}"><ol class="sm-stack" data-sm="stack" aria-label="Legs in the parlay"></ol>
    <div class="sm-sum"><button class="sm-sh" data-sm="stack" aria-expanded="${S.sm.stack}"><span class="lbl" id="smSl"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg></button>
      <div class="sm-nums"><div><small>The runs</small><b class="num" id="smPj"></b><span id="smPjf"></span></div><div><small>Legs multiplied</small><b class="num" id="smPm"></b><span id="smPmf"></span></div><div><small>Books</small><b class="num" id="smBk"></b><span id="smBkf"></span></div><div class="lift" id="smLf"><small>Edge at the books</small><b class="num" id="smEv"></b><span id="smEvf"></span></div></div>
      <div class="sm-ex"><div><div class="sm-exi"><label class="sm-yp"><span>Your price</span><input id="smPx" inputmode="numeric" autocomplete="off" placeholder="+600" value="${esc(S.sm.px)}"></label><p class="sm-ye" id="smYe"></p><div class="sm-gp" id="smGp"></div><button class="btn ghost sm sm-clr" data-sm="clear">Clear slip</button></div></div></div></div></div>`;
  const ol = t.querySelector('.sm-stack'), have = new Map([...ol.children].filter(li => !li.classList.contains('out')).map(li => [li.dataset.u, li]));
  const G = SMD[lg].d.games, gOf = id => G.find(x => x.id === id);
  legs.forEach((l, idx) => { const u = smUid(l.g, l.key), k = n - 1 - idx, g = gOf(l.g); let li = have.get(u);
    if (!li) { li = document.createElement('li'); li.className = 'sm-card'; li.dataset.u = u;
      const team = l.key.startsWith('G|') ? (/^(away|acover)$/.test(l.key.slice(2)) ? g.away : /^(home|hcover)$/.test(l.key.slice(2)) ? g.home : null) : (g.props.find(r => `P|${r.pid}|${r.mkt}` === l.key.replace(/\|[ou]$/, '')) || {}).t === 1 ? g.home : g.away;
      li.setAttribute('style', team ? tcol(lg, team) : '');
      li.innerHTML = `<span class="sm-cs" aria-hidden="true"></span><span class="sm-cb"><b>${esc(l.label)}</b><small>${esc(g.away)} @ ${esc(g.home)}${l.px != null ? ' · books ' + odds(l.px) : ''}</small></span><b class="num sm-cp">${pct(l.p)}</b><button class="sm-cx" data-sm="rm:${esc(u)}" aria-label="Remove ${esc(l.label)}">×</button>`;
      ol.appendChild(li);
      if (!was && !RM()) li.animate([{ transform: 'translateY(115%) scale(.97)', opacity: 0 }], { duration: 400, easing: 'cubic-bezier(.32,.72,0,1)' }); }
    have.delete(u); li.style.setProperty('--k', k); li.style.zIndex = 60 - k; li.setAttribute('aria-hidden', k > 2 && !S.sm.stack ? 'true' : 'false'); });
  for (const [, li] of have) { li.classList.add('out'); if (RM()) li.remove(); else li.animate([{ transform: 'translateX(40%) scale(.96)', opacity: 0 }], { duration: 200, easing: 'cubic-bezier(.23,1,.32,1)', fill: 'forwards' }).finished.then(() => li.remove(), () => li.remove()); }
  const avail = Math.max(160, innerHeight - t.offsetHeight - 120), step = Math.min(56, Math.floor(avail / n));
  ol.style.setProperty('--n', n); ol.style.setProperty('--step', step + 'px');
  smSlipNums(lg);
  if (was && !RM()) t.animate([{ transform: 'translateY(130%)' }, { transform: 'none' }], { duration: 420, easing: 'cubic-bezier(.32,.72,0,1)' });
}
function smSlipNums(lg) {
  const legs = smLegsOf(lg); if (!legs.length) return; const P = smSlipPrice(lg, legs), n = legs.length, multi = Object.values(P.by).some(L => L.length > 1);
  const set = (id, v, cls) => { const el = $('#' + id); if (!el) return; if (cls != null) el.className = 'num ' + cls; if (el.textContent === v) return; el.textContent = v;
    if (!RM() && el.animate && el.tagName === 'B') el.animate([{ transform: 'translateY(35%)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 220, easing: 'cubic-bezier(.23,1,.32,1)' }); };
  set('smSl', `Parlay · ${n} leg${n > 1 ? 's' : ''}${P.games > 1 ? ` · ${P.games} games` : ''}`);
  set('smPj', pct(P.pj)); set('smPjf', `fair ${smOdds(P.pj)}`);
  set('smPm', pct(P.pm)); set('smPmf', multi ? `runs ${(P.pj / P.pm).toFixed(2)}x that` : 'no two from one game');
  if (P.dec) { const ev = P.pj * P.dec - 1; set('smBk', odds(smAm(P.dec))); set('smBkf', `implied ${pct(1 / P.dec)}`); set('smEv', `${ev >= 0 ? '+' : ''}${(ev * 100).toFixed(0)}`, ev >= 0 ? 'pos' : 'neg'); set('smEvf', 'per $100, on the runs'); }
  else { set('smBk', '·'); set('smBkf', `${P.priced} of ${n} legs priced`); set('smEv', '·', ''); set('smEvf', 'needs every leg priced'); }
  const yp = parseFloat(S.sm.px), ye = $('#smYe');
  if (ye) { if (isFinite(yp) && Math.abs(yp) >= 100) { const dec = E.dec(yp), ev = P.pj * dec - 1; ye.innerHTML = `At ${odds(yp)} the runs make it <b class="${ev >= 0 ? 'pos' : 'neg'}">${ev >= 0 ? '+' : ''}${(ev * 100).toFixed(1)}</b> per $100. Break-even is ${odds(smAm(1 / Math.max(P.pj, .001)))}.`; }
    else ye.textContent = `Type the price you are offered to see the edge. The runs make it fair at ${smOdds(P.pj)}.`; }
  const gp = $('#smGp'), G = SMD[lg].d.games;
  if (gp) gp.innerHTML = Object.entries(P.by).map(([gid, L]) => { const g = G.find(x => x.id === gid), pj = L.length > 1 ? smJoint(lg, L.map(l => ({ k: smUid(l.g, l.key), b: l.b, neg: l.neg }))) : L[0].p, pm = L.reduce((a, l) => a * l.p, 1);
    return `<span class="sm-gpi"><b>${esc(g.away)} @ ${esc(g.home)}</b> ${L.length} leg${L.length > 1 ? 's' : ''} · ${pct(pj)}${L.length > 1 ? ` · <i class="${pj >= pm ? 'pos' : 'neg'}">${(pj / pm).toFixed(2)}x</i> together` : ''}</span>`; }).join('');
}
document.addEventListener('input', e => { if (e.target.id !== 'smPx' || S.tab !== 'sim') return; S.sm.px = e.target.value.replace(/[^\d+-]/g, ''); smSlipNums(S.lg); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.tab === 'sim' && S.sm.stack) { S.sm.stack = false; const sl = document.querySelector('.sm-slip'); if (sl) { sl.dataset.open = 0; sl.querySelector('.sm-sh').setAttribute('aria-expanded', false); } } });

/* ---------- mounting and events ---------- */
let SMA = null;       // the live arena
function simAfter(enter) {
  document.querySelectorAll('#main .seg').forEach(sg => placeSeg(sg, false));
  smTray();
  const lg = S.lg, z = SMD[lg]; if (z.st !== 'ready') return; const g = smGame(lg); if (!g) return;
  if (SMA) SMA.destroy();
  const ri = smRi(g);
  SMA = new Arena(lg, g, ri);
  const on = document.querySelector('.sm-r.on'), rl = on && on.parentElement;      // bring the chosen run into view inside its row, not the page
  if (rl && rl.scrollWidth > rl.clientWidth) { const a = on.getBoundingClientRect(), r = rl.getBoundingClientRect(); rl.scrollLeft += a.left - r.left - (r.width - a.width) / 2; }
  const cn = $('#smCount');      // the booth's run counter rolls up to 10,000 on arrival
  if (cn && enter && !RM()) { const t0 = performance.now(), D = 1500; const step = t => { const q = Math.min(1, (t - t0) / D), v = Math.round(10000 * (1 - Math.pow(1 - q, 3))); cn.textContent = v.toLocaleString('en-US').padStart(6, '0'); if (q < 1 && cn.isConnected) requestAnimationFrame(step); }; requestAnimationFrame(step); }
  if (enter && !RM()) {        // the margin bars rise from the baseline, centre out
    document.querySelectorAll('.sm-hb rect').forEach(r => r.animate([{ transform: 'scaleY(.04)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 520, delay: Math.min(+r.style.getPropertyValue('--i') * 9, 300), easing: 'cubic-bezier(.23,1,.32,1)', fill: 'backwards' }));
    document.querySelectorAll('.sm-tile').forEach((el, i) => el.animate([{ transform: 'translateY(10px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 360, delay: 60 + i * 50, easing: 'cubic-bezier(.23,1,.32,1)', fill: 'backwards' }));
  }
}
function simStop() { if (SMA) { SMA.destroy(); SMA = null; } document.body.classList.remove('sm-has-tray'); }
function smPropsPaint() {     // repaint the props list only, keeping the replay running
  const lg = S.lg, g = smGame(lg), sec = document.querySelector('.sm-props'); if (!g || !sec) return;
  const y = scrollY; sec.outerHTML = smPropsHtml(lg, g); window.scrollTo(0, y); document.querySelectorAll('.sm-props .seg').forEach(sg => placeSeg(sg, false));
}
function smLegSync() { document.querySelectorAll('[data-sm="leg"]').forEach(b => { const on = smLegsOf(S.lg).some(l => l.g === b.dataset.g && l.key === b.dataset.k); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); }); smTray(); }
document.addEventListener('click', e => {
  const t = e.target.closest('[data-sm]'); if (!t || S.tab !== 'sim') return;
  const v = t.dataset.sm, i = v.indexOf(':'), key = i < 0 ? v : v.slice(0, i), val = i < 0 ? '' : v.slice(i + 1), lg = S.lg;
  if (key === 'retry') { SMD[lg].st = 'idle'; refreshMain(); return; }
  if (key === 'g') { if (S.sm.g[lg] === val) return; S.sm.g[lg] = val; S.sm.open = null; S.sm.lim = 30; const y = scrollY; S.enter = true; refreshMain(); S.enter = false; window.scrollTo(0, y); simAfter(true); return; }
  if (key === 'run') { const g = smGame(lg); S.sm.run[g.id] = +val; if (SMA) SMA.touched = true; document.querySelectorAll('.sm-r').forEach(b => { const on = b.dataset.sm === 'run:' + val; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
    const n = $('#smRn'); if (n) { n.innerHTML = smRunNote(lg, g, +val); if (!RM()) n.animate([{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'cubic-bezier(.23,1,.32,1)' }); }
    if (SMA) SMA.load(+val, true); return; }
  if (key === 'play') { if (SMA) SMA.toggle(); return; }
  if (key === 'sp') { S.sm.speed = +val; segPress(t); if (SMA) SMA.speed = +val; return; }
  if (key === 'restart') { if (SMA) { SMA.seek(0); SMA.play(); } return; }
  if (key === 'final') { if (SMA) { SMA.touched = true; SMA.seek(1); } return; }
  if (key === 'seek') { const r = t.getBoundingClientRect(); if (SMA) SMA.touched = true; if (SMA) SMA.seek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))); return; }
  if (key === 'mk') { S.sm.mkt = val; S.sm.lim = 30; segPress(t); setTimeout(smPropsPaint, RM() ? 0 : 200); return; }
  if (key === 'so') { S.sm.sort = val; segPress(t); setTimeout(smPropsPaint, RM() ? 0 : 200); return; }
  if (key === 'more') { S.sm.lim += 30; smPropsPaint(); return; }
  if (key === 'open') { const li = t.closest('.sm-pr'), on = S.sm.open !== val; S.sm.open = on ? val : null;
    document.querySelectorAll('.sm-pr.open').forEach(x => { if (x !== li) { x.classList.remove('open'); x.querySelector('.sm-ph').setAttribute('aria-expanded', false); } });
    li.classList.toggle('open', on); t.setAttribute('aria-expanded', on); return; }
  if (key === 'leg') { const legs = smLegsOf(lg), k = t.dataset.k, gid = t.dataset.g, at = legs.findIndex(l => l.g === gid && l.key === k);
    if (at >= 0) legs.splice(at, 1);
    else { const base = k.replace(/\|[ou]$/, ''); const j = legs.findIndex(l => l.g === gid && (l.key.replace(/\|[ou]$/, '') === base || (k.startsWith('G|') && l.key.startsWith('G|') && SM_GX[k.slice(2)] === l.key.slice(2))));
      if (j >= 0) legs.splice(j, 1);           // the other side of the same prop, or the opposite game result, swaps out
      if (legs.length >= 10) legs.shift(); legs.push({ g: gid, key: k, b: t.dataset.b, neg: t.dataset.n === '1', label: t.dataset.l, p: +t.dataset.p, px: t.dataset.px != null ? +t.dataset.px : null }); }
    smLegSync(); return; }
  if (key === 'rm') { const legs = smLegsOf(lg), j = legs.findIndex(l => smUid(l.g, l.key) === val); if (j >= 0) legs.splice(j, 1); smLegSync(); return; }
  if (key === 'clear') { smLegsOf(lg).length = 0; smLegSync(); return; }
  if (key === 'stack') { if (e.target.closest('.sm-cx')) return; S.sm.stack = !S.sm.stack; const sl = t.closest('.sm-slip'); if (sl) { sl.dataset.open = S.sm.stack ? 1 : 0; sl.querySelector('.sm-sh').setAttribute('aria-expanded', S.sm.stack); } smTray(); return; }
  if (key === 'bt') { if (S.sm.bt === val) return; S.sm.bt = val; segPress(t); setTimeout(smBuildPaint, RM() ? 0 : 200); return; }
  if (key === 'bm') { S.sm.bm = val; segPress(t); setTimeout(() => { const el = $('#smBl'), d = SMD[lg].d; if (el && d) el.innerHTML = smBuildList(lg, d); }, RM() ? 0 : 160); return; }
});
const SM_GX = { home: 'away', away: 'home', hcover: 'acover', acover: 'hcover', over: 'under', under: 'over' };
document.addEventListener('keydown', e => { if (S.tab !== 'sim' || !SMA) return; const p = e.target.closest && e.target.closest('#smProg'); if (!p) return;
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); SMA.seek(Math.min(1, Math.max(0, SMA.frac() + (e.key === 'ArrowRight' ? .05 : -.05)))); } });

/* ---------- the arena: script, motion and drawing ---------- */
function smRng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const smPickW = (R, ws) => { let s = 0; for (const w of ws) s += Math.max(w, 0); let x = R() * s; for (let i = 0; i < ws.length; i++) { x -= Math.max(ws[i], 0); if (x <= 0) return i; } return ws.length - 1; };
const smShuffle = (R, a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const smSpring = (o, tx, ty, dt, w) => {      // critically damped spring toward (tx, ty): no overshoot, no wobble, the speed carries through a retarget
  for (const [k, vk, t] of [['x', 'vx', tx], ['y', 'vy', ty]]) { const d = o[k] - t, e = Math.exp(-w * dt), c = o[vk] + w * d; o[k] = t + (d + c * dt) * e; o[vk] = (o[vk] - w * c * dt) * e; } };
function smQuad(p0, p1, p2, p3) {      // unit square to a quadrilateral (Heckbert): (0,0) p0, (1,0) p1, (1,1) p2, (0,1) p3
  const [x0, y0] = p0, [x1, y1] = p1, [x2, y2] = p2, [x3, y3] = p3, dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3, dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1, g = (dx3 * dy2 - dx2 * dy3) / den, h = (dx1 * dy3 - dx3 * dy1) / den;
  return [x1 - x0 + g * x1, x3 - x0 + h * x3, x0, y1 - y0 + g * y1, y3 - y0 + h * y3, y0, g, h]; }
const smEaseIO = u => u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
const smEaseOut = u => 1 - Math.pow(1 - u, 3);
const smLerp = (a, b, u) => a + (b - a) * u;

/* NBA: 16 three-minute shifts; each player's run minutes become shifts on the floor, then every made shot, free throw
   trip, rebound and assist in his line is placed in a shift he played */
function smNbaScript(g, smp, R) {
  const SL = 16, teams = [0, 1].map(j => g.teams[j].players.map((p, i) => ({ id: p.id, name: p.name, lu: p.lu, min: smp.b[j].min[i] || 0, pts: smp.b[j].pts[i] || 0, fg3: smp.b[j].fg3[i] || 0, reb: smp.b[j].reb[i] || 0, ast: smp.b[j].ast[i] || 0 })));
  const lineups = teams.map(rows => {
    const need = rows.map(r => Math.min(SL, Math.max(0, Math.round(r.min / 3)))); let tot = need.reduce((a, b) => a + b, 0);
    const byMin = rows.map((r, i) => i).sort((a, b) => rows[b].min - rows[a].min);
    while (tot > 5 * SL) { const i = [...byMin].reverse().find(i => need[i] > 0); need[i]--; tot--; }
    while (tot < 5 * SL) { const i = byMin.find(i => need[i] < SL); if (i == null) break; need[i]++; tot++; }
    const rem = need.slice(), on = [], five = rows.map((r, i) => i).filter(i => rows[i].lu === 'S' && need[i] > 0);
    for (let s = 0; s < SL; s++) {
      const left = SL - s;
      // v3.24: the opening shift is the starting five the league lists for tonight, when it has posted one
      const pick = s === 0 && five.length === 5 ? five.slice() : rows.map((r, i) => i).filter(i => rem[i] > 0).sort((a, b) => rem[b] / left - rem[a] / left || rows[b].min - rows[a].min).slice(0, 5);
      for (const i of byMin) { if (pick.length >= 5) break; if (!pick.includes(i)) pick.push(i); }
      pick.forEach(i => { if (rem[i] > 0) rem[i]--; }); on.push(pick);
    }
    return on;
  });
  const slotsOf = (j, i) => lineups[j].map((p, s) => p.includes(i) ? s : -1).filter(s => s >= 0);
  const ev = [];
  const at = (j, i, alt) => { let ss = slotsOf(j, i); if (alt != null) { const both = ss.filter(s => lineups[alt[0]][s].includes(alt[1])); if (both.length) ss = both; } if (!ss.length) ss = [Math.floor(R() * SL)]; const s = ss[Math.floor(R() * ss.length)]; return (s + .04 + R() * .92) * 3; };
  teams.forEach((rows, j) => {
    const made = [];
    rows.forEach((r, i) => {
      for (let k = 0; k < r.fg3; k++) made.push({ k: '3', j, i, pts: 3 });
      const non3 = Math.max(0, r.pts - 3 * r.fg3); let ft = Math.min(non3, Math.round(non3 * (.1 + R() * .16))); if ((non3 - ft) % 2) ft += ft < non3 ? 1 : -1;
      for (let k = 0; k < (non3 - ft) / 2; k++) made.push({ k: '2', j, i, pts: 2 });
      let f = ft; while (f > 0) { const n = f >= 2 ? 2 : 1; ev.push({ k: 'ft', j, i, pts: n, t: at(j, i) }); f -= n; }
    });
    rows.forEach((r, i) => { let a = r.ast; const pool = smShuffle(R, made.filter(m => m.i !== i && m.a == null)); for (const m of pool) { if (a <= 0) break; m.a = i; a--; } });
    made.forEach(m => { m.t = at(j, m.i, m.a != null ? [j, m.a] : null); ev.push(m); });
  });
  teams.forEach((rows, j) => rows.forEach((r, i) => { for (let k = 0; k < r.reb; k++) { const off = R() < .23, sj = off ? j : 1 - j, sh = teams[sj];
    const t = at(j, i), s = Math.min(SL - 1, Math.floor(t / 3)), cand = lineups[sj][s].filter(x => !(off && x === i)); const si = cand.length ? cand[smPickW(R, cand.map(x => sh[x].pts + 2))] : 0;
    ev.push({ k: 'miss', j: sj, i: si, rj: j, ri: i, off, t, three: R() < .4 }); } }));
  // turnovers keep the possessions level: each side gets about the same number of trips down the floor
  const trips = [0, 1].map(j => ev.filter(e => e.j === j && (e.k === '2' || e.k === '3' || (e.k === 'ft') || (e.k === 'miss' && !e.off))).length);
  for (const j of [0, 1]) { const n = Math.max(0, trips[1 - j] - trips[j]) + 9 + Math.floor(R() * 5); for (let k = 0; k < n; k++) { const t = R() * 48, s = Math.min(SL - 1, Math.floor(t / 3)), on = lineups[j][s]; ev.push({ k: 'to', j, i: on[Math.floor(R() * on.length)], t }); } }
  ev.sort((a, b) => a.t - b.t);
  // v3.23: the opening tip (each side's best rebounder on the floor jumps) and the start of each quarter. The side that
  // loses the tip has the ball to start the 2nd and 3rd, the winner the 4th, as in the rule book
  const jumper = j => lineups[j][0].slice().sort((a, b) => teams[j][b].reb - teams[j][a].reb || teams[j][b].min - teams[j][a].min)[0];
  const cj = [jumper(0), jumper(1)], tw = R() < .5 ? 0 : 1;
  ev.unshift({ k: 'tip', j: tw, t: 0, c: cj });
  for (const [q, j] of [[2, 1 - tw], [3, 1 - tw], [4, tw]]) { const t = (q - 1) * 12, at = ev.findIndex(e => e.t >= t); ev.splice(at < 0 ? ev.length : at, 0, { k: 'qtr', j, t, q }); }
  return { ev, lineups, teams, SL, final: smp.sc };
}

/* NFL (v3.21): every carry, catch and incompletion is one from the run's box, so the box at the final whistle is the
   run's box. The football around them is real 2023-24 football: the call on each down (run, pass, incompletion) follows
   how often teams made it on that down and distance, the gain is the player's own play nearest a real gain from that
   spot, drives start where real drives started after kicks and punts, a drive that stalls ends on fourth down, and the
   field goals, extra points and touchdowns add up to the run's score. */
function smNflScript(g, smp, R) {
  const LB = (SMD.NFL && SMD.NFL.d && SMD.NFL.d.plib) || null;
  const pick = a => a[Math.floor(R() * a.length)];
  const tb = t => t <= 2 ? 0 : t <= 6 ? 1 : t <= 10 ? 2 : 3, stOf = (dn, tg) => (Math.min(4, dn) - 1) * 4 + tb(tg);
  const runShare = st => LB ? LB.run_share[st] : [.76, .63, .5, .3, .65, .49, .32, .18, .59, .12, .05, .11, .59, .06, .04, .04][st];
  const incShare = st => LB ? LB.inc_share[st] : .33;
  const realGain = (k, st) => LB ? pick(k === 'run' ? LB.run_q[st] : LB.catch_q[st]) : (k === 'run' ? 4 : 11);
  // a player's yards over his n plays, shaped like real gains and adding up to his line exactly
  const split = (tot, n, k) => {
    if (n <= 0) return [];
    // real gains, then shifted (not scaled: scaling a small sum blows the spread up) so they add up to his line
    let y = Array.from({ length: n }, () => realGain(k, 0)); const s0 = y.reduce((a, b) => a + b, 0), sh = Math.trunc((tot - s0) / n);
    y = y.map(v => v + sh);
    let d = tot - y.reduce((a, b) => a + b, 0), it = 0; const lo = k === 'run' ? -6 : -3;
    while (d !== 0 && it++ < 4000) { const i = Math.floor(R() * n); if (d > 0) { y[i]++; d--; } else if (y[i] > lo) { y[i]--; d++; } }
    if (d) y[0] += d;
    return smShuffle(R, y); };
  const T = [0, 1].map(j => {
    const P = g.teams[j].players, b = smp.b[j];
    let qb = 0, best = -1; P.forEach((p, i) => { if ((b.pass_att[i] || 0) > best) { best = b.pass_att[i] || 0; qb = i; } });
    const plays = [];
    P.forEach((p, i) => {
      const add = (arr, m) => {      // touchdowns go on positive plays, the short ones more often (most touchdowns come from close in)
        const c = arr.filter(p => p.y >= 1).sort((x, y) => x.y - y.y);
        for (let k = 0; k < m; k++) { let p = c.length ? c.splice(Math.floor(R() * R() * c.length), 1)[0] : arr.find(p => !p.td); if (!p) break;
          if (p.y < 1) { const dl = 1 - p.y, o = arr.filter(x => x !== p && (!x.td || x.y - dl >= 1)).sort((x, y) => y.y - x.y)[0];
            if (o) { o.y -= dl; p.y = 1; } else continue; }      // no gain to borrow from: that touchdown is not his in this replay
          p.td = true; }
        plays.push(...arr); };
      add(split(b.rush_yds[i] || 0, b.rush_att[i] || 0, 'run').map(y => ({ k: 'run', j, i, y })), Math.max(0, (b.td[i] || 0) - (b.rec_td[i] || 0)));
      add(split(b.rec_yds[i] || 0, b.rec[i] || 0, 'pass').map(y => ({ k: 'pass', j, i, y, q: qb })), b.rec_td[i] || 0);
    });
    const tw = P.map((p, i) => Math.max((b.tgt[i] || 0) - (b.rec[i] || 0), 0) + .2);
    // the quarterback's line is what his receivers caught (within a completion or two of the run's own count), plus
    // incompletions up to his attempts
    // in a run where he left early (his completions well short of what his receivers caught) the backup throws the rest
    const caught = plays.filter(p => p.k === 'pass').length, cmpS = b.pass_cmp[qb] || 0, exit = caught >= 4 && cmpS < .8 * caught, cmpQ = exit ? cmpS : caught;
    const nInc = Math.max(0, (b.pass_att[qb] || 0) - cmpQ) + (exit ? Math.round((caught - cmpQ) * .6) : 0);
    const incs = Array.from({ length: nInc }, () => ({ k: 'inc', j, i: smPickW(R, tw), y: 0, q: qb }));
    return { qb, plays, incs, nInc: incs.length, P, exit, cmpQ };
  });
  // the score, exactly: the run's touchdowns (a few dropped or added when the score cannot hold them), then the field
  // goals, extra points and safeties that make up the rest
  const plan = [0, 1].map(j => {
    const pts = smp.sc[j], pl = T[j].plays; let tdl = pl.filter(p => p.td);
    while (tdl.length * 6 > pts) tdl.pop().td = false;
    let pn = null, ret = 0;
    for (let guard = 0; guard < 4 && !pn; guard++) {
      const a0 = tdl.length + ret, R0 = pts - 6 * a0;
      for (let f = Math.floor(R0 / 3); f >= 0; f--) { const p = R0 - 3 * f; if (p >= 0 && p <= 2 * a0 && (!pn || Math.abs(p - a0) < Math.abs(pn.p - a0))) pn = { fg: f, p, saf: 0 }; }
      // v3.23: the score needs a touchdown the box score does not have: it came on a return (kickoff, punt or a
      // fumble run back), so every player's line stays the run's own. (It used to turn a long gain into a touchdown.)
      if (!pn) { if ((tdl.length + ret + 1) * 6 <= pts) ret++; else break; }
    }
    if (!pn) { const a0 = tdl.length + ret, R0 = pts - 6 * a0, f = Math.floor(R0 / 3); pn = { fg: Math.max(0, f - (R0 % 3 === 1 && f > 0 ? 1 : 0)), p: 0 }; pn.saf = R0 - 3 * pn.fg; }
    const a = tdl.length + ret; pn.pat = Array.from({ length: a }, (_, k) => pn.p >= a ? (k < pn.p - a ? 2 : 1) : (k < pn.p ? 1 : 0));
    pn.ret = ret; pn.box = tdl.length;
    return pn;
  });
  // drives. Each starts from a real starting spot and runs its natural course: the call on every down (run, pass,
  // incompletion) follows how often real teams made it on that down and distance, the gain is a draw from what is left
  // of that player's own plays (so big ones turn up as often as they should), a stall ends on fourth down, and a
  // scoring drive keeps going until it is in range. The one steer is on third down, toward moving the chains on a
  // scoring drive and away from it on a stall that is already deep, so the run's score still comes out exact.
  const drives = [[], []], go4 = (los, tg) => LB ? LB.go4[los < 40 ? 0 : los < 60 ? 1 : los < 70 ? 2 : 3][tb(tg)] : .1;
  const downs = (dr, start) => { let dn = 1, tg = Math.min(10, 100 - start), los = start, fdl = los + tg; const st = [];
    dr.pl.forEach(p => { st.push({ dn, tg, los, fdl }); if (p.k === 'inc') dn++; else if (los + p.y >= fdl) { dn = 1; los += p.y; tg = Math.min(10, 100 - los); fdl = los + tg; return; } else { dn++; tg = fdl - los - p.y; }
      los += p.y; if (dn > 4) { dn = 1; tg = Math.min(10, 100 - los); fdl = los + tg; } });
    return { st, dn, tg, los }; };
  for (const j of [0, 1]) {
    const t = T[j], tdp = smShuffle(R, t.plays.filter(p => p.td)), a = tdp.length, fg = plan[j].fg;
    const nD = Math.max(a + fg + 3, 10 + Math.floor(R() * 2)), kinds = smShuffle(R, [...Array(a).fill('td'), ...Array(fg).fill('fg'), ...Array(nD - a - fg).fill('punt')]);
    const pool = t.plays.filter(p => !p.td), total = pool.length + t.incs.length; let ti = 0;
    // snaps per drive: real-looking lengths (three-and-outs are common, scoring drives run longer), scaled so the
    // team's snaps in the run are all used
    const nb = kinds.map(kd => kd === 'punt' ? 3 + Math.floor(R() * R() * 7) : kd === 'fg' ? 5 + Math.floor(R() * 7) : 4 + Math.floor(R() * 8));
    { const want = total - a; let sb = nb.reduce((x, y) => x + y, 0); const f = want / Math.max(1, sb); for (let i = 0; i < nb.length; i++) nb[i] = Math.max(kinds[i] === 'td' ? 0 : 1, Math.round(nb[i] * f));
      sb = nb.reduce((x, y) => x + y, 0); for (let it = 0; sb !== want && it < 999; it++) { const i = Math.floor(R() * nb.length); if (sb < want) { nb[i]++; sb++; } else if (nb[i] > (kinds[i] === 'punt' ? 3 : 1)) { nb[i]--; sb--; } } }
    const drive = (kd, d) => {
      const out = [], s0 = LB ? pick(LB.start_q) : 25, budget = d < nb.length ? nb[d] : 99; let pos = s0, tg = Math.min(10, 100 - s0), fdl = pos + tg, dn = 1, end = null;
      const tdY = kd === 'td' ? tdp[ti].y : 0, over = Math.min(10, s0 - 1);
      const ok = y => pos + y >= 1 && (kd === 'td' ? pos + y <= 99 : pos + y <= 97);
      const take = (k, want) => { let c = pool.filter(p => p.k === k && ok(p.y)).sort((x, y) => x.y - y.y); if (!c.length) return null;
        if (want) { const f = c.filter(p => want === 'conv' ? p.y >= tg : p.y < tg); if (f.length) c = f; }
        // scoring drives are where the big plays happen, stalls are made of the short ones (as in real games)
        const p = c[Math.min(c.length - 1, Math.floor(Math.pow(R(), kd === 'td' ? .6 : kd === 'fg' ? .8 : 1.4) * c.length))]; pool.splice(pool.indexOf(p), 1); return p; };
      for (let n = 0; n < budget + 9; n++) {
        if (n >= budget && (kd === 'td' || (kd === 'punt' && dn === 4) || n >= budget + (kd === 'fg' ? 8 : 5))) break;      // out of snaps: a stall runs on to fourth down, a field goal drive into range
        if (dn === 4 && (kd === 'punt' || (kd === 'fg' && pos >= 58)) && (kd === 'fg' || n >= budget || R() > go4(pos, tg))) break;      // kick
        const left = budget - n;      // snaps this drive still has: a stall should reach fourth down as they run out
        let want = null;
        if (kd === 'punt' || kd === 'fg') want = left <= 4 - dn ? 'fail' : dn >= 3 ? 'conv' : null;
        else if (dn >= 3) want = 'conv';
        if (kd === 'fg' && pos < 58 && dn >= 3) want = 'conv';
        const st = stOf(dn, tg), rs = runShare(st), haveR = pool.some(p => p.k === 'run' && ok(p.y)), haveC = pool.some(p => p.k === 'pass' && ok(p.y)), incLeft = t.incs.length;
        const rate = t.nInc ? (incLeft / t.nInc) / Math.max(.05, (pool.length + incLeft) / Math.max(1, total)) : 0;
        let w = [haveR ? rs : 0, haveC ? (1 - rs) * (1 - incShare(st)) : 0, incLeft && want !== 'conv' ? (1 - rs) * incShare(st) * Math.min(3, rate) * (want === 'fail' ? 2 : 1) : 0];
        if (w[0] + w[1] + w[2] <= 0) { if (incLeft) w = [0, 0, 1]; else break; }
        const c = smPickW(R, w); const p = c === 2 ? t.incs.pop() : take(c === 0 ? 'run' : 'pass', want); if (!p) break;
        out.push(p);
        if (p.k === 'inc') dn++; else if (pos + p.y >= fdl) { dn = 1; pos += p.y; tg = Math.min(10, 100 - pos); fdl = pos + tg; } else { dn++; tg = fdl - pos - p.y; pos += p.y; }
        if (dn > 4) { if (kd === 'punt') { end = 'downs'; break; } dn = 1; tg = Math.min(10, 100 - pos); fdl = pos + tg; }
      }
      if (kd === 'punt' && !end && dn === 4) end = pos >= 65 && R() < .45 ? 'miss' : 'punt';
      const dr = { j, kind: kd, pl: out, end, s: s0 };
      if (kd === 'td') { dr.pl.push(tdp[ti]); dr.pat = plan[j].pat[ti]; ti++; dr.s = 100 - dr.pl.reduce((x, p) => x + p.y, 0); }
      drives[j].push(dr);
    };
    kinds.forEach((kd, d) => drive(kd, d));
    for (let x = 0; x < 6 && pool.length; x++) drive('punt', kinds.length);      // snaps left over: the game had a few more possessions
    while (ti < a) { drives[j].push({ j, kind: 'td', pl: [tdp[ti]], pat: plan[j].pat[ti], s: 100 - tdp[ti].y }); ti++; }      // only if the plays ran out
    if (pool.length) { const dr = drives[j].filter(d => d.kind === 'punt').slice(-1)[0]; dr.pl.unshift(...pool.splice(0)); dr.end = 'to'; }
    drives[j] = drives[j].filter(d => d.kind !== 'punt' || d.pl.length);      // a possession with no snaps left for it never happened
    for (let k = 0; k < plan[j].ret; k++) {      // return touchdowns: a returner on the roster (the backs and receivers return kicks)
      const P = T[j].P, b = smp.b[j], who = P.map((p, i) => i).filter(i => i !== T[j].qb).sort((x, y) => ((b.rec[y] || 0) + (b.rush_att[y] || 0) * .5) - ((b.rec[x] || 0) + (b.rush_att[x] || 0) * .5)).slice(0, 4);
      const how = R() < .4 ? 'kick' : R() < .58 ? 'punt' : 'fum', at = 1 + Math.floor(R() * Math.max(1, drives[j].length - 1));
      drives[j].splice(at, 0, { j, kind: 'rtd', pl: [], how, i: who.length ? who[Math.floor(R() * who.length)] : 0, pat: plan[j].pat[plan[j].box + k], s: 0,
                                yds: how === 'kick' ? 90 + Math.floor(R() * 11) : how === 'punt' ? 55 + Math.floor(R() * 30) : 8 + Math.floor(R() * 40) }); }
    const span = d => { let x = 0, mx = 0, mn = 0; d.pl.forEach(p => { x += p.y; mx = Math.max(mx, x); mn = Math.min(mn, x); }); return { x, mx, mn }; };
    for (const d of drives[j]) if (d.kind === 'td') {      // a touchdown drive longer than the field hands its biggest gain to a stall it fits in
      for (let k = 0; k < 6 && d.s < 1; k++) { const pre = d.pl.slice(0, -1); if (!pre.length) break; const mv = pre.reduce((m, p) => p.y > m.y ? p : m, pre[0]);
        const to = drives[j].find(o => o.kind === 'punt' && o.s + span(o).mx + mv.y <= 97); if (!to) break;
        d.pl.splice(d.pl.indexOf(mv), 1); to.pl.unshift(mv); d.s += mv.y; } }
    for (const d of drives[j]) if (d.kind === 'fg') { const z = span(d), fin = d.s + z.x;      // a field goal drive short of range started further up the field
      if (fin < 60) d.s = Math.max(1 - z.mn, Math.min(d.s + (60 + Math.floor(R() * 15) - fin), 97 - z.mx)); }
    for (let x = plan[j].saf; x > 0; x -= 2) drives[j].push({ j, kind: 'saf', pl: [], extra: Math.min(2, x) });
  }
  // incompletions left over: first to stalls that are short of fourth down, then where they cost nothing (early in a
  // series that is moved anyway). A stall still short of fourth down ends in a turnover
  for (const j of [0, 1]) { const t = T[j];
    for (const dr of smShuffle(R, drives[j].filter(d => d.kind === 'punt' && !d.end))) { const X = downs(dr, dr.s), need = 4 - X.dn;
      if (need > 0 && need <= t.incs.length) { for (let k = 0; k < need; k++) dr.pl.push(t.incs.pop()); dr.end = 'punt'; } }
    while (t.incs.length) { const cands = [];
      drives[j].forEach(dr => { if (dr.kind === 'saf' || dr.kind === 'rtd' || !dr.pl.length) return; const X = downs(dr, dr.s);
        dr.pl.forEach((p, k) => { const x = X.st[k]; if (x.dn <= 2 && (p.td || (p.k !== 'inc' && x.los + p.y >= x.fdl))) cands.push([dr, k]); }); });
      if (!cands.length) { const dr = drives[j].filter(d => d.kind === 'punt').slice(-1)[0]; if (!dr) break; dr.pl.push(...t.incs.splice(0)); dr.end = 'to'; break; }
      const [dr, k] = pick(cands); dr.pl.splice(k, 0, t.incs.pop()); }
    for (const dr of drives[j]) if (dr.kind === 'punt' && !dr.end) dr.end = dr.pl.length && downs(dr, dr.s).dn < 4 ? 'to' : 'punt';
  }
  for (const j of [0, 1]) for (const d of drives[j]) if (d.kind !== 'td' && d.kind !== 'saf' && d.kind !== 'rtd') {      // last check: every snap on the field
    let x = 0, mx = 0, mn = 0; d.pl.forEach(p => { x += p.y; mx = Math.max(mx, x); mn = Math.min(mn, x); }); d.s = Math.max(1 - mn, Math.min(d.s, 98 - mx)); }
  for (const j of [0, 1]) for (const d of drives[j]) if (d.kind === 'td') { const pre = d.pl.slice(0, -1); let x = d.s, bad = false;
    pre.forEach(p => { x += p.y; if (x > 99 || x < 1) bad = true; });
    if (bad) d.pl = [...pre.filter(p => p.y < 0), ...pre.filter(p => p.y >= 0), d.pl[d.pl.length - 1]]; }      // a loss goes early so the drive never runs past the goal line
  // alternate possessions, away team receives first
  const order = [], nn = Math.max(drives[0].length, drives[1].length);
  for (let d = 0; d < nn; d++) { if (drives[0][d]) order.push(drives[0][d]); if (drives[1][d]) order.push(drives[1][d]); }
  const total = order.reduce((s, d) => s + d.pl.length + 1, 0); let clock = 0;
  const ev = [], dirOf = (p, y) => { if (!LB) return ''; if (p.k === 'run') { const w = LB.run_dir.w[y <= 0 ? 0 : y <= 3 ? 1 : y <= 9 ? 2 : y <= 19 ? 3 : 4]; return LB.run_dir.labels[smPickW(R, w)]; }
    const w = p.k === 'inc' ? LB.pass_dir.inc : LB.pass_dir.w[y <= 4 ? 0 : y <= 9 ? 1 : y <= 19 ? 2 : 3]; return LB.pass_dir.labels[smPickW(R, w)]; };
  const done = [0, 0], gone = [false, false];
  // v3.23: the opening kickoff (the home side kicks, the away side receives first), a kickoff after every score and to
  // start the second half, and punts that come down and are returned to where the next drive starts
  let kick = true, half = false;
  const nextOf = k => { for (let x = k + 1; x < order.length; x++) if (order[x].kind !== 'saf') return order[x]; return null; };
  order.forEach((d, oi) => {
    if (d.kind === 'saf') { ev.push({ k: 'saf', j: d.j, pts: d.extra, t: clock }); kick = true; return; }
    if (!half && clock >= 30) { half = true; ev.push({ k: 'half', j: d.j, t: clock }); kick = true; }
    if (d.kind === 'rtd') {      // a return touchdown: a kickoff or punt run all the way back, or a fumble scooped and scored
      const how = d.how === 'fum' ? 'fum' : kick ? 'kick' : 'punt';
      ev.push({ k: 'rtd', j: d.j, how, i: d.i, yds: how === 'kick' ? Math.max(d.yds, 90) : how === 'punt' ? Math.min(d.yds, 85) : d.yds, t: clock += 60 / total, pts: 6 });
      ev.push({ k: 'pat', j: d.j, pts: d.pat, t: clock }); kick = true; return; }
    const s0 = d.s;
    if (kick) { ev.push({ k: 'kick', j: 1 - d.j, to: s0, tb: s0 === 25 || s0 === 30 || s0 === 35, t: clock }); kick = false; }
    const D = downs(d, s0); ev.push({ k: 'start', j: d.j, los: s0, t: clock, dn: 1, tg: Math.min(10, 100 - s0) });
    d.pl.forEach((p, i) => { const x = D.st[i], lastP = i === d.pl.length - 1, td = d.kind === 'td' && lastP, dir = dirOf(p, p.y);
      const deep = /deep/.test(dir), side = /left/.test(dir) ? -1 : /right/.test(dir) ? 1 : 0;
      const e = Object.assign({}, p, { los: x.los, dn: x.dn, tg: x.tg, fdl: x.fdl, t: clock += 60 / total, td, pts: td ? 6 : 0, dir, side });
      if (p.k === 'inc') e.ay = deep ? 18 + Math.floor(R() * 20) : 3 + Math.floor(R() * 10);
      if (x.dn === 4 && !td) { e.go = true; if (!lastP && (p.k === 'inc' || x.los + p.y < x.fdl)) e.pen = true; }      // went for it; a miss that kept the ball was a flag on the defense
      if (lastP && !td && d.end === 'to') { if (p.k === 'inc') e.int = true; else e.fum = true; }
      if (lastP && !td && d.end === 'downs') e.downs = true;
      if (p.k === 'pass' || p.k === 'inc') { const tj = T[d.j]; if (gone[d.j]) e.q = -1; else if (p.k === 'pass' && ++done[d.j] >= tj.cmpQ && tj.exit) { gone[d.j] = true; e.exitAfter = true; } }
      ev.push(e);
      if (e.exitAfter) ev.push({ k: 'note', j: d.j, t: clock, s: 'out', i: T[d.j].qb, los: Math.min(99, x.los + p.y) }); });
    const fin = D.los;
    if (d.kind === 'td') { ev.push({ k: 'pat', j: d.j, pts: d.pat, t: clock }); kick = true; }
    else if (d.kind === 'fg') { ev.push({ k: 'fg', j: d.j, los: Math.min(fin, 83), pts: 3, t: clock += 60 / total, dn: D.dn, tg: D.tg }); kick = true; }
    else if (d.end === 'miss') ev.push({ k: 'fgx', j: d.j, los: Math.min(fin, 83), t: clock += 60 / total, dn: D.dn, tg: D.tg });
    else if (d.end === 'to' || d.end === 'downs') { /* the ball goes over where it stopped */ }
    else { const nx = nextOf(oi), to = nx && nx.j !== d.j && nx.kind !== 'rtd' ? nx.s : null;      // the receiving side's next drive starts where the return ends
      const land = to == null ? Math.min(95, fin + 42) : Math.min(99, Math.max(fin + 25, 100 - to + Math.floor(R() * 11)));
      ev.push({ k: 'punt', j: d.j, los: fin, land, to, t: clock += 60 / total, dn: D.dn, tg: D.tg }); }
  });
  return { ev, qbOf: T.map(t => t.qb), final: smp.sc };
}

class Arena {
  constructor(lg, g, ri) {
    this.lg = lg; this.g = g; this.speed = S.sm.speed; this.floor = $('#smFloor'); this.live = $('#smLive'); this.stage = $('#smStage');
    this.cx = this.live.getContext('2d'); this.toks = new Map(); this.fx = []; this.ball = { x: 47, y: 25, z: 3, vx: 0, vy: 0 }; this.playing = false; this.vis = true; this.dead = false;
    this.sprites = new Map();
    this.ro = new ResizeObserver(() => this.size()); this.ro.observe(this.stage);
    this.auto = !RM();       // v3.23: starts by itself the first time it comes into view (it used to need to be on screen at load)
    this.io = new IntersectionObserver(es => { this.vis = es[0].isIntersecting; if (this.vis) this.kick();
      if (this.vis && this.auto && !this.touched) { this.auto = false; setTimeout(() => { if (!this.dead && this.vis && !this.touched && !this.playing) this.play(); }, 450); } }); this.io.observe(this.stage);
    this.onVis = () => { if (!document.hidden) this.kick(); }; document.addEventListener('visibilitychange', this.onVis);
    this.load(ri, false);
    this.size();
    this.touched = false;      // starts by itself (see the observer above) only if nobody has touched it
  }
  destroy() { this.dead = true; this.playing = false; cancelAnimationFrame(this.raf); this.ro.disconnect(); this.io.disconnect(); document.removeEventListener('visibilitychange', this.onVis); }
  load(ri, autoplay) {
    this.ri = ri; const sm = this.g.samples[ri]; this.R = smRng(0x5eed + ri * 7919 + this.g.id.length * 31);
    this.sc = this.lg === 'NBA' ? smNbaScript(this.g, sm, this.R) : smNflScript(this.g, sm, this.R);
    this.dur = this.sc.ev.map(e => this.evDur(e)); this.tot = this.dur.reduce((a, b) => a + b, 0);
    this.seek(0, true); this.paintBox(true);
    if (autoplay && !RM()) this.play();
  }
  evDur(e) {      // milliseconds at 1x
    if (this.lg === 'NBA') return e.k === 'tip' ? 2000 : e.k === 'qtr' ? 1100 : e.k === 'to' ? 900 : e.k === 'ft' ? 1500 : e.k === 'miss' ? 1700 : e.a != null ? 2200 : 1800;
    return { start: 700, run: 1500, pass: 1900, inc: 1500, pat: 900, fg: 1700, fgx: 1700, punt: 2300, saf: 1200, note: 1100, kick: 2400, rtd: 3000, half: 1200 }[e.k] || 1000;
  }
  frac() { return this.tot ? this.t / this.tot : 0; }
  // ---- playback
  toggle() { this.touched = true; this.playing ? this.pause() : this.play(); }
  play() { if (this.i >= this.sc.ev.length) this.seek(0); this.playing = true; this.btn(); this.kick(); }
  pause() { this.playing = false; this.btn(); }
  btn() { const b = $('#smPlay'); if (b) { b.classList.toggle('on', this.playing); b.setAttribute('aria-label', this.playing ? 'Pause' : 'Play'); } }
  kick() { if (this.dead || this.raf || !this.vis || document.hidden) return; this.last = performance.now(); this.raf = requestAnimationFrame(n => this.frame(n)); }
  seek(f, quiet) {      // jump: the box and score are replayed instantly up to that point, the players snap to place
    const target = f * this.tot; this.t = 0; this.i = 0; this.u = 0; this.box = this.emptyBox(); this.score = [0, 0]; this.log = [];
    while (this.i < this.sc.ev.length && this.t + this.dur[this.i] <= target) { this.apply(this.sc.ev[this.i], true); this.t += this.dur[this.i]; this.i++; }
    this.u = 0; this.snap = true; this.fx = [];
    if (!quiet) { this.paintBox(true); }
    this.paintScore(true); this.paintClock(); this.paintTick(true); this.prog();
    if (this.i >= this.sc.ev.length) { this.playing = false; this.btn(); this.stampFinal(); }
    this.kick();
  }
  emptyBox() { return this.g.teams.map(T => T.players.map(() => this.lg === 'NBA' ? { pts: 0, reb: 0, ast: 0, fg3: 0 } : { cmp: 0, att: 0, pyd: 0, car: 0, ryd: 0, rec: 0, cyd: 0, td: 0 })); }
  apply(e, quiet) {      // the box score effect of a play, at the moment it lands
    const B = this.box, nm = (j, i) => smLast(this.g.teams[j].players[i].name), T = j => j ? this.g.home : this.g.away;
    let line = '';
    if (this.lg === 'NBA') {
      if (e.k === '2' || e.k === '3') { B[e.j][e.i].pts += e.pts; if (e.k === '3') B[e.j][e.i].fg3++; if (e.a != null) B[e.j][e.a].ast++; this.score[e.j] += e.pts;
        line = `${nm(e.j, e.i)} ${e.k === '3' ? 'three' : ['layup', 'jumper', 'dunk', 'floater', 'hook shot'][Math.floor(e.t * 7) % 5]}${e.a != null ? `, ${nm(e.j, e.a)} with the assist` : ''}`; }
      else if (e.k === 'ft') { B[e.j][e.i].pts += e.pts; this.score[e.j] += e.pts; line = `${nm(e.j, e.i)} makes ${e.pts === 2 ? 'both free throws' : 'a free throw'}`; }
      else if (e.k === 'miss') { B[e.rj][e.ri].reb++; line = `${nm(e.j, e.i)} misses${e.three ? ' a three' : ''}, ${nm(e.rj, e.ri)} ${e.off ? 'grabs the offensive board' : 'rebounds'}`; }
      else if (e.k === 'to') line = `Turnover, ${T(e.j)}`;
      else if (e.k === 'tip') line = `Tip-off: ${smLast(this.sc.teams[0][e.c[0]].name)} and ${smLast(this.sc.teams[1][e.c[1]].name)} go up, ${T(e.j)} win it`;
      else if (e.k === 'qtr') line = `Start of the ${['', '1st', '2nd', '3rd', '4th'][e.q]} quarter, ${T(e.j)} ball`;
    } else {
      const q = e.q != null ? e.q : this.sc.qbOf[e.j], QB = q >= 0 ? nm(e.j, q) : 'The backup', QBs = q >= 0;
      const go = e.go ? 'On fourth down, ' : '', flag = e.pen ? '; flag on the defense, first down' : '';
      const run = d => !d ? 'runs' : d === 'up the middle' ? 'up the middle' : /end/.test(d) ? 'around the ' + d : 'off ' + d;
      const lc = x => go ? x.charAt(0).toLowerCase() + x.slice(1) : x;
      if (e.k === 'run') { B[e.j][e.i].car++; B[e.j][e.i].ryd += e.y; if (e.td) { B[e.j][e.i].td++; this.score[e.j] += 6; }
        line = `${go}${lc(nm(e.j, e.i))} ${run(e.dir)} for ${e.y}${e.td ? ', TOUCHDOWN' : ''}${e.fum ? `, fumbles, ${T(1 - e.j)} recover` : ''}${flag}`; }
      else if (e.k === 'pass') { if (QBs) { B[e.j][q].att++; B[e.j][q].cmp++; B[e.j][q].pyd += e.y; } B[e.j][e.i].rec++; B[e.j][e.i].cyd += e.y; if (e.td) { B[e.j][e.i].td++; this.score[e.j] += 6; }
        line = `${go}${lc(QB)}${e.dir ? ' ' + e.dir : ''} to ${nm(e.j, e.i)} for ${e.y}${e.td ? ', TOUCHDOWN' : ''}${e.fum ? `, fumbles, ${T(1 - e.j)} recover` : ''}${flag}`; }
      else if (e.k === 'inc') { if (QBs) B[e.j][q].att++; line = e.int ? `${go}${lc(QB)} intercepted, intended for ${nm(e.j, e.i)}` : `${go}${lc(QB)}${e.dir ? ' ' + e.dir : ''} incomplete for ${nm(e.j, e.i)}${e.downs ? ', turnover on downs' : ''}${flag}`; }
      else if (e.k === 'pat') { this.score[e.j] += e.pts; line = e.pts === 2 ? 'Two-point try is good' : e.pts ? 'Extra point is good' : 'Extra point is no good'; }
      else if (e.k === 'fg') { this.score[e.j] += 3; line = `Field goal is good from ${100 - e.los + 17}, ${T(e.j)}`; }
      else if (e.k === 'fgx') line = `Field goal from ${100 - e.los + 17} is no good`;
      else if (e.k === 'punt') line = `${T(e.j)} punts on 4th and ${e.tg}${e.to != null ? `, returned to the ${e.to <= 50 ? e.to : 'opp ' + (100 - e.to)}` : ''}`;
      else if (e.k === 'kick') line = `${T(e.j)} kicks off${e.tb ? ', touchback' : `, returned to the ${e.to <= 50 ? e.to : 'opp ' + (100 - e.to)}`}`;
      else if (e.k === 'half') line = 'Halftime';
      else if (e.k === 'rtd') { this.score[e.j] += 6; const who = this.g.teams[e.j].players[e.i] ? nm(e.j, e.i) : T(e.j);
        line = e.how === 'kick' ? `${who} takes the kickoff back ${e.yds} yards, TOUCHDOWN` : e.how === 'punt' ? `${who} returns the punt ${e.yds} yards, TOUCHDOWN` : `Fumble! ${T(e.j)} scoop it up and score from ${e.yds} yards out`; }
      else if (e.k === 'saf') { this.score[e.j] += e.pts; line = `Safety, ${T(e.j)}`; }
      else if (e.k === 'note') line = `${nm(e.j, e.i)} is out, the backup takes over`;
      else if (e.k === 'start') line = `${T(e.j)} ball at the ${e.los <= 50 ? e.los : 'opp ' + (100 - e.los)}`;
      if (e.downs && e.k !== 'inc') line += ', turnover on downs';
    }
    if (line) this.log.push({ t: e.t, q: this.clockOf(e.t), s: line, j: e.j, big: (this.lg === 'NBA' && (e.k === '3')) || e.td || e.k === 'fg' || e.k === 'rtd' });
    if (!quiet) { this.paintScore(false, e.j); this.paintBox(false, e); this.paintTick(false); }
  }
  clockOf(t) { const L = this.lg === 'NBA' ? 12 : 15, q = Math.min(3, Math.floor(t / L)), rem = Math.max(0, L - (t - q * L)), m = Math.floor(rem), s = Math.floor((rem - m) * 60); return { q: q + 1, c: `${m}:${String(s).padStart(2, '0')}` }; }
  // ---- DOM: scoreboard, ticker, box (only what changed is touched)
  paintScore(all, j) { for (const k of [0, 1]) { const el = $(k ? '#smH' : '#smA'); if (!el) continue; if (el.textContent !== String(this.score[k])) { el.textContent = this.score[k]; if (!all && k === j && !RM()) el.animate([{ transform: 'translateY(-3px) scale(1.12)', color: 'var(--led-good)' }, { transform: 'none' }], { duration: 380, easing: 'cubic-bezier(.23,1,.32,1)' }); } } }
  gameT() {        // minutes played so far, between the last play and the next one
    const n = this.sc.ev.length; if (this.i >= n) return this.lg === 'NBA' ? 48 : 60; const e = this.sc.ev[this.i], p = this.i ? this.sc.ev[this.i - 1].t : 0;
    return p + (e.t - p) * Math.min(1, Math.max(0, this.u)); }
  liveMin(j, i) {  // a player's minutes so far: the shifts he has been on the floor for, scaled so the final adds up to his minutes in this run
    const full = this.g.samples[this.ri].b[j].min[i] || 0, L = this.sc.lineups[j], T = this.gameT(); let on = 0, tot = 0;
    for (let s = 0; s < L.length; s++) if (L[s].includes(i)) { tot += 3; on += Math.min(3, Math.max(0, T - 3 * s)); }
    return Math.round(Math.min(T, tot ? full * on / tot : full * T / 48)); }      // never more than the minutes gone in the game
  paintMins() { if (this.lg !== 'NBA') return; document.querySelectorAll('#smBox [data-m]').forEach(td => { const [j, i] = td.dataset.m.split('-').map(Number), v = String(this.liveMin(j, i)); if (td.textContent !== v) td.textContent = v; }); }
  paintClock() { this.paintMins(); const e = this.sc.ev[Math.min(this.i, this.sc.ev.length - 1)], c = this.clockOf(this.i >= this.sc.ev.length ? (this.lg === 'NBA' ? 48 : 60) : e ? e.t : 0), q = $('#smQ'), t = $('#smT');
    if (q) q.textContent = this.i >= this.sc.ev.length ? 'FINAL' : this.lg === 'NBA' ? 'Q' + c.q : ['1ST', '2ND', '3RD', '4TH'][c.q - 1]; if (t) t.textContent = this.i >= this.sc.ev.length ? '0:00' : c.c;
    const dn = $('#smDn'); if (dn) dn.textContent = this.lg === 'NFL' && e && e.los != null && this.i < this.sc.ev.length ? `${e.j ? this.g.home : this.g.away} ball · ${e.dn && e.k !== 'fg' && e.k !== 'fgx' && e.k !== 'punt' ? `${['1st', '2nd', '3rd', '4th'][e.dn - 1]} & ${e.fdl >= 100 ? 'goal' : e.tg} · ` : ''}${e.los < 50 ? 'own ' + e.los : e.los === 50 ? 'midfield' : 'opp ' + (100 - e.los)}` : ''; }
  paintTick(all) {
    const el = $('#smTick'); if (!el) return; const L = this.log.slice(-3);
    const html = L.map((x, k) => `<p class="${k === L.length - 1 ? 'new' : ''}${x.big ? ' big' : ''}" style="--tc:var(--${x.j ? 'h' : 'a'}1)"><span class="num">${this.lg === 'NBA' ? 'Q' + x.q.q : ['1ST', '2ND', '3RD', '4TH'][x.q.q - 1]} ${x.q.c}</span>${esc(x.s)}</p>`).join('');
    el.innerHTML = html;
    if (!all && !RM() && el.lastElementChild) el.lastElementChild.animate([{ transform: 'translateY(8px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 220, easing: 'cubic-bezier(.23,1,.32,1)' });
  }
  paintBox(all, e) {
    const host = $('#smBox'); if (!host) return; const lg = this.lg, g = this.g;
    if (all || !host.firstChild) {
      // NFL lines read like a broadcast box: passing C/ATT and yards, rushing CAR-YDS, receiving REC-YDS, touchdowns
      const cols = lg === 'NBA' ? [['pts', 'PTS'], ['reb', 'REB'], ['ast', 'AST'], ['fg3', '3PM']] : [['pa', 'C/ATT', b => b.att ? `${b.cmp}/${b.att}` : '·'], ['pyd', 'YDS', b => b.att ? b.pyd : '·'], ['ru', 'CAR/YDS', b => b.car ? `${b.car}/${b.ryd}` : '·'], ['re', 'REC/YDS', b => b.rec ? `${b.rec}/${b.cyd}` : '·'], ['td', 'TD', b => b.td || '·']];
      this.cols = cols.map(c => [c[0], c[1], c[2] || (b => b[c[0]])]);
      host.innerHTML = `<div class="two w">${[0, 1].map(j => `<div class="sm-bt${lg === 'NFL' ? ' nfl' : ''}" style="${tcol(lg, j ? g.home : g.away)}"><div class="sm-bh"><b>${esc(j ? g.home : g.away)}</b></div><table><thead><tr><th>Player</th>${lg === 'NBA' ? '<th>MIN</th>' : ''}${cols.map(c => `<th>${c[1]}</th>`).join('')}</tr></thead><tbody>${g.teams[j].players.map((p, i) => {
        const has = lg === 'NBA' || this.sc.ev.some(x => x.j === j && (x.i === i || x.q === i));
        if (!has) return '';
        const nm = String(p.name).split(' '), short = nm.length > 1 ? `${nm[0][0]}. ${nm.slice(1).join(' ')}` : p.name;
        return `<tr data-r="${j}-${i}"><th scope="row" title="${esc(p.name)}"><span class="fn">${esc(p.name)}</span><span class="sn">${esc(short)}</span></th>${lg === 'NBA' ? `<td class="num" data-m="${j}-${i}">${this.liveMin(j, i)}</td>` : ''}${this.cols.map(c => `<td class="num" data-c="${c[0]}">${c[2](this.box[j][i])}</td>`).join('')}</tr>`; }).join('')}</tbody></table></div>`).join('')}</div>`;
      return;
    }
    const touch = [];
    if (lg === 'NBA') { if (e.k === 'miss') touch.push([e.rj, e.ri]); else touch.push([e.j, e.i]); if (e.a != null) touch.push([e.j, e.a]); }
    else if (e.i != null) { touch.push([e.j, e.i]); const q = e.q != null ? e.q : this.sc.qbOf[e.j]; if ((e.k === 'pass' || e.k === 'inc') && q >= 0) touch.push([e.j, q]); }
    for (const [j, i] of touch) { const tr = host.querySelector(`tr[data-r="${j}-${i}"]`); if (!tr) continue;
      for (const c of this.cols) { const td = tr.querySelector(`[data-c="${c[0]}"]`); const v = String(c[2](this.box[j][i])); if (td && td.textContent !== v) { td.textContent = v; td.classList.remove('up'); void td.offsetWidth; td.classList.add('up'); } } }
  }
  prog() { const f = this.tot ? (this.t + (this.dur[this.i] || 0) * this.u) / this.tot : 0, el = $('#smPf'), p = $('#smProg'); if (el) el.style.transform = `scaleX(${f})`; if (p) p.setAttribute('aria-valuenow', Math.round(f * 100)); }
  stampFinal() { this.stamp(`FINAL ${this.score[0]}-${this.score[1]}`, 'fin'); }
  stamp(txt, cls) { const s = $('#smStamp'); if (!s) return; s.textContent = txt; s.className = 'sm-stamp ' + (cls || ''); if (RM()) { s.classList.add('show'); setTimeout(() => s.classList.remove('show'), 1600); return; }
    s.getAnimations().forEach(a => a.cancel());
    s.animate([{ transform: 'translate(-50%,-50%) scale(1.4) rotate(-9deg)', opacity: 0 }, { transform: 'translate(-50%,-50%) scale(.96) rotate(-6deg)', opacity: 1, offset: .22 }, { transform: 'translate(-50%,-50%) scale(1) rotate(-6deg)', opacity: 1, offset: .3 }, { transform: 'translate(-50%,-50%) scale(1) rotate(-6deg)', opacity: 1, offset: .82 }, { transform: 'translate(-50%,-50%) scale(1.02) rotate(-6deg)', opacity: 0 }],
      { duration: cls === 'fin' ? 2600 : 1500, easing: 'cubic-bezier(.23,1,.32,1)', fill: cls === 'fin' ? 'forwards' : 'none' }); }
  // ---- the camera: the floor is drawn in perspective on the canvas itself (a projective map from the court to a
  // trapezoid), so every line and number is rasterised at the screen's own resolution: no 3D-transformed layer to blur
  size() {
    const w = Math.round(this.stage.clientWidth); if (!w || w === this.w) return; this.w = w;
    const L = this.lg === 'NBA' ? 94 : 120, Wd = this.lg === 'NBA' ? 50 : 53.3; this.L = L; this.Wd = Wd;
    const narrow = w < 560, inB = w * .01, inT = w * (narrow ? .085 : .1), hf = Wd / L * w * (narrow ? .7 : .62), top = Math.max(26, hf * .14);
    this.h = Math.round(top + hf + 6); this.k = (w - 2 * inB) / L;
    this.H = smQuad([inT, top], [w - inT, top], [w - inB, top + hf], [inB, top + hf]);
    this.dpr = Math.min(window.devicePixelRatio || 1, 3);
    for (const c of [this.floor, this.live]) { c.width = Math.round(w * this.dpr); c.height = Math.round(this.h * this.dpr); c.style.width = w + 'px'; c.style.height = this.h + 'px'; }
    this.stage.style.setProperty('--sh', this.h + 'px');
    this.r = Math.max(this.lg === 'NBA' ? 8 : 5.6, (this.lg === 'NBA' ? 1.8 : 1.1) * this.k);
    this.sprites.clear(); this.drawFloor(); this.snap = true; this.draw(0);
  }
  P(x, y) { const H = this.H, u = x / this.L, v = y / this.Wd, z = H[6] * u + H[7] * v + 1; return [(H[0] * u + H[1] * v + H[2]) / z, (H[3] * u + H[4] * v + H[5]) / z]; }
  depth(y) { const a = this.P(0, y), b = this.P(this.L, y); return (b[0] - a[0]) / (this.k * this.L); }      // how big things are at that depth, 1 at the near edge
  loc(c, x, y) {        // a local drawing frame at (x, y): one unit is one court pixel at the near edge, foreshortened like the floor
    const d = this.dpr, p = this.P(x, y), a = this.P(x + 1, y), b = this.P(x, y + 1), k = this.k;
    c.setTransform(d * (a[0] - p[0]) / k, d * (a[1] - p[1]) / k, d * (b[0] - p[0]) / k, d * (b[1] - p[1]) / k, d * p[0], d * p[1]); }
  poly(c, pts) { c.beginPath(); pts.forEach(([x, y], i) => { const p = this.P(x, y); i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); }); }
  drawFloor() {
    const c = this.floor.getContext('2d'), d = this.dpr, W = this.w, g = this.g, lg = this.lg, L = this.L, Wd = this.Wd, k = this.k; c.setTransform(d, 0, 0, d, 0, 0); c.clearRect(0, 0, W, this.h);
    const C = t => (TC[lg][t] || ['#566559', '#e6eddb']), self = this;
    const rect = (x0, y0, x1, y1) => this.poly(c, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]);
    const line = (x0, y0, x1, y1) => { this.poly(c, [[x0, y0], [x1, y1]]); c.stroke(); };
    const arc = (cx, cy, r, a0, a1) => { const n = Math.max(12, Math.ceil(Math.abs(a1 - a0) * r * .9)), pts = []; for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); } this.poly(c, pts); c.stroke(); };
    const txt = (s, x, y, size, font, rot) => { c.save(); this.loc(c, x, y); if (rot) c.rotate(rot); c.font = `${size * k}px ${font}`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(s, 0, 0); c.restore(); c.setTransform(d, 0, 0, d, 0, 0); };
    const far = this.P(0, 0)[1], near = this.P(0, Wd)[1];
    // the apron under the floor, so the edge reads as a raised court
    c.save(); c.fillStyle = 'rgba(0,0,0,.45)'; c.filter = 'none'; this.poly(c, [[-1.2, -1], [L + 1.2, -1], [L + 1.2, Wd + 1.6], [-1.2, Wd + 1.6]]); c.fill(); c.restore();
    if (lg === 'NBA') {
      const gr = c.createLinearGradient(0, far, 0, near); gr.addColorStop(0, '#d9a467'); gr.addColorStop(1, '#e8bc84'); c.fillStyle = gr; rect(0, 0, L, Wd); c.fill();
      c.save(); rect(0, 0, L, Wd); c.clip(); c.strokeStyle = 'rgba(90,52,18,.16)'; c.lineWidth = 1;
      for (let y = 0; y <= Wd; y += 1.6) line(0, y, L, y);
      const R = smRng(9); for (let n = 0; n < 260; n++) { const y = Math.floor(R() * Wd / 1.6) * 1.6, x = R() * L; line(x, y, x, y + 1.6); }
      c.restore();
      for (const [x0, t] of [[0, g.away], [L, g.home]]) { const s = x0 ? -1 : 1; c.fillStyle = C(t)[0]; c.globalAlpha = .86; rect(x0, 17, x0 + s * 19, 33); c.fill(); c.globalAlpha = 1; }
      c.save(); c.globalAlpha = .55; c.fillStyle = C(g.home)[0]; const cc = []; for (let i = 0; i <= 48; i++) { const a = i / 48 * Math.PI * 2; cc.push([47 + 6 * Math.cos(a), 25 + 6 * Math.sin(a)]); } this.poly(c, cc); c.fill(); c.restore();
      c.strokeStyle = 'rgba(255,255,255,.95)'; c.lineCap = 'round'; c.lineJoin = 'round'; c.lineWidth = Math.max(1.3, .16 * k);
      rect(0, 0, L, Wd); c.stroke(); line(47, 0, 47, Wd); arc(47, 25, 6, 0, Math.PI * 2); arc(47, 25, 2, 0, Math.PI * 2);
      for (const [x0, s] of [[0, 1], [L, -1]]) {
        rect(x0, 17, x0 + s * 19, 33); c.stroke(); arc(x0 + s * 19, 25, 6, s > 0 ? -Math.PI / 2 : Math.PI / 2, s > 0 ? Math.PI / 2 : Math.PI * 1.5);
        line(x0, 3, x0 + s * 14, 3); line(x0, 47, x0 + s * 14, 47); const bx = x0 + s * 5.25, a = Math.asin(22 / 23.75);
        if (s > 0) arc(bx, 25, 23.75, -a, a); else arc(bx, 25, 23.75, Math.PI - a, Math.PI + a);
        arc(bx, 25, 4, s > 0 ? -Math.PI / 2 : Math.PI / 2, s > 0 ? Math.PI / 2 : Math.PI * 1.5);
        c.save(); c.strokeStyle = '#1b1b1b'; c.lineWidth = Math.max(2.2, .32 * k); line(x0 + s * 4, 22, x0 + s * 4, 28); c.strokeStyle = '#ff6a1a'; c.lineWidth = Math.max(1.6, .22 * k); arc(bx, 25, .75, 0, Math.PI * 2); c.restore();
      }
      c.fillStyle = 'rgba(255,255,255,.92)'; txt(g.home, 47, 25.2, 2.7, 'Ultra, Rockwell, Georgia, serif');
    } else {
      const gr = c.createLinearGradient(0, far, 0, near); gr.addColorStop(0, '#22773f'); gr.addColorStop(1, '#2d8b4d'); c.fillStyle = gr; rect(0, 0, L, Wd); c.fill();
      for (let x = 10; x < 110; x += 10) { c.fillStyle = (x / 10) % 2 ? 'rgba(255,255,255,.04)' : 'rgba(0,0,0,.045)'; rect(x, 0, x + 10, Wd); c.fill(); }
      for (const [x0, t] of [[0, g.away], [110, g.home]]) { const col = C(t); c.fillStyle = col[0]; rect(x0, 0, x0 + 10, Wd); c.fill();
        c.fillStyle = lum(col[0]) < .3 ? 'rgba(255,255,255,.92)' : 'rgba(0,0,0,.78)'; txt(t, x0 + 5, Wd / 2, 4.6, 'Ultra, Rockwell, Georgia, serif', x0 ? Math.PI / 2 : -Math.PI / 2); }
      c.strokeStyle = 'rgba(255,255,255,.92)'; c.lineCap = 'butt';
      for (let x = 10; x <= 110; x += 5) { c.lineWidth = Math.max(1.1, (x % 10 ? .2 : .3) * k); c.globalAlpha = x % 10 ? .6 : .95; line(x, 0, x, Wd); }
      c.lineWidth = Math.max(1, .18 * k); c.globalAlpha = .75;
      for (let x = 11; x < 110; x++) { if (x % 5 === 0) continue; for (const y of [.4, 23.6, 29.7, 52.9]) line(x, y - .5, x, y + .5); }
      c.globalAlpha = 1; rect(0, 0, L, Wd); c.lineWidth = Math.max(1.4, .3 * k); c.stroke();
      c.fillStyle = 'rgba(255,255,255,.88)';
      for (let x = 20; x <= 100; x += 10) { const n = x <= 60 ? x - 10 : 110 - x; txt(String(n), x, 9.5, 2.9, '"Sometype Mono", monospace'); txt(String(n), x, Wd - 9.5, 2.9, '"Sometype Mono", monospace', Math.PI); }
      c.strokeStyle = '#f2d24b'; c.lineWidth = Math.max(2, .45 * k); for (const x of [0, 120]) line(x, 23.6, x, 29.7);
    }
  }
  sprite(key, fill, ring, text, tn, r) {     // one token, drawn once at full resolution, then stamped each frame
    if (this.sprites.has(key)) return this.sprites.get(key);
    const d = this.dpr, pad = 3, s = Math.ceil((r + pad) * 2 * d), cv = document.createElement('canvas'); cv.width = cv.height = s; const c = cv.getContext('2d'); c.scale(d, d); const m = r + pad;
    c.fillStyle = fill; c.beginPath(); c.arc(m, m, r, 0, 7); c.fill(); c.lineWidth = Math.max(1.4, r * .2); c.strokeStyle = ring; c.beginPath(); c.arc(m, m, r - c.lineWidth / 2, 0, 7); c.stroke();
    if (text) { c.fillStyle = tn; c.textAlign = 'center'; c.textBaseline = 'middle'; c.font = `700 ${Math.round(r * (String(text).length > 1 ? 1.02 : 1.2))}px "Sometype Mono", monospace`; c.fillText(text, m, m + r * .06); }
    const o = { cv, m }; this.sprites.set(key, o); return o;
  }
  shadowSprite(r) { const key = 'sh' + r; if (this.sprites.has(key)) return this.sprites.get(key); const d = this.dpr, s = Math.ceil(r * 3 * d), cv = document.createElement('canvas'); cv.width = cv.height = s;
    const c = cv.getContext('2d'), gr = c.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2); gr.addColorStop(0, 'rgba(0,0,0,.42)'); gr.addColorStop(1, 'rgba(0,0,0,0)'); c.fillStyle = gr; c.fillRect(0, 0, s, s);
    const o = { cv, m: r * 1.5 }; this.sprites.set(key, o); return o; }
  // ---- the frame
  frame(now) {
    this.raf = 0; if (this.dead) return; if (!this.live.isConnected) { this.destroy(); return; }
    const dt = Math.min(.05, (now - this.last) / 1000); this.last = now;
    if (this.playing && this.i < this.sc.ev.length) {
      const step = dt * 1000 * this.speed * (RM() ? .6 : 1); let du = step / this.dur[this.i];
      this.u += du;
      while (this.u >= 1 && this.i < this.sc.ev.length) { this.u -= 1; const e = this.sc.ev[this.i]; if (!e.done) this.apply(e, false); this.t += this.dur[this.i]; this.i++; this.onEnd(e); if (this.i < this.sc.ev.length) this.u *= this.dur[this.i - 1] / this.dur[this.i]; }
      if (this.i >= this.sc.ev.length) { this.u = 0; this.playing = false; this.btn(); this.paintClock(); this.stampFinal(); }
      else if (Math.floor(now / 250) !== this.ck) { this.ck = Math.floor(now / 250); this.paintClock(); }
      this.prog();
    }
    this.draw(dt);
    const busy = this.playing || this.fx.length || this.moving;
    if (busy && this.vis && !document.hidden) this.raf = requestAnimationFrame(n => this.frame(n));
  }
  onEnd(e) {
    if (this.lg === 'NFL' && e.td) this.stamp('TOUCHDOWN', e.j ? 'h' : 'a');
    if (this.lg === 'NFL' && e.k === 'fg') this.stamp('IT IS GOOD', e.j ? 'h' : 'a');
  }
  draw(dt) {
    const c = this.cx, d = this.dpr, k = this.k; if (!k) return; c.setTransform(d, 0, 0, d, 0, 0); c.clearRect(0, 0, this.w, this.h);
    const e = this.sc.ev[Math.min(this.i, this.sc.ev.length - 1)], u = this.i >= this.sc.ev.length || RM() ? .999 : this.u;
    const pose = this.lg === 'NBA' ? this.nbaPose(e, u) : this.nflPose(e, u);
    const w = RM() || this.snap ? 1e4 : (this.lg === 'NBA' ? 6.5 : 7.5); this.snap = false; let moving = false;
    const seen = new Set();
    for (const p of pose.toks) { let o = this.toks.get(p.id); if (!o) { o = { x: p.x, y: p.y, vx: 0, vy: 0, a: 0 }; this.toks.set(p.id, o); }
      smSpring(o, p.x, p.y, Math.max(dt, w > 1e3 ? 1 : 0), w > 1e3 ? w : (p.w || w)); o.a = Math.min(1, o.a + dt * 5 + (w > 1e3 ? 1 : 0)); seen.add(p.id); o.p = p;
      if (Math.abs(o.vx) + Math.abs(o.vy) > .05) moving = true; }
    for (const [id, o] of this.toks) if (!seen.has(id)) { o.a -= dt * 5; if (o.a <= 0 || w > 1e3) this.toks.delete(id); else moving = true; }
    this.moving = moving;
    // lines on the field (NFL): scrimmage and the line to gain, under the players
    if (pose.lines) for (const [x, col] of pose.lines) { c.strokeStyle = col; c.lineWidth = Math.max(2, .32 * k); c.globalAlpha = .92; this.poly(c, [[x, 0], [x, this.Wd]]); c.stroke(); c.globalAlpha = 1; }
    for (const f of this.fx) if (f.k === 'glow') { const q = Math.min(1, f.t / f.d); c.globalAlpha = Math.sin(q * Math.PI) * .5; c.fillStyle = f.col; this.poly(c, [[f.x, 0], [f.x + f.w, 0], [f.x + f.w, this.Wd], [f.x, this.Wd]]); c.fill(); c.globalAlpha = 1; }
    // shadows, then players far to near, so the nearer one overlaps
    const list = [...this.toks.values()].sort((a, b) => a.y - b.y), shS = this.shadowSprite(Math.round(this.r));
    for (const o of list) { const s = this.depth(o.y), p = this.P(o.x, o.y), m = shS.m * s; c.globalAlpha = .5 * o.a; c.drawImage(shS.cv, p[0] - m, p[1] - m * .5, m * 2, m * 1.1); }
    const now = performance.now();
    for (const o of list) { const pp = o.p, s = this.depth(o.y), base = pp.small ? this.r * .62 : this.r, sp = this.sprite(pp.key, pp.fill, pp.ring, pp.small ? '' : pp.text, pp.tn, Math.round(base * 2) / 2), q = this.P(o.x, o.y), r = base * s, lift = r * .9;
      c.globalAlpha = o.a * (pp.dim ? .55 : 1);
      if (pp.hot && !RM()) { c.save(); c.globalAlpha = o.a * .95; c.strokeStyle = 'rgba(255,214,90,.95)'; c.lineWidth = 2; c.beginPath(); c.arc(q[0], q[1] - lift, r + 3.4 + Math.sin(now / 160) * .8, 0, 7); c.stroke(); c.restore(); }
      const m = sp.m * s; c.drawImage(sp.cv, q[0] - m, q[1] - lift - m, m * 2, m * 2); }
    c.globalAlpha = 1;
    // the ball: its shadow on the floor, the ball lifted by its height
    const b = pose.ball; if (b) { const z = b.z || 0, s = this.depth(b.y), q = this.P(b.x, b.y), br = (this.lg === 'NBA' ? .8 : .62) * k * s * (1 + z / 45);
      c.globalAlpha = Math.max(.12, .45 - z / 60) * (b.a == null ? 1 : b.a); c.fillStyle = '#000'; c.beginPath(); c.ellipse(q[0], q[1], br * 1.1, br * .5, 0, 0, 7); c.fill(); c.globalAlpha = b.a == null ? 1 : b.a;
      const by = q[1] - z * k * s * .55 - (this.lg === 'NBA' ? 0 : 0);
      if (this.lg === 'NBA') { const R = Math.max(3.4, br); c.fillStyle = '#ef7d22'; c.beginPath(); c.arc(q[0], by, R, 0, 7); c.fill(); c.strokeStyle = 'rgba(60,25,5,.75)'; c.lineWidth = 1; c.beginPath(); c.arc(q[0], by, R, 0, 7); c.moveTo(q[0] - R, by); c.lineTo(q[0] + R, by); c.stroke(); }
      else { c.save(); c.translate(q[0], by); c.rotate(b.rot || 0); c.fillStyle = '#7a3f1c'; c.beginPath(); c.ellipse(0, 0, Math.max(4.2, br * 1.5), Math.max(2.7, br * .95), 0, 0, 7); c.fill(); c.strokeStyle = '#fff'; c.lineWidth = 1; c.beginPath(); c.moveTo(-br * .5, 0); c.lineTo(br * .5, 0); c.stroke(); c.restore(); }
      c.globalAlpha = 1; }
    // effects: the rim flash and the points that float up
    for (const f of this.fx) { f.t += dt; const qq = Math.min(1, f.t / f.d); if (f.k === 'glow') continue;
      const s = this.depth(f.y), p = this.P(f.x, f.y);
      if (f.k === 'ring') { const rr = (1.2 + smEaseOut(qq) * 3.4) * k * s, a = this.P(f.x, f.y + 1)[1] - p[1], b2 = this.P(f.x + 1, f.y)[0] - p[0]; c.globalAlpha = (1 - qq) * .9; c.strokeStyle = f.col; c.lineWidth = 2.2 * (1 - qq) + .6; c.beginPath(); c.ellipse(p[0], p[1] - 10 * k * s * .55, rr, rr * Math.abs(a / b2), 0, 0, 7); c.stroke(); }
      if (f.k === 'txt') { c.globalAlpha = qq < .7 ? 1 : 1 - (qq - .7) / .3; c.fillStyle = f.col; c.font = `${Math.max(13, 2.7 * k * s)}px Ultra, Rockwell, Georgia, serif`; c.textAlign = 'center'; c.strokeStyle = 'rgba(0,0,0,.55)'; c.lineWidth = 3; const yy = p[1] - smEaseOut(qq) * 3.2 * k * s - this.r * s * 2.2; c.strokeText(f.s, p[0], yy); c.fillText(f.s, p[0], yy); } }
    c.globalAlpha = 1; this.fx = this.fx.filter(f => f.t < f.d);
    for (const f of RM() ? [] : pose.fx || []) if (!this.fxSeen || !this.fxSeen.has(f.id)) { (this.fxSeen = this.fxSeen || new Set()).add(f.id); this.fx.push(Object.assign({ t: 0 }, f)); }
    if (this.fxSeen && this.fxSeen.size > 400) this.fxSeen.clear();
  }
  tokStyle(j, id, big) { const lg = this.lg, t = j ? this.g.home : this.g.away, col = TC[lg][t] || ['#566559', '#e6eddb'], p = IDX[lg].byId[id];
    const num = p && p.num != null && p.num !== '' ? String(p.num) : (p ? (p.pos || '').slice(0, 2) : '');
    return { key: `${j}|${num}|${big ? 1 : 0}|${this.r}`, fill: col[0], ring: col[1], tn: lum(col[0]) < .3 ? '#fff' : '#111', text: num }; }
  // ---- NBA poses: where everyone stands at a moment of a play
  // v3.23 special teams: kickoffs, punts that are returned, return touchdowns. j is the side that kicks (for a kickoff or a
  // punt) or the side that scores (a return touchdown). X maps yards from the kicking side's own goal line onto the field.
  nflKick(e, u) {
    const toks = [], fx = [], mid = 26.65, G = this.g;
    const ret = e.k === 'rtd', kj = ret ? 1 - e.j : e.j, rj = 1 - kj, X = y => kj ? 10 + y : 110 - y;
    const small = (jj, n, x, y) => { const s = this.tokStyle(jj, 'x' + n, false); s.small = true; s.key = jj + '|s|' + this.r; s.text = ''; return Object.assign(s, { id: `${jj}|st${n}`, x, y }); };
    const P = G.teams[rj].players, ri = ret ? e.i : P.map((p, i) => i).sort((a, b) => (((this.sc.qbOf || [])[rj] === a) - ((this.sc.qbOf || [])[rj] === b)))[1] ?? 0;
    const rs = P[ri] ? Object.assign(this.tokStyle(rj, P[ri].id, true), { id: `${rj}|${P[ri].id}` }) : small(rj, 9, 0, mid);
    if (e.k === 'half') {      // both sides off to the locker rooms: everyone drifts to the sideline
      for (let n = 0; n < 6; n++) { toks.push(small(0, n, 40 + n * 4 + u * 3, 4 - u * 2)); toks.push(small(1, n, 40 + n * 4 + u * 3, 49.3 + u * 2)); }
      return { toks, ball: { x: 60, y: mid, z: 0 }, fx, lines: [] };
    }
    const fum = ret && e.how === 'fum', punt = e.k === 'punt' || (ret && e.how === 'punt');
    let kx, land, end, cy = mid + (Math.sin((e.t || 0) * 7) * 9);
    if (fum) { const g0 = X(100 - e.yds); kx = g0; land = g0; end = X(100); }
    else if (punt) { const los = ret ? 100 - (e.yds + 10) : e.los; kx = X(los - 13); land = X(ret ? Math.min(99, los + 42) : e.land); end = ret ? X(-0.5) : X(100 - e.to); }
    else { kx = X(35); land = X(97 - ((e.t || 0) * 13 % 6)); end = ret ? X(-0.5) : X(100 - e.to); }
    const dirk = kj ? 1 : -1;
    // the cover team runs down, the return team sets up in front of the returner
    for (let n = 0; n < 6; n++) { const y0 = 6 + n * 8.2, q = smEaseIO(Math.min(1, u / .7)), tx = smLerp(kx, (land + end) / 2, q * .85);
      toks.push(small(kj, n, fum ? smLerp(land - dirk * 6, end - dirk * 4, smEaseIO(u)) : tx + Math.sin(n + u * 5) * .6, smLerp(y0, smLerp(y0, cy, .45), q))); }
    for (let n = 0; n < 5; n++) { const y0 = 9 + n * 9, base = smLerp(land, end, .25) - dirk * 3;
      toks.push(small(rj, n, fum ? smLerp(land, end, u * .6) - dirk * (3 + n) : base + Math.sin(n * 2 + u * 4) * .8, smLerp(y0, cy + (n - 2) * 3, Math.min(1, u * 1.2)))); }
    const catchAt = fum ? .12 : punt ? .52 : .5, run = Math.max(0, (u - catchAt) / (1 - catchAt)), rq = smEaseIO(Math.min(1, run / .92));
    rs.x = u < catchAt ? land : smLerp(land, end, rq); rs.y = u < catchAt ? cy : cy + Math.sin(rq * 3.2) * 4; rs.hot = u > catchAt;
    if (fum) { rs.x = smLerp(land, end, smEaseIO(Math.min(1, u / .9))); rs.y = cy; rs.hot = true; }
    toks.push(rs);
    let ball;
    if (fum) ball = { x: rs.x, y: rs.y, z: 1 };
    else if (u < catchAt) { const q = u / catchAt; ball = { x: smLerp(kx, land, smEaseOut(q)), y: smLerp(mid, cy, q), z: Math.sin(q * Math.PI) * (punt ? 19 : 22) + 1, rot: q * 14 }; }
    else ball = { x: rs.x, y: rs.y, z: 1 };
    if (ret && u > .86) fx.push({ id: `g${this.i}`, k: 'glow', x: end > 60 ? 110 : 0, w: 10, d: .9, col: (TC.NFL[e.j ? G.home : G.away] || ['#fff'])[1] });
    if (ret && u > .9) fx.push({ id: `y${this.i}`, k: 'txt', s: 'TD', x: rs.x, y: rs.y, d: .9, col: '#ffd65a' });
    return { toks, ball, fx, lines: [] };
  }
  nbaPose(e, u) {
    const sc = this.sc, slot = Math.min(sc.SL - 1, Math.floor((e ? e.t : 0) / 3)), off = e ? e.j : 0, toks = [], fx = [];
    const dir = j => j ? 1 : -1, bx = j => j ? 88.75 : 5.25, X = (j, x) => j ? x : 94 - x;
    const R = smRng((e ? Math.floor(e.t * 997) : 1) + 3);
    const spots = [[69, 25], [74, 8.5], [74, 41.5], [86.6, 3.6], [83, 31]], ins = [[84, 21], [83.5, 29], [80, 18]];
    const on = j => sc.lineups[j][slot].map(i => sc.teams[j][i]);
    // which spot each offensive player takes: the shooter goes where his shot comes from
    const offIdx = sc.lineups[off][slot].slice(), shooter = e && e.i != null ? e.i : offIdx[0];
    const need = (arr, i) => { if (i != null && !arr.includes(i)) arr[arr.length - 1] = i; };      // the man in the play is on the floor for it
    if (e) { need(offIdx, e.i); if (e.a != null && e.a !== e.i) { if (!offIdx.includes(e.a)) offIdx[offIdx.length - 2] = e.a; } if (e.k === 'miss' && e.off) { if (!offIdx.includes(e.ri)) offIdx[offIdx.length - 3] = e.ri; } }
    let pos = {}; const shotSpot = e && e.k === '3' ? spots[1 + Math.floor(R() * 4)] : e && (e.k === '2' || e.k === 'miss') ? (e.three ? spots[1 + Math.floor(R() * 4)] : ins[Math.floor(R() * 3)]) : null;
    const rest = spots.slice(); offIdx.forEach((i, n) => { pos[i] = rest[n % 5]; });
    if (shotSpot && pos[shooter]) { const had = pos[shooter]; const other = Object.keys(pos).find(k => pos[k] === shotSpot); if (other != null) pos[other] = had; pos[shooter] = shotSpot; }
    if (e && e.k === 'ft') { const lane = [[79.5, 19], [79.5, 31], [83, 19], [83, 31]]; let n = 0; offIdx.forEach(i => { pos[i] = i === shooter ? [75, 25] : lane[n++ % 4]; }); }
    const jit = i => [(R() - .5) * 2.4, (R() - .5) * 2.4];
    const oT = {}; offIdx.forEach(i => { const p = pos[i] || spots[0], jj = jit(i); oT[i] = [X(off, p[0] + jj[0]), p[1] + jj[1]]; });
    // a little life: everyone but the shooter drifts while the ball moves
    const sway = (i, a) => Math.sin(u * 5 + i * 1.7) * a;
    for (const i of offIdx) { const r = sc.teams[off][i], st = this.tokStyle(off, r.id, true); toks.push(Object.assign(st, { id: off + '|' + r.id, x: oT[i][0] + (i === shooter ? 0 : sway(i, .9)), y: oT[i][1] + (i === shooter ? 0 : sway(i + 3, .9)), hot: e && i === shooter && u > .3 && u < .95 && e.k !== 'to' })); }
    const def = 1 - off, dIdx = sc.lineups[def][slot].slice(); if (e && e.k === 'miss' && !e.off && !dIdx.includes(e.ri)) dIdx[4] = e.ri;
    dIdx.forEach((i, n) => { const man = oT[offIdx[n]] || [X(off, 70), 25], b = [bx(off), 25], r = sc.teams[def][i], st = this.tokStyle(def, r.id, true);
      toks.push(Object.assign(st, { id: def + '|' + r.id, x: man[0] + (b[0] - man[0]) * .24 + sway(i + 9, .5), y: man[1] + (b[1] - man[1]) * .24 })); });
    // the ball
    let ball = null; const rim = [bx(off) + dir(off) * -0.0, 25];
    if (!e) return { toks, ball: { x: 47, y: 25, z: 3 } };
    if (e.k === 'tip') {      // the centre circle: the two jumpers in the middle, everyone else around the ring on his own side
      toks.length = 0;
      for (const j of [0, 1]) { const ring = [[-7, -6.5], [-7, 6.5], [-9.5, 0], [-4, -9.5]], idx = sc.lineups[j][0].filter(i => i !== e.c[j]); let n = 0;
        for (const i of [e.c[j], ...idx]) { const r = sc.teams[j][i], st = this.tokStyle(j, r.id, true), side = j ? 1 : -1, jump = i === e.c[j];
          const p = jump ? [47 + side * 2.1, 25] : [47 + side * -ring[n][0], 25 + ring[n++][1]];
          toks.push(Object.assign(st, { id: j + '|' + r.id, x: p[0] + (jump ? 0 : Math.sin(u * 4 + n) * .25), y: p[1], hot: jump && u > .28 && u < .6 })); } }
      const win = e.j, mate = toks.find(t => t.id.startsWith(win + '|') && t.id !== win + '|' + sc.teams[win][e.c[win]].id), to = mate ? [mate.x, mate.y] : [47 + (win ? 6 : -6), 25];
      let ball;
      if (u < .42) { const q = smEaseOut(u / .42); ball = { x: 47, y: 25, z: 6 + q * 9 }; }
      else if (u < .5) ball = { x: 47, y: 25, z: 15 - (u - .42) * 8 };
      else { const q = smEaseIO(Math.min(1, (u - .5) / .4)); ball = { x: smLerp(47, to[0], q), y: smLerp(25, to[1], q), z: 14.4 - q * 11 + Math.sin(q * Math.PI) * 2 };
        if (u < .62) fx.push({ id: `tp${this.i}`, k: 'ring', x: 47, y: 25, d: .5, col: 'rgba(255,214,90,1)' }); }
      return { toks, ball };
    }
    if (e.k === 'qtr') { const hp0 = [X(off, 46 + u * 18), 25 + Math.sin(u * 3) * 2]; return { toks, ball: { x: hp0[0] + .9 * dir(off), y: hp0[1] + .4, z: 1.2 + Math.abs(Math.sin(u * 9)) * 2.4 } }; }
    const handler = e.a != null ? e.a : offIdx.find(i => i !== shooter) ?? shooter, hp = oT[handler] || oT[shooter], sp = oT[shooter] || hp;
    const dribble = (p, ph) => ({ x: p[0] + .9 * dir(off), y: p[1] + .4, z: 1.2 + Math.abs(Math.sin(ph * 9)) * 2.4 });
    if (e.k === 'to') { const q = smEaseIO(Math.min(1, u / .8)), tgt = oT[offIdx[1]] || hp; ball = { x: smLerp(hp[0], tgt[0], q) + (u > .5 ? (u - .5) * 6 * -dir(off) : 0), y: smLerp(hp[1], tgt[1], q), z: 3 + Math.sin(q * Math.PI) * 2, a: u > .85 ? 1 - (u - .85) / .15 : 1 }; }
    else if (e.k === 'ft') { if (u < .35) ball = { x: X(off, 75) + .9 * dir(off), y: 25.4, z: 1 + Math.abs(Math.sin(u * 30)) * 2 }; else { const q = Math.min(1, (u - .35) / .4), x0 = X(off, 75); ball = { x: smLerp(x0, rim[0], q), y: 25, z: 7 + Math.sin(q * Math.PI) * 6 + (10 - 7) * q }; if (u > .75) { ball = { x: rim[0], y: 25, z: Math.max(0, 10 - (u - .75) * 40) }; fx.push({ id: `r${this.i}`, k: 'ring', x: rim[0], y: 25, d: .5, col: 'rgba(255,255,255,1)' }, { id: `t${this.i}`, k: 'txt', s: `+${e.pts}`, x: X(off, 75), y: 25, d: 1, col: '#ffd65a' }); } } }
    else {
      const p0 = u < .3 ? dribble(hp, u) : null;
      if (u < .3) ball = p0;
      else if (u < .48 && e.a != null) { const q = smEaseIO((u - .3) / .18); ball = { x: smLerp(hp[0], sp[0], q), y: smLerp(hp[1], sp[1], q), z: 4 + Math.sin(q * Math.PI) * 2.2 }; }
      else if (u < .48) { const q = smEaseIO((u - .3) / .18); ball = dribble([smLerp(hp[0], sp[0], q), smLerp(hp[1], sp[1], q)], u); }
      else if (u < .78) { const q = (u - .48) / .3, peak = (e.k === '3' || e.three) ? 15 : 12.5; ball = { x: smLerp(sp[0], rim[0], q), y: smLerp(sp[1], rim[1], q), z: smLerp(7.5, 10, q) + Math.sin(q * Math.PI) * (peak - 8) }; }
      else if (e.k === 'miss') { const rp = e.off ? oT[e.ri] : null; let tgt = rp; if (!tgt) { const dj = e.rj; const mine = toks.find(t => t.id === dj + '|' + sc.teams[dj][e.ri].id); tgt = mine ? [mine.x, mine.y] : [rim[0] - dir(off) * 6, 25]; }
        const q = smEaseOut((u - .78) / .22); ball = { x: smLerp(rim[0], tgt[0], q), y: smLerp(rim[1], tgt[1], q), z: 10 + Math.sin(q * Math.PI) * 3 - q * 4 };
        const rt = toks.find(t => t.id === e.rj + '|' + sc.teams[e.rj][e.ri].id); if (rt) rt.hot = true; }
      else { const q = (u - .78) / .22; ball = { x: rim[0] - dir(off) * q * .6, y: 25, z: Math.max(0, 10 - q * 12) };
        fx.push({ id: `r${this.i}`, k: 'ring', x: rim[0], y: 25, d: .55, col: e.k === '3' ? 'rgba(255,214,90,1)' : 'rgba(255,255,255,1)' }, { id: `t${this.i}`, k: 'txt', s: `+${e.pts}`, x: sp[0], y: sp[1], d: 1.1, col: e.k === '3' ? '#ffd65a' : '#ffffff' }); }
    }
    return { toks, ball, fx };
  }
  // ---- NFL poses
  nflPose(e, u) {
    const toks = [], fx = []; if (!e) return { toks, ball: { x: 60, y: 26.65, z: 0 } };
    if (e.k === 'kick' || e.k === 'rtd' || e.k === 'half' || (e.k === 'punt' && e.to != null)) return this.nflKick(e, u);
    const j = e.j, dir = j ? 1 : -1, X = y => j ? 10 + y : 110 - y;      // y = yards from own goal line
    const los = e.los != null ? e.los : 25, L = X(los), mid = 26.65, P = this.g.teams[j].players, D = this.g.teams[1 - j].players;
    const R = smRng(Math.floor((e.t || 0) * 997) + 11);
    const qb = e.q != null ? e.q : this.sc.qbOf[j];
    const big = (jj, i) => { const p = this.g.teams[jj].players[i]; return p ? this.tokStyle(jj, p.id, true) : null; };
    const small = (jj, n) => { const s = this.tokStyle(jj, 'x' + n, false); s.small = true; s.key = jj + '|s|' + this.r; s.text = ''; return s; };
    // offense: five linemen, a tight end, the quarterback, a back and receivers; the player in the play gets his number
    const ol = [-4, -2, 0, 2, 4].map((dy, n) => Object.assign(small(j, n), { id: `${j}|ol${n}`, x: L - dir * .8, y: mid + dy * 1.1 }));
    const runner = e.k === 'run' ? e.i : null, catcher = e.k === 'pass' || e.k === 'inc' ? e.i : null;
    const wrs = P.map((p, i) => i).filter(i => i !== qb && i !== runner).slice(0, 3);
    if (catcher != null && !wrs.includes(catcher)) wrs[0] = catcher;
    const rb = runner != null ? runner : P.findIndex((p, i) => i !== qb && !wrs.includes(i));
    let qx = L - dir * 5, qy = mid, bx = L, by = mid, bz = 0, rot = 0;
    const off = [];
    const qbS = big(j, qb); if (qbS) off.push(Object.assign(qbS, { id: `${j}|${P[qb].id}`, x: qx, y: qy })); else off.push(Object.assign(small(j, 8), { id: `${j}|bq`, x: qx, y: qy }));
    if (rb >= 0 && P[rb]) off.push(Object.assign(big(j, rb), { id: `${j}|${P[rb].id}`, x: L - dir * 7.5, y: mid + 1.2 }));
    const wy = [6, 47.3, 14]; wrs.forEach((i, n) => P[i] && off.push(Object.assign(big(j, i), { id: `${j}|${P[i].id}`, x: L - dir * (n === 2 ? 1.5 : .8), y: wy[n] })));
    off.push(Object.assign(small(j, 9), { id: `${j}|te`, x: L - dir * 1, y: mid + 6.2 }));
    const dl = [-3, -1, 1, 3].map((dy, n) => Object.assign(small(1 - j, n), { id: `${1 - j}|dl${n}`, x: L + dir * 1.2, y: mid + dy * 1.4 }));
    const lb = [-5, 0, 5].map((dy, n) => Object.assign(small(1 - j, n + 4), { id: `${1 - j}|lb${n}`, x: L + dir * 5, y: mid + dy }));
    const db = [[7, 6.5], [7, 46.8], [13, 18], [13, 35.3]].map(([dx, yy], n) => Object.assign(small(1 - j, n + 7), { id: `${1 - j}|db${n}`, x: L + dir * dx, y: yy }));
    const find = i => off.find(t => P[i] && t.id === `${j}|${P[i].id}`);
    let lines = [[L, 'rgba(90,150,255,.95)']];
    const tgtX = X(Math.min(100, los + (e.y || 0)));
    if (e.k === 'run' && find(runner)) { const t = find(runner), q = u < .25 ? 0 : smEaseIO(Math.min(1, (u - .25) / .62)); const sx = L - dir * 7.5, ex = tgtX;
      t.x = smLerp(sx, ex, q); t.y = mid + 1.2 + Math.sin(q * 3.1) * 2.2 * (R() > .5 ? 1 : -1); t.hot = u > .2; t.w = 14;
      if (u < .25) { bx = qx; by = qy; } else { bx = t.x; by = t.y; bz = 1; }
      [...dl, ...lb].forEach((d, n) => { const c = Math.max(0, q - .2 - n * .03); d.x = smLerp(d.x, t.x + dir * 1.5, Math.min(1, c * 1.2)); d.y = smLerp(d.y, t.y + (n - 3) * .8, Math.min(1, c)); });
      if (e.td && u > .85) fx.push({ id: `g${this.i}`, k: 'glow', x: j ? 110 : 0, w: 10, d: .9, col: (TC.NFL[j ? this.g.home : this.g.away] || ['#fff'])[1] }); }
    else if ((e.k === 'pass' || e.k === 'inc') && find(catcher)) { const t = find(catcher), qbT = find(qb);
      const air = e.k === 'inc' ? e.ay : Math.max(1, Math.min(e.y, Math.round(e.y * (/deep/.test(e.dir || '') ? .75 : .45) + R() * e.y * .3))), cx = X(Math.min(100, los + air)), cy = Math.max(4, Math.min(49.3, e.side ? mid + e.side * dir * (7 + R() * 13) : t.y + (R() - .5) * 14));
      if (qbT) { qbT.x = qx - dir * Math.min(1, u * 4) * 2.4; qbT.hot = u < .45; }
      const q1 = Math.min(1, u / .62); t.x = smLerp(t.x, cx, smEaseIO(q1)); t.y = smLerp(t.y, cy, smEaseIO(q1)); t.hot = u > .3; t.w = 12;
      if (u < .38) { bx = qbT ? qbT.x : qx; by = qy; bz = 2; }
      else if (u < .62) { const q = (u - .38) / .24; bx = smLerp(qbT ? qbT.x : qx, cx, q); by = smLerp(qy, cy, q); bz = 2 + Math.sin(q * Math.PI) * Math.min(14, 3 + air * .45); rot = Math.atan2(cy - qy, (cx - (qbT ? qbT.x : qx)) * 1) ; }
      else if (e.k === 'inc') { const q = (u - .62) / .38; bx = cx + dir * q * 2; by = cy + q * 1.5; bz = Math.max(0, 2 - q * 3); }
      else { const q = smEaseOut(Math.min(1, (u - .62) / .3)); t.x = smLerp(cx, tgtX, q); t.y = cy; bx = t.x; by = t.y; bz = 1; }
      db.forEach((d, n) => { const c = Math.min(1, u * 1.4); d.x = smLerp(d.x, t.x + dir * (1.5 + n * .4), c * .8); d.y = smLerp(d.y, t.y + (n - 1.5) * 1.5, c * .7); });
      if (e.td && u > .85) fx.push({ id: `g${this.i}`, k: 'glow', x: j ? 110 : 0, w: 10, d: .9, col: (TC.NFL[j ? this.g.home : this.g.away] || ['#fff'])[1] }); }
    else if (e.k === 'fg' || e.k === 'fgx') { const q = Math.max(0, (u - .2) / .7), sx = L - dir * 7, gx = j ? 120 : 0; bx = smLerp(sx, gx, smEaseOut(q)); by = mid + (e.k === 'fgx' ? q * q * 9 : 0); bz = Math.sin(Math.min(1, q) * Math.PI * .85) * 16; rot = q * 9; }
    else if (e.k === 'punt') { const q = Math.max(0, (u - .2) / .7), sx = L - dir * 13, ex = X(Math.min(92, los + 42)); bx = smLerp(sx, ex, smEaseOut(q)); by = mid + Math.sin(q * 2) * 3; bz = Math.sin(Math.min(1, q) * Math.PI) * 18; rot = q * 12; lines = [[L, 'rgba(90,150,255,.95)']]; }
    else { bx = L; by = mid; bz = 0; }
    if (e.k !== 'punt' && e.k !== 'fg' && e.k !== 'fgx' && e.k !== 'pat' && e.k !== 'note') { const fd = X(Math.min(100, e.fdl != null ? e.fdl : los + 10)); lines.push([fd, 'rgba(242,210,75,.95)']); }
    if (e.k === 'pat' || e.k === 'saf' || e.k === 'start') { bx = e.k === 'pat' ? (j ? 105 : 15) : L; by = mid; }
    toks.push(...ol, ...off, ...dl, ...lb, ...db);
    if ((e.k === 'run' || e.k === 'pass') && u > .9 && e.y) fx.push({ id: `y${this.i}`, k: 'txt', s: e.td ? 'TD' : `${e.y > 0 ? '+' : ''}${e.y}`, x: bx / 1, y: by, d: .9, col: e.td ? '#ffd65a' : '#ffffff' });
    return { toks, ball: { x: bx, y: by, z: bz, rot }, fx, lines };
  }
}
