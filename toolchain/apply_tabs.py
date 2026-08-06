#!/usr/bin/env python3
"""Phase 2 — create one per-chapter tab master (S<k>-<Title>) and apply it.

Runs on a build tree that already has per-chapter Sections (see sectionize.py).
For the Kth chapter in reading order it builds a master owning exactly one tab
(+ number) at slot K-1, cloned from BT-BaseTabs' pre-baked native strip, based on
B-Base so no inherited strip shows, mirrored on both pages, digit = K
(sequential). The master is then applied to every page of that chapter.

    apply_tabs.py <build_dir> [--dry-run]

Geometry & swatch conventions come from the kit's BaseTabs, and the tab grid is
READ from that strip rather than assumed — N, pitch and the number origin all come
from the kit, so this works at any chapter count. Nothing is re-tweened here;
configure_chapters.py is what rebuilds the strip for a given N, and this refuses a
kit whose strip doesn't match the chapters detected. Chapter detection is shared
with sectionize.
"""
import argparse
import glob
import os
import re
import sys

import sectionize as S

PAGE_H, M_TOP, M_BOT = 595.275590551, 22.170070866, 55.842519685
Y0 = M_TOP - PAGE_H / 2          # margin-box top (rect grid origin)
BOX_H = PAGE_H - M_TOP - M_BOT

# The grid is READ FROM THE KIT, never assumed. The chapter count belongs to the
# manual being made -- 26 (v1.76) and 18 (make_18ch.py) were just instances --
# and configure_chapters.py rebuilds the strip for whatever N the content has.
# These are defaults only, replaced by set_grid() before anything uses them.
NSLOTS, PITCH, TY0_NUM = 26, BOX_H / 26, -264.692
RSLOT = lambda ytop: round((ytop - Y0) / PITCH)
NSLOT = lambda ty: round((ty - TY0_NUM) / PITCH)
TABFILL = r'FillColor="(?:MixedInk/tab_\d+|Color/PANTONE [^"]+|Color/Black)"'


def read_grid(basetabs_xml):
    """(N, pitch, number-origin) inferred from BT-BaseTabs' own strip."""
    per_side = {"L": 0, "R": 0}
    for m in re.finditer(r'<Rectangle\b[^>]*>.*?</Rectangle>', basetabs_xml, re.S):
        if not re.search(TABFILL, m.group(0)):
            continue
        it = list(map(float, re.search(r'ItemTransform="([^"]+)"', m.group(0)).group(1).split()))
        xs = [float(p.split()[0]) * it[0] + it[4]
              for p in re.findall(r'Anchor="([^"]+)"', m.group(0))]
        per_side["R" if sum(xs) / len(xs) > 0 else "L"] += 1
    n = max(per_side.values()) or 26
    # Pitch is MEASURED, not derived from the box: v1.76's 26-slot strip inherits
    # the .ai artwork's 20.7233 (26 x 20.7233 = 538.8, which overflows the 517.26pt
    # margin box), whereas a strip from configure_chapters.py tiles the box exactly.
    # The median of consecutive gaps ignores the one off-strip stray.
    tys = {"L": [], "R": []}
    for m in re.finditer(r'<TextFrame\b[^>]*>', basetabs_xml):
        it = re.search(r'ItemTransform="([^"]+)"', m.group(0))
        if not it or 'ParentStory="' not in m.group(0):
            continue
        v = list(map(float, it.group(1).split()))
        if abs(v[4]) >= 300:
            tys["R" if v[4] > 0 else "L"].append(v[5])
    col = sorted(max(tys.values(), key=len))
    gaps = sorted(b - a for a, b in zip(col, col[1:]))
    pitch = gaps[len(gaps) // 2] if gaps else BOX_H / n
    return n, pitch, (min(col) if col else TY0_NUM)


def set_grid(grid):
    global NSLOTS, PITCH, TY0_NUM
    NSLOTS, PITCH, TY0_NUM = grid


def local(t):
    return t.split("}")[-1]


def master_by_name(build, name):
    for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
        t = open(f, encoding="utf-8").read()
        m = re.search(r'<MasterSpread\b[^>]*?\bName="([^"]*)"', t)
        if m and m.group(1) == name:
            return f, t
    raise SystemExit(f"master named {name!r} not found")


def corners(block):
    a, b, c, d, tx, ty = map(float, re.search(r'ItemTransform="([^"]+)"', block).group(1).split())
    frame = block.split('<PDF', 1)[0]
    return [(a*float(p.split()[0])+c*float(p.split()[1])+tx,
             b*float(p.split()[0])+d*float(p.split()[1])+ty)
            for p in re.findall(r'Anchor="([^"]+)"', frame)]


def rect_slot(block):
    return RSLOT(min(p[1] for p in corners(block)))


def numframe_slot(tag):
    """(in_tab_column, slot) for a master text frame.

    in_tab_column separates "a tab number belonging to some other slot" -- drop it
    from this master -- from "a different frame entirely" -- keep it, but it then
    has to own its own story. slot is None for a frame that sits in the tab column
    yet off the strip: BT-BaseTabs carries one such stray, u94e, parked at ty=792
    (~495pt below the page), which computes to slot 51. Treating that as "not a
    number frame" copied it into every chapter master still pointing at the
    original's story, leaving four unthreaded frames sharing one story.
    """
    it = re.search(r'ItemTransform="([^"]+)"', tag)
    ps = re.search(r'ParentStory="([^"]+)"', tag)
    if not it or not ps:
        return False, None
    vals = it.group(1).split()
    tx, ty = float(vals[4]), float(vals[5])
    if abs(tx) < 300:          # tab numbers sit in the outer margin
        return False, None
    s = NSLOT(ty)
    return True, (s if 0 <= s < NSLOTS else None)


def repair_strip(xml):
    """Move any off-strip tab-number frame back to its slot. Returns (xml, log).

    BT-BaseTabs should carry N slots x 2 pages of number frames, N being whatever
    the strip itself says. v1.76 ships its 26-slot strip one frame short: slot 25's
    right-page number, u25f77, parked exactly one strip height (26 x 20.7233 =
    538.80pt) below its home at ty=253.39, and every file derived from the manual
    inherited it. A frame's x tells us which side it belongs to; the single gap in
    the grid tells us which slot. Without this the last chapter would come out with
    a left-page number only. A strip rebuilt by configure_chapters.py never has
    this problem -- it is generated whole.
    """
    set_grid(read_grid(xml))          # the strip defines its own grid
    frames = []
    for m in re.finditer(r'<TextFrame\b[^>]*>', xml):
        tag = m.group(0)
        it = re.search(r'ItemTransform="([^"]+)"', tag)
        if not it or 'ParentStory="' not in tag:
            continue
        vals = it.group(1).split()
        tx, ty = float(vals[4]), float(vals[5])
        if abs(tx) < 300:                      # not in the tab column
            continue
        frames.append(dict(start=m.start(), end=m.end(), tag=tag, it=it.group(1),
                           tx=tx, ty=ty, slot=NSLOT(ty)))

    present = {(f["slot"], "R" if f["tx"] > 0 else "L")
               for f in frames if 0 <= f["slot"] < NSLOTS}
    missing = [(s, side) for s in range(NSLOTS) for side in ("L", "R")
               if (s, side) not in present]

    splices, log = [], []
    for f in frames:
        if 0 <= f["slot"] < NSLOTS:
            continue
        side = "R" if f["tx"] > 0 else "L"
        gaps = [g for g in missing if g[1] == side]
        if len(gaps) != 1:
            log.append(f"off-strip frame at ty={f['ty']:.2f} ({side} side): "
                       f"{len(gaps)} gaps on that side - left alone, needs a human")
            continue
        slot = gaps.pop(0)[0]
        missing.remove((slot, side))
        new_ty = TY0_NUM + slot * PITCH
        vals = f["it"].split()
        vals[5] = f"{new_ty:.10g}"
        new_tag = f["tag"].replace(f'ItemTransform="{f["it"]}"',
                                   'ItemTransform="%s"' % " ".join(vals))
        splices.append((f["start"], f["end"], new_tag))
        log.append(f"off-strip number frame belongs at slot {slot} {side}: "
                   f"ty {f['ty']:.2f} -> {new_ty:.2f}")
    for start, end, repl in sorted(splices, key=lambda s: s[0], reverse=True):
        xml = xml[:start] + repl + xml[end:]
    return xml, log


def set_attr(tag, n, v):
    if re.search(rf'\b{n}="', tag):
        return re.sub(rf'\b{n}="[^"]*"', f'{n}="{v}"', tag)
    return tag[:-1] + f' {n}="{v}"' + tag[-1]


def set_digit(story_xml, digit):
    """Fill the (empty) tab-number CharacterStyleRange with a literal digit."""
    if re.search(r'<CharacterStyleRange[^>]*>\s*<Content>', story_xml):
        return re.sub(r'(<CharacterStyleRange[^>]*>\s*<Content>)[^<]*(</Content>)',
                      rf'\g<1>{digit}\g<2>', story_xml, count=1)
    return re.sub(r'<CharacterStyleRange([^>]*?)\s*/>',
                  rf'<CharacterStyleRange\1><Content>{digit}</Content></CharacterStyleRange>',
                  story_xml, count=1)


def build_chapter_master(build, basetabs_xml, k, slot, title, base_self, mint):
    """Return (master_filename, master_xml, [(story_filename, story_xml)], master_self)."""
    t = basetabs_xml
    # --- prune tab rectangles to this slot ---
    def keep_rect(m):
        blk = m.group(0)
        if not re.search(TABFILL, blk):
            return blk                      # not a tab rect: leave (shouldn't happen)
        return blk if rect_slot(blk) == slot else ""
    t = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>', keep_rect, t, flags=re.S)

    # --- prune number frames to this slot; capture the two kept stories ---
    # EVERY frame kept here must end up owning its own story -- a story belongs to
    # exactly one frame chain, so leaving a clone pointing at the source's story
    # gives N unthreaded frames sharing it, which corrupts the document.
    kept_stories = []      # (orig_story_id, is_tab_number)
    def keep_num(m):
        blk = m.group(0)
        tag = re.match(r'<TextFrame\b[^>]*>', blk).group(0)
        in_col, s = numframe_slot(tag)
        story = re.search(r'ParentStory="([^"]+)"', tag)
        if in_col:
            if s != slot:
                return ""                   # another slot's number, or an off-strip stray
            kept_stories.append((story.group(1), True))
            return blk
        if story:                           # a different frame: keep, but clone its story
            kept_stories.append((story.group(1), False))
        return blk
    t = re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>', keep_num, t, flags=re.S)

    # --- fresh ids: lowercase-hex u<hex>, like InDesign's own. Uppercase ids are
    # tolerated by older InDesign but CRASH InDesign 2026 (v21) on open. ---
    ren = {}
    master_self = mint()
    ren[re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"', t).group(1)] = master_self
    for p in re.findall(r'<Page\b[^>]*Self="([^"]+)"', t):
        ren[p] = mint()
    for rself in re.findall(r'<Rectangle\b[^>]*Self="([^"]+)"', t):
        ren[rself] = mint()
    for fself in re.findall(r'<TextFrame\b[^>]*Self="([^"]+)"', t):
        ren[fself] = mint()
    story_ren, is_number = {}, {}
    for sid, isnum in kept_stories:
        story_ren.setdefault(sid, mint())
        is_number[sid] = is_number.get(sid, False) or isnum
    ren.update(story_ren)

    for old, new in ren.items():
        t = re.sub(rf'"{re.escape(old)}"', f'"{new}"', t)

    # rename + rebase. A master's identity is NamePrefix + BaseName (Name is just
    # the composed display form) and each master page is named after the prefix.
    # Renaming only Name left every clone still claiming prefix "BT" / base
    # "BaseTabs", i.e. four masters with one identity -- InDesign 2026 crashes on
    # open; 2025 tolerated it. Mirror the shipped manual: S<k> / <title> / S<k>.
    prefix, base = f"S{k}", S.xml_escape(title)
    t = re.sub(r'(<MasterSpread\b[^>]*?\bName=")[^"]*(")', rf'\g<1>{prefix}-{base}\g<2>', t, count=1)
    t = re.sub(r'(<MasterSpread\b[^>]*?\bNamePrefix=")[^"]*(")', rf'\g<1>{prefix}\g<2>', t, count=1)
    t = re.sub(r'(<MasterSpread\b[^>]*?\bBaseName=")[^"]*(")', rf'\g<1>{base}\g<2>', t, count=1)
    t = re.sub(r'(<Page\b[^>]*?\bName=")[^"]*(")', rf'\g<1>{prefix}\g<2>', t)
    t = re.sub(r'(<MasterSpread\b[^>]*Self="%s"[^>]*OverriddenPageItemProps=")[^"]*(")' % re.escape(master_self),
               r'\g<1>\g<2>', t)

    # --- clone every kept frame's story with fresh ids; digit=k on the numbers ---
    story_files = []
    for old_sid, new_sid in story_ren.items():
        sp = os.path.join(build, "Stories", f"Story_{old_sid}.xml")
        sx = open(sp, encoding="utf-8").read()
        sx = re.sub(rf'"{re.escape(old_sid)}"', f'"{new_sid}"', sx)
        if is_number[old_sid]:
            sx = set_digit(sx, str(k))
        story_files.append((f"Story_{new_sid}.xml", sx, new_sid))

    return f"MasterSpread_{master_self}.xml", t, story_files, master_self


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build

    chapters, ordered_pages = S.detect_chapters(build)   # topmost level present
    if not chapters:
        raise SystemExit("no chapters found")
    secs = S.compute_sections(chapters, ordered_pages)
    base_self = re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"',
                          master_by_name(build, "B-Base")[1]).group(1)
    bt_path, basetabs_xml = master_by_name(build, "BT-BaseTabs")
    # The kit's strip must already be complete -- correcting it on every run would
    # paper over a broken kit. fix_tab_strip.py is the one-time migration.
    _, strip_log = repair_strip(basetabs_xml)
    if strip_log:
        raise SystemExit("BT-BaseTabs' tab strip is incomplete:\n  "
                         + "\n  ".join(strip_log)
                         + f"\nRepair the kit first:  python3 fix_tab_strip.py {build}")
    # the strip must have exactly one slot per chapter -- the count belongs to the
    # manual, so a mismatch means the strip was built for a different document
    if len(chapters) != NSLOTS:
        raise SystemExit(
            f"tab strip has {NSLOTS} slots but {len(chapters)} chapters were detected.\n"
            f"Rebuild the strip for this manual:  python3 configure_chapters.py {build}")

    # mint lowercase-hex ids that don't collide with anything already in the tree
    existing = set()
    for f in glob.glob(os.path.join(build, "**", "*.xml"), recursive=True):
        existing |= set(re.findall(r'"(u[0-9a-fA-F]+)"', open(f, encoding="utf-8").read()))
    counter = [0x800000]

    def mint():
        while True:
            c = "u%x" % counter[0]
            counter[0] += 1
            if c not in existing:
                existing.add(c)
                return c

    print(f"{len(secs)} chapters; Base={base_self}")
    plan = []
    for i, s in enumerate(secs):
        k = i + 1
        slot = k - 1
        c = s["chapter"]
        # pages this chapter covers, in order
        start = c["page_order"]
        page_selfs = [p["self"] for p in ordered_pages[start:start + s["length"]]]
        fname, mxml, stories, master_self = build_chapter_master(
            build, basetabs_xml, k, slot, c["title"], base_self, mint)
        plan.append(dict(k=k, slot=slot, title=c["title"], fname=fname, mxml=mxml,
                         stories=stories, page_selfs=page_selfs, master_self=master_self))
        # report the fill this master actually got. It used to be looked up in
        # {0: "pure 292", 25: "pure Black"} -- the DM32 ramp hardcoded -- which
        # mislabelled every other manual: DM42n's slot 0 is pure PANTONE 130 U.
        got = re.search(TABFILL, mxml)
        fill = re.search(r'"([^"]+)"', got.group(0)).group(1).split("/", 1)[-1] if got else "?"
        print(f"  S{k}-{c['title'][:40]:40} slot{slot} fill={fill:22} "
              f"digit={k} pages={page_selfs[0]}..+{len(page_selfs)-1}")

    if args.dry_run:
        print("\n(dry-run: nothing written)")
        # sanity: show the kept items in the first master
        m = plan[0]["mxml"]
        nrect = len(re.findall(r'<Rectangle\b', m))
        nnum = len([1 for tg in re.findall(r'<TextFrame\b[^>]*>', m)
                    if numframe_slot(tg)[1] is not None])
        sids = [s[2] for s in plan[0]["stories"]]
        print(f"first master rects={nrect} numframes={nnum} stories={sids}")
        return

    # --- write master + story files ---
    new_master_selfs, new_story_ids = [], []
    for p in plan:
        open(os.path.join(build, "MasterSpreads", p["fname"]), "w", encoding="utf-8").write(p["mxml"])
        new_master_selfs.append(p["master_self"])
        for sfname, sxml, sid in p["stories"]:
            open(os.path.join(build, "Stories", sfname), "w", encoding="utf-8").write(sxml)
            new_story_ids.append(sid)

    # --- apply masters to pages (edit each spread) ---
    page_to_master = {}
    for p in plan:
        for ps in p["page_selfs"]:
            page_to_master[ps] = p["master_self"]
    for sf in glob.glob(os.path.join(build, "Spreads", "*.xml")):
        sx = open(sf, encoding="utf-8").read()
        changed = False
        def repl(m):
            nonlocal changed
            tag = m.group(0)
            self = re.search(r'Self="([^"]+)"', tag).group(1)
            if self in page_to_master:
                changed = True
                return set_attr(tag, "AppliedMaster", page_to_master[self])
            return tag
        sx = re.sub(r'<Page\b[^>]*?>', repl, sx)
        if changed:
            open(sf, "w", encoding="utf-8").write(sx)

    # --- register in designmap: master refs, story refs, StoryList ---
    dmp = os.path.join(build, "designmap.xml")
    d = open(dmp, encoding="utf-8").read()
    mrefs = "".join(f'\t<idPkg:MasterSpread src="MasterSpreads/MasterSpread_{ms}.xml" />\n'
                    for ms in new_master_selfs)
    d = re.sub(r'(\t<idPkg:MasterSpread\b)', mrefs + r'\1', d, count=1)
    srefs = "".join(f'\t<idPkg:Story src="Stories/Story_{sid}.xml" />\n' for sid in new_story_ids)
    d = re.sub(r'(\t<idPkg:Story\b)', srefs + r'\1', d, count=1)
    d = re.sub(r'StoryList="([^"]*)"',
               lambda m: f'StoryList="{m.group(1)} ' + " ".join(new_story_ids) + '"', d, count=1)
    open(dmp, "w", encoding="utf-8").write(d)

    print(f"\nwrote {len(plan)} chapter masters + {len(new_story_ids)} number stories; "
          f"applied to {len(page_to_master)} pages")


if __name__ == "__main__":
    main()
