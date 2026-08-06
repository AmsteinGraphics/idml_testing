#!/usr/bin/env python3
"""Rebuild BT-BaseTabs' thumb-tab strip for N chapters — any N.

The chapter count is a property of the manual being made, not of the toolchain.
26 (v1.76) and 18 (make_18ch.py) were both instances; this generalises them. N
defaults to the number of chapters actually detected in the document, so the
strip follows the content.

The strip is GENERATED from templates rather than pruned from a fixed grid --
make_18ch.py could only ever shrink 26 down, never grow past it. One existing tab
rectangle and one number frame per page are taken as templates; N of each are
emitted at pitch = margin_box_height / N, and the ink ramp from
<build>.tabstops.csv is re-tweened across the new N.

Rebuilt per run: N tab rectangles x 2 pages, N number frames x 2 pages (each with
its own story, digit 1..N), and N tab swatches (mixed inks, plus pure Color/ for
single-ink stops) registered in Graphic.xml and designmap.

    configure_chapters.py <build_dir> [--n N] [--tabstops FILE] [--dry-run]

Run AFTER sectionize.py (which is what detects the chapters) and BEFORE
apply_tabs.py (which clones one slot per chapter off this strip). It supersedes
fix_tab_strip.py on this path: the strip is rebuilt wholesale, so an inherited
off-strip frame is simply gone.

Physical limits, not enforced: ~26 tabs fit comfortably, ~40 forces tabs under
14pt, and beyond that you want grouped or two-level tabs -- a design decision.
"""
import argparse
import csv
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sectionize as S

PAGE_H, M_TOP, M_BOT = 595.275590551, 22.170070866, 55.842519685
Y0 = M_TOP - PAGE_H / 2                  # margin-box top, spread space (-275.468)
BOX_H = PAGE_H - M_TOP - M_BOT           # 517.263
PITCH26 = 20.7233                        # the kit's grid, used only as the
TY0_NUM26 = -264.692                     # reference the templates come from
TABFILL = r'FillColor="(?:MixedInk/tab_\d+|Color/PANTONE [^"]+|Color/Black)"'

KEYS = ["Black", "292", "130", "Warm Gray 1"]
TRAP = ["Black", "Warm Gray 1", "130", "292"]
INK_REF = {"Black": "Ink/$ID/Process Black", "Warm Gray 1": "Ink/PANTONE Warm Gray 1 U",
           "130": "Ink/PANTONE 130 U", "292": "Ink/PANTONE 292 U"}
INK_NAME = {"Black": "$ID/Process Black", "Warm Gray 1": "PANTONE Warm Gray 1 U",
            "130": "PANTONE 130 U", "292": "PANTONE 292 U"}
COLOR_REF = {"Black": "Color/Black", "Warm Gray 1": "Color/PANTONE Warm Gray 1 U",
             "130": "Color/PANTONE 130 U", "292": "Color/PANTONE 292 U"}
COLOR_NAME = {"Black": "Black", "Warm Gray 1": "PANTONE Warm Gray 1 U",
              "130": "PANTONE 130 U", "292": "PANTONE 292 U"}
enc = lambda s: s.replace(" ", "%20")


def set_attr(tag, n, v):
    if re.search(rf'\b{n}="', tag):
        return re.sub(rf'\b{n}="[^"]*"', f'{n}="{v}"', tag)
    return tag[:-1] + f' {n}="{v}"' + tag[-1]


def load_stops(build, explicit):
    for p in (explicit, build.rstrip("/") + ".tabstops.csv", "template_build.tabstops.csv"):
        if p and os.path.exists(p):
            rows = list(csv.reader(open(p)))
            return [[float(v) for v in r] for r in rows[1:]], p
    raise SystemExit("no tabstops CSV found (looked for <build>.tabstops.csv, "
                     "template_build.tabstops.csv); pass --tabstops FILE")


def tween(stops, p):
    n = len(stops) - 1
    seg = min(int(p * n), n - 1)
    p0, p1 = seg / n, (seg + 1) / n
    f = (p - p0) / (p1 - p0) if p1 > p0 else 0
    return {KEYS[k]: round(stops[seg][k] + f * (stops[seg + 1][k] - stops[seg][k]))
            for k in range(4)}


def build_swatches(stops, n):
    """Return (tab_fill[], mixedink_xml[], colorgroupswatch_xml[]).

    A stop that lands on a single ink is emitted as a plain Color/ + FillTint, not
    a one-ink MixedInk -- that is what makes an unmixed spot actually print solid.
    """
    mixes = [tween(stops, i / (n - 1) if n > 1 else 0.0) for i in range(n)]
    fills, inks, cgs = [], [], []
    for i, mix in enumerate(mixes):
        nz = [(k, mix[k]) for k in TRAP if mix[k] > 0]
        if len(nz) == 1:
            fills.append(COLOR_REF[nz[0][0]])
            continue
        name, ref = f"tab_{i:02d}", f"uTABcgs{i}"
        inks.append(
            f'\t<MixedInk Self="MixedInk/{name}" Model="Mixedinkmodel" Space="MixedInk" '
            f'InkList="{" ".join(enc(INK_REF[k]) for k, _ in nz)}" '
            f'InkPercentages="{" ".join(str(p) for _, p in nz)}" BaseColor="n" '
            f'InkNameList="{" ".join(enc(INK_NAME[k]) for k, _ in nz)}" '
            f'MixedInkSpotColorNameList="{" ".join(enc(COLOR_NAME[k]) for k, _ in nz)}" '
            f'MixedInkSpotColorList="{" ".join(enc(COLOR_REF[k]) for k, _ in nz)}" '
            f'Name="{name}" ColorEditable="true" ColorRemovable="true" Visible="true" '
            f'SwatchCreatorID="7937" SwatchColorGroupReference="{ref}" />')
        cgs.append(f'\t\t<ColorGroupSwatch Self="{ref}" SwatchItemRef="MixedInk/{name}" />')
        fills.append(f"MixedInk/{name}")
    return fills, inks, cgs


def rect_xml(open_tag, x0, x1, ytop, ybot, fill):
    """A tab rectangle as absolute anchors under an identity transform."""
    quad = [(x1, ytop), (x0, ytop), (x0, ybot), (x1, ybot)]
    pts = "".join(f'<PathPointType Anchor="{x} {y}" LeftDirection="{x} {y}" '
                  f'RightDirection="{x} {y}" />' for x, y in quad)
    t = set_attr(open_tag, "ItemTransform", "1 0 0 1 0 0")
    t = set_attr(t, "FillColor", fill)
    t = set_attr(t, "FillTint", "100")
    return (t + '<Properties><PathGeometry><GeometryPathType PathOpen="false">'
            '<PathPointArray>' + pts + '</PathPointArray></GeometryPathType>'
            '</PathGeometry></Properties></Rectangle>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--n", type=int, help="chapter count (default: detected)")
    ap.add_argument("--tabstops")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build

    n = args.n
    if n is None:
        chapters, _ = S.detect_chapters(build, "titles:lvl2")
        n = len(chapters)
        if not n:
            raise SystemExit("no chapters detected; pass --n N explicitly")
    if n < 1:
        raise SystemExit("N must be >= 1")

    stops, stops_path = load_stops(build, args.tabstops)
    fills, inks, cgs = build_swatches(stops, n)
    pitch = BOX_H / n
    scale = pitch / PITCH26
    ty0 = Y0 + (TY0_NUM26 - Y0) * scale     # number origin, scaled about the box top

    # --- locate BaseTabs -----------------------------------------------------
    bt_path = None
    for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
        t = open(f, encoding="utf-8").read()
        m = re.search(r'<MasterSpread\b[^>]*\bName="([^"]*)"', t)
        if m and "BaseTabs" in m.group(1):
            bt_path, bt = f, t
            break
    if not bt_path:
        raise SystemExit("BT-BaseTabs master not found")

    # A chapter master built off the OLD grid would keep stale swatches and slots.
    # Key on the generated naming (apply_tabs.py mints NamePrefix S1..SN), not on
    # fill colour -- the kit's own Sx-Section master carries a PANTONE fill too.
    stale = []
    for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
        if f == bt_path:
            continue
        m = re.search(r'<MasterSpread\b[^>]*\bNamePrefix="(S\d+)"', open(f, encoding="utf-8").read())
        if m:
            stale.append((f, m.group(1)))
    if stale:
        raise SystemExit(f"{len(stale)} chapter master(s) already built off the old grid "
                         f"({', '.join(sorted(p for _, p in stale)[:4])}...).\nRun "
                         f"configure_chapters.py BEFORE apply_tabs.py, on a tree that has none.")

    # --- templates: one tab rect and one number frame per page ---------------
    rects = [m.group(0) for m in re.finditer(r'<Rectangle\b[^>]*>.*?</Rectangle>', bt, re.S)
             if re.search(TABFILL, m.group(0))]
    frames = [m.group(0) for m in re.finditer(r'<TextFrame\b[^>]*>.*?</TextFrame>', bt, re.S)]

    def tx_of(block):
        it = re.search(r'ItemTransform="([^"]+)"', block)
        return float(it.group(1).split()[4]) if it else 0.0

    def xspan(block):
        it = list(map(float, re.search(r'ItemTransform="([^"]+)"', block).group(1).split()))
        xs = [float(p.split()[0]) * it[0] + it[4]
              for p in re.findall(r'Anchor="([^"]+)"', block)]
        return min(xs), max(xs)

    numframes = [f for f in frames if 'ParentStory="' in f and abs(tx_of(f)) >= 300]
    if not rects or not numframes:
        raise SystemExit("BT-BaseTabs has no recognisable tab rectangles / number frames")

    tpl = {}
    for side, pick in (("L", lambda v: v < 0), ("R", lambda v: v > 0)):
        r = next((x for x in rects if pick(sum(xspan(x)) / 2)), None)
        f = next((x for x in numframes if pick(tx_of(x))), None)
        if not r or not f:
            raise SystemExit(f"no {side}-page tab template in BT-BaseTabs")
        tpl[side] = dict(rect_open=re.match(r'<Rectangle\b[^>]*>', r).group(0),
                         xspan=xspan(r), frame=f)

    # --- mint ids ------------------------------------------------------------
    existing = set()
    for f in glob.glob(os.path.join(build, "**", "*.xml"), recursive=True):
        existing |= set(re.findall(r'"(u[0-9a-fA-F]+)"', open(f, encoding="utf-8").read()))
    counter = [0x900000]

    def mint():
        while True:
            i = f"u{counter[0]:x}"
            counter[0] += 1
            if i not in existing:
                existing.add(i)
                return i

    # --- old stories to retire ----------------------------------------------
    old_story_ids = {re.search(r'ParentStory="([^"]+)"', f).group(1) for f in numframes}
    story_tpl = None
    for sid in old_story_ids:
        p = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(p):
            story_tpl = open(p, encoding="utf-8").read()
            break
    if story_tpl is None:
        raise SystemExit("no number-frame story to use as a template")

    # --- generate ------------------------------------------------------------
    new_rects, new_frames, new_stories = [], [], []
    for side in ("L", "R"):
        x0, x1 = tpl[side]["xspan"]
        for i in range(n):
            new_rects.append(rect_xml(tpl[side]["rect_open"], x0, x1,
                                      Y0 + i * pitch, Y0 + (i + 1) * pitch, fills[i]))
            sid = mint()
            blk = re.sub(r'(\bSelf=")[^"]*(")', rf'\g<1>{mint()}\g<2>', tpl[side]["frame"], count=1)
            blk = re.sub(r'(\bParentStory=")[^"]*(")', rf'\g<1>{sid}\g<2>', blk, count=1)
            it = list(map(float, re.search(r'ItemTransform="([^"]+)"', blk).group(1).split()))
            it[5] = round(ty0 + i * pitch, 6)
            blk = re.sub(r'ItemTransform="[^"]*"',
                         'ItemTransform="%s"' % " ".join(str(v) for v in it), blk, count=1)
            new_frames.append(blk)
            sx = re.sub(r'(<XmlStory|<Story)\b([^>]*?)\bSelf="[^"]*"',
                        rf'\g<1>\g<2>Self="{sid}"', story_tpl, count=1)
            sx = re.sub(r'"' + re.escape(re.search(r'<Story\b[^>]*Self="([^"]+)"',
                        story_tpl).group(1)) + r'"', f'"{sid}"', sx)
            sx = set_digit(sx, str(i + 1))
            new_stories.append((sid, sx))

    if args.dry_run:
        print(f"N={n} pitch={pitch:.4f} scale={scale:.4f} stops={os.path.basename(stops_path)}")
        print(f"would write {len(new_rects)} tab rects, {len(new_frames)} number frames, "
              f"{len(new_stories)} stories, {len(inks)} mixed inks "
              f"({n - len(inks)} pure)")
        print(f"retiring {len(rects)} rects, {len(numframes)} frames, "
              f"{len(old_story_ids)} stories")
        return 0

    # --- splice BaseTabs -----------------------------------------------------
    bt = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>',
                lambda m: "" if re.search(TABFILL, m.group(0)) else m.group(0), bt, flags=re.S)
    bt = re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>',
                lambda m: "" if m.group(0) in numframes else m.group(0), bt, flags=re.S)
    body = "\n\t\t" + "\n\t\t".join(new_rects + new_frames) + "\n\t"
    bt = bt.replace("</MasterSpread>", body + "</MasterSpread>", 1)
    open(bt_path, "w", encoding="utf-8").write(bt)

    for sid in old_story_ids:
        p = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(p):
            os.remove(p)
    for sid, sx in new_stories:
        open(os.path.join(build, "Stories", f"Story_{sid}.xml"), "w",
             encoding="utf-8").write(sx)

    # --- Graphic.xml: swap the tab swatches ---------------------------------
    gp = os.path.join(build, "Resources", "Graphic.xml")
    g = open(gp, encoding="utf-8").read()
    g = re.sub(r'[ \t]*<MixedInk\b[^>]*Self="MixedInk/tab_\d+"[^>]*/>\s*\n?', "", g)
    if inks:
        g = g.replace("</idPkg:Graphic>", "\n".join(inks) + "\n</idPkg:Graphic>")
    open(gp, "w", encoding="utf-8").write(g)

    # --- designmap: swatch refs + story registration -------------------------
    dp = os.path.join(build, "designmap.xml")
    d = open(dp, encoding="utf-8").read()
    d = re.sub(r'[ \t]*<ColorGroupSwatch\b[^>]*SwatchItemRef="MixedInk/tab_\d+"[^>]*/>\s*\n?', "", d)
    if cgs:
        d = re.sub(r'(</ColorGroup>)', "\n".join(cgs) + r'\n\t\1', d, count=1)
    for sid in old_story_ids:
        d = re.sub(r'[ \t]*<idPkg:Story\b[^>]*src="Stories/Story_%s\.xml"[^>]*/>\s*\n?'
                   % re.escape(sid), "", d)
    refs = "".join(f'\t<idPkg:Story src="Stories/Story_{sid}.xml" />\n'
                   for sid, _ in new_stories)
    d = re.sub(r'(\t<idPkg:Story\b)', refs + r'\1', d, count=1) if "<idPkg:Story" in d \
        else d.replace("</Document>", refs + "</Document>")
    keep = [s for s in re.search(r'StoryList="([^"]*)"', d).group(1).split()
            if s not in old_story_ids]
    d = re.sub(r'StoryList="[^"]*"',
               'StoryList="' + " ".join(keep + [sid for sid, _ in new_stories]) + '"',
               d, count=1)
    open(dp, "w", encoding="utf-8").write(d)

    print(f"N={n} pitch={pitch:.4f} (was {PITCH26}) | {len(new_rects)} tab rects, "
          f"{len(new_frames)} numbered frames, {len(inks)} mixed inks + "
          f"{n - len(inks)} pure | stops: {os.path.basename(stops_path)}")
    return 0


def set_digit(story_xml, digit):
    if re.search(r'<CharacterStyleRange[^>]*>\s*<Content>', story_xml):
        return re.sub(r'(<CharacterStyleRange[^>]*>\s*<Content>)[^<]*(</Content>)',
                      rf'\g<1>{digit}\g<2>', story_xml, count=1)
    return re.sub(r'<CharacterStyleRange([^>]*?)\s*/>',
                  rf'<CharacterStyleRange\1><Content>{digit}</Content></CharacterStyleRange>',
                  story_xml, count=1)


if __name__ == "__main__":
    sys.exit(main())
