O="/home/claude/props/out/"; S="/home/claude/props/src/"
h=open(S+"index.src.html").read(); ENG=open(S+"engine.js").read().replace("if (typeof module !== 'undefined') module.exports = E;","")
import json, os, datetime
D=json.load(open(O+"data.json"))
D["desk"]=json.load(open(O+"history.json")) if os.path.exists(O+"history.json") else {"bets":[],"days":[],"unit":0.5,"bankroll":25}
D["feed"]=json.load(open(O+"feed.json")) if os.path.exists(O+"feed.json") else {}
D["calib"]=json.load(open(O+"calib.json")) if os.path.exists(O+"calib.json") else {}
# with/without history for the stress test (display only). Not fatal: without it the page says there is nothing to check against.
D["ww"]=json.load(open(O+"ww.json")) if os.path.exists(O+"ww.json") else {}
# every book's quote on every prop in the latest pull, graded against the others (display only). Not fatal.
try:
    import books; D["books"]=books.build(D)
except Exception as e:
    print("market grades skipped:",e); D["books"]={}
# game picks: the slate, the backtest and the record so far (display only). Not fatal.
D["games"]=json.load(open(O+"games.json")) if os.path.exists(O+"games.json") else {}
D["gpicks"]=json.load(open(O+"gpicks.json")) if os.path.exists(O+"gpicks.json") else []
try:
    D["gline"]=json.load(open(O+"gline.json")) if os.path.exists(O+"gline.json") else {}      # v4.2 game price lane (shadow)
except Exception as e:
    print("game price lane skipped:",e); D["gline"]={}
D["audit_n"]=len(json.load(open(O+"audit.json"))) if os.path.exists(O+"audit.json") else 0
# jersey numbers for the page (display only). Not fatal: a player with no number shows his position instead.
try:
    import pandas as pd
    DT="/home/claude/props/data/"
    r=pd.read_parquet(DT+"nfl_roster_weekly_2026.parquet",columns=["gsis_id","jersey_number","week"]).dropna(subset=["gsis_id","jersey_number"]).sort_values("week")
    nf={g:int(n) for g,n in zip(r.gsis_id,r.jersey_number)}
    q=pd.read_parquet(DT+"nba_pb_2027.parquet",columns=["athlete_id","athlete_jersey","game_date"]).dropna(subset=["athlete_id","athlete_jersey"]).sort_values("game_date")
    nb={str(float(a)):str(j) for a,j in zip(q.athlete_id,q.athlete_jersey)}
    for p in D["NFL"]["players"]: p["num"]=nf.get(p["id"])
    for p in D["NBA"]["players"]: p["num"]=nb.get(str(p["id"]))
    print("jersey numbers:",sum(p.get("num") is not None for p in D["NFL"]["players"]),"NFL,",sum(p.get("num") is not None for p in D["NBA"]["players"]),"NBA")
except Exception as e:
    print("jersey numbers skipped:",e)
D["built"]=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
d=json.dumps(D,separators=(",",":")).replace("</","<\\/")
# v3.20 the Sim tab lives in its own two files, poured into the page here
h=h.replace("/*__SIM_CSS__*/",open(S+"simtab.css").read()).replace("/*__SIM_JS__*/",open(S+"simtab.js").read())
# v3.38 the effects layer (ten switchable effects, display only) lives in fx.css and fx.js
h=h.replace("/*__FX_CSS__*/",open(S+"fx.css").read()).replace("/*__FX_JS__*/",open(S+"fx.js").read())
h=h.replace("/*__ENGINE__*/",ENG).replace("/*__DATA__*/",d)
open(O+"index.html","w").write(h); print(len(h))
