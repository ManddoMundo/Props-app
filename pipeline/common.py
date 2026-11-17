"""Shared pieces: negative binomial distribution fit and calibration scoring."""
import json, os, re, unicodedata
import numpy as np
from scipy import stats, optimize


def norm(s):
    """Name key used everywhere a book, injury report and box score have to agree on a player."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    return " ".join(t for t in s.split() if t not in ("jr", "sr", "ii", "iii", "iv", "v"))


def load_news(lg, dates, path="/home/claude/props/out/news.json"):
    """Today's lineup news for one league (built by `daily.py news`). Ignored unless it is dated inside the slate,
    so a stale file can never set a lineup. Returns sets of normalised names: out, q (questionable), inn (book has a line)."""
    empty = dict(out=set(), q=set(), inn=set(), qb_game={}, on=False)
    try:
        n = json.load(open(path)).get(lg) or {}
    except Exception:
        return empty
    if n.get("date") not in set(dates):
        return empty
    return dict(out=set(n.get("out", [])), q=set(n.get("q", [])), inn=set(n.get("in", [])), qb_game=n.get("qb_game", {}), on=True)


def nb_k(mu, a, b):
    return np.clip(np.exp(a + b * np.log(np.maximum(mu, 1e-6))), 0.05, 400.0)


def fit_dispersion(mu, y):
    """Fit log k = a + b log mu by maximum likelihood. y are non-negative ints."""
    mu = np.maximum(np.asarray(mu, float), 1e-4)
    y = np.maximum(np.round(np.asarray(y, float)), 0).astype(int)

    def nll(p):
        k = nb_k(mu, p[0], p[1])
        return -stats.nbinom.logpmf(y, k, k / (k + mu)).sum()

    best = None
    for a0 in (0.0, 1.0, 2.5):
        r = optimize.minimize(nll, [a0, 0.0], method="Nelder-Mead",
                              options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": 800})
        if best is None or r.fun < best.fun:
            best = r
    return float(best.x[0]), float(best.x[1])


def nb_cdf(x, mu, a, b):
    k = nb_k(mu, a, b)
    return stats.nbinom.cdf(np.floor(x), k, k / (k + mu))


def score(mu, y, a, b, rng):
    """Out-of-sample checks for a set of projections."""
    mu = np.maximum(np.asarray(mu, float), 1e-4)
    y = np.maximum(np.round(np.asarray(y, float)), 0)
    k = nb_k(mu, a, b)
    p = k / (k + mu)
    lo = stats.nbinom.cdf(y - 1, k, p)
    hi = stats.nbinom.cdf(y, k, p)
    pit = lo + rng.random(len(y)) * (hi - lo)          # randomised PIT
    q10 = stats.nbinom.ppf(0.10, k, p)
    q90 = stats.nbinom.ppf(0.90, k, p)
    med = stats.nbinom.ppf(0.5, k, p)
    # reliability: price a half-point line near each projection and see how often the
    # over actually lands, bucketed by the model's stated probability
    off = rng.choice([-0.35, -0.2, -0.1, 0.0, 0.1, 0.2, 0.35], size=len(y))
    line = np.floor(mu * (1 + off)) + 0.5
    pov = 1 - stats.nbinom.cdf(np.floor(line), k, p)
    hit = (y > line).astype(float)
    bins = np.array([0, .2, .3, .4, .45, .5, .55, .6, .7, .8, 1.0001])
    rel = []
    for i in range(len(bins) - 1):
        m = (pov >= bins[i]) & (pov < bins[i + 1])
        if m.sum() >= 25:
            rel.append({"lo": float(bins[i]), "hi": float(min(bins[i + 1], 1)), "n": int(m.sum()),
                        "pred": float(pov[m].mean()), "obs": float(hit[m].mean())})
    return {
        "n": int(len(y)),
        "mae": float(np.abs(y - mu).mean()),
        "bias": float((y - mu).mean()),
        "cover80": float(((y >= q10) & (y <= q90)).mean()),
        "pit_deciles": [float(x) for x in np.histogram(pit, bins=10, range=(0, 1))[0] / len(y)],
        "over_median": float((y > med).mean()),
        "brier": float(((pov - hit) ** 2).mean()),
        "brier_coinflip": float(((0.5 - hit) ** 2).mean()),
        "reliability": rel,
    }
