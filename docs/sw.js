/* Fair Line service worker (site.py, v3.36). Network first: the saved copy is only for when there is no signal. */
const V = 'fl-3.36', CORE = ['./', 'manifest.webmanifest', 'icon-192.png', 'research/nfl.json', 'research/splits_nba.json', 'research/splits_nfl.json', 'research/nba_match.json', 'research/sim_nba.json', 'research/sim_nfl.json'];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => Promise.all(CORE.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('fl-') && k !== V && k !== 'fl-fonts').map(k => caches.delete(k)))).then(() => self.clients.claim())); });
const late = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error('slow')), ms))]);
self.addEventListener('fetch', e => {
  const r = e.request, u = new URL(r.url); if (r.method !== 'GET') return;
  if (/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) {
    e.respondWith(caches.open('fl-fonts').then(c => c.match(r).then(hit => hit || fetch(r).then(res => { if (res.ok || res.type === 'opaque') c.put(r, res.clone()); return res; })))); return; }
  if (u.origin !== location.origin) return;
  const net = fetch(r).then(res => { if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); } return res; });
  const saved = () => caches.match(r, { ignoreSearch: true }).then(hit => hit || (r.mode === 'navigate' ? caches.match('./') : null));
  // slow network: use the saved copy if there is one, otherwise keep waiting for the network; no network at all: the saved copy
  e.respondWith(late(net, 6000).catch(() => saved().then(hit => hit || net.catch(() => saved().then(h => h || Response.error())))));
});
