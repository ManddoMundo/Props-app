#!/usr/bin/env python3
"""Wrap the built page as a standalone web app (Fair Line) that a phone can add to its home screen.
Writes /home/claude/props/site/docs: index.html, research/nfl.json, manifest, icons. Hosted from the repo's /docs folder by GitHub Pages."""
import json, os, shutil
O="/home/claude/props/out/"; S="/home/claude/props/src/"; D="/home/claude/props/site/docs/"
os.makedirs(D+"research",exist_ok=True)
page=open(O+"index.html").read()
head="""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Fair Line">
<meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="theme-color" content="#f5f7ea" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#22302a" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-180.png"><link rel="icon" type="image/png" href="icon-192.png">
<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style></head><body>
"""
open(D+"index.html","w").write(head+page+"\n</body></html>\n")
json.dump({"name":"Fair Line","short_name":"Fair Line","description":"NBA and NFL player prop model with a paper-bet desk.","start_url":".","scope":".","display":"standalone","background_color":"#cdd8c4","theme_color":"#f5f7ea",
           "icons":[{"src":"icon-192.png","sizes":"192x192","type":"image/png"},{"src":"icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]},open(D+"manifest.webmanifest","w"),indent=1)
if os.path.exists(O+"research/nfl.json"): shutil.copy(O+"research/nfl.json",D+"research/nfl.json")
for f in ("splits_nba.json","splits_nfl.json"):      # trends by split, fetched when the sheet opens
    if os.path.exists(O+"research/"+f): shutil.copy(O+"research/"+f,D+"research/"+f)
for n in ("icon-180.png","icon-192.png","icon-512.png"):
    if os.path.exists(S+"icons/"+n): shutil.copy(S+"icons/"+n,D+n)
open(D+".nojekyll","w").write("")
print("site:",sorted(os.listdir(D)),os.path.getsize(D+"index.html")//1024,"KB")
