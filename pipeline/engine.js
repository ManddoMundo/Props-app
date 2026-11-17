/* Projection engine. Pure functions, shared by the page and the Node check. */
const E = (() => {
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const nbK = (mu, a, b) => clamp(Math.exp(a + b * Math.log(Math.max(mu, 1e-6))), 0.05, 400);

  function pmf(mu, k) {
    mu = Math.max(mu, 1e-4);
    const p = k / (k + mu), q = 1 - p;
    let v = Math.exp(k * Math.log(p)), c = v, n = 0;
    const out = [v];
    while (c < 1 - 1e-7 && n < 3000) { v = v * (n + k) / (n + 1) * q; n++; out.push(v); c += v; }
    return out;
  }
  function split(d, line) {
    let under = 0, push = 0, over = 0;
    for (let n = 0; n < d.length; n++) { if (n < line) under += d[n]; else if (n === line) push += d[n]; else over += d[n]; }
    return { over, under, push };
  }
  function quantile(d, q) { let c = 0; for (let n = 0; n < d.length; n++) { c += d[n]; if (c >= q) return n; } return d.length - 1; }
  function fairLine(d) {
    let c = 0, best = 0.5, gap = 9;
    for (let n = 0; n < d.length; n++) { c += d[n]; const g = Math.abs(1 - c - 0.5); if (g < gap) { gap = g; best = n + 0.5; } }
    return best;
  }

  /* ---------- NFL: team volume x share x efficiency ---------- */
  function nflSide(model, side, roster, isActive) {
    const act = roster.filter(isActive);
    let St = side.rest[0], Sc = side.rest[1], Sa = side.rest[2];
    for (const p of act) { St += p.ts; Sc += p.cs; if (p.pos === 'QB') Sa += p.as_; }
    const b = model.beta, c = model.cal, out = {};
    for (const p of act) {
      const tsn = p.ts * Math.pow(Math.max(St, 1e-9), -b), csn = p.cs * Math.pow(Math.max(Sc, 1e-9), -b);
      const asn = p.pos === 'QB' ? Math.min(p.as_ / Math.max(Sa, 1e-6), 1) * 0.985 : 0;
      const tgt = side.PA * model.tpa * tsn, car = side.CAR * csn, att = side.PA * asn;
      const L = (k, v) => (model.lin && model.lin[k] ? Math.max(0.05, model.lin[k][0] + model.lin[k][1] * v) : v);
      out[p.id] = {
        parts: { PA: side.PA, CAR: side.CAR, tsn, csn, asn, tgt, car: car * c.rush_att, att: att * c.pass_att, padj: side.padj, radj: side.radj, tdadj: side.tdadj },
        mu: {
          rec: L('rec', tgt * p.cr * c.rec), rec_yds: L('rec_yds', tgt * p.cr * p.ypr * side.padj * c.rec_yds),
          rush_att: L('rush_att', car * c.rush_att), rush_yds: L('rush_yds', car * p.ypc * side.radj * c.rush_yds),
          pass_att: L('pass_att', att * c.pass_att), pass_cmp: L('pass_cmp', att * p.cp * c.pass_cmp), pass_yds: L('pass_yds', att * p.ypa * side.padj * c.pass_yds),
          pass_td: L('pass_td', att * p.ptd * side.tdadj * c.pass_td), td: (tgt * p.rtd + car * p.rutd) * side.tdadj * c.td, tgt,
        },
      };
    }
    return out;
  }

  /* ---------- NBA: minutes x per-minute rate, re-balanced to the team total ---------- */
  const NBA_BASE = ['pts', 'reb', 'ast', 'fg3'];
  const NBA_COMBO = { pra: ['pts', 'reb', 'ast'], pr: ['pts', 'reb'], pa: ['pts', 'ast'], ra: ['reb', 'ast'] };
  function nbaSide(model, side, roster, isActive) {
    const act = roster.filter(isActive);
    let tot = 0, W = 0;
    for (const p of act) { tot += p.m; W += p.m * Math.max(38 - p.m, 0.5); }
    const out = {}, mins = {};
    for (const p of act) {
      const up = p.m + (240 - tot) * (p.m * Math.max(38 - p.m, 0.5)) / W;
      mins[p.id] = Math.min(p.m + model.bm * ((tot < 240 ? up : p.m * 240 / tot) - p.m), 40);
      out[p.id] = { parts: { m: p.m, mn: mins[p.id], boost: {} }, mu: {} };
    }
    for (const k of NBA_BASE) {
      let R = 0;
      for (const p of act) R += mins[p.id] * p.r[k];
      const boost = Math.pow(side.T[k] / R, model.bs[k]) * model.cal[k];
      const ln = model.lin && model.lin[k];
      for (const p of act) { const raw = mins[p.id] * p.r[k] * boost; out[p.id].mu[k] = ln ? Math.max(0.05, ln[0] + ln[1] * raw) : raw; out[p.id].parts.boost[k] = boost; }
    }
    for (const p of act) for (const c in NBA_COMBO) out[p.id].mu[c] = NBA_COMBO[c].reduce((s, k) => s + out[p.id].mu[k], 0);
    return out;
  }

  /* ---------- pricing ---------- */
  const dec = a => (a > 0 ? 1 + a / 100 : 1 + 100 / -a);
  const amer = p => (p <= 0 || p >= 1 ? null : p >= 0.5 ? -Math.round(100 * p / (1 - p)) : Math.round(100 * (1 - p) / p));
  // expected profit per 1 staked; a push returns the stake
  const ev = (pWin, pLose, odds) => pWin * (dec(odds) - 1) - pLose;
  const kelly = (pWin, pLose, odds) => { const b = dec(odds) - 1; return Math.max(0, (pWin * b - pLose) / b); };

  return { nbK, pmf, split, quantile, fairLine, nflSide, nbaSide, dec, amer, ev, kelly, NBA_BASE, NBA_COMBO };
})();
if (typeof module !== 'undefined') module.exports = E;
