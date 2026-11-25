"""Lab, v3.52 (research only; nothing here runs in the daily job and nothing in the desk is changed).
Replays the saved midday lines under different ways of building the market number, to test the pricing changes that
were proposed for v3.52 and NOT made: the power de-vig as the live de-vig, and a leave-one-out weighted average of the
other books in place of the median of all books.

For each saved day it rebuilds every side the way price_all() does, from: the day's lines file (out/lines), the day's
priced file (the model's own number, slate history, minutes and flags as they stood that day) and the results in
audit.json. The weight on the model is the one the desk used that day (read back from the priced rows).
Variants:  live      plain de-vig, median of all books (v3.51)
           power     power de-vig, median of all books
           loo_med   plain de-vig, median of the OTHER books (the book being priced left out)
           loo_wavg  plain de-vig, weighted average of the other books (CFG mk_w)
           package   power de-vig, weighted average of the other books (the proposed v3.52)
Run from /home/claude/props/src or lab: python3 policy_replay.py"""
import glob, json, os, re, sys
sys.path.insert(0, "/home/claude/props/src")
import numpy as np
import daily as D
from daily import CFG, MK, dec, probs, implied_mean, power_fair, parse, norm, eligible, centre

O = D.O
DATA, _ = D.load()
A = json.load(open(O + "audit.json"))
VAR = {"live": (0, "med_all"), "power": (1, "med_all"), "loo_med": (0, "med_oth"), "loo_wavg": (0, "wavg_oth"), "package": (1, "wavg_oth")}
W_FIXED = None      # set to a number to price every market at that weight on the model
COMPUTED = ("large edge, check news", "no market check", "model far from market, check news")


def cons(imp, how, bk=None):
    if how == "med_all":
        v = list(imp.values()); return (float(np.median(v)) if v else None), max(len(v) - 1, 0)
    it = [(v, CFG["mk_w"].get(k, 1.0)) for k, v in imp.items() if k != bk]
    if not it: return None, 0
    if how == "med_oth": return float(np.median([v for v, _ in it])), len(it)
    return float(sum(v * w for v, w in it) / sum(w for _, w in it)), len(it)


def day(lg, date):
    L = DATA[lg]
    pr = json.load(open(O + f"priced/{lg}_{date}.json"))
    if not any(b.get("ver") for b in pr): return None
    base = {}
    for b in pr:
        base.setdefault((norm(b["name"]), b["mkt"]), []).append(b)
    wd = {}
    for b in pr:      # the weight the desk used that day, per market
        if b.get("mm") is None: continue
        den = b["cen"] * b["mu"] - b["mm"]
        if abs(den) >= 0.4: wd.setdefault(b["mkt"], []).append((b["muf"] - b["mm"]) / den)
    wd = {k: float(np.clip(np.median(v), 0, 1)) for k, v in wd.items()}
    quotes = {}
    for r in parse(O + f"lines/{lg}_{date}.txt"):
        quotes.setdefault((norm(r["player"]), r["market"]), {})[r["book"]] = r
    rows = []
    for (nm, market), books in quotes.items():
        mkt = MK[lg].get(market)
        if not mkt or mkt == "any_td" or (nm, mkt) not in base or mkt not in L["model"]["disp"]: continue
        if len({b["pid"] for b in base[(nm, mkt)]}) != 1: continue
        good = {bk: x for bk, x in books.items() if x["line"] is not None and x["o"] is not None and x["u"] is not None and CFG["sane"][0] <= 1 / dec(x["o"]) + 1 / dec(x["u"]) <= CFG["sane"][1]}
        bet = {bk: x for bk, x in good.items() if bk in CFG["bet_books"]}
        if not bet: continue
        imp = [{}, {}]
        for bk, x in good.items():
            po, pu = 1 / dec(x["o"]), 1 / dec(x["u"])
            imp[0][bk] = implied_mean(L, lg, mkt, x["line"], po / (po + pu)); imp[1][bk] = implied_mean(L, lg, mkt, x["line"], power_fair(x["o"], x["u"]))
        rows.append(dict(b=base[(nm, mkt)][0], bs=base[(nm, mkt)], mkt=mkt, bet=bet, imp=imp))
    out = {}
    for vn, (dv, how) in VAR.items():
        cen = {}
        for mkt in {x["mkt"] for x in rows}:
            z = [(x["b"]["mu"], cons(x["imp"][dv], "med_all" if how == "med_all" else how)) for x in rows if x["mkt"] == mkt]
            g = [(mu, m) for mu, (m, n) in z if m is not None and n >= CFG["min_books"]] or [(mu, m) for mu, (m, n) in z if m is not None]
            cen[mkt] = centre(g)
        sides = []
        for x in rows:
            b, mkt = x["b"], x["mkt"]; mu = b["mu"]; c0 = cen[mkt]; w = wd.get(mkt, CFG["cal_w0"]) if W_FIXED is None else W_FIXED
            flags0 = [f for f in b["flags"] if f not in COMPUTED]
            cb = b["conf"] / (0.85 if "large edge, check news" in b["flags"] else 1.0)
            res = (A.get(b["id"] + "|Over") or A.get(b["id"] + "|Under") or {}).get("result")
            best = {}
            for bk, r in x["bet"].items():
                mm, nb = cons(x["imp"][dv], how, bk)
                muf = mu if mm is None else mm + w * (c0 * mu - mm)
                pov, pun, _ = probs(L, lg, mkt, muf, r["line"]); povc, punc, _ = probs(L, lg, mkt, c0 * mu, r["line"])
                pm = None
                if mm is not None:
                    a_, b_, _ = probs(L, lg, mkt, mm, r["line"]); pm = a_ / (a_ + b_)
                for side, pw, pl, pwc, plc, odds in (("Over", pov, pun, povc, punc, r["o"]), ("Under", pun, pov, punc, povc, r["u"])):
                    pn = pw / (pw + pl); be = 1 / dec(odds); edge = pn - be; ev = pw * (dec(odds) - 1) - pl
                    c = cb * (0.85 if edge >= .10 else 1.0); adj = ev * (c if ev > 0 else 1); edgec = pwc / (pwc + plc) - be
                    win = None if (res is None or res == r["line"]) else int((res > r["line"]) == (side == "Over"))
                    rec = dict(id=b["id"], pid=b["pid"], game=b["game"], lg=lg, date=date, name=b["name"], mkt=mkt, side=side, line=r["line"], odds=int(odds), book=bk,
                               p=pn, edge=edge, ev=ev, adj=adj, edgec=edgec, nb=nb, n=b["n"], mn=b.get("mn"), flags=flags0, win=win,
                               pmk=None if pm is None else (pm if side == "Over" else 1 - pm))
                    k = (adj, ev, bk == CFG["book"])
                    if side not in best or k > best[side][0]: best[side] = (k, rec)
                    sides.append(rec)
            x.setdefault("best", {})[vn] = {s: v[1] for s, v in best.items()}
        out[vn] = sides
    return rows, out


def pick(bestrows):
    pool = sorted([b for b in bestrows if eligible(b)], key=lambda b: -b["adj"]); picks, pg, seen = [], {}, set()
    for b in pool:
        if b["pid"] in seen or pg.get(b["game"], 0) >= CFG["max_per_game"]: continue
        seen.add(b["pid"]); pg[b["game"]] = pg.get(b["game"], 0) + 1; picks.append(b)
        if len(picks) == CFG["max_picks"]: break
    return pool, picks


def rec(z):
    z = [b for b in z if b["win"] is not None]
    if not z: return "0-0"
    w = sum(b["win"] for b in z); u = sum((dec(b["odds"]) - 1) if b["win"] else -1 for b in z)
    return f"{w}-{len(z) - w} ({u:+.2f}u)"


if __name__ == "__main__":
    ll = lambda p, y: -(y * np.log(np.clip(p, 1e-4, 1 - 1e-4)) + (1 - y) * np.log(1 - np.clip(p, 1e-4, 1 - 1e-4)))
    allq = {v: [] for v in VAR}; pools = {v: [] for v in VAR}; pk = {v: [] for v in VAR}; chk = []
    for f in sorted(glob.glob(O + "lines/*.txt")):
        m = re.search(r"/(NBA|NFL)_(\d{4}-\d\d-\d\d)\.txt$", f)
        if not m or not os.path.exists(O + f"priced/{m.group(1)}_{m.group(2)}.json"): continue
        r = day(m.group(1), m.group(2))
        if r is None: continue
        rows, out = r
        for x in rows:      # does the "live" replay land on the numbers the desk filed that day?
            for b in x["bs"]:
                me = x["best"]["live"].get(b["side"])
                if me and me["book"] == b["book"] and me["line"] == b["line"]: chk.append(abs(me["edge"] - b["edge"]))
        line = f"{m.group(1)} {m.group(2)}: {len(rows)} props"
        for v in VAR:
            allq[v] += out[v]
            pool, picks = pick([b for x in rows for b in x["best"][v].values()]); pools[v] += pool; pk[v] += picks
            line += f" | {v} cleared {len(pool)} picks {rec(picks)}"
        print(line)
    print(f"\nreplay check: {len(chk)} sides matched to the desk's own filed rows, median edge difference {np.median(chk) * 100:.2f} points, 90th percentile {np.percentile(chk, 90) * 100:.2f}")
    print("\n1) the market number on its own (no model), every bet-book over quote, log loss at that book's line (lower is better):")
    ref = None
    for v in VAR:
        z = [b for b in allq[v] if b["side"] == "Over" and b["win"] is not None and b["pmk"] is not None and b["nb"] >= CFG["min_books"]]
        key = {(b["id"], b["book"]): b for b in z}
        if ref is None: ref = key
        common = [k for k in key if k in ref]
        l1 = np.array([ll(key[k]["pmk"], key[k]["win"]) for k in common]); l0 = np.array([ll(ref[k]["pmk"], ref[k]["win"]) for k in common])
        g = np.array([key[k]["game"] for k in common]); ug = np.unique(g); idx = {u: np.where(g == u)[0] for u in ug}; rng = np.random.default_rng(7)
        bs = [(l1 - l0)[np.concatenate([idx[u] for u in rng.choice(ug, len(ug))])].mean() for _ in range(1000)]
        ld = np.array([ll(key[k]["p"], key[k]["win"]) for k in common])
        print(f"  {v:<9} n {len(common):5d}  market {l1.mean():.5f}  vs live {l1.mean() - l0.mean():+.5f} (better in {np.mean(np.array(bs) < 0):.0%} of game resamples)   desk blend {ld.mean():.5f}")
    print("\n2) what the pick rules would have done (same rules, same days):")
    live = {(b["id"], b["side"]) for b in pk["live"]}
    for v in VAR:
        mine = {(b["id"], b["side"]) for b in pk[v]}
        hr = [b for b in pools[v] if b["book"] == CFG["book"]]
        print(f"  {v:<9} cleared {len(pools[v]):3d} {rec(pools[v]):<16} picked {len(pk[v]):3d} {rec(pk[v]):<15} same picks as live {len(mine & live)} of {len(live)}   cleared at Hard Rock {len(hr)} {rec(hr)}"
              f"   by market {dict((m, sum(b['mkt'] == m for b in pools[v])) for m in sorted({b['mkt'] for b in pools[v]}))}")
