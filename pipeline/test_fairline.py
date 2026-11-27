#!/usr/bin/env python3
"""v3.52 quick checks on the desk's sums: the player id key, the de-vig, pushes on whole-number lines, the implied
projection, the pick guards and the NBA box score lookup. No data files needed; runs in under a second.
Run from pipeline/: python3 test_fairline.py
It changes nothing and is not part of the daily job. Run it after any edit to daily.py or common.py."""
import math, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, daily

L = {"model": {"disp": {"pts": [1.8, 0.1], "reb": [1.5, 0.0], "ast": [1.2, 0.0]}}}


class Desk(unittest.TestCase):
    def test_player_id_key(self):
        # the books hold ids as the text of a float; a whole number, a float and either as text must all land there
        for x in (4066261, 4066261.0, "4066261", "4066261.0"):
            self.assertEqual(common.pid_str(x), "4066261.0")
        self.assertEqual(common.pid_str("00-0036900"), "00-0036900")      # NFL ids pass through
        self.assertEqual(common.pid_str(None), "")

    def test_power_devig(self):
        self.assertAlmostEqual(daily.power_fair(-110, -110), 0.5, places=4)
        a, b = 1 / daily.dec(-400), 1 / daily.dec(300)
        pf = daily.power_fair(-400, 300)
        self.assertGreater(pf, a / (a + b))      # the power method gives the favourite more than the plain split
        self.assertTrue(0.76 < pf < 0.80)

    def test_whole_line_push(self):
        ov, un, push = daily.probs(L, "NBA", "pts", 20.0, 20.0)
        self.assertGreater(push, 0.02)
        self.assertAlmostEqual(ov + un + push, 1.0, places=6)
        ov2, un2, push2 = daily.probs(L, "NBA", "pts", 20.0, 20.5)
        self.assertEqual(push2, 0.0)
        self.assertAlmostEqual(ov2 + un2, 1.0, places=6)
        self.assertAlmostEqual(ov2, ov, places=6)      # over 20.5 and over 20 both need 21 or more

    def test_implied_mean_round_trip(self):
        for mu in (5.5, 18.2, 27.4):
            line = math.floor(mu) + 0.5
            ov, un, _ = daily.probs(L, "NBA", "pts", mu, line)
            self.assertAlmostEqual(daily.implied_mean(L, "NBA", "pts", line, ov / (ov + un)), mu, delta=0.05)

    def test_pick_guards(self):
        base = dict(lg="NBA", mkt="pts", odds=-110, n=20, mn=30.0, flags=[], nb=3, edge=0.05, edgec=0.18, adj=0.04)
        self.assertTrue(daily.eligible(base))
        self.assertFalse(daily.eligible(dict(base, lg="NFL", mkt="rec_yds")))      # NFL: paused since v3.54 (and holds at 12 points)
        self.assertFalse(daily.eligible(dict(base, edgec=0.26)))                   # NBA holds at 25
        self.assertFalse(daily.eligible(dict(base, edge=0.13)))                    # the edge ceiling is 12 in both leagues
        self.assertFalse(daily.eligible(dict(base, mkt="fg3")))                    # a market on trial
        self.assertFalse(daily.eligible(dict(base, flags=["questionable"])))
        self.assertFalse(daily.eligible(dict(base, nb=1)))                         # no market check
        self.assertFalse(daily.eligible(dict(base, mn=18.0)))

    def test_calibration_cap(self):
        self.assertLessEqual(daily.CFG["cal_w_max"], 0.45)

    def test_nba_box_lookup(self):
        box = dict(ok=True, games={"401"}, rows={("401", "77.0"): dict(pts=20, reb=5, ast=7, fg3=2, pra=32, pr=25, pa=27, ra=12)})
        t = dict(game="401", pid="77.0", mkt="pra", tag="11-20")
        self.assertEqual(daily.nba_actual(box, t), 32)
        self.assertEqual(daily.nba_actual(box, dict(t, pid=77)), 32)               # id type does not matter
        self.assertIsNone(daily.nba_actual(box, dict(t, pid="78.0")))              # no minutes: no result, the ticket voids

    def test_lineup_reader(self):
        # v3.54: the nba.com file lists five starters with a position, then the whole dressed roster again with the
        # position blank, then the inactives. Only the rows with a position are starters.
        import tempfile
        d = tempfile.mkdtemp() + "/"
        five = [("A One", "PG"), ("B Two", "SG"), ("C Three", "SF"), ("D Four", "PF"), ("E Five", "C")]
        rows = ["Source: nba.com daily lineups", "| team | player | pos | lineup | roster |", "|---|---|---|---|---|"]
        for team, st in (("PHI", "Expected"), ("BOS", "Confirmed")):
            rows += [f"| {team} | {n} | {p} | {st} | Active |" for n, p in five]
            rows += [f"| {team} | {n} |  | Confirmed | Active |" for n, _ in five]
            rows += [f"| {team} | Bench {i} |  | Confirmed | Active |" for i in range(8)]
            rows += [f"| {team} | Hurt Guy |  | Confirmed | Inactive |"]
        open(d + "NBA_2026-11-25.txt", "w").write("\n".join(rows))
        lu = common.load_lineups("NBA", "2026-11-25", d)
        self.assertEqual(set(lu), {"PHI", "BOS"})
        self.assertEqual(lu["PHI"]["start"], {common.norm(n) for n, _ in five})
        self.assertEqual(lu["PHI"]["inactive"], {"hurt guy"})
        self.assertFalse(lu["PHI"]["confirmed"])      # starters still "Expected"
        self.assertTrue(lu["BOS"]["confirmed"])
        self.assertEqual(common.load_lineups("NBA", "2026-11-26", d), {})      # no file for the day: nothing is set

    def test_nfl_model_paused(self):
        # v3.54: the desk prices the NFL off the other books alone; the fitted weight is still learned and filed
        import json, tempfile
        d = tempfile.mkdtemp() + "/"
        A = {}
        for i in range(60):
            for lg, mkt in (("NFL", "rec_yds"), ("NBA", "ast")):
                for side in ("Over", "Under"):
                    A[f"2026-11-2{i % 3}|{lg}|p{i}|{mkt}|{side}"] = dict(side=side, lg=lg, mkt=mkt, date=f"2026-11-2{i % 3}", mu=30.0 + i % 7, mm=28.0 + i % 5,
                                                                    line=27.5, odds=-110, win=i % 2, result=20 + (i * 7) % 25, ver="1.7", nb=3)
        json.dump(A, open(d + "audit.json", "w"))
        old = daily.O; daily.O = d; daily._CAL.clear()
        try:
            cal = dict(daily.calib({"NFL": {"model": {"disp": {"rec_yds": [-4.2, 1.2]}}}, "NBA": {"model": {"disp": {"ast": [1.5, 0.9]}}}}))
        finally:
            daily.O = old; daily._CAL.clear()
        self.assertEqual(cal["NFL|rec_yds"]["w"], 0.0)
        self.assertTrue(cal["NFL|rec_yds"]["paused"])
        self.assertIn("w_fit", cal["NFL|rec_yds"])
        self.assertNotIn("paused", cal["NBA|ast"])
        self.assertTrue(all(v["w"] == 0.0 for k, v in cal.items() if k.startswith("NFL")))
        ok = dict(lg="NFL", mkt="rec_yds", odds=-110, n=20, mn=None, flags=[], nb=3, edge=0.05, edgec=0.05, adj=0.04)
        self.assertFalse(daily.eligible(ok))                         # a paused league is never bet
        self.assertEqual(daily.pass_reason(ok)[0], "PAUSED")

    def test_paused_league_gets_no_leans(self):
        # v3.55: v3.54 paused the NFL in the pick guard but the lean filler has its own guard and still logged NFL leans.
        # The same priced side must be logged when the league is live (so this test cannot pass by accident) and not when paused.
        import io, json, tempfile, contextlib
        from unittest import mock
        side = dict(id="2026-11-26|NFL|00-1|rec_yds", pid="00-1", game="g1", lg="NFL", date="2026-11-26", tag="11-26", name="Test Player", team="AAA", opp="BBB",
                    mkt="rec_yds", side="Under", line=9.5, odds=-110, book="hardrockbet", p=0.545, edge=0.021, ev=0.04, adj=0.03, edgec=0.03, nb=3, n=20, mn=None,
                    flags=[], mu=8.0, be=0.524, conf=0.8, units=0.25, usd=6.25)
        def fill(paused):
            d = tempfile.mkdtemp() + "/"; os.makedirs(d + "priced"); json.dump([side], open(d + "priced/NFL_2026-11-26.json", "w"))
            old = daily.O; daily.O = d
            try:
                with mock.patch.dict(daily.CFG, {"model_pause": ("NFL",) if paused else ()}), mock.patch.object(daily, "cmd_explain", lambda *a: None), \
                     mock.patch.object(daily, "put_stake", lambda h, b: True), contextlib.redirect_stdout(io.StringIO()):
                    daily.cmd_fill("2026-11-26")
                return json.load(open(d + "history.json"))["bets"] if os.path.exists(d + "history.json") else []
            finally:
                daily.O = old
        self.assertEqual(len(fill(paused=False)), 1)
        self.assertEqual(fill(paused=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
