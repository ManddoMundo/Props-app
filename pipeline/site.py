#!/usr/bin/env python3
"""Wrap the built page as a standalone web app (Fair Line) that a phone can add to its home screen.
Writes /home/claude/props/site/docs: index.html, research/*.json, manifest, icons, share card, service worker.
Hosted from the repo's /docs folder by GitHub Pages (https://manddomundo.github.io/Props-app/).
v3.36: the title, font links and other head tags the built page opens with are moved into the real <head> (they sat in
<body>, so link previews found no title); a description, Open Graph and Twitter card tags and a 1200x630 share card (og.png)
are added; and a service worker keeps the app usable offline: network first, the saved copy only when the network fails,
so it never shows yesterday's lines while today's can be fetched.
v4.2.4: the saved app's status area is "black-translucent" (it was "default"). After iOS 27.2.1 the iPhone Duo kept its side
strip for itself under "default", so the side rail had nowhere to draw; the same page inside another app still got the strip.
With this setting the page runs under the status areas and keeps clear of them with the safe-area insets it already uses."""
import json, os, re, shutil
O="/home/claude/props/out/"; S="/home/claude/props/src/"; D="/home/claude/props/site/docs/"
URL="https://manddomundo.github.io/Props-app/"
DESC="NBA and NFL player props priced from ten thousand simulated games, with a paper-bet desk that keeps score."
os.makedirs(D+"research",exist_ok=True)
page=open(O+"index.html").read()
# the head tags the built page starts with (title, metas, font links) belong in <head>
m=re.match(r'(?:\s*(?:<title>[^<]*</title>|<meta\b[^>]*>|<link\b[^>]*>))+',page)
lead=m.group(0).strip() if m else ""
body=page[m.end():] if m else page
if "<title>" not in lead: lead="<title>Fair Line</title>\n"+lead
VER=open(S+"VERSION").read().strip()
head=f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{lead}
<meta name="description" content="{DESC}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Fair Line"><meta property="og:title" content="Fair Line">
<meta property="og:description" content="{DESC}"><meta property="og:url" content="{URL}">
<meta property="og:image" content="{URL}og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Fair Line: NBA and NFL player props, with a tote board showing a fair line, the desk's chance and the edge">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="Fair Line"><meta name="twitter:description" content="{DESC}"><meta name="twitter:image" content="{URL}og.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Fair Line">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="theme-color" content="#f5f7ea" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#22302a" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-180.png"><link rel="icon" type="image/png" href="icon-192.png">
<style>:root{{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}body{{margin:0;font:14px system-ui,sans-serif}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
<script>if('serviceWorker' in navigator&&location.protocol==='https:'&&/github\\.io$/.test(location.hostname))addEventListener('load',()=>navigator.serviceWorker.register('sw.js').catch(()=>{{}}));</script>
</head><body>
"""
open(D+"index.html","w").write(head+body+"\n</body></html>\n")
json.dump({"name":"Fair Line","short_name":"Fair Line","description":DESC,"start_url":".","scope":".","display":"standalone","background_color":"#cdd8c4","theme_color":"#f5f7ea",
           "icons":[{"src":"icon-192.png","sizes":"192x192","type":"image/png"},{"src":"icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]},open(D+"manifest.webmanifest","w"),indent=1)
R=["nfl.json","splits_nba.json","splits_nfl.json","nba_match.json","sim_nba.json","sim_nfl.json"]      # fetched when their sheet or tab opens (sim: v3.20)
for f in R:
    if os.path.exists(O+"research/"+f): shutil.copy(O+"research/"+f,D+"research/"+f)
for n in ("icon-180.png","icon-192.png","icon-512.png"):
    if os.path.exists(S+"icons/"+n): shutil.copy(S+"icons/"+n,D+n)
if os.path.exists(S+"og.png"): shutil.copy(S+"og.png",D+"og.png")
# the service worker: network first for the app's own files (fresh lines whenever there is a signal), the saved copy when
# the network fails or takes over 6 seconds; Google Fonts are saved on first use. A new version name drops the old caches.
SW="""/* Fair Line service worker (site.py, v3.36). Network first: the saved copy is only for when there is no signal. */
const V = 'fl-__VER__', CORE = ['./', 'manifest.webmanifest', 'icon-192.png', __RESEARCH__];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => Promise.all(CORE.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('fl-') && k !== V && k !== 'fl-fonts').map(k => caches.delete(k)))).then(() => self.clients.claim())); });
const late = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error('slow')), ms))]);
self.addEventListener('fetch', e => {
  const r = e.request, u = new URL(r.url); if (r.method !== 'GET') return;
  if (/fonts\\.(googleapis|gstatic)\\.com$/.test(u.hostname)) {
    e.respondWith(caches.open('fl-fonts').then(c => c.match(r).then(hit => hit || fetch(r).then(res => { if (res.ok || res.type === 'opaque') c.put(r, res.clone()); return res; })))); return; }
  if (u.origin !== location.origin) return;
  const net = fetch(r).then(res => { if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); } return res; });
  const saved = () => caches.match(r, { ignoreSearch: true }).then(hit => hit || (r.mode === 'navigate' ? caches.match('./') : null));
  // slow network: use the saved copy if there is one, otherwise keep waiting for the network; no network at all: the saved copy
  e.respondWith(late(net, 6000).catch(() => saved().then(hit => hit || net.catch(() => saved().then(h => h || Response.error())))));
});
"""
open(D+"sw.js","w").write(SW.replace("__VER__",VER).replace("__RESEARCH__",", ".join(f"'research/{f}'" for f in R if os.path.exists(D+"research/"+f))))
open(D+".nojekyll","w").write("")
print("site:",sorted(os.listdir(D)),os.path.getsize(D+"index.html")//1024,"KB")
