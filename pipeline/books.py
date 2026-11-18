"""Market grades: every book's quote on every prop in the latest lines pull, set against the consensus of the books.
Display only. The desk's picks come from daily.py and are untouched by this file.

For each prop the books quote, each book's line and two prices are turned into the projection they imply (on the model's
own curve, as daily.py does). The consensus is the median of the other books' implied projections (Hard Rock left out, so
Hard Rock is graded against everyone else). Each book's over and under is then priced at that consensus: its edge is the
consensus chance minus the price's break-even. Hard Rock's better side gets a letter.

Writes out/books.json: {lg: {asof, file, props: {"lg|game|pid|mkt": {...}}}}. Called from build.py; never fatal."""
import glob, json, os, re, time
import numpy as np
from daily import MK, CFG, dec, probs, implied_mean, parse
from common import norm

O = "/home/claude/props/out/"
GRADES = [(0.02, "A"), (0.0, "B"), (-0.025, "C"), (-0.05, "D")]      # Hard Rock's best side, edge against the consensus


def latest(lg):
    """The newest full pull for a league (not the opening or closing snapshots), if it is under 36 hours old."""
    ov = dict(x.split("=", 1) for x in os.environ.get("FL_LINES", "").split(",") if "=" in x)
    if lg in ov:
        return ov[lg]
    fs = [f for f in glob.glob(O + f"lines/{lg}_*.txt") if re.search(r"_\d{4}-\d\d-\d\d(_today)?\.txt$", f)]
    fs = [f for f in fs if time.time() - os.path.getmtime(f) < 36 * 3600]
    if not fs:
        return None
    full = [f for f in fs if not f.endswith("_today.txt")]
    return max(full or fs, key=os.path.getmtime)


def grade(e):
    return next((g for t, g in GRADES if e >= t), "F")


def build(D):
    res = {}
    for lg in ("NBA", "NFL"):
        f = latest(lg)
        if not f:
            continue
        L = D[lg]
        head = open(f).readline().strip()
        # v3.27: a team can have two games on the slate (the NBA board runs three days). The pull is for one day, so tie each
        # team to its game on the file's date, else to its next game. Before, the last game won, and tonight's lines were filed
        # under a game two days out (the hit rates then listed the player twice).
        gday = {g["id"]: g.get("day") for g in L["games"]}
        fd = re.search(r"_(\d{4}-\d\d-\d\d)", os.path.basename(f))
        sides = {}
        for s in L["sides"]:
            if s["team"] not in sides or (fd and gday.get(s["game"]) == fd.group(1) and gday.get(sides[s["team"]]["game"]) != fd.group(1)):
                sides[s["team"]] = s
        byname = {}
        for p in L["players"]:
            if p["team"] in sides:
                byname.setdefault(norm(p["name"]), []).append(p)
        quotes = {}
        for r in parse(f):
            quotes.setdefault((norm(r["player"]), r["market"]), {})[r["book"]] = r
        props, miss = {}, 0
        for (nm, market), books in quotes.items():
            mkt = MK[lg].get(market); c = byname.get(nm, [])
            if not mkt or len(c) != 1:
                miss += 1; continue
            p = c[0]; s = sides[p["team"]]
            bin_ = mkt == "any_td"

            def imp(x):          # what one book's quote implies: a mean (counts) or a yes chance (anytime TD)
                if x["o"] is None:
                    return None
                if bin_:
                    po = 1 / dec(x["o"])
                    return po / (po + 1 / dec(x["u"])) if x["u"] is not None else po * 0.93      # one-way TD price: take out a typical margin
                if x["line"] is None or x["u"] is None:
                    return None
                po, pu = 1 / dec(x["o"]), 1 / dec(x["u"])
                return implied_mean(L, lg, mkt, x["line"], po / (po + pu))
            if not bin_:      # v3.22: drop stale or one-sided quotes (an exchange's Under at 1.01): both sides must add to 1.00 to 1.12
                books = {bk: x for bk, x in books.items() if x["o"] is not None and x["u"] is not None and CFG["sane"][0] <= 1 / dec(x["o"]) + 1 / dec(x["u"]) <= CFG["sane"][1]}
                if not books:
                    continue
            ims = {bk: imp(x) for bk, x in books.items()}
            others = [v for bk, v in ims.items() if bk != CFG["book"] and v is not None]
            allv = [v for v in ims.values() if v is not None]
            if not allv:
                continue
            cons = float(np.median(others)) if len(others) >= 2 else None
            lines = [x["line"] for x in books.values() if x["line"] is not None]
            q = []
            for bk, x in sorted(books.items(), key=lambda kv: (kv[0] != CFG["book"], kv[0])):
                eo = eu = None
                if cons is not None and x["o"] is not None:
                    if bin_:
                        eo = cons - 1 / dec(x["o"])
                        if x["u"] is not None: eu = (1 - cons) - 1 / dec(x["u"])
                    elif x["line"] is not None:
                        ov, un, _ = probs(L, lg, mkt, cons, x["line"])
                        eo = ov - 1 / dec(x["o"])
                        if x["u"] is not None: eu = un - 1 / dec(x["u"])
                q.append([bk, x["line"], int(x["o"]) if x["o"] is not None else None, int(x["u"]) if x["u"] is not None else None,
                          None if eo is None else round(eo, 4), None if eu is None else round(eu, 4), None if ims[bk] is None else round(ims[bk], 3)])
            row = dict(q=q, nb=len(books), ml=float(np.median(lines)) if lines and not bin_ else None, cm=None if cons is None else round(cons, 3))
            hr = books.get(CFG["book"])
            if hr is not None and cons is not None:
                h = next(z for z in q if z[0] == CFG["book"])
                sd = [(e, nm_) for e, nm_ in ((h[4], "Over" if not bin_ else "Yes"), (h[5], "Under" if not bin_ else "No")) if e is not None]
                if sd:
                    e, side = max(sd)
                    row.update(g=grade(e), gs=side, ge=round(e, 4))
                    hm = ims[CFG["book"]]
                    if hm is not None and not bin_:
                        row["off"] = bool(abs(hm - cons) / max(cons, 0.5) > 0.08 or (row["ml"] is not None and abs((hr["line"] or 0) - row["ml"]) >= 1.5))
            props[f'{lg}|{s["game"]}|{p["id"]}|{mkt}'] = row
        res[lg] = dict(asof=head.replace("# relay pulled ", "").split(",")[0], file=os.path.basename(f), props=props)
        print(f"books: {lg} {len(props)} props from {os.path.basename(f)}, {sum('g' in v for v in props.values())} graded at Hard Rock, {miss} unmatched")
    return res


if __name__ == "__main__":
    D = json.load(open(O + "data.json"))
    json.dump(build(D), open(O + "books.json", "w"), separators=(",", ":"))
