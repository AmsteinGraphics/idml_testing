#!/usr/bin/env python3
"""Prototype: compute a discrete tab strip from evenly-spaced ink-mix stops.

Each stop is a mix of the sanctioned inks in %; stops are evenly spaced along
the strip (first stop = first tab, last stop = last tab). Each of the N tabs
samples the piecewise-linear (per-channel) tween between its bounding stops.
Tabs tile the MARGIN box (top margin -> bottom margin) as adjacent rectangles.

This is the compute half of the future configure_chapters.py tab generator;
it prints numbers only (no IDML written).
"""
INKS = ["Black", "292", "130", "WarmGray1"]

# ---- the throwaway example stops (unspecified channels = 0%) ----------------
STOPS = [
    {"Black": 100},                       # 1
    {"292": 100, "130": 0},               # 2
    {"130": 100, "292": 25},              # 3
    {"WarmGray1": 100, "292": 0},         # 4
]
N = 18   # tabs

# ---- page / margin geometry (NavTabs master, pt) ----------------------------
PAGE_H, M_TOP, M_BOT = 595.2756, 22.1701, 55.8425
box_top, box_h = M_TOP, PAGE_H - M_TOP - M_BOT
pitch = box_h / N

# ---- 100%-ink appearance on white, for a rough on-paper preview -------------
INK_RGB = {"Black": (30, 30, 28), "292": (93, 167, 229),
           "130": (251, 154, 45), "WarmGray1": (215, 208, 200)}

def vec(stop): return [stop.get(k, 0) for k in INKS]

def sample(pos):
    """piecewise-linear tween of each channel at strip position pos in [0,1]."""
    S = len(STOPS) - 1
    seg = min(int(pos * S), S - 1)          # bounding stop index
    p0, p1 = seg / S, (seg + 1) / S
    f = (pos - p0) / (p1 - p0) if p1 > p0 else 0
    a, b = vec(STOPS[seg]), vec(STOPS[seg + 1])
    return [a[i] + f * (b[i] - a[i]) for i in range(len(INKS))]

def on_paper(mix):
    """multiply/overprint the tinted inks over white -> approx (r,g,b) hex."""
    r = g = b = 1.0
    for k, pct in zip(INKS, mix):
        t = pct / 100.0
        ir, ig, ib = INK_RGB[k]
        r *= 1 - t * (1 - ir / 255); g *= 1 - t * (1 - ig / 255); b *= 1 - t * (1 - ib / 255)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))

# ---- report -----------------------------------------------------------------
print(f"stops: {len(STOPS)} (positions {[round(j/(len(STOPS)-1),3) for j in range(len(STOPS))]})"
      f"   tabs: {N}")
print(f"margin box: top={box_top:.3f}  height={box_h:.3f}  pitch={pitch:.4f} pt/tab\n")
hdr = f"{'#':>2} {'y_top':>8} {'y_bot':>8} | " + " ".join(f"{k:>9}" for k in INKS) + " | preview"
print(hdr); print("-" * len(hdr))
for i in range(N):
    pos = i / (N - 1)
    mix = sample(pos)
    yt = box_top + i * pitch
    cells = " ".join(f"{m:8.1f}%" for m in mix)
    star = "  <- stop" if any(abs(pos - j/(len(STOPS)-1)) < 1e-9 for j in range(len(STOPS))) else ""
    print(f"{i:2d} {yt:8.2f} {yt+pitch:8.2f} | {cells} | {on_paper(mix)}{star}")
print(f"\nlast tab bottom = {box_top + N*pitch:.3f}  (bottom margin = {PAGE_H - M_BOT:.3f})  "
      f"-> {'tiles exactly' if abs(box_top + N*pitch - (PAGE_H - M_BOT)) < 1e-6 else 'MISMATCH'}")
