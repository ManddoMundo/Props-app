#!/usr/bin/env python3
"""Fast unit test suite for Fair Line pricing math, devigging, push normalization, and policy guards.
Run: python3 test_fairline.py"""
import math, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, daily


MOCK_L = {"model": {"disp": {"pts": [1.8, 0.1], "reb": [1.5, 0.0], "ast": [1.2, 0.0]}}}


class TestFairLineMath(unittest.TestCase):
    def test_pid_str_consistency(self):
        self.assertEqual(common.pid_str(4066261), "4066261.0")
        self.assertEqual(common.pid_str(4066261.0), "4066261.0")
        self.assertEqual(common.pid_str("4066261"), "4066261.0")
        self.assertEqual(common.pid_str("00-0036900"), "00-0036900")

    def test_power_fair_vs_proportional(self):
        # Balanced market: both methods give 50%
        self.assertAlmostEqual(daily.power_fair(-110, -110), 0.5, places=4)
        # Skewed market (-400 / +300): power method assigns higher true prob to favorite than proportional split
        pf = daily.power_fair(-400, 300)
        prop = (1 / daily.dec(-400)) / (1 / daily.dec(-400) + 1 / daily.dec(300))
        self.assertGreater(pf, prop)
        self.assertGreater(pf, 0.76)
        self.assertLess(pf, 0.80)

    def test_probs_whole_line_push_normalization(self):
        ov, un, push = daily.probs(MOCK_L, "NBA", "pts", 20.0, 20.0)
        self.assertGreater(push, 0.02)
        self.assertAlmostEqual(ov + un + push, 1.0, places=6)
        # Push-normalized probabilities must sum to 1.0
        self.assertAlmostEqual(ov / (ov + un) + un / (ov + un), 1.0, places=6)

    def test_implied_mean_roundtrip(self):
        for target_mu in (5.5, 18.2, 27.4):
            line = math.floor(target_mu) + 0.5
            ov, un, _ = daily.probs(MOCK_L, "NBA", "pts", target_mu, line)
            p_ov = ov / (ov + un)
            rec_mu = daily.implied_mean(MOCK_L, "NBA", "pts", line, p_ov)
            self.assertAlmostEqual(rec_mu, target_mu, delta=0.05)

    def test_leave_one_out_weighted_consensus(self):
        # Suppose FanDuel & DraftKings imply 20.0, while Hard Rock hangs a stale 22.0
        impd = {"fanduel": 20.0, "draftkings": 20.0, "hardrockbet": 22.0}
        loo_hr = daily.weighted_cons(impd, exclude="hardrockbet")
        incl_all = daily.weighted_cons(impd, exclude=None)
        self.assertAlmostEqual(loo_hr, 20.0, places=6)
        self.assertGreater(incl_all, loo_hr)

    def test_eligible_guards(self):
        base = dict(lg="NBA", mkt="pts", odds=-110, n=20, mn=30.0, flags=[], nb=3, edge=0.05, edgec=0.18, adj=0.04)
        # NBA allows edgec up to 0.25
        self.assertTrue(daily.eligible(base))
        # NFL caps edgec at 0.12
        nfl_b = dict(base, lg="NFL", mkt="rec_yds")
        self.assertFalse(daily.eligible(nfl_b))
        # Trial market (fg3) blocked
        self.assertFalse(daily.eligible(dict(base, mkt="fg3")))
        # Questionable blocked
        self.assertFalse(daily.eligible(dict(base, flags=["questionable"])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
