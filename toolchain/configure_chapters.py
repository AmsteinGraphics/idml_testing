#!/usr/bin/env python3
"""Rebuild BT-BaseTabs' thumb-tab strip for N chapters — any N.

The chapter count is a property of the manual being made, not of the toolchain.
26 (v1.76) and 18 (make_18ch.py) were both instances; this generalises them. N
defaults to the number of chapters actually detected in the document, so the
strip follows the content.

The strip is GENERATED from templates rather than pruned from a fixed grid --
make_18ch.py could only ever shrink 26 down, never grow past it. One existing tab
rectangle and one number frame per page are taken as templates; N of each are
emitted at pitch = margin_box_height / N, and the ink ramp from the
manual's .manual config is re-tweened across the new N.

Rebuilt per run: N tab rectangles x 2 pages, N number frames x 2 pages (each with
its own story, digit 1..N), and N tab swatches (mixed inks, plus pure Color/ for
single-ink stops) registered in Graphic.xml and designmap.

    configure_chapters.py <build_dir> [--n N] [--config FILE] [--dry-run]

Run AFTER sectionize.py (which is what detects the chapters) and BEFORE
apply_tabs.py (which clones one slot per chapter off this strip). It supersedes
fix_tab_strip.py on this path: the strip is rebuilt wholesale, so an inherited
off-strip frame is simply gone.

Physical limits, not enforced: ~26 tabs fit comfortably, ~40 forces tabs under
14pt, and beyond that you want grouped or two-level tabs -- a design decision.
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manualconf
import sectionize as S

PAGE_H, M_TOP, M_BOT = 595.275590551, 22.170070866, 55.842519685
Y0 = M_TOP - PAGE_H / 2                  # margin-box top, spread space (-275.468)
BOX_H = PAGE_H - M_TOP - M_BOT           # 517.263
PITCH26 = 20.7233                        # the kit's grid, used only as the
TY0_NUM26 = -264.692                     # reference the templates come from
TABFILL = r'FillColor="(?:MixedInk/tab_\d+|Color/PANTONE [^"]+|Color/Black)"'

enc = lambda s: s.replace(" ", "%20")


def resolve_palette(build, keys):
    """Bind the configured stop ink names to THIS document's inks and colours.

    The ink identities used to be hardcoded to the DM32 palette. They are now
    resolved against Resources/Graphic.xml and ordered by the document's own
    TrapOrder -- which is what InDesign lists a mixed ink's components by. A stop
    may name an ink in full ("PANTONE 292 U") or short ("292", "Black").

    Returns (trap_ordered_keys, {key: {ink_ref, ink_name, color_ref, color_name}}).
    """
    g = open(os.path.join(build, "Resources", "Graphic.xml"), encoding="utf-8").read()
    inks = {}
    for m in re.finditer(r'<Ink\b([^>]*?)/?>', g):
        nm = re.search(r'\bName="([^"]*)"', m.group(1))
        to = re.search(r'\bTrapOrder="(\d+)"', m.group(1))
        if nm:
            inks[nm.group(1)] = int(to.group(1)) if to else 9999
    colors = set(re.findall(r'<Color\b[^>]*\bName="([^"]*)"', g))

    ref = {}
    for k in keys:
        ink = next((c for c in (k, f"PANTONE {k} U", f"$ID/Process {k}") if c in inks), None)
        if ink is None:
            raise SystemExit(f"tab_stop ink {k!r} is not an ink in this document.\n"
                             f"inks present: {sorted(inks)}")
        color = "Black" if ink == "$ID/Process Black" else ink
        if color not in colors:
            raise SystemExit(f"ink {ink!r} has no matching Color swatch "
                             f"(looked for Name={color!r})")
        ref[k] = dict(ink_ref=f"Ink/{ink}", ink_name=ink,
                      color_ref=f"Color/{color}", color_name=color, trap=inks[ink])
    return sorted(keys, key=lambda k: ref[k]["trap"]), ref


def set_attr(tag, n, v):
    if re.search(rf'\b{n}="', tag):
        return re.sub(rf'\b{n}="[^"]*"', f'{n}="{v}"', tag)
    return tag[:-1] + f' {n}="{v}"' + tag[-1]


# Below this the tab is too shallow to hold its number comfortably; the fix is a
# design decision (grouped or two-level tabs), so this advises rather than fails.
MIN_PITCH = 14.0


def load_stops(build, explicit=None):
    """(stops as numeric rows, ink names, config path).

    Stops come from the manual's .manual config as `tab_stop` lines naming their
    inks inline, replacing the old positional tabstops.csv.
    """
    conf = manualconf.load(build, explicit)
    if not conf["tab_stops"]:
        raise SystemExit(
            f"no tab_stop lines in {conf['path'] or 'any .manual config'} — the tab "
            f"strip needs at least one.\n"
            f"e.g.  tab_stop = PANTONE 292 U\n"
            f"      tab_stop = Black")
    keys = []
    for mix in conf["tab_stops"]:
        for k in mix:
            if k not in keys:
                keys.append(k)
    rows = [[mix.get(k, 0.0) for k in keys] for mix in conf["tab_stops"]]
    return rows, keys, conf["path"]


def tween(stops, keys, p):
    n = len(stops) - 1
    seg = min(int(p * n), n - 1)
    p0, p1 = seg / n, (seg + 1) / n
    f = (p - p0) / (p1 - p0) if p1 > p0 else 0
    return {keys[k]: round(stops[seg][k] + f * (stops[seg + 1][k] - stops[seg][k]))
            for k in range(len(keys))}


def build_swatches(stops, keys, trap, ref, n):
    """Return (tab_fill[], mixedink_xml[], colorgroupswatch_xml[]).

    A stop that lands on a single ink is emitted as a plain Color/ + FillTint, not
    a one-ink MixedInk -- that is what makes an unmixed spot actually print solid.
    """
    mixes = [tween(stops, keys, i / (n - 1) if n > 1 else 0.0) for i in range(n)]
    fills, inks, cgs = [], [], []
    for i, mix in enumerate(mixes):
        nz = [(k, mix[k]) for k in trap if mix[k] > 0]
        if len(nz) == 1:
            fills.append(ref[nz[0][0]]["color_ref"])
            continue
        name, cgsid = f"tab_{i:02d}", f"uTABcgs{i}"
        inks.append(
            f'\t<MixedInk Self="MixedInk/{name}" Model="Mixedinkmodel" Space="MixedInk" '
            f'InkList="{" ".join(enc(ref[k]["ink_ref"]) for k, _ in nz)}" '
            f'InkPercentages="{" ".join(str(p) for _, p in nz)}" BaseColor="n" '
            f'InkNameList="{" ".join(enc(ref[k]["ink_name"]) for k, _ in nz)}" '
            f'MixedInkSpotColorNameList="{" ".join(enc(ref[k]["color_name"]) for k, _ in nz)}" '
            f'MixedInkSpotColorList="{" ".join(enc(ref[k]["color_ref"]) for k, _ in nz)}" '
            f'Name="{name}" ColorEditable="true" ColorRemovable="true" Visible="true" '
            f'SwatchCreatorID="7937" SwatchColorGroupReference="{cgsid}" />')
        cgs.append(f'\t\t<ColorGroupSwatch Self="{cgsid}" SwatchItemRef="MixedInk/{name}" />')
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
    ap.add_argument("--config", help="explicit <product>.manual path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build

    n = args.n
    if n is None:
        chapters, _ = S.detect_chapters(build)   # topmost level present
        n = len(chapters)
        if not n:
            raise SystemExit("no chapters detected; pass --n N explicitly")
    if n < 1:
        raise SystemExit("N must be >= 1")

    stops, keys, stops_path = load_stops(build, args.config)
    trap, palette = resolve_palette(build, keys)
    fills, inks, cgs = build_swatches(stops, keys, trap, palette, n)
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

    # Chapter masters, if this tree has any. Keyed on the naming convention
    # (NamePrefix S1..SN, as both v1.76 and apply_tabs.py use), NOT on fill colour
    # -- the kit's own Sx-Section master carries a PANTONE fill too. A tree with
    # none is the forward-pipeline case: apply_tabs.py mints them afterwards.
    chapter_masters = {}
    for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
        if f == bt_path:
            continue
        t = open(f, encoding="utf-8").read()
        m = re.search(r'<MasterSpread\b[^>]*\bNamePrefix="S(\d+)"', t)
        if m:
            chapter_masters[int(m.group(1))] = (f, t)

    base_self = None
    for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
        t = open(f, encoding="utf-8").read()
        m = re.search(r'<MasterSpread\b[^>]*\bName="B-Base"[^>]*>', t)
        if m or re.search(r'<MasterSpread\b[^>]*\bNamePrefix="B"\s', t):
            base_self = re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"', t).group(1)
            break

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
    tpl_story_self = re.search(r'<Story\b[^>]*Self="([^"]+)"', story_tpl).group(1)

    def emit_slot(i):
        """Slot i's tab + number on both pages: (rects, frames, [(sid, story_xml)]).

        One code path for the strip and for a chapter master, so a chapter's tab is
        by construction identical to the strip slot it corresponds to.
        """
        rects, frames, stories = [], [], []
        for side in ("L", "R"):
            x0, x1 = tpl[side]["xspan"]
            rects.append(rect_xml(tpl[side]["rect_open"], x0, x1,
                                  Y0 + i * pitch, Y0 + (i + 1) * pitch, fills[i]))
            sid = mint()
            blk = re.sub(r'(\bSelf=")[^"]*(")', rf'\g<1>{mint()}\g<2>', tpl[side]["frame"], count=1)
            blk = re.sub(r'(\bParentStory=")[^"]*(")', rf'\g<1>{sid}\g<2>', blk, count=1)
            it = list(map(float, re.search(r'ItemTransform="([^"]+)"', blk).group(1).split()))
            it[5] = round(ty0 + i * pitch, 6)
            blk = re.sub(r'ItemTransform="[^"]*"',
                         'ItemTransform="%s"' % " ".join(str(v) for v in it), blk, count=1)
            frames.append(blk)
            sx = re.sub(r'"' + re.escape(tpl_story_self) + r'"', f'"{sid}"', story_tpl)
            stories.append((sid, set_digit(sx, str(i + 1))))
        return rects, frames, stories

    new_rects, new_frames, new_stories = [], [], []
    for i in range(n):
        r, f, s = emit_slot(i)
        new_rects += r
        new_frames += f
        new_stories += s

    if args.dry_run:
        cm = sorted(chapter_masters)
        print(f"N={n} pitch={pitch:.4f} scale={scale:.4f} "
              f"stops={os.path.basename(stops_path)}")
        print(f"strip: would write {len(new_rects)} tab rects, {len(new_frames)} number "
              f"frames, {len(new_stories)} stories, {len(inks)} mixed inks "
              f"({n - len(inks)} pure); retiring {len(rects)} rects, "
              f"{len(numframes)} frames, {len(old_story_ids)} stories")
        if cm:
            print(f"chapter masters: {len([k for k in cm if k <= n])} would be kept and "
                  f"regenerated, {len([k for k in cm if k > n])} dropped "
                  f"(S1..S{max(cm)} present)")
        return 0

    # --- splice BaseTabs -----------------------------------------------------
    bt = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>',
                lambda m: "" if re.search(TABFILL, m.group(0)) else m.group(0), bt, flags=re.S)
    bt = re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>',
                lambda m: "" if m.group(0) in numframes else m.group(0), bt, flags=re.S)
    body = "\n\t\t" + "\n\t\t".join(new_rects + new_frames) + "\n\t"
    bt = bt.replace("</MasterSpread>", body + "</MasterSpread>", 1)
    open(bt_path, "w", encoding="utf-8").write(bt)

    # --- reconcile existing chapter masters to N (was make_18ch.py) ----------
    # Chapters past N go; those that remain get slot k-1's tab and number
    # regenerated on both pages from the same emit_slot() the strip uses, are
    # re-based off the full-strip BaseTabs onto tab-less Base so only their own
    # tab shows, and have the now-moot override list cleared.
    dropped_masters, kept_masters = [], 0
    for k in sorted(chapter_masters):
        path, t = chapter_masters[k]
        self_id = re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"', t).group(1)
        # retire this master's stories either way -- a dropped master orphans them,
        # a kept one has its tab and number regenerated
        old_story_ids |= set(re.findall(r'ParentStory="([^"]+)"', t))
        if k > n:
            os.remove(path)
            dropped_masters.append(self_id)
            continue
        t = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>',
                   lambda m: "" if re.search(TABFILL, m.group(0)) else m.group(0), t, flags=re.S)
        t = re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>', "", t, flags=re.S)
        if base_self:
            t = re.sub(r'AppliedMaster="[^"]*"', f'AppliedMaster="{base_self}"', t)
        t = re.sub(r'OverrideList="[^"]*"', 'OverrideList=""', t)
        rects, frames, stories = emit_slot(k - 1)
        t = t.replace("</MasterSpread>",
                      "\n\t\t" + "\n\t\t".join(rects + frames) + "\n\t</MasterSpread>", 1)
        open(path, "w", encoding="utf-8").write(t)
        new_stories += stories
        kept_masters += 1

    # Retire and write only now that BOTH passes have declared what they retire --
    # doing it before the chapter-master pass left its old stories on disk but
    # unregistered in designmap.
    for sid in old_story_ids:
        p = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(p):
            os.remove(p)
    for sid, sx in new_stories:
        open(os.path.join(build, "Stories", f"Story_{sid}.xml"), "w",
             encoding="utf-8").write(sx)

    # a page pointing at a master we just deleted would dangle
    repointed = 0
    if dropped_masters and base_self:
        for sp in glob.glob(os.path.join(build, "Spreads", "*.xml")):
            sx = open(sp, encoding="utf-8").read()
            new = sx
            for dead in dropped_masters:
                new = new.replace(f'AppliedMaster="{dead}"', f'AppliedMaster="{base_self}"')
            if new != sx:
                repointed += new.count(f'AppliedMaster="{base_self}"') - \
                             sx.count(f'AppliedMaster="{base_self}"')
                open(sp, "w", encoding="utf-8").write(new)

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
    for dead in dropped_masters:
        d = re.sub(r'[ \t]*<idPkg:MasterSpread\b[^>]*src="MasterSpreads/MasterSpread_%s\.xml"'
                   r'[^>]*/>\s*\n?' % re.escape(dead), "", d)
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

    if pitch < MIN_PITCH:
        print(f"NOTE: {n} tabs gives a {pitch:.2f}pt pitch, below the ~{MIN_PITCH:.0f}pt "
              f"a tab needs to hold its number comfortably. Consider grouped or "
              f"two-level tabs — a design decision this tool won't make.")
    print(f"N={n} pitch={pitch:.4f} | strip: {len(new_rects)} tab rects, "
          f"{len(new_frames)} numbered frames, {len(inks)} mixed inks + "
          f"{n - len(inks)} pure | stops: {os.path.basename(stops_path)}")
    if chapter_masters:
        print(f"chapter masters: {kept_masters} kept and regenerated, "
              f"{len(dropped_masters)} dropped"
              + (f", {repointed} page(s) repointed to Base" if repointed else ""))
        # keep/drop is all we can do here -- minting a new chapter master needs a
        # chapter title, which only the content has (that is apply_tabs.py's job)
        if kept_masters < n:
            print(f"NOTE: the strip has {n} slots but only {kept_masters} chapter "
                  f"master(s) exist, so slots {kept_masters + 1}..{n} have no master. "
                  f"Run apply_tabs.py on a document with {n} chapters to mint them.")
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
