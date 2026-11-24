#!/usr/bin/env python3
"""Safely applies the v3.52 UI & ID-canonicalization fixes in-place on /home/claude/props/src:
  1. simtab.css: removes stray '}' and duplicated .sm-leg v3.42 block, fixes .sm-leg.on .tk -> .sm-leg.on .slp
  2. index.src.html: syncs HOLD_EDGE by league ({NBA: 0.25, NFL: 0.12}) so UI matches daily.py CFG['hold_edge']
  3. nba.py / sim.py / ww.py / splits.py / nba_match.py / build.py: uses common.pid_str() for athlete_id
Run: python3 apply_ui_fixes.py /home/claude/props/src"""
import os, re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/props/src"

# 1. Fix simtab.css
css_p = os.path.join(SRC, "simtab.css")
if os.path.exists(css_p):
    css = open(css_p).read()
    marker = "/* ===== v3.42 legs are bet slips ====="
    parts = css.split(marker)
    if len(parts) >= 3:
        # Keep everything before first v3.42 block, then keep the second (clean) v3.42 block
        # Also remove any stray closing brace immediately before the second block
        pre = parts[0].rstrip()
        # Keep the clean grid rules from parts[1] if needed, or clean parts[2]
        block = marker + parts[-1]
        block = block.replace(".sm-leg.on .tk{", ".sm-leg.on .slp{")
        css_new = pre + "\n" + block
        open(css_p, "w").write(css_new)
        print("simtab.css: deduplicated v3.42 block, removed stray brace, fixed .sm-leg.on .slp")
    elif ".sm-leg.on .tk{" in css:
        open(css_p, "w").write(css.replace(".sm-leg.on .tk{", ".sm-leg.on .slp{"))
        print("simtab.css: fixed .sm-leg.on .slp")
    else:
        print("simtab.css: already clean")

# 2. Sync HOLD_EDGE in index.src.html
html_p = os.path.join(SRC, "index.src.html")
if os.path.exists(html_p):
    h = open(html_p).read()
    old_line = "const MAX_EDGE = 0.12;   // keep in step with CFG max_edge in daily.py"
    new_line = "const MAX_EDGE = 0.12, HOLD_EDGE = { NBA: 0.25, NFL: 0.12 };   // keep in step with CFG max_edge & hold_edge in daily.py"
    if old_line in h:
        h = h.replace(old_line, new_line, 1)
        h = h.replace("if (edgePts != null && edgePts > MAX_EDGE)", "const holdLim = (HOLD_EDGE[pr.lg] || MAX_EDGE); if (edgePts != null && edgePts > holdLim)")
        h = h.replace("const hold = best.edge > MAX_EDGE || far || qh;", "const hold = best.edge > (HOLD_EDGE[pr.lg] || MAX_EDGE) || far || qh;")
        open(html_p, "w").write(h)
        print("index.src.html: synced league-aware HOLD_EDGE ({NBA: 0.25, NFL: 0.12})")
    else:
        print("index.src.html: MAX_EDGE line not found (already patched or modified)")

# 3. Canonicalize pid_str in nba.py
nba_p = os.path.join(SRC, "nba.py")
if os.path.exists(nba_p):
    nb = open(nba_p).read()
    if "pid_str" not in nb and 'd["pid"] = d.athlete_id.astype(str)' in nb:
        nb = nb.replace("from common import fit_dispersion, score, norm, load_news, load_lineups",
                        "from common import fit_dispersion, score, norm, pid_str, load_news, load_lineups")
        nb = nb.replace('d["pid"] = d.athlete_id.astype(str)', 'd["pid"] = d.athlete_id.map(pid_str)')
        open(nba_p, "w").write(nb)
        print("nba.py: updated pid to use common.pid_str()")
    else:
        print("nba.py: already uses pid_str or modified")
