"""NBA opening and closing lines for the game model's track record: the DraftKings spread, total and moneylines that ESPN
shows on each finished game, read from the public sportsdataverse copy of ESPN's game files (raw.githubusercontent.com). Keeps
out/nba_lines.jsonl (one game a line: {id, pc: [...]}) and fetches only finished games it does not have yet, so after the
first run it reads a handful of files a day. Games before the 2025-26 season carry no lines in those files and are skipped.
A failure leaves the file as it was; the game model then simply has fewer graded games."""
import json, os, sys, urllib.request, concurrent.futures as cf
import pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
OUT = O + "nba_lines.jsonl"
URL = "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-raw/main/nba/json/final/{}.json"
CAP = 1600          # most files read in one run


def side(o):
    o = o or {}
    return dict(ml=o.get("moneyLine"), so=o.get("spreadOdds"), fav=o.get("favorite"))


def num(v):
    """ESPN writes opening and closing numbers as text: '+10.5', 'o234.5', '-556', 'EVEN'."""
    if v is None:
        return None
    t = str(v).strip().lstrip("ou").replace("+", "")
    if t.upper() in ("EVEN", "EV"):
        return 100.0
    try:
        return float(t)
    except ValueError:
        return None


def oc(x):
    """Opening and closing home spread line, total and moneylines: {o: [home line, total, home ML, away ML], c: [...]}."""
    ps, tt, ml = x.get("pointSpread") or {}, x.get("total") or {}, x.get("moneyline") or {}
    g = lambda d, k, w, f: num((((d.get(k) or {}).get(w)) or {}).get(f))
    return {w[0]: [g(ps, "home", w, "line"), g(tt, "over", w, "line"), g(ml, "home", w, "odds"), g(ml, "away", w, "odds")] for w in ("open", "close")}


def get(i):
    try:
        with urllib.request.urlopen(URL.format(i), timeout=60) as r:
            d = json.load(r)
    except Exception as e:
        return dict(id=i, err=str(e)[:60])
    pc = d.get("pickcenter") or []
    return dict(id=i, pc=[dict(p=(x.get("provider") or {}).get("name"), spread=x.get("spread"), det=x.get("details"), ou=x.get("overUnder"),
                               oo=x.get("overOdds"), uo=x.get("underOdds"), a=side(x.get("awayTeamOdds")), h=side(x.get("homeTeamOdds")), oc=oc(x)) for x in pc], v=2)


def main():
    ids = set()
    for y in (2026, 2027):
        f = f"{D}nba_pb_{y}.parquet"
        if os.path.exists(f):
            b = pd.read_parquet(f, columns=["game_id", "season_type"])
            ids |= set(b[b.season_type.isin([2, 3])].game_id.astype(int).astype(str))
    old = {}
    if os.path.exists(OUT):
        for l in open(OUT):
            if l.strip():
                x = json.loads(l); old[x["id"]] = x
    have = {i for i, x in old.items() if x.get("v") == 2}          # v2 rows carry the opening numbers too; older rows are read again
    todo = sorted(ids - have)[:CAP]
    n = got = 0
    with cf.ThreadPoolExecutor(10) as ex:
        for r in ex.map(get, todo):
            if "err" in r:
                continue                        # not up yet or a network hiccup: try again next run
            old[r["id"]] = r; n += 1; got += bool(r["pc"])
    with open(OUT + ".tmp", "w") as f:
        for x in old.values():
            f.write(json.dumps(x) + "\n")
    os.replace(OUT + ".tmp", OUT)
    print(f"nba lines: {len(old)} games on file, {n} read now ({got} with lines), {len(ids - have) - n} still to read")


if __name__ == "__main__":
    main()
