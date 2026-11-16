#!/usr/bin/env python3
"""Over the Moon — a humpback whale breaching across a giant full moon.

Draws the image procedurally with the standard library only and writes
/output/entry.png (1024x1024). Deterministic: no randomness, no network,
no timestamps. Run it twice and the bytes are identical.

Scene: a humpback arcs out of a glowing night ocean and flies across a
huge full moon, water streaming off its back, while a tiny boat with one
lantern watches from below. The whale is built as a lofted spine — a
curved centre line with a width profile — filled with a scanline polygon
filler, so the body tapers from the broad mid-body to the tail stock and
the rostrum.
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024


# ------------------------------------------------------------------ colour
def clamp01(t):
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def mix(a, b, t):
    """Linear blend of two RGB triples."""
    t = clamp01(t)
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def ease(t):
    """Cosine ease-in-out, for gradients that should feel soft, not linear."""
    return 0.5 - 0.5 * math.cos(math.pi * clamp01(t))


def lcg(seed):
    """Deterministic pseudo-random stream (LCG) — same numbers every run."""
    state = [seed & 0x7FFFFFFF]

    def nxt():
        state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
        return state[0] / 0x7FFFFFFF

    return nxt


# ---------------------------------------------------------------- framebuffer
class Frame:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def set(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = int(rgb[0])
            self.px[i + 1] = int(rgb[1])
            self.px[i + 2] = int(rgb[2])

    def blend(self, x, y, rgb, a):
        """Alpha-blend rgb over the pixel at (x, y); a in 0..1."""
        if a <= 0.0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        if a >= 1.0:
            self.set(x, y, rgb)
            return
        i = (y * self.w + x) * 3
        self.px[i] = int(self.px[i] + (rgb[0] - self.px[i]) * a)
        self.px[i + 1] = int(self.px[i + 1] + (rgb[1] - self.px[i + 1]) * a)
        self.px[i + 2] = int(self.px[i + 2] + (rgb[2] - self.px[i + 2]) * a)

    def vgrad(self, y0, y1, stops):
        """Vertical gradient between (y, rgb) stops, cosine-eased."""
        for y in range(max(0, y0), min(self.h, y1)):
            t = (y - y0) / max(1, y1 - y0 - 1)
            for k in range(len(stops) - 1):
                ya, ca = stops[k]
                yb, cb = stops[k + 1]
                if ya <= t <= yb:
                    f = ease((t - ya) / max(1e-9, yb - ya))
                    col = mix(ca, cb, f)
                    break
            else:
                col = stops[-1][1]
            base = y * self.w * 3
            r, g, b = int(col[0]), int(col[1]), int(col[2])
            for x in range(self.w):
                i = base + x * 3
                self.px[i] = r
                self.px[i + 1] = g
                self.px[i + 2] = b


def disc(frame, cx, cy, r, rgb, alpha=1.0):
    """Filled circle with a soft half-pixel edge."""
    x0 = max(0, int(cx - r - 1))
    x1 = min(frame.w - 1, int(cx + r + 1))
    y0 = max(0, int(cy - r - 1))
    y1 = min(frame.h - 1, int(cy + r + 1))
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        for x in range(x0, x1 + 1):
            dx = x + 0.5 - cx
            d = math.sqrt(dx * dx + dy * dy)
            cov = clamp01(r + 0.5 - d)
            if cov > 0.0:
                frame.blend(x, y, rgb, alpha * cov)


def ring_glow(frame, cx, cy, r_inner, r_outer, rgb, peak):
    """Radial glow that is strongest at r_inner and fades to nothing."""
    x0 = max(0, int(cx - r_outer))
    x1 = min(frame.w - 1, int(cx + r_outer))
    y0 = max(0, int(cy - r_outer))
    y1 = min(frame.h - 1, int(cy + r_outer))
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        for x in range(x0, x1 + 1):
            dx = x + 0.5 - cx
            d = math.sqrt(dx * dx + dy * dy)
            if d <= r_inner:
                a = peak
            elif d >= r_outer:
                continue
            else:
                a = peak * (1.0 - (d - r_inner) / (r_outer - r_inner)) ** 2
            frame.blend(x, y, rgb, a)


def poly_fill(frame, pts, rgb):
    """Scanline polygon fill with 4x vertical supersampling for smooth edges.

    pts: list of (x, y) vertices in order. For each row, the coverage is
    averaged over four sub-scanlines, which anti-aliases slanted edges
    without a full supersampled buffer.
    """
    if len(pts) < 3:
        return
    ys = [p[1] for p in pts]
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(frame.h - 1, int(math.ceil(max(ys))))
    n = len(pts)
    for y in range(y0, y1 + 1):
        spans = []
        for s in (0.125, 0.375, 0.625, 0.875):
            yy = y + s
            xs = []
            for i in range(n):
                x0, y0p = pts[i]
                x1, y1p = pts[(i + 1) % n]
                if (y0p <= yy < y1p) or (y1p <= yy < y0p):
                    t = (yy - y0p) / (y1p - y0p)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                spans.append((xs[k], xs[k + 1]))
        if not spans:
            continue
        # Merge the sub-scanline spans: a pixel is covered by the fraction
        # of sub-rows whose span contains its centre.
        lo = min(s[0] for s in spans)
        hi = max(s[1] for s in spans)
        x0 = max(0, int(math.floor(lo)))
        x1 = min(frame.w - 1, int(math.ceil(hi)))
        for x in range(x0, x1 + 1):
            xc = x + 0.5
            hit = sum(1 for a, b in spans if a <= xc < b)
            if hit:
                frame.blend(x, y, rgb, hit / 4.0)


def quad_bezier(p0, p1, p2, t):
    u = 1.0 - t
    return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def spine_points(ctrl, steps):
    """Smooth curve through the control points, as a chain of quadratic
    beziers joined at the midpoints between consecutive controls.

    Each segment runs from the midpoint before a control point to the
    midpoint after it, with the control point itself as the bezier
    control — so the joints are continuous and the curve never jumps
    back along itself (a naive segment-per-triple chain does).
    """
    def mid(a, b):
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    n = len(ctrl)
    pts = []
    for i in range(1, n - 1):
        start = ctrl[0] if i == 1 else mid(ctrl[i - 1], ctrl[i])
        end = ctrl[-1] if i == n - 2 else mid(ctrl[i], ctrl[i + 1])
        for k in range(steps):
            pts.append(quad_bezier(start, ctrl[i], end, k / steps))
    pts.append(ctrl[-1])
    return pts


def loft(centre, widths):
    """Build a closed polygon around a centre line with per-point half-widths.

    Offsets run along the local normal, so the body keeps a constant
    cross-section even where the spine bends sharply.
    """
    left, right = [], []
    n = len(centre)
    for i, (cx, cy) in enumerate(centre):
        ax, ay = centre[max(0, i - 1)]
        bx, by = centre[min(n - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        w = widths[i]
        left.append((cx + nx * w, cy + ny * w))
        right.append((cx - nx * w, cy - ny * w))
    return left + right[::-1]

# --------------------------------------------------------------------- scene
SKY_TOP = (8, 12, 40)
SKY_MID = (22, 30, 74)
SKY_LOW = (58, 46, 104)
HORIZON = (148, 92, 96)
MOON = (255, 243, 210)
MOON_CORE = (255, 250, 232)
MOON_SHADE = (238, 222, 178)
WHALE = (13, 26, 54)
WHALE_EDGE = (38, 62, 104)
BELLY = (148, 176, 200)
SEA_TOP = (14, 58, 72)
SEA_BOT = (6, 30, 46)
WAVE = (96, 168, 188)
LAMP = (255, 178, 70)
INK = (255, 244, 214)

MOON_C = (600.0, 385.0)
MOON_R = 248.0
SEA_Y = 800


def draw_sky(f):
    f.vgrad(0, SEA_Y, [
        (0.00, SKY_TOP),
        (0.45, SKY_MID),
        (0.80, SKY_LOW),
        (0.97, HORIZON),
        (1.00, HORIZON),
    ])
    # stars: deterministic, denser and brighter toward the top
    rnd = lcg(20261117)
    for _ in range(240):
        x = rnd() * W
        y = (rnd() ** 1.6) * 760
        r = 0.6 + rnd() * 1.3
        bright = 0.35 + 0.65 * (1.0 - y / 800.0) * rnd()
        # keep the moon disc itself star-free
        if math.hypot(x - MOON_C[0], y - MOON_C[1]) < MOON_R + 8:
            continue
        disc(f, x, y, r, (235, 240, 255), bright * 0.9)
    # a few four-point sparkles
    rnd = lcg(777)
    for _ in range(14):
        x = 40 + rnd() * 940
        y = 30 + rnd() * 420
        if math.hypot(x - MOON_C[0], y - MOON_C[1]) < MOON_R + 20:
            continue
        s = 5 + rnd() * 7
        a = 0.5 + rnd() * 0.4
        for k in range(-int(s), int(s) + 1):
            f.blend(int(x) + k, int(y), (255, 255, 255), a * (1 - abs(k) / s))
            f.blend(int(x), int(y) + k, (255, 255, 255), a * (1 - abs(k) / s))


def draw_moon(f):
    cx, cy = MOON_C
    ring_glow(f, cx, cy, MOON_R, MOON_R + 130, (255, 236, 190), 0.55)
    ring_glow(f, cx, cy, MOON_R, MOON_R + 46, (255, 244, 214), 0.5)
    disc(f, cx, cy, MOON_R, MOON)
    disc(f, cx - 18, cy - 26, MOON_R - 22, MOON_CORE, 0.55)
    # maria: soft darker patches, low contrast so the disc stays bright
    for mx, my, mr in ((700, 470, 52), (520, 500, 34), (660, 300, 28),
                       (540, 300, 20), (740, 380, 18)):
        disc(f, mx, my, mr, MOON_SHADE, 0.5)
    # thin bright rim on the upper-left edge
    for t in range(0, 101):
        ang = math.pi * (0.62 + 0.62 * t / 100.0)
        x = cx + (MOON_R - 3) * math.cos(ang)
        y = cy + (MOON_R - 3) * math.sin(ang)
        disc(f, x, y, 3.5, (255, 252, 240), 0.7)


def draw_whale(f):
    # Spine: tail stock low-left, arcing up over the moon, head to the right.
    ctrl = [(118, 806), (215, 640), (330, 470), (470, 330), (640, 258),
            (800, 288), (905, 372)]
    centre = spine_points(ctrl, 26)
    # Half-width profile: slim tail stock, broad mid-body, tapering rostrum.
    prof = []
    for i, (x, y) in enumerate(centre):
        t = i / max(1, len(centre) - 1)
        w = 30.0 + 118.0 * math.sin(math.pi * (0.12 + 0.76 * t)) ** 1.15
        w *= 1.0 - 0.35 * max(0.0, t - 0.88) / 0.12
        prof.append(w)
    body = loft(centre, prof)
    poly_fill(f, body, WHALE)

    # Pale belly: a crescent hugging the underside of the spine — its top
    # edge is the spine itself, its lower edge is a shallower loft, so the
    # light band never crosses onto the whale's back.
    belly_poly = list(centre)
    n = len(centre)
    for i in range(n - 1, -1, -1):
        cx, cy = centre[i]
        ax, ay = centre[max(0, i - 1)]
        bx, by = centre[min(n - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        belly_poly.append((cx + nx * prof[i] * 0.55,
                           cy + ny * prof[i] * 0.55))
    poly_fill(f, belly_poly, BELLY)

    # Throat grooves: three dark arcs across the belly near the head.
    for k, gt in enumerate((0.78, 0.83, 0.88)):
        i = int(gt * (len(centre) - 1))
        gx, gy = centre[i]
        ax, ay = centre[max(0, i - 1)]
        bx, by = centre[min(len(centre) - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        for s in range(-46, 47, 2):
            px = gx + nx * s * 0.9
            py = gy + ny * s * 0.9 + 34
            f.blend(int(px), int(py), WHALE, 0.55)

    # Moonlit rim along the whale's back: a thin loft just inside the upper
    # edge, so the dark body separates from the dark sky.
    rim_poly = []
    for i, (cx, cy) in enumerate(centre):
        ax, ay = centre[max(0, i - 1)]
        bx, by = centre[min(n - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        rim_poly.append((cx - nx * prof[i], cy - ny * prof[i]))
    for i in range(n - 1, -1, -1):
        cx, cy = centre[i]
        ax, ay = centre[max(0, i - 1)]
        bx, by = centre[min(n - 1, i + 1)]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        rim_poly.append((cx - nx * (prof[i] - 8), cy - ny * (prof[i] - 8)))
    poly_fill(f, rim_poly, (168, 202, 228))

    # Pectoral fin: a long curved blade sweeping down from the belly.
    fin = [(592, 332), (548, 408), (492, 486), (428, 548), (408, 552),
           (452, 500), (508, 424), (566, 360), (606, 338)]
    poly_fill(f, fin, WHALE)

    # Tail fluke: two lobes fanning out at the tail stock.
    fluke = [(118, 806), (58, 742), (28, 736), (72, 786), (96, 812),
             (82, 850), (48, 872), (110, 840), (136, 820)]
    poly_fill(f, fluke, WHALE)

    # Rostrum / jaw: a thin bright edge under the head, plus the eye.
    jaw = [(812, 330), (868, 356), (912, 388), (898, 396), (856, 368),
           (806, 342)]
    poly_fill(f, jaw, WHALE_EDGE)
    disc(f, 856, 344, 7, (4, 8, 18))
    disc(f, 858, 342, 2.2, (255, 255, 255), 0.9)


def draw_spray(f):
    """Water streaming off the whale: droplet arcs near the tail and belly."""
    rnd = lcg(4242)
    # Big burst where the tail leaves the water.
    for _ in range(260):
        a = math.pi * (0.55 + rnd() * 0.9)
        r = 30 + (rnd() ** 0.7) * 190
        x = 128 + r * math.cos(a) * 0.8
        y = 806 - r * math.sin(a) * 0.9
        if y < 430:
            continue
        rad = 1.0 + rnd() * 3.2
        bright = 0.5 + rnd() * 0.5
        disc(f, x, y, rad, (178, 222, 240), bright * 0.85)
    # Thin streams peeling off the belly as it rises.
    rnd = lcg(991)
    for _ in range(150):
        t = rnd()
        x = 300 + t * 520
        y = 300 + 210 * math.sin(math.pi * t) - rnd() * 60
        rad = 0.8 + rnd() * 2.2
        disc(f, x, y, rad, (190, 228, 244), 0.45 + rnd() * 0.45)
    # A bright splash crown right at the waterline under the tail.
    for _ in range(90):
        x = 60 + rnd() * 160
        y = 790 + rnd() * 22
        rad = 1.2 + rnd() * 3.4
        disc(f, x, y, rad, (205, 235, 248), 0.6 + rnd() * 0.4)


def draw_sea(f):
    f.vgrad(SEA_Y, H, [(0.0, SEA_TOP), (1.0, SEA_BOT)])
    # Moonlight path: a shimmering column under the moon.
    rnd = lcg(31337)
    for _ in range(70):
        y = SEA_Y + 8 + rnd() * 200
        spread = 60 + (y - SEA_Y) * 1.1
        x = MOON_C[0] + (rnd() - 0.5) * 2 * spread
        ln = 12 + rnd() * 46
        for k in range(int(ln)):
            f.blend(int(x) + k, int(y), (255, 226, 170), 0.10 + rnd() * 0.12)
    # Wave dashes, denser near the horizon.
    rnd = lcg(2026)
    for _ in range(120):
        y = SEA_Y + 10 + (rnd() ** 1.4) * 200
        x = rnd() * W
        ln = 14 + rnd() * 60
        for k in range(int(ln)):
            f.blend(int(x) + k, int(y), WAVE, 0.22 + rnd() * 0.2)


def draw_boat(f):
    bx, by = 812, 838
    # Hull and mast, a small dark silhouette.
    hull = [(bx - 34, by), (bx + 34, by), (bx + 22, by + 16),
            (bx - 22, by + 16)]
    poly_fill(f, hull, (6, 12, 26))
    for k in range(52):
        f.blend(bx, by - k, (6, 12, 26), 1.0)
    # The one lantern: warm glow, bright core, and its reflection below.
    ring_glow(f, bx, by - 56, 4, 42, LAMP, 0.85)
    disc(f, bx, by - 56, 7, (255, 224, 150))
    disc(f, bx, by - 56, 3.5, (255, 246, 220))
    rnd = lcg(55)
    for _ in range(40):
        y = by + 20 + rnd() * 150
        x = bx + (rnd() - 0.5) * (10 + (y - by) * 0.22)
        ln = 6 + rnd() * 22
        for k in range(int(ln)):
            f.blend(int(x) + k, int(y), LAMP, 0.12 + rnd() * 0.18)


# --------------------------------------------------------------------- font
# 5x7 bitmap glyphs, rows top to bottom, 5 bits each. My own letterforms.
GLYPHS = {
    "O": [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    "V": [0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b01010, 0b00100],
    "E": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
    "R": [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
    "T": [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
    "H": [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    "M": [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
    "N": [0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001],
    " ": [0, 0, 0, 0, 0, 0, 0],
}


def draw_text(f, text, cx, y, scale, rgb):
    cell = 6 * scale
    total = len(text) * cell - scale
    x = cx - total // 2
    for ch in text:
        g = GLYPHS.get(ch, GLYPHS[" "])
        for row in range(7):
            bits = g[row]
            for col in range(5):
                if bits & (1 << (4 - col)):
                    for dy in range(scale):
                        for dx in range(scale):
                            f.set(x + col * scale + dx, y + row * scale + dy,
                                  rgb)
        x += cell


# ---------------------------------------------------------------------- png
def chunk(typ, data):
    out = struct.pack(">I", len(data)) + typ + data
    out += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    return out


def write_png(f, path):
    raw = bytearray()
    for y in range(f.h):
        raw.append(0)
        raw += f.px[y * f.w * 3:(y + 1) * f.w * 3]
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", f.w, f.h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    f = Frame(W, H)
    draw_sky(f)
    draw_moon(f)
    draw_whale(f)
    draw_spray(f)
    draw_sea(f)
    draw_boat(f)
    draw_text(f, "OVER THE MOON", W // 2, 918, 7, INK)
    path = os.path.join(out_dir, "entry.png")
    n = write_png(f, path)
    print(f"wrote {path} ({n} bytes)")


if __name__ == "__main__":
    main()
