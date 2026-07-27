#!/usr/bin/env python3
"""Recolour each chapter master's active tab from the placed .ai to a native
mixed-ink swatch, IN PLACE — preserving every rectangle's geometry (so the
existing bleed is kept) and the whole BaseTabs->Sx override/filiation structure
(which is an InDesign-bug workaround and must not be touched).

Per chapter master: find its single tab rectangle (the one holding the
tab_gradient PDF/Link), delete the PDF+Link, and fill the rectangle with the
mixed-ink for that chapter's tab index (index derived from the number frame's
vertical position). Colours come from <src>.tabstops.csv, tweened over N=26.

Usage: python3 bake_masters.py [src_dir] [out_dir]
"""
import os, re, sys, csv, glob, shutil

SRC = sys.argv[1] if len(sys.argv) > 1 else "template_build"
OUT = sys.argv[2] if len(sys.argv) > 2 else "template_build_masters"
N = 26
TY0, PITCH = -264.69, 20.7233                 # slot grid from BaseTabs number frames

KEYS = ["Black", "292", "130", "Warm Gray 1"]
TRAP = ["Black", "Warm Gray 1", "130", "292"]
INK_REF  = {"Black":"Ink/$ID/Process Black","Warm Gray 1":"Ink/PANTONE Warm Gray 1 U",
            "130":"Ink/PANTONE 130 U","292":"Ink/PANTONE 292 U"}
INK_NAME = {"Black":"$ID/Process Black","Warm Gray 1":"PANTONE Warm Gray 1 U",
            "130":"PANTONE 130 U","292":"PANTONE 292 U"}
COLOR_REF= {"Black":"Color/Black","Warm Gray 1":"Color/PANTONE Warm Gray 1 U",
            "130":"Color/PANTONE 130 U","292":"Color/PANTONE 292 U"}
COLOR_NAME={"Black":"Black","Warm Gray 1":"PANTONE Warm Gray 1 U",
            "130":"PANTONE 130 U","292":"PANTONE 292 U"}
enc = lambda s: s.replace(" ", "%20")

# ---- tween the stops -------------------------------------------------------
with open(SRC + ".tabstops.csv") as fh:
    stops = [[float(v) for v in r] for r in list(csv.reader(fh))[1:]]
def tween(p):
    S = len(stops) - 1; seg = min(int(p * S), S - 1)
    p0, p1 = seg / S, (seg + 1) / S
    f = (p - p0) / (p1 - p0) if p1 > p0 else 0
    return {KEYS[k]: round(stops[seg][k] + f*(stops[seg+1][k]-stops[seg][k])) for k in range(4)}
tabs = [tween(i/(N-1)) for i in range(N)]

# ---- swatches --------------------------------------------------------------
mixedinks, cgswatches, tab_fill, black_tabs = [], [], [], []
for i, mix in enumerate(tabs):
    nz = [(k, mix[k]) for k in TRAP if mix[k] > 0]
    if len(nz) == 1:
        tab_fill.append(COLOR_REF[nz[0][0]]); continue
    name, cgs = f"tab_{i:02d}", f"uTABcgs{i}"
    il = " ".join(enc(INK_REF[k]) for k,_ in nz); pc = " ".join(str(p) for _,p in nz)
    inm = " ".join(enc(INK_NAME[k]) for k,_ in nz); cnm = " ".join(enc(COLOR_NAME[k]) for k,_ in nz)
    cl = " ".join(enc(COLOR_REF[k]) for k,_ in nz)
    mixedinks.append(f'\t<MixedInk Self="MixedInk/{name}" Model="Mixedinkmodel" Space="MixedInk" '
        f'InkList="{il}" InkPercentages="{pc}" BaseColor="n" InkNameList="{inm}" '
        f'MixedInkSpotColorNameList="{cnm}" MixedInkSpotColorList="{cl}" Name="{name}" '
        f'ColorEditable="true" ColorRemovable="true" Visible="true" SwatchCreatorID="7937" '
        f'SwatchColorGroupReference="{cgs}" />')
    cgswatches.append(f'\t\t<ColorGroupSwatch Self="{cgs}" SwatchItemRef="MixedInk/{name}" />')
    tab_fill.append(f"MixedInk/{name}")
    if any(k == "Black" for k,_ in nz): black_tabs.append(i)

# ---- open the proof build --------------------------------------------------
if os.path.exists(OUT): shutil.rmtree(OUT)
shutil.copytree(SRC, OUT)

def set_attr(tag, name, val):
    if re.search(rf'\b{name}="[^"]*"', tag):
        return re.sub(rf'\b{name}="[^"]*"', f'{name}="{val}"', tag)
    return tag[:-1] + f' {name}="{val}"' + tag[-1]      # insert before '>'

# ---- recolour EVERY tab rectangle in EVERY tab master (incl. BaseTabs) ------
def frame_index(block):
    """tab index from the rectangle's own window centre in spread space."""
    a,b,c,d,tx,ty = map(float, re.search(r'ItemTransform="([^"]+)"', block).group(1).split())
    frame = block.split('<PDF', 1)[0]                    # rect's own geometry, before the art
    ys = [b*float(p.split()[0]) + d*float(p.split()[1]) + ty
          for p in re.findall(r'Anchor="([^"]+)"', frame)]
    return max(0, min(N-1, round((sum(ys)/len(ys) - TY0) / PITCH)))

report = []
for f in glob.glob(OUT + "/MasterSpreads/*.xml"):
    t = open(f, encoding="utf-8").read()
    if "tab_gradient" not in t: continue
    self = re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"', t).group(1)
    name = re.search(r'<MasterSpread\b[^>]*Name="([^"]+)"', t).group(1)
    hits = []
    def repl(m):
        blk = m.group(0)
        if "tab_gradient" not in blk: return blk
        idx = frame_index(blk); hits.append(idx)
        blk = re.sub(r'<PDF\b.*?</PDF>', '', blk, flags=re.S)     # drop placed art
        blk = re.sub(r'<Link\b[^>]*/>', '', blk)                  # drop link
        open_tag = re.match(r'<Rectangle\b[^>]*>', blk).group(0)
        nt = set_attr(open_tag, "ContentType", "Unassigned")
        nt = set_attr(nt, "FillColor", tab_fill[idx])
        nt = set_attr(nt, "FillTint", "100")
        return nt + blk[len(open_tag):]
    t2 = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>', repl, t, flags=re.S)
    open(f, "w", encoding="utf-8").write(t2)
    report.append((name, self, sorted(set(hits)), len(hits)))

# ---- inject swatches -------------------------------------------------------
g = OUT + "/Resources/Graphic.xml"; gx = open(g, encoding="utf-8").read()
open(g, "w", encoding="utf-8").write(gx.replace("</idPkg:Graphic>", "\n".join(mixedinks) + "\n</idPkg:Graphic>"))
dm = OUT + "/designmap.xml"; dx = open(dm, encoding="utf-8").read()
open(dm, "w", encoding="utf-8").write(dx.replace("\t</ColorGroup>", "\n".join(cgswatches) + "\n\t</ColorGroup>"))

# ---- demo: show two chapters on the donor spread pages ---------------------
sp = OUT + "/Spreads/Spread_u7973e.xml"; sx = open(sp, encoding="utf-8").read()
demo = {"u79767": "u1e21d", "u79768": "u26448"}          # left=idx0, right=idx25
for page, master in demo.items():
    sx = re.sub(rf'(<Page\b[^>]*Self="{page}"[^>]*AppliedMaster=")[^"]*(")',
                rf'\g<1>{master}\g<2>', sx)
open(sp, "w", encoding="utf-8").write(sx)

# ---- report ----------------------------------------------------------------
total_rects = sum(c for _, _, _, c in report)
report.sort(key=lambda r: (r[3] != 52, min(r[2]) if r[2] else 99))   # BaseTabs first
print(f"src={SRC} out={OUT}  N={N}")
print(f"masters touched={len(report)}  tab rectangles recoloured={total_rects}  mixed-ink swatches={len(mixedinks)}")
print(f"pure endpoints via Color: tab0={tab_fill[0]}, tab{N-1}={tab_fill[N-1]}")
print("\nmaster                                   self       #tabs indices")
for name, self, idxs, cnt in report:
    ix = f"{min(idxs)}..{max(idxs)} ({len(idxs)} distinct)" if cnt > 2 else str(idxs)
    print(f"  {name:38s} {self:9s} {cnt:3d}   {ix}")
