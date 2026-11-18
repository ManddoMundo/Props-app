"""v3.31 pixel dragons for hot and cold props (display only). An original fire dragon and ice drake, drawn in code from a
small rig (body, neck curve, head, jaw, two wings on an angle, legs, tail curve) on a 56 x 44 pixel grid, shaded with light
from the upper left and outlined. Also draws the breath, the smoke and mist puffs, and the small looping flame and frost
that stay on a lit number. Run it to rebuild the art; it writes the sheets into index.src.html between the DRAGON markers
as data URIs, so the page stays one file. `--preview out.png` writes a contact sheet instead.

Dragon frames (each 56 x 44, facing left): 0-5 the wing beat (up, half up, level, down, half down on the upstroke, rising),
6 landing (wings high, legs reaching), 7 perched, 8 perched breathing in (idle), 9 rearing back (inhale),
10 breathing out (jaw open, head forward)."""
import base64, io, math, re, sys
from PIL import Image, ImageDraw

W, H = 56, 54
OY = 10     # everything is drawn 8 rows down, so a raised wing has room above the head
PAL = {
    "fire": dict(hi=(244, 120, 72), body=(212, 60, 38), mid=(170, 40, 30), sh=(118, 24, 24), belly=(240, 196, 120), belly_sh=(204, 146, 82),
                 plate=(176, 116, 64), wing_hi=(176, 58, 64), wing=(136, 34, 48), wing_sh=(92, 20, 36), far=(84, 22, 34), bone=(240, 230, 204),
                 bone_sh=(188, 168, 138), eye=(255, 222, 70), pupil=(60, 12, 8), line=(40, 10, 12), mouth=(84, 14, 18), spike=(236, 222, 190)),
    "ice": dict(hi=(186, 230, 255), body=(96, 176, 236), mid=(64, 134, 200), sh=(40, 92, 156), belly=(232, 248, 255), belly_sh=(178, 214, 238),
                plate=(140, 186, 220), wing_hi=(132, 196, 246), wing=(70, 138, 210), wing_sh=(42, 92, 158), far=(36, 76, 132), bone=(250, 254, 255),
                bone_sh=(196, 224, 244), eye=(210, 255, 248), pupil=(10, 40, 70), line=(10, 26, 50), mouth=(18, 44, 88), spike=(236, 252, 255)),
}
ORDER = ["far", "tail", "leg_far", "body", "belly", "leg", "wing", "neck", "head", "top"]      # paint order (later wins)


class Canvas:
    def __init__(s):
        s.tag = [[None] * W for _ in range(H)]; s.z = [[-1] * W for _ in range(H)]

    def put(s, x, y, tag, z):
        x, y = int(round(x)), int(round(y + OY))
        if 0 <= x < W and 0 <= y < H and z >= s.z[y][x]: s.tag[y][x] = tag; s.z[y][x] = z

    def poly(s, pts, tag, z):
        im = Image.new("L", (W, H), 0); ImageDraw.Draw(im).polygon([(round(x), round(y + OY)) for x, y in pts], fill=1); P = im.load()
        for y in range(H):
            for x in range(W):
                if P[x, y]: s.put(x, y - OY, tag, z)

    def disc(s, cx, cy, r, tag, z):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= r * r: s.put(x, y, tag, z)

    def ell(s, cx, cy, rx, ry, tag, z, rot=0):
        c, n = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        for y in range(int(cy - max(rx, ry) - 1), int(cy + max(rx, ry) + 2)):
            for x in range(int(cx - max(rx, ry) - 1), int(cx + max(rx, ry) + 2)):
                dx, dy = x + .5 - cx, y + .5 - cy; u, v = dx * c + dy * n, -dx * n + dy * c
                if (u / rx) ** 2 + (v / ry) ** 2 <= 1: s.put(x, y, tag, z)

    def tube(s, pts, r0, r1, tag, z, steps=40):      # a thick curve (bezier through 3 or 4 points), radius r0 to r1
        for i in range(steps + 1):
            t = i / steps; x, y = bez(pts, t); s.disc(x, y, r0 + (r1 - r0) * t, tag, z)

    def stroke(s, a, b, tag, z):
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
        for i in range(n + 1):
            t = i / max(n, 1); s.put(round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), tag, z)


def bez(p, t):
    if len(p) == 3: (a, b, c) = p; return ((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1])
    (a, b, c, d) = p; u = 1 - t
    return (u ** 3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t ** 3 * d[0], u ** 3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t ** 3 * d[1])


def pol(o, ang, ln):      # a point at angle (0 = back, toward +x; negative = up) and length from o
    return (o[0] + math.cos(math.radians(ang)) * ln, o[1] + math.sin(math.radians(ang)) * ln)


def wing(c, sh, att, a, z, far=False):
    """Bat wing: arm from the shoulder to the wrist, three fingers fanning from it, membrane scalloped between them."""
    k = .82 if far else 1
    wr = pol(sh, a - 18, 11 * k)
    tips = [pol(wr, a - 62, 13 * k), pol(wr, a - 22, 17 * k), pol(wr, a + 14, 15 * k)]
    edge = [tips[0]]
    for p, q in zip(tips, tips[1:] + [att]):
        m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2); edge += [(m[0] + (wr[0] - m[0]) * .3, m[1] + (wr[1] - m[1]) * .3), q]
    tagm = "farwing" if far else "wing"
    c.poly([sh, wr] + edge, tagm, z)
    if not far:
        c.tube([sh, ((sh[0] + wr[0]) / 2, (sh[1] + wr[1]) / 2 - 1), wr], 1.3, 1.0, "wbone", z + 1, 12)
        for t in tips: c.stroke(wr, t, "wfinger", z + 1)
        c.put(round(wr[0]), round(wr[1]) - 1, "claw", z + 2)


def dragon(f):
    c = Canvas()
    fly = f <= 5; land = f == 6; perch = f in (7, 8); inhale = f == 9; breathe = f == 10
    bob = [0, 1, 2, 2, 1, 0][f] if fly else 0
    bx, by = 31, (19 + bob) if fly else 26 if not land else 22
    if perch and f == 8: by += .5
    tilt = -6 if fly else -10 if land else -14
    # wing angle: 0 = straight back, negative = up
    a = {0: -78, 1: -52, 2: -14, 3: 30, 4: 12, 5: -40, 6: -70}.get(f, None)
    sh, att = (bx - 3, by - 5), (bx + 9, by - 1)
    if a is not None: wing(c, (sh[0] + 4, sh[1] - 2), (att[0] + 3, att[1] - 2), a - 10, 1, far=True)
    # tail
    if fly: c.tube([(bx + 9, by + 1), (bx + 17, by + 2), (bx + 21, by - 2 + bob), (bx + 24, by - 4)], 3.4, 1.0, "body", 2)
    else: c.tube([(bx + 8, by + 2), (bx + 14, by + 9), (bx + 20, by + 11), (bx + 23, by + 7)], 3.6, 1.0, "body", 2)
    tip = (bx + 24, by - 4) if fly else (bx + 23, by + 7)
    c.poly([(tip[0] - 1, tip[1] - 3), (tip[0] + 3, tip[1]), (tip[0] - 1, tip[1] + 3), (tip[0] - 1, tip[1])], "body", 2)
    # far legs
    if fly: c.tube([(bx + 5, by + 4), (bx + 9, by + 7), (bx + 12, by + 8)], 2.0, 1.2, "legfar", 1)
    elif land: c.tube([(bx + 5, by + 3), (bx + 6, by + 9), (bx + 7, by + 14)], 2.2, 1.3, "legfar", 1)
    else: c.tube([(bx + 6, by + 3), (bx + 9, by + 8), (bx + 8, by + 12)], 2.4, 1.4, "legfar", 1)
    # body and chest
    c.ell(bx, by, 11, 6.4, "body", 3, tilt); c.ell(bx - 7, by - 1, 5.6, 5.4, "body", 3, tilt)
    c.ell(bx - 1, by + 3.2, 9, 2.6, "belly", 4, tilt)
    # near legs
    if fly:
        c.tube([(bx + 4, by + 4), (bx + 8, by + 7), (bx + 11, by + 8)], 2.6, 1.4, "body", 5); c.put(bx + 12, by + 8, "claw", 6); c.put(bx + 12, by + 9, "claw", 6)
        c.tube([(bx - 7, by + 3), (bx - 5, by + 6), (bx - 3, by + 7)], 1.8, 1.1, "body", 5); c.put(bx - 2, by + 8, "claw", 6)
    elif land:
        c.ell(bx + 4, by + 3, 3.6, 4.4, "body", 5); c.tube([(bx + 4, by + 6), (bx + 3, by + 11), (bx + 4, by + 15)], 2.2, 1.4, "body", 5)
        for i in range(3): c.put(bx + 2 + i * 2, by + 16, "claw", 6)
        c.tube([(bx - 8, by + 3), (bx - 9, by + 8), (bx - 9, by + 12)], 1.8, 1.2, "body", 5); c.put(bx - 10, by + 13, "claw", 6); c.put(bx - 8, by + 13, "claw", 6)
    else:
        c.ell(bx + 4, by + 3, 4.2, 5, "body", 5); c.tube([(bx + 5, by + 7), (bx + 3, by + 11), (bx + 3, by + 14)], 2.2, 1.6, "body", 5)
        for i in range(3): c.put(bx + 1 + i * 2, by + 15, "claw", 6)
        c.tube([(bx - 8, by + 3), (bx - 9, by + 9), (bx - 9, by + 14)], 2.0, 1.4, "body", 5)
        for i in range(2): c.put(bx - 11 + i * 2, by + 15, "claw", 6)
    # back spikes
    for i in range(6):
        x, y = bx - 6 + i * 3.4, by - 6.4 + i * .5 - (0 if fly else 1)
        c.poly([(x - 1, y + 1), (x + .5, y - 2), (x + 2, y + 1)], "spike", 4)
    # near wing
    if a is not None: wing(c, sh, att, a, 7)
    else:      # folded: tucked up along the back, the finger tips standing up behind the shoulder
        lift = -2 if inhale else 0
        c.poly([(sh[0], sh[1] + 1), (sh[0] + 4, sh[1] - 9 + lift), (sh[0] + 8, sh[1] - 13 + lift), (sh[0] + 11, sh[1] - 7), (sh[0] + 15, sh[1] - 4), (att[0] + 1, att[1] + 1), (sh[0] + 5, sh[1] + 3)], "wing", 7)
        c.tube([(sh[0], sh[1] + 1), (sh[0] + 4, sh[1] - 7 + lift), (sh[0] + 8, sh[1] - 13 + lift)], 1.2, .9, "wbone", 8, 14)
        c.stroke((sh[0] + 8, sh[1] - 13 + lift), (sh[0] + 13, sh[1] - 5), "wfinger", 8); c.put(sh[0] + 8, sh[1] - 14 + lift, "claw", 9)
    # neck and head
    if fly: nb, hb = (bx - 10, by - 3), (bx - 21, by - 6)
    elif land: nb, hb = (bx - 10, by - 4), (bx - 19, by - 12)
    elif inhale: nb, hb = (bx - 10, by - 5), (bx - 14, by - 17)
    elif breathe: nb, hb = (bx - 10, by - 4), (bx - 21, by - 12)
    else: nb, hb = (bx - 10, by - 4), (bx - 17, by - 14) if f == 7 else (bx - 17, by - 13)
    mid = ((nb[0] + hb[0]) / 2 + (2 if not fly else 0), (nb[1] + hb[1]) / 2 + (0 if fly else 2))
    c.tube([nb, mid, hb], 4.4, 3.0, "body", 9, 30)
    c.tube([(nb[0] + 1, nb[1] + 3), (mid[0] + 1, mid[1] + 2.6), (hb[0] + 1.5, hb[1] + 2.4)], 2.2, 1.3, "belly", 10, 30)
    for i in range(3):      # neck spikes
        x, y = bez([nb, mid, hb], .25 + i * .22); c.poly([(x + 1.5, y - 3.5), (x + 3, y - 5.5), (x + 3.5, y - 3)], "spike", 8)
    hx, hy = hb[0] - 1, hb[1]
    up = -1 if inhale else 0
    skull = [(hx + 5, hy - 3 + up), (hx + 1, hy - 4 + up), (hx - 4, hy - 3 + up), (hx - 9, hy - 1 + up), (hx - 10, hy + 1 + up), (hx - 9, hy + 2), (hx - 2, hy + 2), (hx + 4, hy + 3), (hx + 6, hy)]
    c.poly(skull, "body", 11)
    c.poly([(hx + 1, hy - 4 + up), (hx - 3, hy - 3 + up), (hx - 1, hy - 5 + up)], "body", 11)      # brow
    if breathe:
        c.poly([(hx - 8, hy + 4), (hx - 2, hy + 3), (hx + 4, hy + 3), (hx + 3, hy + 5), (hx - 3, hy + 6), (hx - 8, hy + 6)], "body", 11)      # dropped jaw
        c.poly([(hx - 9, hy + 2), (hx + 3, hy + 2), (hx + 3, hy + 3), (hx - 8, hy + 4)], "mouth", 12)
        for x in (hx - 8, hx - 6, hx - 4): c.put(x, hy + 2, "tooth", 13); c.put(x + 1, hy + 4, "tooth", 13)
    else:
        c.poly([(hx - 9, hy + 2), (hx + 4, hy + 3), (hx + 2, hy + 4), (hx - 8, hy + 3)], "body", 11)
        c.stroke((hx - 8, hy + 2), (hx + 2, hy + 3), "mouth", 12); c.put(hx - 7, hy + 3, "tooth", 13)
    c.put(hx - 9, hy, "mouth", 12)      # nostril
    c.put(hx - 2, hy - 2 + up, "eye", 13); c.put(hx - 1, hy - 2 + up, "eye", 13); c.put(hx - 1, hy - 1 + up, "pupil", 13)
    # horns, curving back
    c.tube([(hx + 2, hy - 3 + up), (hx + 6, hy - 6 + up), (hx + 10, hy - 6 + up)], 1.2, .6, "bone", 12, 16)
    c.tube([(hx + 4, hy - 1 + up), (hx + 8, hy - 3 + up), (hx + 11, hy - 2 + up)], 1.0, .5, "bone", 12, 16)
    c.poly([(hx + 4, hy + 1), (hx + 8, hy + 3), (hx + 5, hy + 3)], "spike", 12)      # cheek frill
    return c


def render(c, pal):
    T = c.tag
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); P = img.load()
    g = lambda x, y: T[y][x] if 0 <= x < W and 0 <= y < H else None
    same = lambda a, b: a is not None and (a == b or {a, b} <= {"body", "belly"})
    for y in range(H):
        for x in range(W):
            t = T[y][x]
            if t is None: continue
            ul, u, d, d2, r = g(x - 1, y - 1), g(x, y - 1), g(x, y + 1), g(x, y + 2), g(x + 1, y)
            if t in ("body", "legfar"):
                if t == "legfar": col = pal["sh"] if not same(d, t) else pal["mid"]
                elif not same(u, t) or not same(ul, t): col = pal["hi"]
                elif not same(d, t): col = pal["sh"]
                elif not same(d2, t) or not same(r, t): col = pal["mid"]
                else: col = pal["body"]
            elif t == "belly":
                col = pal["belly_sh"] if not same(d, t) else pal["plate"] if x % 3 == 0 and same(u, t) and same(g(x, y + 1), t) else pal["belly"]
            elif t == "wing":
                near = sum(1 for dy in range(-2, 3) for dx in range(-2, 3) if g(x + dx, y + dy) in ("wbone", "wfinger"))
                col = pal["wing_hi"] if near >= 2 else pal["wing_sh"] if g(x, y + 1) is None or g(x, y + 2) is None else pal["wing"]
            elif t == "farwing": col = pal["far"]
            elif t == "wbone": col = pal["hi"] if not same(u, t) else pal["body"]
            elif t == "wfinger": col = pal["body"]
            elif t in ("bone", "claw", "tooth"): col = pal["bone"] if g(x, y - 1) != t else pal["bone_sh"]
            elif t == "spike": col = pal["spike"] if g(x, y - 1) is None and g(x, y - 2) is None else pal["mid"]
            else: col = pal[t]
            P[x, y] = col + (255,)
    out = img.copy(); O = out.load()
    for y in range(H):
        for x in range(W):
            if T[y][x] is not None: continue
            if any(g(x + dx, y + dy) is not None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))): O[x, y] = pal["line"] + (255,)
    # inner lines where the near wing or the neck crosses the body, so the parts read apart
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            t = T[y][x]
            if t in ("wing",) and T[y + 1][x] in ("body", "belly") and c.z[y + 1][x] < c.z[y][x]: O[x, y + 1] = pal["line"] + (255,)
    return out


def breath(kind, frame, bw=64, bh=26):
    """Billowing breath from the mouth (right edge) spreading left, 4 flicker frames; fire carries sparks, frost carries flecks."""
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); P = img.load()
    cols = [(255, 252, 226), (255, 236, 120), (255, 180, 50), (240, 104, 34), (184, 50, 28)] if kind == "fire" else \
           [(255, 255, 255), (226, 250, 255), (168, 224, 252), (104, 176, 236), (62, 116, 188)]
    best = [[9.0] * bw for _ in range(bh)]
    for i in range(34):
        d = i / 33
        cx = bw - 2 - d * (bw - 8) + math.sin(i * 1.7 + frame * 1.6) * 1.4
        cy = bh / 2 + math.sin(i * .7 + frame * 1.3) * d * 2.8
        r = 1.4 + d * 8.6 + ((i * 7 + frame * 3) % 3) * .4
        for y in range(bh):
            for x in range(bw):
                q = math.hypot(x + .5 - cx, y + .5 - cy) / r
                if q <= 1: best[y][x] = min(best[y][x], q * .74 + d * .48)
    for y in range(bh):
        for x in range(bw):
            k = best[y][x]
            if k < 9: P[x, y] = cols[min(4, int(k / 1.22 * 5))] + (255,)
    for j in range(7):      # sparks or flecks flying off the edge
        x = int((j * 9 + frame * 5) % (bw - 12)) + 4; y = int(bh / 2 + ((j * 5 + frame * 3) % 9 - 4) * (1.2 + x / bw))
        if 0 <= y < bh and P[x, y][3] == 0: P[x, y] = (cols[1] if kind == "fire" else cols[0]) + (255,)
    return img


def puff(kind, s=12):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0)); P = img.load()
    base, hi, lo = ((122, 118, 134), (168, 164, 180), (88, 84, 100)) if kind == "fire" else ((206, 234, 252), (246, 252, 255), (160, 204, 236))
    for (cx, cy, r) in ((s * .36, s * .58, s * .3), (s * .64, s * .52, s * .3), (s * .5, s * .32, s * .25)):
        for y in range(s):
            for x in range(s):
                if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 <= r * r: P[x, y] = (hi if y < cy - r * .3 else lo if y > cy + r * .4 else base) + (255,)
    return img


def linger(kind, frame, lw=24, lh=24):
    """What stays on a lit number, tiled behind its digits: tongues of flame rising from the foot (fire), or ice crystals and
    a frosted foot (frost). 3 frames, stacked top to bottom so the page can tile them sideways and step through them."""
    img = Image.new("RGBA", (lw, lh), (0, 0, 0, 0)); P = img.load()
    if kind == "fire":
        cols = [(255, 250, 214), (255, 222, 104), (255, 168, 52), (246, 106, 34), (214, 66, 26)]
        for i, x0 in enumerate((3, 9, 15, 21)):
            hgt = (15, 21, 13, 19)[(i + frame) % 4] + (frame % 2) * 2; sway = (0, 1, -1)[(i + frame) % 3]
            for y in range(lh - hgt, lh):
                t = (lh - y) / hgt; half = 4.4 * (1 - t) ** .65 + .4
                cx = x0 + sway * t * 2
                for x in range(-3, lw + 3):
                    d = abs(x + .5 - cx)
                    if d <= half:
                        k = min(4, int(t * 2.6 + d / half * 1.7))
                        P[x % lw, y] = cols[k] + (255,)
    else:
        cols = [(255, 255, 255), (206, 240, 255), (140, 204, 244), (90, 156, 220)]
        for i, (x0, y0) in enumerate(((4, 16), (12, 9), (19, 18), (8, 4), (20, 6))):
            on = (i + frame) % 3 == 0; r = 2 if on else 1
            for d in range(-r, r + 1):
                for (x, y) in ((x0 + d, y0), (x0, y0 + d)):
                    if 0 <= y < lh: P[x % lw, y] = cols[0 if d == 0 else 1] + (255,)
            if on:
                for (x, y) in ((x0 - 1, y0 - 1), (x0 + 1, y0 + 1), (x0 - 1, y0 + 1), (x0 + 1, y0 - 1)):
                    if 0 <= y < lh: P[x % lw, y] = cols[2] + (255,)
        for x in range(lw):      # frost along the foot
            for y in range(lh - 3 - (x * 7 + 3) % 3, lh): P[x, y] = cols[2 if y < lh - 1 else 3] + (255,)
    return img


def vsheet(imgs):
    w = max(i.width for i in imgs); h = sum(i.height for i in imgs); s = Image.new("RGBA", (w, h), (0, 0, 0, 0)); y = 0
    for i in imgs: s.paste(i, (0, y)); y += i.height
    return s


def sheet(imgs):
    w = sum(i.width for i in imgs); h = max(i.height for i in imgs); s = Image.new("RGBA", (w, h), (0, 0, 0, 0)); x = 0
    for i in imgs: s.paste(i, (x, 0)); x += i.width
    return s


def uri(img):
    b = io.BytesIO(); img.save(b, "PNG", optimize=True); return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def build():
    out = {}
    for kind in ("fire", "ice"):
        out[kind] = sheet([render(dragon(f), PAL[kind]) for f in range(11)])
        out[kind + "_b"] = sheet([breath(kind, f) for f in range(4)])
        out[kind + "_p"] = puff(kind)
        out[kind + "_l"] = vsheet([linger(kind, f) for f in range(3)])
    return out


if __name__ == "__main__":
    out = build()
    if "--preview" in sys.argv:
        Z = 5; rows = []
        for kind in ("fire", "ice"):
            rows.append(out[kind].resize((out[kind].width * Z, H * Z), Image.NEAREST))
            ex = sheet([out[kind + "_b"], Image.new("RGBA", (6, 1)), out[kind + "_p"], Image.new("RGBA", (6, 1)), out[kind + "_l"]])
            rows.append(ex.resize((ex.width * Z, ex.height * Z), Image.NEAREST))
        pv = Image.new("RGBA", (max(r.width for r in rows), sum(r.height + 10 for r in rows)), (26, 32, 29, 255)); y = 0
        for r in rows: pv.paste(r, (0, y), r); y += r.height + 10
        pv.save(sys.argv[sys.argv.index("--preview") + 1]); print("preview", pv.size)
    else:
        css = "\n".join(f"  --drg-{k.replace('_', '-')}:url({uri(v)});" for k, v in out.items())
        p = "/home/claude/props/src/index.src.html"; s = open(p).read()
        s2 = re.sub(r"/\*DRAGON:start\*/.*?/\*DRAGON:end\*/", lambda m: "/*DRAGON:start*/:root{\n" + css + "\n}/*DRAGON:end*/", s, flags=re.S)
        if "/*DRAGON:start*/" not in s: print("markers not found"); sys.exit(1)
        open(p, "w").write(s2); print("sheets:", {k: v.size for k, v in out.items()}, len(css), "bytes of css")
