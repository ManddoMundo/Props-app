"""Comprehensive verification & adversarial regression suite for Fair Line v4.2 (gline.py, sharps.py, gline_fit.py, games.py).
Run: python3 test_gline.py   Uses scratch folders only; touches no production books."""
import datetime, json, math, os, shutil, sys, tempfile, time, unittest
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gline, gline_fit, sharps, games


def book(sp=None, tl=None, ml=None, a="AAA", h="HHH"):
    m = {}
    if ml:
        m["h2h"] = {h: (None, ml[0]), a: (None, ml[1])}
    if sp:
        m["spreads"] = {h: (sp[0], sp[1]), a: (-sp[0], sp[2])}
    if tl:
        m["totals"] = {"Over": (tl[0], tl[1]), "Under": (tl[0], tl[2])}
    return m


def others(n, **k):
    return {f"b{i}": book(**k) for i in range(n)}


class TestGlineMath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.DS = gline.load_dist()
        cls.dm_nfl, cls.dt_nfl = gline.dists("NFL", cls.DS)
        cls.dm_nba, cls.dt_nba = gline.dists("NBA", cls.DS)

    def test_dist_roundtrip_and_extremes(self):
        mu = self.dm_nfl.solve(3.5, 0.5238)
        self.assertAlmostEqual(self.dm_nfl.over(mu, 3.5)[0], 0.5238, places=4)
        # Log-sum-exp guard against underflow at extreme mu
        p_ext = self.dm_nfl.pmf(600.0)
        self.assertTrue(np.all(np.isfinite(p_ext)))
        self.assertAlmostEqual(float(p_ext.sum()), 1.0, places=9)
        with self.assertRaises(ValueError):
            gline.Dist(0.0)

    def test_nba_has_exact_zero_tie_probability(self):
        self.assertEqual(self.DS["NBA"]["keys"]["0"], 0.0)
        p_over, push = self.dm_nba.over(0.0, 0.0)
        self.assertEqual(push, 0.0)
        self.assertAlmostEqual(p_over, 0.5, places=6)

    def test_power_devig_eliminates_underdog_phantom_ev(self):
        # Books at -355/+260, HR dog at +295: under multiplicative de-vig this falsely cleared at +3.7% EV.
        # Under power de-vig, true dog prob ~0.244 -> EV at +295 (d=3.95) is negative!
        q = dict(others(5, ml=(-355, 260)), hardrockbet=book(ml=(-355, 295)))
        f = gline.fair("NBA", "AAA", "HHH", q, DS=self.DS)
        S = {s["side"]: s for s in gline.sides("NBA", "AAA", "HHH", q, f, self.DS)}
        self.assertLess(S["AAA"]["ev"], 0.0)
        self.assertFalse(S["AAA"]["ok"])

    def test_exchange_additive_midpoint_exact(self):
        # Binary exchange with 0.04 spread around mid=0.80 -> asks 0.82 (-456) and 0.22 (+355)
        a_h, a_a = sharps.american(0.82), sharps.american(0.22)
        pr = gline.pair({"HHH": (None, a_h), "AAA": (None, a_a)}, "HHH", "AAA", bk="polymarket", mk="h2h")
        self.assertIsNotNone(pr)
        self.assertAlmostEqual(pr[2], 0.80, delta=0.002)

    def test_ieee754_zero_vig_pairs_preserved(self):
        # All 401 symmetric zero-vig pairs (-a/+a, a=100..500) must pass sane=(0.995, 1.12)
        for a in range(100, 501):
            pr = gline.pair({"HHH": (None, -a), "AAA": (None, a)}, "HHH", "AAA", bk="novig", mk="h2h")
            self.assertIsNotNone(pr, f"dropped zero-vig pair -{a}/+{a}")

    def test_push_adjusted_ev_and_nfl_key_3(self):
        # Market at -3.5 (-110/-110), HR at -3.0 (-110/-110)
        q = dict(others(5, sp=(-3.5, -110, -110)), hardrockbet=book(sp=(-3.0, -110, -110)))
        f = gline.fair("NFL", "AAA", "HHH", q, DS=self.DS)
        S = {(s["mkt"], s["side"]): s for s in gline.sides("NFL", "AAA", "HHH", q, f, self.DS)}
        h = S[("spreads", "HHH")]
        self.assertTrue(h["ok"])
        self.assertGreater(h["push"], 0.07)
        # True per-unit EV must equal (1 - push) * (p_cond * d - 1)
        expected_ev = (1.0 - h["push"]) * (h["p"] * gline.dec(-110) - 1.0)
        self.assertAlmostEqual(h["ev"], expected_ev, delta=0.001)
        self.assertAlmostEqual(h["p_win"], h["p"] * (1.0 - h["push"]), delta=0.001)
        self.assertFalse(S[("spreads", "AAA")]["ok"])

    def test_market_equal_never_clears_and_filters(self):
        q = dict(others(5, sp=(-3.5, -110, -110), tl=(44.5, -110, -110), ml=(-180, 155)),
                 hardrockbet=book(sp=(-3.5, -110, -110), tl=(44.5, -110, -110), ml=(-180, 155)))
        f = gline.fair("NFL", "AAA", "HHH", q, DS=self.DS)
        self.assertFalse(any(s["ok"] for s in gline.sides("NFL", "AAA", "HHH", q, f, self.DS)))

        # ML -130 clears vs fair 60%, -160 does not
        for px, want in ((-130, True), (-160, False)):
            q = dict(others(5, ml=(-165, 140)), hardrockbet=book(ml=(px, 110)))
            f = gline.fair("NBA", "AAA", "HHH", q, DS=self.DS)
            s = [s for s in gline.sides("NBA", "AAA", "HHH", q, f, self.DS) if s["side"] == "HHH"][0]
            self.assertEqual(s["ok"], want)

        # Too few sources & too wide gap & broken quote & NBA totals
        q3 = dict(others(3, sp=(-3.5, -110, -110)), hardrockbet=book(sp=(-3, -110, -110)))
        self.assertFalse(any(s["ok"] for s in gline.sides("NFL", "AAA", "HHH", q3, gline.fair("NFL", "AAA", "HHH", q3, DS=self.DS), self.DS)))

        qw = dict(others(5, sp=(-6.5, -110, -110)), hardrockbet=book(sp=(-3, -110, -110)))
        sw = [s for s in gline.sides("NFL", "AAA", "HHH", qw, gline.fair("NFL", "AAA", "HHH", qw, DS=self.DS), self.DS) if s["side"] == "HHH"][0]
        self.assertFalse(sw["ok"])
        self.assertTrue(sw["why"].startswith("gap too wide"))

        qb = dict(others(4, tl=(220.5, -110, -110)), bad=book(tl=(220.5, 150, 150)), hardrockbet=book(tl=(220.5, -110, -110)))
        self.assertEqual(gline.fair("NBA", "AAA", "HHH", qb, DS=self.DS)["n"]["totals"], 4)

        qt = dict(others(5, tl=(220.5, -110, -110)), hardrockbet=book(tl=(218.5, -110, -110)))
        St = {s["side"]: s for s in gline.sides("NBA", "AAA", "HHH", qt, gline.fair("NBA", "AAA", "HHH", qt, DS=self.DS), self.DS)}
        self.assertGreater(St["Over"]["ev"], 0.02)
        self.assertLess(St["Under"]["ev"], 0.02)

    def test_sharp_weighted_consensus_and_pinnacle_disagree_guard(self):
        # 4 soft books stale at -3.5, Pinnacle + HR already moved to -5.0 (apparent EV in [2%, 8%]) -> blocked by sharp_ref guard!
        q = {
            "betmgm": book(sp=(-3.5, -110, -110)),
            "williamhill_us": book(sp=(-3.5, -110, -110)),
            "betrivers": book(sp=(-3.5, -110, -110)),
            "fanatics": book(sp=(-3.5, -110, -110)),
            "pinnacle": book(sp=(-5.0, -110, -110)),
            "hardrockbet": book(sp=(-5.0, -110, -110)),
        }
        f = gline.fair("NBA", "AAA", "HHH", q, DS=self.DS)
        S = {s["side"]: s for s in gline.sides("NBA", "AAA", "HHH", q, f, self.DS)}
        # Even though soft books make AAA +5.0 look +EV (inside 2%-8%), Pinnacle says -5.0 is fair -> blocked!
        self.assertGreaterEqual(S["AAA"]["ev"], 0.02)
        self.assertLessEqual(S["AAA"]["ev"], 0.08)
        self.assertFalse(S["AAA"]["ok"])
        self.assertEqual(S["AAA"]["why"], "Pinnacle disagrees")

    def test_mismatched_lines_and_invalid_odds_rejected(self):
        # Book quoting mismatched home -3.0 / away +3.5 must be rejected by pair() and sides()
        bad_sp = {"HHH": (-3.0, -110), "AAA": (3.5, -110)}
        self.assertIsNone(gline.pair(bad_sp, "HHH", "AAA", mk="spreads"))
        bad_tl = {"Over": (220.5, -110), "Under": (221.5, -110)}
        self.assertIsNone(gline.pair(bad_tl, "Over", "Under", mk="totals"))
        for bad in (0, None, "even", -50, 50, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                gline.dec(bad)

    def test_calib_bins_breaks_tautology_and_wilson_ci(self):
        # Adversarial 0%-accuracy inverted model: predicts 0.52 on losers and 0.48 on winners across 100 markets.
        # Old symmetric 5-bin strip falsely reported 50.0% / 50.0%! v4.2 canonical favorite side must report hit=0.0%!
        A = []
        for i in range(100):
            A.append(dict(lg="NBA", id=str(i), mkt="spreads", side="HHH", home="HHH", p=0.52, won=0, status="lost"))
            A.append(dict(lg="NBA", id=str(i), mkt="spreads", side="AAA", home="HHH", p=0.48, won=1, status="won"))
        cb = gline.calib_bins(A)
        b0 = cb[0]  # [0.50, 0.55)
        self.assertEqual(b0["n"], 100)
        self.assertAlmostEqual(b0["said"], 0.52, places=3)
        self.assertEqual(b0["hit"], 0.0)
        self.assertLess(b0["ci_hi"], 0.05)

    def test_settle_and_nan_rejection(self):
        self.assertEqual((gline.settle(dict(mkt="spreads", side="HHH", home="HHH", line=-3.0), 4, 40),
                          gline.settle(dict(mkt="spreads", side="HHH", home="HHH", line=-3.0), 3, 40),
                          gline.settle(dict(mkt="spreads", side="HHH", home="HHH", line=-3.0), 2, 40)), (1, None, 0))
        self.assertEqual(gline.settle(dict(mkt="spreads", side="AAA", home="HHH", line=3.0), 2, 40), 1)
        self.assertEqual((gline.settle(dict(mkt="totals", side="Under", home="HHH", line=44.0), 1, 41),
                          gline.settle(dict(mkt="totals", side="Under", home="HHH", line=44.0), 1, 44)), (1, None))
        self.assertEqual(gline.settle(dict(mkt="h2h", side="AAA", home="HHH", line=None), -1, 40), 1)
        self.assertIsNone(gline.settle(dict(mkt="h2h", side="HHH", home="HHH", line=None), 0, 40))
        with self.assertRaises(ValueError):
            gline.settle(dict(mkt="h2h", side="HHH", home="HHH", line=None), float("nan"), 40.0)

    def test_promotion_clustered_t_and_clv_n_floor(self):
        # 200 graded sides with only 5 closed sides MUST fail promotion (old code ignored clv_n)
        S = [dict(lg="NBA", id=str(i), mkt="spreads", side="HHH", ev=0.03, status="won" if i % 2 == 0 else "lost",
                  won=1 if i % 2 == 0 else 0, units=0.91 if i % 2 == 0 else -1.0,
                  close=dict(clv=0.02) if i < 5 else None) for i in range(200)]
        self.assertFalse(gline.promotion(S)["met"])
        # 200 independent games with steady +2.5% CLV and winning units MUST pass
        S2 = [dict(lg="NBA", id=str(i), mkt="spreads", side="HHH", ev=0.03, status="won" if i < 110 else "lost",
                   won=1 if i < 110 else 0, units=0.91 if i < 110 else -1.0,
                   close=dict(clv=0.02 + (0.01 if i % 2 == 0 else -0.002))) for i in range(200)]
        self.assertTrue(gline.promotion(S2)["met"])

    def test_gline_fit_degenerate_guards(self):
        df1 = pd.DataFrame([dict(season=2025, m=3.0, spr=3.0, tot=40.0, tl=40.0, mh=-110, ma=-110)])
        with self.assertRaises(ValueError):
            gline_fit.fit(df1, "NFL")


class TestGlineLifecycleAndFuzz(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp() + "/"
        os.makedirs(self.tmp + "games")
        self.old_go, self.old_gd, self.old_gr = gline.O, gline.D, gline.results
        self.old_so, self.old_ss, self.old_sg = sharps.O, sharps.S, sharps.get
        gline.O = self.tmp
        gline.D = self.tmp + "data/"
        sharps.O = self.tmp
        sharps.S = self.tmp + "sharps/"

    def tearDown(self):
        gline.O, gline.D, gline.results = self.old_go, self.old_gd, self.old_gr
        sharps.O, sharps.S, sharps.get = self.old_so, self.old_ss, self.old_sg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_day_nba_nfl_fl_exchanges_and_grade_refreshes_card(self):
        today = datetime.datetime.now(gline.ET).date().isoformat()
        nfl_day = (datetime.datetime.now(gline.ET).date() + datetime.timedelta(days=3)).isoformat()
        json.dump({
            "NBA": {"games": [
                dict(id="900", day=today, time="19:30", away="AAA", home="HHH", pm=2.0, pt=220.0),
                dict(id="901", day=today, time="20:00", away="CCC", home="DDD", pm=5.0, pt=220.0),
            ]},
            "NFL": {"games": [
                dict(id="2026_12_NYG_DAL", day=nfl_day, time="13:00", away="NYG", home="DAL", pm=3.0, pt=45.0),
            ]},
        }, open(self.tmp + "games.json", "w"))

        # NBA midday pull: Game 900 has HR -3.0 vs market -4.5 AND Novig -3.0 (tests gfl.json!);
        # Game 901 has heavy favorite DDD fair ~72% at HR -225 (EV > 1.5%, enters glikely!)
        nba_rows = [
            f"# relay pulled {today} 11:30 ET, midday, game odds",
            "bookmaker_key|market_key|team|point|price",
            "# game: AAA @ HHH", f"# tip: {today} 19:30 ET",
        ]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us"):
            nba_rows += [f"{bk}|spreads|HHH|-4.5|-110", f"{bk}|spreads|AAA|4.5|-110"]
        nba_rows += ["hardrockbet|spreads|HHH|-3.0|-110", "hardrockbet|spreads|AAA|3.0|-110"]
        nba_rows += ["novig|spreads|HHH|-3.0|-105", "novig|spreads|AAA|3.0|-105"]
        nba_rows += ["# game: CCC @ DDD", f"# tip: {today} 20:00 ET"]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us"):
            nba_rows += [f"{bk}|h2h|DDD||-285", f"{bk}|h2h|CCC||235"]
        nba_rows += ["hardrockbet|h2h|DDD||-225", "hardrockbet|h2h|CCC||190"]
        open(self.tmp + f"games/NBA_{today}.txt", "w").write("\n".join(nba_rows) + "\n")

        # NFL midday pull: 3 days ahead (must log into gshadow, NOT into gaudit until game day)
        nfl_rows = [
            f"# relay pulled {today} 11:30 ET, midday, game odds",
            "bookmaker_key|market_key|team|point|price",
            "# game: NYG @ DAL", f"# tip: {nfl_day} 13:00 ET",
        ]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us"):
            nfl_rows += [f"{bk}|spreads|DAL|-3.5|-110", f"{bk}|spreads|NYG|3.5|-110"]
        nfl_rows += ["hardrockbet|spreads|DAL|-3.0|-110", "hardrockbet|spreads|NYG|3.0|-110"]
        open(self.tmp + f"games/NFL_{today}.txt", "w").write("\n".join(nfl_rows) + "\n")

        gline.cmd_log(today)
        gline.cmd_log(today)  # idempotent
        S = json.load(open(self.tmp + "gshadow.json"))
        A = json.load(open(self.tmp + "gaudit.json"))
        K = json.load(open(self.tmp + "glikely.json"))
        F = json.load(open(self.tmp + "gfl.json"))
        self.assertEqual(len(S), 3)  # NBA 900 HHH, NBA 901 DDD, NFL DAL
        self.assertEqual(len(A), 4)  # NBA game-day sides only, with src persisted
        self.assertIn("pinnacle", A[0]["src"])
        self.assertEqual(len(K), 1)
        self.assertEqual(K[0]["side"], "DDD")
        self.assertGreaterEqual(K[0]["ev"], 0.015)
        self.assertEqual(len(F), 1)
        self.assertEqual(F[0]["book"], "novig")
        self.assertFalse(os.path.exists(self.tmp + "history.json"))

        # Evening pull moves line further our way -> positive CLV, and logged badge reflects actual gshadow membership
        pm_rows = [
            f"# relay pulled {today} 18:00 ET, evening, game odds",
            "bookmaker_key|market_key|team|point|price",
            "# game: AAA @ HHH", f"# tip: {today} 19:30 ET",
        ]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us"):
            pm_rows += [f"{bk}|spreads|HHH|-5.5|-110", f"{bk}|spreads|AAA|5.5|-110"]
        pm_rows += ["hardrockbet|spreads|HHH|-5.5|-110", "hardrockbet|spreads|AAA|5.5|-110"]
        open(self.tmp + f"games/NBA_{today}_pm.txt", "w").write("\n".join(pm_rows) + "\n")
        gline.cmd_close(today)
        S = json.load(open(self.tmp + "gshadow.json"))
        nba900 = [x for x in S if x["id"] == "900"][0]
        self.assertGreater(nba900["close"]["clv"], nba900["ev"])
        self.assertIsNotNone(nba900["close"]["pin_clv"])
        card = json.load(open(self.tmp + "gline.json"))
        # On evening pull HR moved to -5.5 (ok=False), yet HHH IS in gshadow so logged MUST stay True!
        hhh_card = [s for g in card["lg"]["NBA"]["games"] if g["id"] == "900" for s in g["sides"] if s["side"] == "HHH"][0]
        self.assertFalse(hhh_card["ok"])
        self.assertTrue(hhh_card["logged"])

        # Morning grading MUST refresh gline.json immediately (fixing v4.1 stale card bug)
        gline.results = lambda: {("NBA", "900"): (8.0, 220.0), ("NBA", "901"): (-3.0, 215.0)}
        gline.cmd_grade()
        card2 = json.load(open(self.tmp + "gline.json"))
        self.assertEqual(card2["rec"]["NBA"]["w"], 1)
        self.assertEqual(card2["rec"]["NBA"]["l"], 1)
        self.assertEqual(card2["likely"]["rec"]["NBA"]["l"], 1)
        # Verify report, show, summary all run without error
        gline.cmd_report()
        gline.cmd_show(today)
        sum_p = self.tmp + "summary.json"
        json.dump({"version": "4.2"}, open(sum_p, "w"))
        gline.cmd_summary(sum_p)
        sj = json.load(open(sum_p))
        self.assertEqual(sj["gline"]["ver"], gline.VER)
        self.assertEqual(sj["gline"]["fl"]["n"], 1)

    def test_newest_pull_wins_whatever_its_name(self):
        """Sunday: midday 11:30, close 12:30, evening 6:00, lineups 6:40. The lane must read the newest pull each time."""
        d = "2026-11-29"
        def put(sfx, hhmm, head=True):
            with open(self.tmp + f"games/NFL_{d}{sfx}.txt", "w") as f:
                f.write((f"# relay pulled {d} {hhmm} ET, x\n" if head else "") + "# game: DEN @ SEA\n")
        put("", "11:30"); put("_close12", "12:30")
        self.assertTrue(gline.files("NFL", d)[0].endswith("_close12.txt"))
        put("_pm", "18:00")
        self.assertTrue(gline.files("NFL", d)[0].endswith("_pm.txt"))
        put("_late", "18:40")
        self.assertTrue(gline.files("NFL", d)[0].endswith("_late.txt"))
        put("_late", "", head=False)                      # a file with no time stamp never outranks a dated one
        self.assertTrue(gline.files("NFL", d)[0].endswith("_pm.txt"))
        self.assertEqual(gline.files("NBA", d), (None, None))

    def test_b2b_same_matchup_neutral_flip_inplay_and_nan_guards(self):
        # 1. Back-to-back NBA mini-series BOS @ LAL on consecutive days in one file: BOTH must survive!
        json.dump({
            "NBA": {"games": [
                dict(id="1001", day="2026-11-27", time="19:30", away="BOS", home="LAL"),
                dict(id="1002", day="2026-11-28", time="19:30", away="BOS", home="LAL"),
            ]},
            "NFL": {"games": [
                dict(id="2026_12_SF_KC", day="2026-11-27", time="16:25", away="SF", home="KC"),
            ]},
        }, open(self.tmp + "games.json", "w"))
        rows = [
            "# relay pulled 2026-11-27 11:30 ET, midday, game odds",
            "bookmaker_key|market_key|team|point|price",
            "# game: BOS @ LAL", "# tip: 2026-11-27 19:30 ET",
        ]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us"):
            rows += [f"{bk}|spreads|LAL|-4.5|-110", f"{bk}|spreads|BOS|4.5|-110"]
        rows += ["badbook|spreads|LAL|nan|-110", "badbook|spreads|BOS|nan|-110", "infbook|h2h|LAL||inf", "infbook|h2h|BOS||-inf"]
        rows += ["hardrockbet|spreads|LAL|-3.0|-110", "hardrockbet|spreads|BOS|3.0|-110"]
        # Second game next day at -7.5 everywhere (previously overwrote Game 1!)
        rows += ["# game: BOS @ LAL", "# tip: 2026-11-28 19:30 ET"]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us", "hardrockbet"):
            rows += [f"{bk}|spreads|LAL|-7.5|-110", f"{bk}|spreads|BOS|7.5|-110"]
        open(self.tmp + "games/NBA_2026-11-27.txt", "w").write("\n".join(rows) + "\n")

        # Neutral-site NFL feed lists KC @ SF while games.json lists SF @ KC -> sportsbooks must NOT be dropped!
        nfl_rows = [
            "# relay pulled 2026-11-27 11:30 ET, midday, game odds",
            "bookmaker_key|market_key|team|point|price",
            "# game: KC @ SF", "# tip: 2026-11-27 16:25 ET",
        ]
        for bk in ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us", "hardrockbet"):
            nfl_rows += [f"{bk}|h2h|KC||-130", f"{bk}|h2h|SF||110"]
        open(self.tmp + "games/NFL_2026-11-27.txt", "w").write("\n".join(nfl_rows) + "\n")

        gline.cmd_log("2026-11-27")
        S = json.load(open(self.tmp + "gshadow.json"))
        self.assertEqual(len(S), 1)
        self.assertEqual(S[0]["id"], "1001")
        nfl_slate, _ = gline.slate("NFL", "2026-11-27")
        self.assertEqual(len(nfl_slate), 1)
        self.assertTrue(nfl_slate[0]["hr"])
        self.assertEqual(nfl_slate[0]["fair"]["n"]["h2h"], 5)

        # In-play guard: pull timestamped 21:15 ET for 19:30 ET tipoff must be skipped!
        live_rows = [r.replace("11:30 ET", "21:15 ET") for r in rows[:15]]
        open(self.tmp + "games/NBA_2026-11-27_late.txt", "w").write("\n".join(live_rows) + "\n")
        # Also verify files() prefers _late over midday regardless of mtime
        os.utime(self.tmp + "games/NBA_2026-11-27.txt", (time.time() + 100, time.time() + 100))
        self.assertTrue(gline.files("NBA", "2026-11-27")[0].endswith("_late.txt"))
        live_slate, _ = gline.slate("NBA", "2026-11-27")
        self.assertEqual(len(live_slate), 0)

    def test_sharps_hardened_alt_totals_arb_filter_and_adversarial_trades(self):
        day = datetime.datetime.now(sharps.ET) + datetime.timedelta(hours=3)
        d = day.strftime("%Y-%m-%d")
        next_wk = (day + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        json.dump({
            "NBA": {"games": [dict(id="900", day=d, time=day.strftime("%H:%M"), away="BOS", home="LAL")]},
            "NFL": {"games": []},
        }, open(self.tmp + "games.json", "w"))
        now = int(time.time())
        t_tip = int(day.timestamp())

        def fake(url, params=None):
            if url.endswith("/sports"):
                return [dict(sport="nba", series="10345"), dict(sport="nfl", series="10187")]
            if url.endswith("/events/keyset"):
                return dict(data=[
                    # Future reverse-venue rematch next week MUST NOT match today's game!
                    dict(title="Lakers vs. Celtics", startDate=f"{next_wk}T23:00:00Z", markets=[
                        dict(sportsMarketType="moneyline", outcomes='["Lakers", "Celtics"]', bestBid=0.34, bestAsk=0.36, conditionId="0xfut"),
                    ]),
                    # Today's game with MAIN total (224.5, mid 0.50) AND an extreme ALT total (239.5, mid 0.15) after it!
                    dict(title="Celtics vs. Lakers", startDate=day.astimezone(datetime.timezone.utc).isoformat(), markets=[
                        dict(sportsMarketType="moneyline", outcomes='["Celtics", "Lakers"]', clobTokenIds='["tok_bos","tok_lal"]', bestBid=0.39, bestAsk=0.41, conditionId="0xabc"),
                        dict(sportsMarketType="totals", line=224.5, outcomes='["Over", "Under"]', bestBid=0.49, bestAsk=0.51, liquidityNum=50000, conditionId="0xdef"),
                        dict(sportsMarketType="totals", line=239.5, outcomes='["Over", "Under"]', bestBid=0.14, bestAsk=0.16, liquidityNum=5000, conditionId="0xalt"),
                        dict(sportsMarketType="totals", line="TBD", outcomes='["Over", "Under"]', bestBid=0.49, bestAsk=0.51, conditionId="0xbad"),
                    ]),
                ], next_cursor=None)
            if url.endswith("/v2/leaderboard"):
                return dict(data=[dict(user_id="0xAAA", pnl=5), dict(user_id="0xARB", pnl=99)], pagination=dict(next_cursor=None))
            if url.endswith("/v2/trades"):
                return dict(data=[
                    # Legit directional sharp (Lakers +1500 shares via outcome_index & token_id, plus duplicate id!)
                    dict(id="t1", proxy_wallet="0xAAA", side="BUY", outcome_index=1, size=1000, price=0.58, timestamp=now - 50),
                    dict(id="t1", proxy_wallet="0xAAA", side="BUY", outcome_index=1, size=1000, price=0.58, timestamp=now - 50),
                    dict(id="t2", proxy_wallet="0xAAA", side="SELL", asset="tok_bos", size=500, price=0.40, timestamp=now - 30),
                    # Arb/MM bot buys both sides for guaranteed +$3 profit & N=0 -> MUST be filtered out of flow AND board!
                    dict(id="t3", proxy_wallet="0xARB", side="BUY", outcome="Lakers", size=1000, price=0.48, timestamp=now - 45),
                    dict(id="t4", proxy_wallet="0xARB", side="BUY", outcome="Celtics", size=1000, price=0.49, timestamp=now - 44),
                    # Adversarial junk: None wallet, NaN size, CANCEL side, post-tip live trade -> ALL dropped!
                    dict(id="t5", proxy_wallet=None, side="BUY", outcome="Lakers", size=500, price=0.55, timestamp=now - 20),
                    dict(id="t6", proxy_wallet="0xNAN", side="BUY", outcome="Lakers", size=float("nan"), price=0.55, timestamp=now - 20),
                    dict(id="t7", proxy_wallet="0xCAN", side="CANCEL", outcome="Lakers", size=500, price=0.55, timestamp=now - 20),
                    dict(id="t8", proxy_wallet="0xLIVE", side="BUY", outcome="Lakers", size=500, price=0.98, timestamp=t_tip + 3600),
                ], pagination=dict(next_cursor=None))
            raise RuntimeError("unexpected " + url)

        sharps.get = fake
        sharps.cmd_pull(d)
        txt = open(self.tmp + f"poly/NBA_{d}.txt").read()
        self.assertIn("# tip:", txt)
        self.assertIn("polymarket|h2h|LAL||-156", txt)
        self.assertIn("polymarket|totals|Over|224.5|-104", txt)
        self.assertNotIn("239.5", txt)  # alt total did NOT overwrite main total!

        M = json.load(open(self.tmp + "sharps/m/NBA_900.json"))["w"]
        self.assertNotIn("none", M)
        self.assertNotIn("0xnan", M)
        self.assertNotIn("0xcan", M)
        self.assertNotIn("0xlive", M)
        self.assertEqual(M["0xaaa"][:2], [1500.0, 880.0])  # duplicate t1 deduped!

        # Open flow uses open shares N * mid_home (1500 * 0.60 = $900) and excludes flat arb bot 0xARB!
        fl = json.load(open(self.tmp + f"sharps/{d}.json"))["NBA"]["BOS@LAL"]["h2h"]
        self.assertEqual(fl["LAL"]["usd"], 900)
        self.assertEqual(fl["LAL"]["n"], 1)  # only 0xAAA, NOT 0xARB!

        # Second pull with identical boundary timestamps adds nothing
        sharps.cmd_pull(d)
        self.assertEqual(json.load(open(self.tmp + "sharps/m/NBA_900.json"))["w"]["0xaaa"][:2], [1500.0, 880.0])

        # Scoring: 0xAAA scored cleanly; 0xARB filtered out by min_dir_ratio!
        gline.results = lambda: {("NBA", "900"): (7.0, 221.0)}
        sharps.cmd_score()
        W = json.load(open(self.tmp + "sharps/wallets.json"))
        self.assertIn("0xaaa", W)
        self.assertNotIn("0xarb", W)
        self.assertEqual(W["0xaaa"]["clv"], 20.0)
        self.assertEqual(W["0xaaa"]["pnl"], 620.0)
        self.assertGreater(W["0xaaa"]["sw"], 0.0)

        # Fail-closed tip() when time is missing/nan
        self.assertIsNone(sharps.tip(dict(day=d, time="")))
        self.assertIsNone(sharps.tip(dict(day=d, time="nan")))

        # Expanded team code normalization
        self.assertEqual(sharps.code("NBA", "LAC"), "LAC")
        self.assertEqual(sharps.code("NBA", "Boston Celtics (BOS)"), "BOS")
        self.assertEqual(sharps.code("NBA", "New Orleans Hornets"), "NO")
        self.assertEqual(sharps.code("NFL", "Niners"), "SF")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)
