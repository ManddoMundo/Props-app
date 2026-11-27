"""v3.55 check (changes nothing in out/; works on a scratch copy). For every paused league in CFG model_pause, price the
newest saved lines for it as a day with no other league on the slate, run every command that can log a ticket (pick,
confident, fill), and count the tickets. The answer must be 0. Run after any change to daily.py: python3 pause_check.py
Why it exists: v3.54 paused the NFL in the pick guard and missed the lean filler, which logged two NFL leans on Nov 26."""
import contextlib, glob, io, json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily as M

T = tempfile.mkdtemp() + "/o/"; shutil.copytree(M.O, T, ignore=shutil.ignore_patterns("research", "index.html")); M.O = T; M.NEWS = T + "news.json"
D = json.load(open(T + "data.json")); bad = 0
for lg in M.CFG.get("model_pause", ()):
    files = sorted(f for f in glob.glob(T + f"lines/{lg}_*.txt") if f[-14:-4].count("-") == 2)
    if not files: print(lg, "no saved lines to check with"); continue
    for date in sorted({g["day"] for g in D[lg]["games"]})[:2]:
        h = json.load(open(T + "history.json")); h["bets"] = [b for b in h["bets"] if b["date"] < date]; json.dump(h, open(T + "history.json", "w"))
        for f in glob.glob(T + f"priced/*_{date}*.json"): os.remove(f)
        M._CAL.clear(); priced, _, _ = M.price_all(date, lg, [files[-1]]); json.dump(priced, open(T + f"priced/{lg}_{date}.json", "w")); made = {}
        for name, fn in (("pick", lambda: M.cmd_pick(date, lg)), ("confident", lambda: M.cmd_confident(date, lg, [files[-1]])), ("fill", lambda: M.cmd_fill(date))):
            n0 = len(json.load(open(T + "history.json"))["bets"])
            with contextlib.redirect_stdout(io.StringIO()): fn()
            made[name] = len(json.load(open(T + "history.json"))["bets"]) - n0
        bad += sum(made.values()); print(f"{lg} {date}: {len(priced)} sides priced from {os.path.basename(files[-1])}, tickets logged {made}")
print("PASS: a paused league logs no tickets" if not bad else f"FAIL: {bad} tickets logged in a paused league"); sys.exit(1 if bad else 0)
