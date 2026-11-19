/* ===== Fair Line effects layer (v3.38). Display only: nothing here touches the model, the pick policy or history.json. =====
   Ten effects, each with its own switch (Your book, Effects). Reduce Motion turns all of them off.
   Rules for this layer: real-time drawing happens on small canvases only, only while they are on screen, and stops when
   the tab is hidden. Page-level moves stay on transform and opacity. No whole-page snapshots (the cause of the blank
   screen on the unfolded Duo in v3.7.1). */
const FX = {};
(() => {
  const KEY = 'fl-fx-1';
  const LIST = [
    ['drop', 'The 10,000 drop', 'In a credit memo, ten thousand balls fall through pegs and pile into the outcome curve, with the book line as the gate.'],
    ['rooms', 'Rooms', 'Changing tabs turns the camera from one room to the next instead of sliding a sheet.'],
    ['tote', 'Tote board glass', 'Split-flap digits that really flip, LED glow, and glare that moves across the glass as you scroll or tilt.'],
    ['foil', 'Foil cards', 'Spotlight cards have thickness and tilt under your finger. A grades carry a foil sheen.'],
    ['paper', 'Paper tickets', 'Tickets can be picked up, dragged and flicked, and settle back like paper. Settled tickets stack on a spike.'],
    ['fire', 'Fire and frost', 'Live flame on hot numbers and frost that creeps over cold cards. Wipe the frost off with a finger.'],
    ['lever', 'Press lever', 'Pull the lever on the parlay press yourself. Sparks and a jolt when the ram lands.'],
    ['hinge', 'Case unfold', 'Unfolding the phone opens the app like a case, with a soft crease at the hinge.'],
    ['cam', 'Broadcast camera', 'The Sim replay cuts between camera angles and slows down for the deciding score.'],
    ['reveal', 'Morning reveal', 'Last night\'s tickets are stamped one by one while the units counter rolls.'],
  ];
  let st = {}; try { st = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { st = {}; }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };
  const on = k => !RM() && st.all !== false && st[k] !== false;
  const apply = () => { const h = document.documentElement; for (const [k] of LIST) h.classList.toggle('fx-' + k, on(k)); };
  const scans = [], boots = [];
  let scanQ = false;
  const scan = () => { scanQ = false; for (const f of scans) { try { f(); } catch (e) { console.warn('fx', e); } } };
  const queue = () => { if (!scanQ) { scanQ = true; requestAnimationFrame(scan); } };
  FX.on = on; FX.reg = f => scans.push(f); FX.atBoot = f => boots.push(f); FX.queue = queue; FX.LIST = LIST;
  FX.get = k => st[k]; FX.put = (k, v) => { st[k] = v; save(); };
  FX.set = (k, v) => { st[k] = v; save(); apply(); render(); };
  FX.clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  FX.lerp = (a, b, t) => a + (b - a) * t;
  FX.buzz = ms => { try { if (navigator.vibrate) navigator.vibrate(ms); } catch (e) {} };

  /* a damped spring on one or more numbers, run on requestAnimationFrame. cb(values, done). Returns { stop, to(target) }. */
  FX.spring = (from, to, cb, o = {}) => {
    const k = o.k || 170, c = o.c || 22, x = from.slice(), v = (o.v || from.map(() => 0)).slice(); let tgt = to.slice(), raf = 0, last = 0, dead = false;
    const step = now => { if (dead) return; const dt = Math.min(.032, last ? (now - last) / 1000 : .016); last = now; let rest = true;
      for (let i = 0; i < x.length; i++) { const a = -k * (x[i] - tgt[i]) - c * v[i]; v[i] += a * dt; x[i] += v[i] * dt; if (Math.abs(v[i]) > (o.eps || .02) || Math.abs(x[i] - tgt[i]) > (o.eps || .02)) rest = false; }
      if (rest) { for (let i = 0; i < x.length; i++) x[i] = tgt[i]; cb(x, true); return; }
      cb(x, false); raf = requestAnimationFrame(step); };
    raf = requestAnimationFrame(step);
    return { stop() { dead = true; cancelAnimationFrame(raf); }, to(t) { tgt = t.slice(); if (dead) return; }, x, v };
  };

  /* one shared "on screen" watcher: FX.watch(el, fn(visible)) */
  const seen = new WeakMap();
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => { const f = seen.get(e.target); if (f) f(e.isIntersecting); }), { rootMargin: '60px' }) : null;
  FX.watch = (el, fn) => { if (!io) { fn(true); return; } seen.set(el, fn); io.observe(el); };
  FX.unwatch = el => { if (io) io.unobserve(el); seen.delete(el); };

  /* tilt: -1..1 on each axis. From the phone's motion sensor where the page is allowed to read it (the standalone app,
     after one tap on "Use phone tilt"), else from the pointer on a desktop, else from where the element sits on the screen
     as the page scrolls. Values are written onto the on-screen elements that asked for them, never onto the whole page. */
  const tilt = { gx: 0, gy: 0, live: false, ptr: false }, users = new Set(); let tiltQ = false;
  const paintTilt = () => { tiltQ = false; const H = innerHeight;
    for (const el of users) { if (!el.isConnected) { users.delete(el); continue; }
      const r = el.getBoundingClientRect(); if (r.bottom < -40 || r.top > H + 40) continue;
      const sy = FX.clamp(((r.top + r.height / 2) - H / 2) / (H / 2), -1, 1);
      const gx = tilt.live || tilt.ptr ? tilt.gx : sy * .7, gy = tilt.live || tilt.ptr ? tilt.gy : sy;
      el.style.setProperty('--gx', gx.toFixed(3)); el.style.setProperty('--gy', gy.toFixed(3)); } };
  const tiltKick = () => { if (!tiltQ && users.size) { tiltQ = true; requestAnimationFrame(paintTilt); } };
  FX.tiltUse = el => { users.add(el); tiltKick(); }; FX.tilt = tilt;
  addEventListener('scroll', tiltKick, { passive: true });
  addEventListener('pointermove', e => { if (e.pointerType !== 'mouse' || tilt.live) return; tilt.ptr = true; tilt.gx = FX.clamp((e.clientX / innerWidth - .5) * 2, -1, 1); tilt.gy = FX.clamp((e.clientY / innerHeight - .5) * 2, -1, 1); tiltKick(); }, { passive: true });
  const onOri = e => { if (e.gamma == null) return; tilt.live = true; const land = Math.abs(window.orientation || 0) === 90;
    const a = land ? e.beta : e.gamma, b = land ? e.gamma : e.beta - 45;
    tilt.gx = FX.lerp(tilt.gx, FX.clamp(a / 28, -1, 1), .25); tilt.gy = FX.lerp(tilt.gy, FX.clamp(b / 28, -1, 1), .25); tiltKick(); };
  FX.tiltAsk = async () => {      // iPhones only hand over motion after a tap; inside Claude the frame refuses it and the scroll version stays
    try { const D = window.DeviceOrientationEvent; if (!D) return false;
      if (typeof D.requestPermission === 'function') { const r = await D.requestPermission(); if (r !== 'granted') return false; }
      addEventListener('deviceorientation', onOri, { passive: true }); FX.put('tilt', true); return true; } catch (e) { return false; } };

  /* the Effects panel, added to the foot of Your book */
  const panel = () => `<section class="card fxp" id="fxPanel" aria-label="Effects">
    <div class="fxp-h"><h3>Effects</h3><label class="fxp-all"><span>All effects</span><input type="checkbox" class="sw" data-fx="all"${st.all !== false ? ' checked' : ''} aria-label="All effects"></label></div>
    <p class="prose">Each effect has its own switch. They are display only: the model, the picks and the record are the same with every one of them off. Your phone's Reduce Motion setting turns them all off.${RM() ? ' <b>Reduce Motion is on, so they are off now.</b>' : ''}</p>
    <ul class="fxp-l">${LIST.map(([k, n, d]) => `<li><label><span><b>${n}</b><small>${d}</small></span><input type="checkbox" class="sw" data-fx="${k}"${st[k] !== false ? ' checked' : ''}${st.all === false ? ' disabled' : ''} aria-label="${n}"></label></li>`).join('')}</ul>
    <div class="fxp-f"><button class="btn ghost sm" data-fxa="tilt">${tilt.live ? 'Phone tilt is on' : 'Use phone tilt'}</button><button class="btn ghost sm" data-fxa="reveal">Replay last night</button></div>
    <p class="lbl fxp-n" id="fxNote" role="status"></p></section>`;
  FX.reg(() => { if (S.tab !== 'book') return; const m = $('#main'); if (m && !m.querySelector('#fxPanel')) m.insertAdjacentHTML('beforeend', panel()); });
  document.addEventListener('change', e => { const t = e.target; if (!t.dataset || !t.dataset.fx) return; FX.set(t.dataset.fx, t.checked); });
  document.addEventListener('click', async e => { const b = e.target.closest && e.target.closest('[data-fxa]'); if (!b) return; const note = t => { const n = $('#fxNote'); if (n) n.textContent = t; };
    if (b.dataset.fxa === 'tilt') { const ok = await FX.tiltAsk(); b.textContent = ok ? 'Phone tilt is on' : 'Use phone tilt'; note(ok ? 'Tilt the phone: the glass and the cards follow.' : 'This screen will not share the motion sensor (it works in the standalone app). Glare follows your scrolling instead.'); }
    if (b.dataset.fxa === 'reveal') { if (!FX.revealPlay || !FX.revealPlay(true)) note(RM() ? 'Reduce Motion is on.' : 'No settled tickets to replay yet.'); } });

  FX.boot = () => { apply();
    try { matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => { apply(); render(); }); } catch (e) {}
    const mo = new MutationObserver(queue); const m = $('#main'), me = $('#memo');
    if (m) mo.observe(m, { childList: true, subtree: true }); if (me) mo.observe(me, { childList: true, subtree: true });
    if (st.tilt && window.DeviceOrientationEvent && typeof window.DeviceOrientationEvent.requestPermission !== 'function') addEventListener('deviceorientation', onOri, { passive: true });
    for (const f of boots) { try { f(); } catch (e) { console.warn('fx boot', e); } }
    queue(); };
  FX.hinge = () => false; FX.rooms = () => false;      // replaced further down when those effects load
})();
/* ---- 2. Rooms: a tab change turns the camera from one room to the next. Only the pieces on screen move (as one wall, turned
   about the centre of the screen), nothing is photographed, and a second tap while it runs finishes the first at once. ---- */
(() => {
  let tok = 0, pending = null;
  const P = 'perspective(1150px) ';
  const onScreen = m => { const H = innerHeight; return [...m.children].filter(el => { const r = el.getBoundingClientRect(); return r.height && r.bottom > 0 && r.top < H; }).slice(0, 6); };
  const origin = el => { const r = el.getBoundingClientRect(); el.style.transformOrigin = `${(innerWidth / 2 - r.left).toFixed(1)}px ${(innerHeight / 2 - r.top).toFixed(1)}px`; return r.height > innerHeight * 2.4; };
  const away = (k, flat) => flat ? `translate3d(${-k * 30}vw,0,0)` : P + `translate3d(${-k * 34}vw,0,-360px) rotateY(${k * 44}deg)`;
  function sign(tab, k) {
    const b = document.querySelector(`#tabs button[data-tab="${tab}"]`), hd = document.querySelector('header.top'); if (!b) return;
    const top = Math.max(0, hd ? hd.getBoundingClientRect().bottom : 0);
    const el = document.createElement('div'); el.className = 'fx-sign'; el.setAttribute('aria-hidden', 'true'); el.style.top = top + 'px'; el.style.setProperty('--tc', `var(--c-${tab})`);
    el.innerHTML = `<i class="fx-sign-fl"></i><b>${esc(b.textContent.trim())}</b>`; document.body.appendChild(el);
    const pl = el.lastElementChild;
    pl.animate([{ transform: `translate3d(${k * 60}vw,0,0) scale(.82)`, opacity: 0 }, { transform: 'translate3d(0,0,0) scale(1)', opacity: 1, offset: .42 }, { transform: 'translate3d(0,0,0) scale(1)', opacity: 1, offset: .6 }, { transform: `translate3d(${-k * 60}vw,0,0) scale(1.18)`, opacity: 0 }], { duration: 620, easing: 'cubic-bezier(.3,.1,.3,1)', fill: 'both' });
    el.firstElementChild.animate([{ opacity: 0 }, { opacity: 1, offset: .35 }, { opacity: 0 }], { duration: 560, fill: 'both' });
    setTimeout(() => el.remove(), 700);
  }
  function enter(k) {
    const m = $('#main'); if (!m) return;
    onScreen(m).forEach(el => { const flat = origin(el);
      const a = el.animate([{ transform: away(-k, flat), opacity: 0 }, { transform: flat ? 'translate3d(0,0,0)' : P + 'translate3d(0,0,0) rotateY(0deg)', opacity: 1 }], { duration: 480, easing: 'cubic-bezier(.18,.9,.24,1.04)', fill: 'backwards' });
      const done = () => { el.style.transformOrigin = ''; }; a.onfinish = done; a.oncancel = done; });
  }
  FX.rooms = (fn, dir) => {
    if (!FX.on('rooms')) return false; const m = $('#main'); if (!m || !m.animate) return false;
    if (pending) pending();      // a second tap: land the first move now
    const k = dir === 'back' ? -1 : 1, my = ++tok, was = S.tab, out = onScreen(m), anims = []; let done = false;
    const swap = () => { if (done) return; done = true; pending = null; anims.forEach(a => a.cancel()); out.forEach(el => { el.style.transformOrigin = ''; });
      fn(); if (my !== tok) return; if (S.tab !== was) sign(S.tab, k); enter(k); };
    pending = swap;
    out.forEach(el => { const flat = origin(el); anims.push(el.animate([{ transform: flat ? 'translate3d(0,0,0)' : P + 'translate3d(0,0,0) rotateY(0deg)', opacity: 1 }, { transform: away(k, flat), opacity: 0 }], { duration: 150, easing: 'cubic-bezier(.5,0,.85,.45)', fill: 'forwards' })); });
    setTimeout(swap, 155);
    return true;
  };
})();

/* ---- 3. Tote board glass: glare that moves with scroll or tilt, a board that leans a degree or two, LED bloom, real flaps (the flap itself is CSS) ---- */
FX.reg(() => {
  if (!FX.on('tote')) return;
  document.querySelectorAll('.tote:not([data-fxg])').forEach(t => { t.dataset.fxg = 1; t.insertAdjacentHTML('beforeend', '<i class="fx-glare" aria-hidden="true"></i>'); FX.tiltUse(t); });
});
/* ---- 1. The 10,000 drop. In the credit memo: ten thousand balls fall through pegs and pile into the desk's outcome curve.
   The counts are not random: each outcome gets its exact share of 10,000 from the same curve the verdict below is priced
   from, so Over and Under on the board agree with the chances in the memo. The line is the gate. ---- */
(() => {
  const N = 10000, DUR = 5200;
  let cur = null;
  function deskDist(pr) {      // the curve the verdict uses: market-anchored when the desk has a line, else the model's own
    const ln = getLine(pr.key), am = ln ? anchMu(pr, ln) : null;
    return am != null && !pr.binary ? dist({ key: pr.key + '#m', mu: am, lg: pr.lg, mkt: pr.mkt, binary: false }) : dist(pr); }
  function plan(pr, line) {
    const d = deskDist(pr); let bins = [];
    if (pr.binary) bins = [{ lo: 0, hi: 0, p: d[0], over: false, lab: 'No' }, { lo: 1, hi: 1, p: d[1], over: true, lab: 'Yes' }];
    else { const lo = E.quantile(d, .003), hi = E.quantile(d, .997), w = Math.max(1, Math.ceil((hi - lo + 1) / 54));
      for (let s = lo; s <= hi; s += w) { let p = 0, po = 0; for (let n = s; n < s + w && n < d.length; n++) { p += d[n]; if (n > line) po += d[n]; }
        if (s === lo) for (let n = 0; n < lo; n++) { p += d[n]; if (n > line) po += d[n]; }
        if (s + w > hi) for (let n = s + w; n < d.length; n++) { p += d[n]; po += n > line ? d[n] : 0; }
        bins.push({ lo: s, hi: Math.min(hi, s + w - 1), p, po }); } }
    // exact shares of 10,000 by largest remainder; inside a bin that straddles the line, the over share is split the same way
    const tot = bins.reduce((a, b) => a + b.p, 0) || 1; let left = N;
    bins.forEach(b => { b.x = b.p / tot * N; b.n = Math.floor(b.x); left -= b.n; });
    bins.slice().sort((a, b) => (b.x - b.n) - (a.x - a.n)).slice(0, left).forEach(b => b.n++);
    bins.forEach(b => { b.no = pr.binary ? (b.over ? b.n : 0) : Math.round(b.n * (b.p ? b.po / b.p : 0)); });
    return { bins, over: bins.reduce((a, b) => a + b.no, 0), max: Math.max(1, ...bins.map(b => b.n)) };
  }
  function mount(host, pr) {
    const ln = draftLine(pr), M = MK[pr.lg][pr.mkt];
    const sec = document.createElement('div'); sec.className = 'sec fx-drop'; sec.id = 'fxDrop';
    sec.innerHTML = `<h3><span>The 10,000 drop</span><button class="btn ghost sm" data-fxdrop="go">Drop again</button></h3>
      <div class="fxd-box"><canvas class="fxd-cv" aria-hidden="true"></canvas>
        <div class="fxd-read" role="status"><span class="fxd-u"><small>${pr.binary ? 'No' : 'Under'}</small><b>0</b></span><span class="fxd-n"><b>0</b><small>of 10,000</small></span><span class="fxd-o"><small>${pr.binary ? 'Yes' : 'Over'}</small><b>0</b></span></div></div>
      <p class="fxd-cap">Each ball is one game from the desk's curve for ${esc(pr.e.p.name)}, ${esc(M.n.toLowerCase())}. ${pr.binary ? 'Right of the gate, he scores.' : 'The brass gate is the line: right of it is the Over.'}</p>`;
    host.after(sec); return sec;
  }
  function start(sec, pr, animate) {
    if (cur) cur.kill();
    const cv = sec.querySelector('canvas'), box = sec.querySelector('.fxd-box'), W = Math.max(240, Math.round(box.clientWidth)), Ht = W < 420 ? 236 : 264, dpr = Math.min(3, window.devicePixelRatio || 1);
    cv.width = W * dpr; cv.height = Ht * dpr; cv.style.height = Ht + 'px'; const c = cv.getContext('2d');
    const line = draftLine(pr).line, pl = plan(pr, line), B = pl.bins, nb = B.length;
    const padX = 12, floor = Ht - 10, pileH = Math.round(Ht * .46), pegTop = 30, pegBot = floor - pileH - 14, x0 = padX, x1 = W - padX, bw = (x1 - x0) / nb;
    const cell = Math.max(1.05, Math.min(4, Math.sqrt(bw * pileH / pl.max) * .97)), per = Math.max(1, Math.floor((bw - .6) / cell)), cw = (bw - .6) / per;
    const rows = Math.ceil(pl.max / per), ch = Math.min(cell, pileH / rows);
    const cs = getComputedStyle(sec), colO = cs.getPropertyValue('--fxd-o').trim() || '#ffb833', colU = cs.getPropertyValue('--fxd-u').trim() || '#7d8b82', brass = '#c9a24a';
    // where the gate stands, in pixels
    let gx; if (pr.binary) gx = x0 + bw; else { const i = B.findIndex(b => b.hi > line); const b = i < 0 ? null : B[i];
      gx = !b ? x1 : b.lo > line ? x0 + i * bw : x0 + i * bw + bw * ((Math.floor(line) + 1 - b.lo) / (b.hi - b.lo + 1)); }
    // static layer: pegs, floor, bin ticks
    const bg = document.createElement('canvas'); bg.width = cv.width; bg.height = cv.height; const g = bg.getContext('2d'); g.scale(dpr, dpr);
    const R = Math.max(5, Math.min(8, Math.round((pegBot - pegTop) / 16))), gapX = Math.max(13, Math.min(22, W / 20));
    g.fillStyle = 'rgba(201,162,74,.5)';
    for (let r = 0; r < R; r++) { const y = pegTop + (pegBot - pegTop) * (r + .5) / R, off = r % 2 ? gapX / 2 : 0;
      for (let x = x0 + off + (((x1 - x0) % gapX) / 2); x <= x1; x += gapX) { g.beginPath(); g.arc(x, y, 1.5, 0, 7); g.fill(); } }
    g.fillStyle = 'rgba(255,255,255,.14)'; g.fillRect(x0, floor + .5, x1 - x0, 1);
    g.font = '600 9px "Sometype Mono", monospace'; g.textAlign = 'center'; g.fillStyle = 'rgba(154,167,157,.9)';
    if (!pr.binary) { const span = B[nb - 1].hi - B[0].lo, step = [1, 2, 5, 10, 20, 25, 50, 100].find(s => span / s <= (W < 420 ? 6 : 9)) || 100;
      for (let v = Math.ceil(B[0].lo / step) * step; v <= B[nb - 1].hi; v += step) { const i = B.findIndex(b => v >= b.lo && v <= b.hi); if (i < 0) continue; const b = B[i];
        g.fillText(v, x0 + i * bw + bw * ((v - b.lo + .5) / (b.hi - b.lo + 1)), Ht - 1); } }
    // hopper
    g.strokeStyle = brass; g.lineWidth = 2; g.beginPath(); g.moveTo(W / 2 - 34, 6); g.lineTo(W / 2 - 9, 22); g.moveTo(W / 2 + 34, 6); g.lineTo(W / 2 + 9, 22); g.stroke();
    // the pile, kept on its own canvas so a frame costs the same at ball 9,000 as at ball 9
    const pile = document.createElement('canvas'); pile.width = cv.width; pile.height = cv.height; const pc = pile.getContext('2d'); pc.scale(dpr, dpr);
    const got = B.map(() => 0), gotO = B.map(() => 0); let landed = 0, landedO = 0;
    const dot = (i, isOver) => { const k = got[i]++, col = k % per, row = (k / per) | 0, bx = x0 + i * bw + .3;
      // in a bin the line cuts through, Unders stack on the left of it and Overs on the right
      const split = B[i].no > 0 && B[i].no < B[i].n; let xx = bx + (col + .5) * cw;
      if (split) { const cut = bx + (bw - .6) * (1 - B[i].no / B[i].n), kk = isOver ? gotO[i]++ : k - gotO[i], wd = isOver ? bx + bw - .6 - cut : cut - bx, pp = Math.max(1, Math.floor(wd / cw)); xx = (isOver ? cut : bx) + ((kk % pp) + .5) * (wd / pp); }
      pc.fillStyle = isOver ? colO : colU; const s = Math.max(.9, Math.min(cw, ch) - .25); pc.fillRect(xx - s / 2, floor - (row + .5) * ch - s / 2 + (split ? 0 : 0), s, s); };
    const uB = sec.querySelector('.fxd-u b'), oB = sec.querySelector('.fxd-o b'), nB = sec.querySelector('.fxd-n b');
    const fmt = n => n.toLocaleString('en-US'); let shown = -1;
    const read = () => { if (shown === landed) return; shown = landed; uB.textContent = fmt(landed - landedO); oB.textContent = fmt(landedO); nB.textContent = fmt(landed); };
    const gate = a => { c.globalAlpha = a; c.fillStyle = brass; c.fillRect(gx - 1, pegBot + 4, 2, floor - pegBot - 4); c.beginPath(); c.arc(gx, pegBot + 4, 3.2, 0, 7); c.fill();
      c.font = '700 10px "Sometype Mono", monospace'; const lab = pr.binary ? 'SCORES' : 'LINE ' + line, right = gx < W - 70; c.textAlign = right ? 'left' : 'right'; c.fillStyle = '#f2f1e6'; c.fillText(lab, gx + (right ? 7 : -7), pegBot + 9); c.globalAlpha = 1; };
    const paint = balls => { c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, cv.width, cv.height); c.drawImage(bg, 0, 0); c.drawImage(pile, 0, 0); c.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (balls) for (const b of balls) { c.fillStyle = b.o ? colO : colU; c.fillRect(b.px - 1.2, b.py - 1.2, 2.4, 2.4); } gate(1); read(); };
    const fill = () => { B.forEach((b, i) => { for (let k = 0; k < b.n - b.no; k++) dot(i, false); for (let k = 0; k < b.no; k++) dot(i, true); }); landed = N; landedO = pl.over; };
    const me = { dead: false, kill() { this.dead = true; cancelAnimationFrame(this.raf); }, sec, line, key: pr.key, W };
    cur = me; sec.dataset.line = line; sec.dataset.key = pr.key;
    if (!animate) { fill(); paint(null); return; }
    // the order the balls leave the hopper: shuffled, so both sides of the gate fill together
    const order = new Uint16Array(N), isO = new Uint8Array(N); let q = 0;
    B.forEach((b, i) => { for (let k = 0; k < b.n; k++) { order[q] = i; isO[q] = k < b.no ? 1 : 0; q++; } });
    let seed = 0x9e3779b1 ^ (line * 977 | 0) ^ nb; const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    for (let i = N - 1; i > 0; i--) { const j = (rnd() * (i + 1)) | 0, a = order[i], b = isO[i]; order[i] = order[j]; isO[i] = isO[j]; order[j] = a; isO[j] = b; }
    const live = []; let sent = 0, t0 = 0, last = 0; const FALL = 1150;
    const frame = now => { if (me.dead) return; if (!sec.isConnected) { me.kill(); return; } if (!t0) { t0 = now; last = now; }
      const el = now - t0, want = Math.min(N, Math.floor(N * Math.pow(Math.min(1, el / DUR), 1.25)));      // a trickle, then the flood
      while (sent < want) { const i = order[sent], tx = x0 + (i + .2 + rnd() * .6) * bw;
        live.push({ i, o: isO[sent], t: 0, sx: W / 2 + (rnd() - .5) * 12, tx, j1: (rnd() - .5) * gapX * 1.6, j2: (rnd() - .5) * gapX * 1.2, ph: rnd() * 6.28, px: 0, py: 0, d: FALL * (.82 + rnd() * .36) }); sent++; }
      const dt = now - last; last = now;
      for (let k = live.length - 1; k >= 0; k--) { const b = live[k]; b.t += dt / b.d;
        if (b.t >= 1) { dot(b.i, !!b.o); landed++; if (b.o) landedO++; live[k] = live[live.length - 1]; live.pop(); continue; }
        const t = b.t, top = floor - (((got[b.i] / per) | 0) + 1) * ch, y = 18 + (top - 18) * (t * t * .62 + t * .38);
        // through the pegs the ball wanders (zero at both ends, so it still lands in its own bin), with a small hop at each row
        const w = Math.sin(Math.PI * t), inPeg = y > pegTop && y < pegBot ? 1 : 0;
        b.px = b.sx + (b.tx - b.sx) * (t * t * (3 - 2 * t)) + w * (b.j1 * Math.sin(t * 9 + b.ph) + b.j2 * Math.sin(t * 17 + b.ph * 1.7));
        b.py = y - inPeg * Math.abs(Math.sin((y - pegTop) / (pegBot - pegTop) * R * Math.PI)) * 2.2; }
      paint(live);
      if (sent < N || live.length) me.raf = requestAnimationFrame(frame); else { paint(null); sec.classList.add('done'); } };
    sec.classList.remove('done'); paint(null); me.raf = requestAnimationFrame(frame);
  }
  FX.reg(() => {
    const host = document.querySelector('#memo #mDist'), old = $('#fxDrop'), pr = S.memo && PMAP[S.memo];
    if (!host || !pr || !FX.on('drop')) { if (old) { if (cur) cur.kill(); old.remove(); } return; }
    const sec0 = host.closest('.sec'); if (!sec0) return;
    if (old && (old.dataset.key !== pr.key || old.previousElementSibling !== sec0)) { if (cur) cur.kill(); old.remove(); }
    let sec = $('#fxDrop');
    if (!sec) { sec = mount(sec0, pr); sec.dataset.key = pr.key; sec.dataset.line = '';
      // it plays once, when it first comes into view in the memo
      FX.watch(sec, vis => { if (!vis || sec.dataset.played) return; sec.dataset.played = 1; FX.unwatch(sec); start(sec, pr, true); });
      start(sec, pr, false); sec.dataset.line = draftLine(pr).line; return; }
    const line = String(draftLine(pr).line), w = Math.round(sec.querySelector('.fxd-box').clientWidth);
    if (sec.dataset.line !== line || (cur && cur.sec === sec && Math.abs(cur.W - w) > 4 && w > 0)) start(sec, PMAP[S.memo], false);      // the line moved or the sheet changed size: the settled pile, re-cut, no replay
  });
  document.addEventListener('click', e => { const b = e.target.closest && e.target.closest('[data-fxdrop]'); if (!b) return; const sec = $('#fxDrop'), pr = S.memo && PMAP[S.memo]; if (sec && pr) { sec.dataset.played = 1; start(sec, pr, true); } });
})();
/* ---- 4. Foil cards: the Spotlight's front card has thickness and leans toward your finger (or the phone's tilt, or the scroll);
   an A, AA or AAA pick carries a foil sheen that slides as it leans. ---- */
(() => {
  FX.reg(() => {
    if (!FX.on('foil')) return; const fan = $('#spFan'); if (!fan) return;
    fan.querySelectorAll('.sp-c:not([data-fxf])').forEach(c => { c.dataset.fxf = 1; const pr = SPOT[+c.dataset.spot]; let a = null; try { a = pr && assess(pr); } catch (e) {}
      const foil = a && !a.hold && /^A/.test(a.rating);
      c.insertAdjacentHTML('beforeend', `${foil ? '<i class="fx-foil-l" aria-hidden="true"></i>' : ''}<i class="fx-spec" aria-hidden="true"></i>`); if (foil) c.classList.add('fx-foiled'); FX.tiltUse(c); });
  });
  let held = null;
  const lean = e => { if (!held) return; const r = held.r, x = FX.clamp((e.clientX - r.left) / r.width * 2 - 1, -1.4, 1.4), y = FX.clamp((e.clientY - r.top) / r.height * 2 - 1, -1.4, 1.4);
    held.el.style.setProperty('--fx', x.toFixed(3)); held.el.style.setProperty('--fy', y.toFixed(3)); };
  const drop = () => { if (!held) return; const el = held.el; held = null; el.classList.remove('fx-held'); el.style.removeProperty('--fx'); el.style.removeProperty('--fy'); };
  document.addEventListener('pointerdown', e => { if (!FX.on('foil')) return; const c = e.target.closest && e.target.closest('.sp-c[aria-current="true"]'); if (!c) return;
    held = { el: c, r: c.getBoundingClientRect() }; c.classList.add('fx-held'); lean(e); });
  document.addEventListener('pointermove', e => { if (held) lean(e); else if (e.pointerType === 'mouse' && FX.on('foil')) { const c = e.target.closest && e.target.closest('.sp-c[aria-current="true"]');
    if (c) { const r = c.getBoundingClientRect(); c.style.setProperty('--fx', ((e.clientX - r.left) / r.width * 2 - 1).toFixed(3)); c.style.setProperty('--fy', ((e.clientY - r.top) / r.height * 2 - 1).toFixed(3)); c.dataset.fxh = 1; }
    else { const h = document.querySelector('.sp-c[data-fxh]'); if (h) { delete h.dataset.fxh; h.style.removeProperty('--fx'); h.style.removeProperty('--fy'); } } } }, { passive: true });
  document.addEventListener('pointerup', drop); document.addEventListener('pointercancel', drop);
})();

/* ---- 5. Paper tickets: an open ticket can be picked up sideways, leans with the hand, curls at the corner and settles back on a
   spring (a hard flick sends it round once). Settled tickets stack on a spike above the ledger. Nothing is moved or changed. ---- */
(() => {
  let g = null;
  const curl = (el, v) => el.style.setProperty('--curl', v.toFixed(3));
  const set = (el, x, y, r) => { el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) rotate(${r.toFixed(2)}deg)`; };
  document.addEventListener('pointerdown', e => { if (!FX.on('paper') || e.button) return; const tk = e.target.closest && e.target.closest('.cards > .tk, .pk-tk'); if (!tk || e.target.closest('.tk-file')) return;
    if (tk._fxs) { tk._fxs.stop(); tk._fxs = null; }
    const r = tk.getBoundingClientRect(); g = { el: tk, x0: e.clientX, y0: e.clientY, on: false, lx: e.clientX, lt: performance.now(), vx: 0, gy: FX.clamp((e.clientY - r.top) / r.height * 2 - 1, -1, 1), w: r.width, x: 0, y: 0, r: 0 }; });
  document.addEventListener('pointermove', e => { if (!g) return; const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
    if (!g.on) { if (Math.abs(dx) < 9 || Math.abs(dx) < Math.abs(dy) * 1.2) { if (Math.abs(dy) > 14) g = null; return; }
      g.on = true; g.el.classList.add('fx-up'); try { g.el.setPointerCapture(e.pointerId); } catch (x) {} }
    const now = performance.now(), dtm = Math.max(1, now - g.lt); g.vx = FX.lerp(g.vx, (e.clientX - g.lx) / dtm * 1000, .5); g.lx = e.clientX; g.lt = now;
    // rubber band: the further it is pulled, the less it gives
    const lim = g.w * .55, x = lim * Math.tanh((dx - Math.sign(dx) * 9) / lim), y = FX.clamp(dy * .22, -26, 26);
    g.x = x; g.y = y; g.r = (x / g.w) * 9 * (g.gy <= 0 ? 1 : -1) * (.5 + Math.abs(g.gy) * .5) + FX.clamp(g.vx / 900, -4, 4);
    set(g.el, g.x, g.y, g.r); curl(g.el, Math.min(1, Math.abs(x) / (g.w * .3))); });
  const end = () => { if (!g) return; const h = g; g = null; if (!h.on) return; const el = h.el;
    const eat = ev => { ev.stopPropagation(); ev.preventDefault(); }; el.addEventListener('click', eat, { capture: true, once: true }); setTimeout(() => el.removeEventListener('click', eat, { capture: true }), 150);      // the release of a drag is not a tap
    const spin = Math.abs(h.vx) > 1500 ? Math.sign(h.vx) * 360 * (h.gy <= 0 ? 1 : -1) : 0;      // a hard flick: once round
    if (spin) FX.buzz(8);
    el._fxs = FX.spring([h.x, h.y, h.r - spin], [0, 0, 0], (v, done) => { if (!el.isConnected) return; set(el, v[0], v[1], v[2]); curl(el, Math.min(1, Math.abs(v[0]) / (h.w * .3)));
      if (done) { el.style.transform = ''; el.classList.remove('fx-up'); el.style.removeProperty('--curl'); el._fxs = null; } }, { k: 210, c: spin ? 17 : 13, v: [h.vx * .55, 0, h.vx / 60], eps: .08 }); };
  document.addEventListener('pointerup', end); document.addEventListener('pointercancel', end);

  // the spike
  const fmtRes = b => b.status === 'won' ? 'PAID' : b.status === 'lost' ? 'LOST' : b.status === 'push' ? 'PUSH' : 'VOID';
  const pnl = b => { const u = b.unit != null ? b.unit : (DESK.unit || .5), s = b.usd != null ? b.usd : (b.units || 0) * u; return b.status === 'won' ? s * (E.dec(b.odds) - 1) : b.status === 'lost' ? -s : 0; };
  function spikeHtml(L) {
    const w = L.filter(b => b.status === 'won').length, l = L.filter(b => b.status === 'lost').length, o = L.length - w - l, net = L.reduce((a, b) => a + pnl(b), 0);
    return `<section class="fx-spike" id="fxSpike" aria-label="The last ${L.length} settled tickets: ${w} paid, ${l} lost${o ? ', ' + o + ' void or push' : ''}">
      <div class="fxs-stack" style="--n:${L.length}">${L.slice().reverse().map((b, i) => { const top = i === L.length - 1, M = (MK[b.lg] || {})[b.mkt], r = fmtRes(b), cls = b.status === 'won' ? 'g' : b.status === 'lost' ? 'b' : 'n', rot = (((i * 37 + b.name.length * 13) % 11) - 5) * (top ? .22 : .5), dx = ((i * 53) % 9) - 4;
        return `<div class="fxs-slip ${cls}${top ? ' top' : ''}" style="--i:${i};--r:${rot}deg;--dx:${dx}px"><i></i><span><b>${esc(b.name)}</b> ${esc(b.side)} ${b.line} ${esc(M ? M.s : b.mkt)}</span><em>${r}${b.status === 'won' || b.status === 'lost' ? ' ' + (pnl(b) >= 0 ? '+' : '-') + '$' + Math.abs(pnl(b)).toFixed(2) : ''}</em></div>`; }).join('')}<u class="fxs-pin" aria-hidden="true"></u></div>
      <div class="fxs-cap"><span class="lbl">On the spike</span><b>${w} paid · ${l} lost${o ? ' · ' + o + ' void' : ''}</b><small>last ${L.length} settled, ${S.lg}, ${net >= 0 ? '+' : '-'}$${Math.abs(net).toFixed(2)}</small><button class="btn ghost sm" data-fxa2="riffle">Riffle</button></div></section>`;
  }
  FX.reg(() => {
    const m = $('#main'); if (!m || S.tab !== 'desk') return; const old = $('#fxSpike');
    if (!FX.on('paper')) { if (old) old.remove(); return; }
    const led = m.querySelector(':scope > .ledger'); if (!led || old) return;
    const L = DESK.bets.filter(b => b.lg === S.lg && !b.superseded && b.status !== 'open').slice(-12); if (L.length < 2) return;
    led.insertAdjacentHTML('beforebegin', spikeHtml(L)); const sp = $('#fxSpike');
    FX.watch(sp, vis => { if (vis) { sp.classList.add('in'); FX.unwatch(sp); } });
    m.querySelectorAll('.cards > .tk:not([data-fxc])').forEach(t => { t.dataset.fxc = 1; t.insertAdjacentHTML('beforeend', '<i class="fx-curl" aria-hidden="true"></i>'); });
  });
  FX.reg(() => { if (!FX.on('paper')) return; document.querySelectorAll('.cards > .tk:not([data-fxc]), .pk-tk:not([data-fxc])').forEach(t => { t.dataset.fxc = 1; t.insertAdjacentHTML('beforeend', '<i class="fx-curl" aria-hidden="true"></i>'); }); });
  document.addEventListener('click', e => { const b = e.target.closest && e.target.closest('[data-fxa2="riffle"], .fxs-stack'); if (!b) return; const sp = $('#fxSpike'); if (!sp) return;
    sp.classList.remove('riffle'); void sp.offsetWidth; sp.classList.add('riffle'); FX.buzz(6); setTimeout(() => sp.classList.remove('riffle'), 1400); });
})();
/* ---- 6. Fire and frost, drawn live in the same chunky pixels as the dragons. Fire: a small heat grid under each hot number
   (every cell cools and drifts as it rises), so no two flames are alike. Frost: crystals grow in from the edges of a cold
   card along branching paths; a finger or the pointer wipes them off and they grow back. Runs only for cards on screen. ---- */
(() => {
  const PAL = (() => { const p = []; for (let i = 0; i < 37; i++) { const t = i / 36; let r, g, b, a;
      if (t < .25) { r = 120 + t * 4 * 110; g = 20 * t * 4; b = 8; a = t * 4 * .7; } else if (t < .6) { const u = (t - .25) / .35; r = 235 + u * 20; g = 30 + u * 130; b = 10; a = .75 + u * .2; }
      else { const u = (t - .6) / .4; r = 255; g = 160 + u * 85; b = 20 + u * 170; a = .97; }
      p.push([r | 0, g | 0, b | 0, i ? (a * 255) | 0 : 0]); } return p; })();
  const fires = new Set(), frosts = new Set(); let timer = 0, clock = 0;
  const tick = () => { timer = 0; if (document.hidden) return; clock++; let live = false;
    for (const f of fires) { if (!f.cv.isConnected) { fires.delete(f); continue; } if (f.vis) { f.step(); live = true; } }
    for (const f of frosts) { if (!f.cv.isConnected) { frosts.delete(f); continue; } if (f.vis && f.busy) { f.step(); live = true; } }
    if (live) timer = setTimeout(() => requestAnimationFrame(tick), 48); };      // about 20 frames a second: fire reads better a little choppy
  const kick = () => { if (!timer && FX.on('fire')) timer = setTimeout(() => requestAnimationFrame(tick), 16); };
  document.addEventListener('visibilitychange', kick);

  function fire(t) {
    const r = t.getBoundingClientRect(); if (r.width < 8) return; const cell = 3, W = Math.max(10, Math.ceil((r.width + 18) / cell)), H = Math.max(14, Math.ceil(r.height * 1.7 / cell));
    const cv = document.createElement('canvas'); cv.className = 'fx-fire-cv'; cv.width = W; cv.height = H; cv.setAttribute('aria-hidden', 'true'); t.appendChild(cv); t.dataset.fxfi = 1;
    const c = cv.getContext('2d'), img = c.createImageData(W, H), heat = new Uint8Array(W * H), me = { cv, vis: false };
    me.step = () => {
      for (let x = 0; x < W; x++) { const edge = Math.min(x, W - 1 - x); heat[(H - 1) * W + x] = edge < 3 ? 8 + edge * 7 : 27 + ((Math.random() * 10) | 0); }      // the coals: hottest under the middle of the number
      for (let y = 0; y < H - 1; y++) for (let x = 0; x < W; x++) { const src = (y + 1) * W + x, rnd = (Math.random() * 3) | 0, h = heat[src] - ((Math.random() * (y < H * .45 ? 5.6 : 4.2)) | 0), dx = x - rnd + 1;
        heat[y * W + (dx < 0 ? 0 : dx >= W ? W - 1 : dx)] = h > 0 ? h : 0; }
      const d = img.data; for (let i = 0; i < W * H; i++) { const p = PAL[heat[i] > 36 ? 36 : heat[i]], j = i * 4; d[j] = p[0]; d[j + 1] = p[1]; d[j + 2] = p[2]; d[j + 3] = p[3]; }
      c.putImageData(img, 0, 0); };
    fires.add(me); FX.watch(cv, v => { me.vis = v; if (v) kick(); });
  }

  // v3.40: the ice keeps to the card's rim (about 24px, a little more at the corners) and is thinner. It used to reach 15% of
  // the card's short side with corners at 2.6 times that, which on a tall hit-rate card ran across the name and the numbers.
  function frost(box) {
    const r = box.getBoundingClientRect(); if (r.width < 60) return; const cell = 3, W = Math.ceil(r.width / cell), H = Math.ceil(r.height / cell);
    const cv = document.createElement('canvas'); cv.className = 'fx-frost-cv'; cv.width = W; cv.height = H; cv.setAttribute('aria-hidden', 'true'); box.appendChild(cv); box.dataset.fxfr = 1;
    const c = cv.getContext('2d'), img = c.createImageData(W, H), arrive = new Uint16Array(W * H).fill(65535), amt = new Uint8Array(W * H), wiped = new Int32Array(W * H);
    // crystals: walkers leave the edges and wander inward, branching; each cell remembers when the ice reaches it and how thick it gets
    let seed = (W * 73856093) ^ (H * 19349663); const R = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    const reach = Math.min(Math.min(W, H) * .15, 8), walk = (x, y, ang, step, life, thick) => { while (life-- > 0) { const xi = x | 0, yi = y | 0; if (xi < 0 || yi < 0 || xi >= W || yi >= H) return;
        const dEdge = Math.min(xi, yi, W - 1 - xi, H - 1 - yi); if (dEdge > reach * (.55 + R() * .6)) return;
        const i = yi * W + xi; if (step < arrive[i]) arrive[i] = step; amt[i] = Math.max(amt[i], Math.min(255, thick * (1 - dEdge / (reach * 1.25)) * 255) | 0);
        ang += (R() - .5) * .16; x += Math.cos(ang); y += Math.sin(ang); step += 1 + (R() * 2 | 0);
        if (R() < .16 && thick > .25) walk(x, y, ang + (R() < .5 ? 1 : -1) * (Math.PI / 3), step, (life * .6) | 0, thick * .8); } };
    const per = 2 * (W + H), n = Math.round(per / 6);
    for (let k = 0; k < n; k++) { const q = R() * per; let x, y, a; if (q < W) { x = q; y = 0; a = Math.PI / 2; } else if (q < 2 * W) { x = q - W; y = H - 1; a = -Math.PI / 2; } else if (q < 2 * W + H) { x = 0; y = q - 2 * W; a = 0; } else { x = W - 1; y = q - 2 * W - H; a = Math.PI; }
      const corner = Math.min(x, W - 1 - x) + Math.min(y, H - 1 - y) < reach; walk(x, y, a + (R() - .5) * 1.1, (R() * 30) | 0, (reach * (corner ? 1.9 : 1.1)) | 0, corner ? 1 : .62); }
    const me = { cv, vis: false, busy: true, t0: clock, box };
    me.step = () => { const d = img.data, now = (clock - me.t0) * 3; let grow = false;
      for (let i = 0; i < W * H; i++) { const j = i * 4, a = arrive[i]; if (a === 65535) { d[j + 3] = 0; continue; }
        const age = now - wiped[i] - a; if (age < 0) { d[j + 3] = 0; grow = true; continue; }
        const k = age > 24 ? 1 : age / 24; if (k < 1) grow = true; const v = amt[i]; d[j] = 205 + (v >> 3); d[j + 1] = 232 + (v >> 4); d[j + 2] = 255; d[j + 3] = (v * k * .55) | 0; }
      c.putImageData(img, 0, 0); me.busy = grow; };
    me.wipe = (px, py) => { const cx = px / cell, cy = py / cell, rad = 9, now = (clock - me.t0) * 3; let hit = false;
      for (let y = Math.max(0, (cy - rad) | 0); y < Math.min(H, cy + rad); y++) for (let x = Math.max(0, (cx - rad) | 0); x < Math.min(W, cx + rad); x++) { if ((x - cx) * (x - cx) + (y - cy) * (y - cy) > rad * rad) continue; const i = y * W + x; if (arrive[i] !== 65535) { wiped[i] = now + 60; hit = true; } }      // it stays clear a moment, then the ice creeps back
      if (hit) { me.busy = true; kick(); } };
    box._fxFrost = me; frosts.add(me); FX.watch(cv, v => { me.vis = v; if (v) kick(); });
  }
  FX.reg(() => {
    if (!FX.on('fire')) return;
    document.querySelectorAll('.drg-t.hot.lit:not([data-fxfi])').forEach(fire);
    document.querySelectorAll('.drg-t.cold.lit').forEach(t => { const box = t.closest('.row, article'); if (box && !box.dataset.fxfr) frost(box); });
  });
  // the dragons add .lit by class, which the page observer does not report: look again shortly after one lands
  FX.atBoot(() => { new MutationObserver(ms => { for (const m of ms) if (m.target.classList && m.target.classList.contains('drg-t')) { FX.queue(); return; } }).observe($('#main'), { attributes: true, attributeFilter: ['class'], subtree: true }); });
  const wipeAt = (x, y, target) => { const box = target && target.closest && target.closest('[data-fxfr]'); if (!box || !box._fxFrost) return; const r = box.getBoundingClientRect(); box._fxFrost.wipe(x - r.left, y - r.top); };
  document.addEventListener('pointermove', e => { if (e.pointerType === 'mouse') wipeAt(e.clientX, e.clientY, e.target); }, { passive: true });
  document.addEventListener('touchmove', e => { const t = e.touches[0]; if (t) wipeAt(t.clientX, t.clientY, document.elementFromPoint(t.clientX, t.clientY)); }, { passive: true });
  document.addEventListener('touchstart', e => { const t = e.touches[0]; if (t) wipeAt(t.clientX, t.clientY, e.target); }, { passive: true });
})();
/* ---- 7. Press lever: a brass lever on the side of the parlay press. Pull it down past the stop and it packs (the same thing the
   Pack it button does, which stays). When the ram lands: sparks, a jolt, and a short buzz on phones that have one. ---- */
(() => {
  let d = null;
  const travel = el => el.clientHeight - 30;
  const put = (lv, y) => { lv._y = y; lv.querySelector('.fx-lv-h').style.transform = `translate3d(0,${y.toFixed(1)}px,0)`; lv.querySelector('.fx-lv-r').style.transform = `scaleY(${(y / Math.max(1, travel(lv))).toFixed(3)})`; };
  const back = lv => { if (lv._sp) lv._sp.stop(); lv._sp = FX.spring([lv._y || 0], [0], (v, done) => { if (!lv.isConnected) return; put(lv, Math.max(0, v[0])); if (done) lv._sp = null; }, { k: 260, c: 15, eps: .1 }); };
  FX.reg(() => {
    const m = document.querySelector('#pk .pk-m'), old = $('#fxLever'); if (!m) return;
    if (!FX.on('lever')) { if (old) old.remove(); return; } if (old) return;
    m.insertAdjacentHTML('beforeend', `<div class="fx-lv" id="fxLever" role="slider" tabindex="0" aria-label="Press lever. Pull down to pack the parlay." aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i class="fx-lv-t"></i><i class="fx-lv-r"></i><b class="fx-lv-h"></b></div><canvas class="fx-sparks" id="fxSparks" aria-hidden="true"></canvas>`);
  });
  const ready = () => { const b = $('#pkGo'); return b && !b.disabled; };
  document.addEventListener('pointerdown', e => { const h = e.target.closest && e.target.closest('#fxLever'); if (!h || !FX.on('lever')) return; e.preventDefault(); if (h._sp) { h._sp.stop(); h._sp = null; }
    d = { lv: h, y0: e.clientY - (h._y || 0), ok: ready() }; try { h.setPointerCapture(e.pointerId); } catch (x) {} h.classList.add('held'); });
  document.addEventListener('pointermove', e => { if (!d) return; const T = travel(d.lv); let y = e.clientY - d.y0;
    y = d.ok ? FX.clamp(y, 0, T) : FX.clamp(T * .28 * Math.tanh(y / (T * .5)), 0, T);      // nothing to pack: it gives a little and no more
    if (d.ok && y >= T - 1 && (d.lv._y || 0) < T - 1) FX.buzz(10);
    put(d.lv, y); d.lv.setAttribute('aria-valuenow', Math.round(y / T * 100)); });
  const up = () => { if (!d) return; const lv = d.lv, T = travel(lv), go = d.ok && (lv._y || 0) > T * .72; d = null; lv.classList.remove('held');
    if (go) { put(lv, T); const b = $('#pkGo'); if (b) b.click(); setTimeout(() => back(lv), 520); } else { if (!ready() && (lv._y || 0) > 6) { const r = $('#pkSt'); if (r && r.animate) r.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-3px)' }, { transform: 'translateX(3px)' }, { transform: 'translateX(0)' }], { duration: 220 }); } back(lv); }
    lv.setAttribute('aria-valuenow', 0); };
  document.addEventListener('pointerup', up); document.addEventListener('pointercancel', up);
  document.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') && e.target.id === 'fxLever') { e.preventDefault(); const b = $('#pkGo'); if (b && !b.disabled) { put(e.target, travel(e.target)); b.click(); setTimeout(() => back(e.target), 520); } } });

  function sparks() {
    const cv = $('#fxSparks'), ram = $('#pkRam'), m = cv && cv.parentElement; if (!cv || !ram || !m) return;
    const mr = m.getBoundingClientRect(), rr = ram.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1), W = mr.width, H = mr.height;
    cv.width = W * dpr; cv.height = H * dpr; const c = cv.getContext('2d'); c.scale(dpr, dpr);
    const y0 = rr.bottom - mr.top, xa = rr.left - mr.left + rr.width * .08, xb = rr.right - mr.left - rr.width * .08, P = [];
    for (let i = 0; i < 54; i++) { const side = i % 2 ? 1 : -1, x = side > 0 ? xb - Math.random() * 14 : xa + Math.random() * 14, sp = 90 + Math.random() * 260, a = (side > 0 ? -.15 : Math.PI + .15) + (Math.random() - .5) * 1.1 * -side;
      P.push({ x, y: y0, vx: Math.cos(a) * sp, vy: -Math.abs(Math.sin(a)) * sp - 40 - Math.random() * 120, l: .35 + Math.random() * .45, t: 0 }); }
    let last = 0; const step = now => { if (!cv.isConnected) return; const dt = Math.min(.04, last ? (now - last) / 1000 : .016); last = now; c.clearRect(0, 0, W, H); let live = 0; c.lineCap = 'round';
      for (const p of P) { p.t += dt; if (p.t > p.l) continue; live++; const ox = p.x, oy = p.y; p.vy += 900 * dt; p.x += p.vx * dt; p.y += p.vy * dt; const k = 1 - p.t / p.l;
        c.strokeStyle = `rgba(255,${(170 + 70 * k) | 0},${(60 + 150 * k * k) | 0},${k})`; c.lineWidth = 1 + k * 1.3; c.beginPath(); c.moveTo(ox, oy); c.lineTo(p.x, p.y); c.stroke(); }
      if (live) requestAnimationFrame(step); else c.clearRect(0, 0, W, H); };
    requestAnimationFrame(step);
    const pk = $('#pk'); if (pk && pk.animate) pk.animate([{ transform: 'translate3d(0,0,0)' }, { transform: 'translate3d(0,5px,0) rotate(.25deg)' }, { transform: 'translate3d(0,-3px,0) rotate(-.2deg)' }, { transform: 'translate3d(0,2px,0)' }, { transform: 'translate3d(0,0,0)' }], { duration: 300, easing: 'cubic-bezier(.3,.6,.4,1)' });
    FX.buzz([18, 30, 12]);
  }
  FX.atBoot(() => { let t = 0; new MutationObserver(ms => { for (const m of ms) { if (m.target.id !== 'pk' || m.target.dataset.st !== 'seal' || !FX.on('lever')) continue; clearTimeout(t); t = setTimeout(sparks, 385); } }).observe($('#main'), { attributes: true, attributeFilter: ['data-st'], subtree: true }); });
})();

/* ---- 8. Case unfold: when a folding phone opens, the covers are the two halves of a case. The latches flip, the lids swing open on
   springs, and a soft crease stays at the hinge. Closing runs it the other way. Still triggered by the jump in page width. ---- */
(() => {
  let seenFold = false;
  const squareish = () => { const r = innerWidth / innerHeight; return innerWidth >= 700 && innerWidth <= 1400 && r > .72 && r < 1.45; };
  const crease = () => { const want = FX.on('hinge') && innerWidth >= 700 && (seenFold || (matchMedia('(horizontal-viewport-segments: 2)').matches) || (matchMedia('(pointer: coarse)').matches && squareish())); let c = $('#fxCrease');
    if (want && !c) { c = document.createElement('i'); c.id = 'fxCrease'; c.className = 'fx-crease'; c.setAttribute('aria-hidden', 'true'); document.body.appendChild(c); } else if (!want && c) c.remove(); };
  FX.reg(crease); addEventListener('resize', () => setTimeout(crease, 400));
  FX.hinge = (el0, open) => {
    if (!FX.on('hinge')) return false; seenFold = true;
    document.querySelectorAll('.fx-case').forEach(n => n.remove());
    const el = document.createElement('div'); el.className = 'fx-case ' + (open ? 'open' : 'shut'); el.setAttribute('aria-hidden', 'true');
    const lid = (side, word) => `<i class="fx-lid ${side}"><s class="fx-lid-in"><em>${word}</em><u class="c1"></u><u class="c2"></u></s></i>`;
    el.innerHTML = lid('l', 'Fair') + lid('r', 'Line') + '<b class="fx-latch a"></b><b class="fx-latch b"></b>'; document.body.appendChild(el);
    const [L, R, la, lb] = el.children, sp = 'cubic-bezier(.3,1.35,.5,1)', sw = 'cubic-bezier(.5,0,.2,1)';
    const P = 'perspective(1700px) ';
    if (open) {
      [la, lb].forEach((n, i) => n.animate([{ transform: 'translate(-50%,0) rotateX(0deg)' }, { transform: 'translate(-50%,0) rotateX(-150deg)', opacity: 1, offset: .8 }, { transform: 'translate(-50%,0) rotateX(-150deg)', opacity: 0 }], { duration: 300, delay: 220 + i * 90, easing: sp, fill: 'both' }));
      L.animate([{ transform: P + 'rotateY(0deg)' }, { transform: P + 'rotateY(-104deg)' }], { duration: 950, delay: 620, easing: sw, fill: 'both' });
      R.animate([{ transform: P + 'rotateY(0deg)' }, { transform: P + 'rotateY(104deg)' }], { duration: 950, delay: 620, easing: sw, fill: 'both' });
      el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, delay: 1380, fill: 'both' }); setTimeout(() => { el.remove(); crease(); }, 1700);
      FX.buzz([8, 60, 8]);
    } else {
      L.animate([{ transform: P + 'rotateY(-104deg)' }, { transform: P + 'rotateY(0deg)' }], { duration: 620, easing: sp, fill: 'both' });
      R.animate([{ transform: P + 'rotateY(104deg)' }, { transform: P + 'rotateY(0deg)' }], { duration: 620, easing: sp, fill: 'both' });
      [la, lb].forEach((n, i) => n.animate([{ transform: 'translate(-50%,0) rotateX(-150deg)', opacity: 0 }, { transform: 'translate(-50%,0) rotateX(-150deg)', opacity: 1, offset: .1 }, { transform: 'translate(-50%,0) rotateX(0deg)', opacity: 1 }], { duration: 240, delay: 600 + i * 80, easing: sp, fill: 'both' }));
      el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 280, delay: 1150, fill: 'both' }); setTimeout(() => { el.remove(); crease(); }, 1460);
    }
    return true;
  };
})();
/* ---- 10. Morning reveal: the last settled night, one ticket at a time. Each ticket lands, takes its stamp, and the units counter rolls.
   Winners go on the paid pile; losers crumple and drop in the bin. It plays by itself once per settled night when the desk opens,
   and again from Your book, Effects, Replay last night. It reads the record; it never changes it. ---- */
(() => {
  const SEEN = 'fl-fx-night';
  const uOf = b => b.status === 'won' ? (E.dec(b.odds) - 1) * b.units : b.status === 'lost' ? -b.units : 0;
  const usdOf = b => uOf(b) * (b.unit != null ? b.unit : (DESK.unit || .5));
  function night() { const B = DESK.bets.filter(b => !b.superseded && b.status !== 'open'); if (!B.length) return null;
    const date = B.map(b => b.date).sort().pop(); return { date, list: B.filter(b => b.date === date) }; }
  const sgnU = x => (x >= 0 ? '+' : '-') + Math.abs(x).toFixed(2);
  let live = null;
  FX.revealPlay = manual => {
    if (RM() || (!manual && !FX.on('reveal'))) return false; const N = night(); if (!N) return false; if (live) live.close();
    const L = N.list, n = L.length, d = new Date(N.date + 'T12:00:00'), day = isNaN(d) ? N.date : d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    const el = document.createElement('div'); el.className = 'fx-rv'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'Last night at the desk');
    el.innerHTML = `<div class="fx-rv-in"><div class="fx-rv-h"><small>The morning grade</small><b>${esc(day)}</b></div>
      <div class="fx-rv-led"><span><small>Units</small><b id="fxRvU">+0.00</b></span><span><small>Record</small><b id="fxRvR">0-0</b></span><span><small>Paper</small><b id="fxRvD">$0.00</b></span></div>
      <div class="fx-rv-stage" id="fxRvS"><div class="fx-rv-pile" id="fxRvP"><i>Paid</i></div><div class="fx-rv-bin" id="fxRvB"><i></i><u></u></div></div>
      <div class="fx-rv-f"><span class="lbl" id="fxRvC">Ticket 1 of ${n}</span><button class="btn ghost sm" data-fxrv="x">Skip</button></div></div>`;
    document.body.appendChild(el); document.documentElement.classList.add('fx-rv-on');
    const stage = el.querySelector('#fxRvS'), uB = el.querySelector('#fxRvU'), rB = el.querySelector('#fxRvR'), dB = el.querySelector('#fxRvD'), cap = el.querySelector('#fxRvC'), pile = el.querySelector('#fxRvP'), bin = el.querySelector('#fxRvB');
    let units = 0, usd = 0, w = 0, l = 0, dead = false, shownU = 0, raf = 0; const timers = [];
    const wait = ms => new Promise(r => timers.push(setTimeout(r, ms)));
    const roll = () => { cancelAnimationFrame(raf); const from = shownU, to = units, t0 = performance.now(); const step = now => { const q = Math.min(1, (now - t0) / 420), v = from + (to - from) * (1 - Math.pow(1 - q, 3)); shownU = v; uB.textContent = sgnU(v); uB.className = v > .004 ? 'gd' : v < -.004 ? 'bd' : ''; if (q < 1 && !dead) raf = requestAnimationFrame(step); }; raf = requestAnimationFrame(step);
      rB.textContent = `${w}-${l}`; dB.textContent = (usd >= 0 ? '+$' : '-$') + Math.abs(usd).toFixed(2); dB.className = usd > 0 ? 'gd' : usd < 0 ? 'bd' : ''; };
    const finish = () => { units = L.reduce((a, b) => a + uOf(b), 0); usd = L.reduce((a, b) => a + usdOf(b), 0); w = L.filter(b => b.status === 'won').length; l = L.filter(b => b.status === 'lost').length; roll();
      stage.querySelectorAll('.fx-rv-tk').forEach(t => t.remove()); const o = n - w - l;
      stage.insertAdjacentHTML('beforeend', `<div class="fx-rv-sum"><b class="${units >= 0 ? 'gd' : 'bd'}">${units >= 0 ? 'A winning night' : units === 0 ? 'Flat' : 'A losing night'}</b><span>${w} paid, ${l} lost${o ? ', ' + o + ' void or push' : ''}. ${sgnU(units)} units on paper.</span></div>`);
      cap.textContent = `${n} ticket${n === 1 ? '' : 's'} graded`; el.querySelector('[data-fxrv]').textContent = 'Close'; el.querySelector('[data-fxrv]').dataset.fxrv = 'close'; el.classList.add('done'); };
    const close = () => { if (dead && !el.isConnected) return; dead = true; timers.forEach(clearTimeout); cancelAnimationFrame(raf); live = null; document.documentElement.classList.remove('fx-rv-on');
      const a = el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, fill: 'forwards' }); a.onfinish = () => el.remove(); setTimeout(() => el.remove(), 260); };
    let skipped = false; const skip = () => { if (skipped) return; skipped = true; timers.forEach(clearTimeout); finish(); };
    el.addEventListener('click', e => { const b = e.target.closest('[data-fxrv]'); if (b) { b.dataset.fxrv === 'close' ? close() : skip(); return; } if (el.classList.contains('done') && !e.target.closest('.fx-rv-in')) close(); });
    const onKey = e => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } }; document.addEventListener('keydown', onKey);
    live = { close };
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240, fill: 'backwards' });
    const pace = n > 9 ? .62 : n > 5 ? .8 : 1;
    (async () => {
      await wait(520);
      for (let i = 0; i < n && !skipped && !dead; i++) { const b = L[i], M = (MK[b.lg] || {})[b.mkt], won = b.status === 'won', lost = b.status === 'lost', word = won ? 'PAID' : lost ? 'LOST' : b.status === 'push' ? 'PUSH' : 'VOID', cls = won ? 'g' : lost ? 'b' : 'n';
        cap.textContent = `Ticket ${i + 1} of ${n}`;
        const tk = document.createElement('div'); tk.className = 'fx-rv-tk'; tk.style.cssText = tcol(b.lg, b.team);
        tk.innerHTML = `<i class="st"></i><small>${esc(b.lg)} · ${esc(b.gl || '')}</small><b>${esc(b.name)}</b><span>${esc(b.side)} ${b.line} ${esc(M ? M.n.toLowerCase() : b.mkt)}</span><em>${odds(b.odds)} · ${b.units}u${b.result != null ? ' · finished with ' + esc(b.result) : ''}</em><strong class="fx-rv-stamp ${cls}">${word}</strong>`;
        stage.appendChild(tk); const rot = ((i * 37) % 9) - 4;
        tk.animate([{ transform: `translate3d(0,120%,0) rotate(${rot * 3}deg) scale(.9)`, opacity: 0 }, { transform: `translate3d(0,0,0) rotate(${rot}deg) scale(1)`, opacity: 1 }], { duration: 420 * pace, easing: 'cubic-bezier(.2,1.2,.35,1)', fill: 'both' });
        await wait(480 * pace); if (skipped || dead) break;
        const st = tk.querySelector('.fx-rv-stamp'); st.animate([{ transform: 'rotate(-9deg) scale(2.6)', opacity: 0 }, { transform: 'rotate(-9deg) scale(.94)', opacity: 1, offset: .7 }, { transform: 'rotate(-9deg) scale(1)', opacity: 1 }], { duration: 190, easing: 'cubic-bezier(.5,0,1,.5)', fill: 'both' });
        await wait(150); if (skipped || dead) break;
        el.querySelector('.fx-rv-in').animate([{ transform: 'translate3d(0,0,0)' }, { transform: `translate3d(${won ? 0 : 3}px,4px,0)` }, { transform: 'translate3d(0,-2px,0)' }, { transform: 'translate3d(0,0,0)' }], { duration: 200 }); FX.buzz(won ? [14, 40, 14] : 14);
        units += uOf(b); usd += usdOf(b); if (won) w++; if (lost) l++; roll();
        if (won) for (let k = 0; k < 12; k++) { const s = document.createElement('i'); s.className = 'fx-rv-sp'; tk.appendChild(s); const a = (k / 12) * Math.PI * 2 + i, r = 70 + (k * 29 % 50);
          s.animate([{ transform: 'translate3d(0,0,0) scale(1)', opacity: 1 }, { transform: `translate3d(${(Math.cos(a) * r).toFixed(0)}px,${(Math.sin(a) * r * .7 - 20).toFixed(0)}px,0) scale(.2)`, opacity: 0 }], { duration: 560, easing: 'cubic-bezier(.1,.8,.3,1)', fill: 'both' }); }
        await wait(620 * pace); if (skipped || dead) break;
        const sr = stage.getBoundingClientRect(), tr = tk.getBoundingClientRect(), to = (won ? pile : bin).getBoundingClientRect(), dx = to.left + to.width / 2 - (tr.left + tr.width / 2), dy = to.top + to.height / 2 - (tr.top + tr.height / 2);
        if (lost) { tk.classList.add('crumple'); tk.animate([{ transform: `translate3d(0,0,0) rotate(${rot}deg) scale(1)`, borderRadius: '10px' }, { transform: `translate3d(0,-14px,0) rotate(${rot + 14}deg) scale(.42,.36)`, borderRadius: '46%', offset: .45 }, { transform: `translate3d(${dx}px,${dy - 46}px,0) rotate(${rot + 200}deg) scale(.2)`, borderRadius: '50%', offset: .82 }, { transform: `translate3d(${dx}px,${dy}px,0) rotate(${rot + 260}deg) scale(.16)`, borderRadius: '50%', opacity: 0 }], { duration: 640 * pace, easing: 'cubic-bezier(.4,0,.6,1)', fill: 'both' });
          timers.push(setTimeout(() => bin.animate([{ transform: 'rotate(0)' }, { transform: 'rotate(-5deg)' }, { transform: 'rotate(4deg)' }, { transform: 'rotate(0)' }], { duration: 260 }), 520 * pace)); }
        else { tk.animate([{ transform: `translate3d(0,0,0) rotate(${rot}deg) scale(1)`, opacity: 1 }, { transform: `translate3d(${dx}px,${dy}px,0) rotate(${won ? -6 + (w * 5 % 9) : 0}deg) scale(.24)`, opacity: won ? 1 : 0 }], { duration: 460 * pace, easing: 'cubic-bezier(.5,0,.2,1)', fill: 'both' });
          if (won) timers.push(setTimeout(() => { pile.dataset.n = w; pile.classList.add('has'); }, 440 * pace)); }
        await wait((lost ? 560 : 420) * pace); tk.remove(); void sr; }
      if (!dead && !skipped) { skipped = true; finish(); }
    })();
    return true;
  };
  FX.atBoot(() => { if (!FX.on('reveal') || S.tab !== 'desk') return; const N = night(); if (!N) return; let seen = ''; try { seen = localStorage.getItem(SEEN) || ''; } catch (e) { return; }
    if (seen >= N.date) return; try { localStorage.setItem(SEEN, N.date); } catch (e) { return; }
    setTimeout(() => { if (S.tab === 'desk' && !S.memo && !document.hidden) FX.revealPlay(false); }, 900); });
})();
