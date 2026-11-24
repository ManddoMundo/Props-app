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
        self.assertFalse(daily.eligible(dict(base, lg="NFL", mkt="rec_yds")))      # NFL holds at 12 points from the market
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
