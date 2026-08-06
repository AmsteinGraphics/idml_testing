#!/usr/bin/env python3
"""Bake a native mixed-ink tab strip into an IDML (replaces the placed .ai).

Reads evenly-spaced ink-mix stops from <src>.tabstops.csv, tweens N tabs, emits
one mixed-ink swatch per tab (schema mirrored byte-for-byte from InDesign), and
draws the tab rectangles tiling the margin box along the page edge. Non-current
tabs are dimmed via FillTint; the current tab is full.

This build is a PROOF (N override, own output dir) — it does not touch the real
template. Once the look is approved it extends to the full per-master bake.

Usage: python3 bake_tab_strip.py [src_dir] [out_dir] [--n N] [--current i]
"""
import os, re, sys, csv, shutil, copy

SRC = "template_build"; OUT = "template_build_tabproof"; N = 18; CUR = 9
a = sys.argv[1:]; pos = [x for x in a if not x.startswith("-")]
if len(pos) > 0: SRC = pos[0]
if len(pos) > 1: OUT = pos[1]
if "--n" in a: N = int(a[a.index("--n")+1])
if "--current" in a: CUR = int(a[a.index("--current")+1])

# ---- ink metadata ----------------------------------------------------------
KEYS = ["Black", "292", "130", "Warm Gray 1"]          # CSV column order
TRAP = ["Black", "Warm Gray 1", "130", "292"]          # InDesign lists in trap order
INK_REF   = {"Black":"Ink/$ID/Process Black", "Warm Gray 1":"Ink/PANTONE Warm Gray 1 U",
             "130":"Ink/PANTONE 130 U", "292":"Ink/PANTONE 292 U"}
INK_NAME  = {"Black":"$ID/Process Black", "Warm Gray 1":"PANTONE Warm Gray 1 U",
             "130":"PANTONE 130 U", "292":"PANTONE 292 U"}
COLOR_REF = {"Black":"Color/Black", "Warm Gray 1":"Color/PANTONE Warm Gray 1 U",
             "130":"Color/PANTONE 130 U", "292":"Color/PANTONE 292 U"}
COLOR_NAME= {"Black":"Black", "Warm Gray 1":"PANTONE Warm Gray 1 U",
             "130":"PANTONE 130 U", "292":"PANTONE 292 U"}
enc = lambda s: s.replace(" ", "%20")

# ---- page / strip geometry (pt, NavTabs / donor spread) --------------------
PAGE_W, PAGE_H = 419.527559055, 595.275590551
M_TOP, M_BOT = 22.170070866, 55.842519685
STRIP_W = 45.4
box_h = PAGE_H - M_TOP - M_BOT
pitch = box_h / N
Y0 = M_TOP - PAGE_H / 2                 # spread-space top of margin box (= -275.468)

# ---- read + tween the stops ------------------------------------------------
csv_path = SRC + ".tabstops.csv"
with open(csv_path) as fh:
    rows = list(csv.reader(fh))
stops = [[float(v) for v in r] for r in rows[1:]]        # list of [K,292,130,WG]
def tween(p):
    S = len(stops) - 1
    seg = min(int(p * S), S - 1)
    p0, p1 = seg / S, (seg + 1) / S
    f = (p - p0) / (p1 - p0) if p1 > p0 else 0
    return {KEYS[k]: round(stops[seg][k] + f * (stops[seg+1][k] - stops[seg][k]))
            for k in range(4)}
tabs = [tween(i / (N - 1)) for i in range(N)]

# ---- build swatches (mixed inks) -------------------------------------------
mixedinks, cgswatches = [], []           # xml fragments
tab_fill = []                            # (fillcolor, is_mixed) per tab
black_tabs = []
for i, mix in enumerate(tabs):
    nz = [(k, mix[k]) for k in TRAP if mix[k] > 0]
    if len(nz) == 1:                     # pure single ink -> plain colour + tint
        tab_fill.append(COLOR_REF[nz[0][0]])
        continue
    name = f"tab_{i:02d}"
    cgs = f"uTABcgs{i}"
    il = " ".join(enc(INK_REF[k]) for k, _ in nz)
    pc = " ".join(str(p) for _, p in nz)
    inm = " ".join(enc(INK_NAME[k]) for k, _ in nz)
    cnm = " ".join(enc(COLOR_NAME[k]) for k, _ in nz)
    cl = " ".join(enc(COLOR_REF[k]) for k, _ in nz)
    mixedinks.append(
        f'\t<MixedInk Self="MixedInk/{name}" Model="Mixedinkmodel" Space="MixedInk" '
        f'InkList="{il}" InkPercentages="{pc}" BaseColor="n" InkNameList="{inm}" '
        f'MixedInkSpotColorNameList="{cnm}" MixedInkSpotColorList="{cl}" Name="{name}" '
        f'ColorEditable="true" ColorRemovable="true" Visible="true" SwatchCreatorID="7937" '
        f'SwatchColorGroupReference="{cgs}" />')
    cgswatches.append(f'\t\t<ColorGroupSwatch Self="{cgs}" SwatchItemRef="MixedInk/{name}" />')
    tab_fill.append(f"MixedInk/{name}")
    if any(k == "Black" for k, _ in nz):
        black_tabs.append(i)

# ---- rectangle builder -----------------------------------------------------
def rect(sid, xl, xr, yt, yb, fill, tint, pos):
    pts = [(xr, yt), (xl, yt), (xl, yb), (xr, yb)]
    pa = "".join(f'<PathPointType Anchor="{x} {y}" LeftDirection="{x} {y}" '
                 f'RightDirection="{x} {y}" />' for x, y in pts)
    return (f'\t\t<Rectangle Self="{sid}" ContentType="Unassigned" StoryTitle="$ID/" '
            f'ParentInterfaceChangeCount="" TargetInterfaceChangeCount="" '
            f'LastUpdatedInterfaceChangeCount="" OverriddenPageItemProps="" '
            f'BeforeGroupingLayerReference="ucb" BeforeGroupingLayerPosition="{pos}" '
            f'FillColor="{fill}" FillTint="{tint}" StrokeColor="Swatch/None" StrokeWeight="0" '
            f'MiterLimit="10" GradientFillStart="0 0" GradientFillLength="0" '
            f'AppliedObjectStyle="ObjectStyle/$ID/[None]" Visible="true" Name="$ID/" '
            f'ItemTransform="1 0 0 1 0 0"><Properties><PathGeometry><GeometryPathType '
            f'PathOpen="false"><PathPointArray>{pa}</PathPointArray></GeometryPathType>'
            f'</PathGeometry></Properties></Rectangle>')

rects = []
# LEFT page (outer=left edge): all tabs FULL — colour reference
xl_L, xr_L = -PAGE_W, -PAGE_W + STRIP_W
# RIGHT page (outer=right edge): in-use look — current full, others 45%
xl_R, xr_R = PAGE_W - STRIP_W, PAGE_W
for i in range(N):
    yt = Y0 + i * pitch; yb = yt + pitch
    rects.append(rect(f"uTABl{i}", xl_L, xr_L, yt, yb, tab_fill[i], 100, i))
    rects.append(rect(f"uTABr{i}", xl_R, xr_R, yt, yb, tab_fill[i],
                      100 if i == CUR else 45, N + i))

# ---- write into a fresh proof build ---------------------------------------
if os.path.exists(OUT): shutil.rmtree(OUT)
shutil.copytree(SRC, OUT)

g = OUT + "/Resources/Graphic.xml"
gx = open(g, encoding="utf-8").read()
gx = gx.replace("</idPkg:Graphic>", "\n".join(mixedinks) + "\n</idPkg:Graphic>")
open(g, "w", encoding="utf-8").write(gx)

dm = OUT + "/designmap.xml"
dx = open(dm, encoding="utf-8").read()
dx = dx.replace("\t</ColorGroup>", "\n".join(cgswatches) + "\n\t</ColorGroup>")
open(dm, "w", encoding="utf-8").write(dx)

sp = OUT + "/Spreads/Spread_u7973e.xml"
sx = open(sp, encoding="utf-8").read()
sx = sx.replace('ShowMasterItems="true"', 'ShowMasterItems="false"')
sx = re.sub(r'AppliedMaster="[^"]*"', 'AppliedMaster="n"', sx)
sx = re.sub(r'[ \t]*</Spread>', "\n" + "\n".join(rects) + "\n\t</Spread>", sx, count=1)
open(sp, "w", encoding="utf-8").write(sx)

# ---- report ----------------------------------------------------------------
print(f"src={SRC}  out={OUT}  N={N}  pitch={pitch:.3f}pt  current-tab={CUR}")
print(f"stops={len(stops)}  mixed-ink swatches={len(mixedinks)}  rectangles={len(rects)}")
print(f"last tab bottom (spread y) = {Y0 + N*pitch:.3f}  (margin-box bottom = {M_BOT and PAGE_H-M_BOT-PAGE_H/2:.3f})")
print("\n # y_top(spread)  Black 292 130 WG   fill")
for i, mix in enumerate(tabs):
    yt = Y0 + i * pitch
    flag = "  <-- black-mixed (schema-unverified)" if i in black_tabs else \
           ("  <-- current" if i == CUR else "")
    print(f"{i:2d} {yt:9.2f}    {mix['Black']:3d} {mix['292']:3d} {mix['130']:3d} "
          f"{mix['Warm Gray 1']:3d}   {tab_fill[i]}{flag}")
