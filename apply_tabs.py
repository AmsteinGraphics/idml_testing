#!/usr/bin/env python3
"""Phase 2 — create one per-chapter tab master (S<k>-<Title>) and apply it.

Runs on a build tree that already has per-chapter Sections (see sectionize.py).
For the Kth chapter in reading order it builds a master owning exactly one tab
(+ number) at slot K-1, cloned from BT-BaseTabs' pre-baked native strip, based on
B-Base so no inherited strip shows, mirrored on both pages, digit = K
(sequential). The master is then applied to every page of that chapter.

    apply_tabs.py <build_dir> [--dry-run]

Geometry & swatch conventions come from the kit's BaseTabs (native mixed-ink
tabs, tab_00 pure 292 .. tab_25 pure Black) — nothing is re-tweened here; the
uniform N=26 grid is reused as-is. Chapter detection is shared with sectionize.
"""
import argparse
import glob
import os
import re
import sys

import sectionize as S

PITCH = 20.7233
PAGE_H, M_TOP = 595.275590551, 22.170070866
Y0 = M_TOP - PAGE_H / 2          # margin-box top (rect grid origin)
TY0_NUM = -264.69               # number-frame grid origin
RSLOT = lambda ytop: round((ytop - Y0) / PITCH)
NSLOT = lambda ty: round((ty - TY0_NUM) / PITCH)
TABFILL = r'FillColor="(?:MixedInk/tab_\d+|Color/PANTONE 292 U|Color/Black)"'


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
    it = re.search(r'ItemTransform="([^"]+)"', tag)
    ps = re.search(r'ParentStory="([^"]+)"', tag)
    if not it or not ps:
        return None
    vals = it.group(1).split()
    tx, ty = float(vals[4]), float(vals[5])
    if abs(tx) < 300:          # tab numbers sit in the outer margin
        return None
    s = NSLOT(ty)
    return s if 0 <= s <= 25 else None


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


def build_chapter_master(build, basetabs_xml, k, slot, title, base_self):
    """Return (master_filename, master_xml, [(story_filename, story_xml)]) for chapter k."""
    t = basetabs_xml
    # --- prune tab rectangles to this slot ---
    def keep_rect(m):
        blk = m.group(0)
        if not re.search(TABFILL, blk):
            return blk                      # not a tab rect: leave (shouldn't happen)
        return blk if rect_slot(blk) == slot else ""
    t = re.sub(r'<Rectangle\b[^>]*>.*?</Rectangle>', keep_rect, t, flags=re.S)

    # --- prune number frames to this slot; capture the two kept stories ---
    kept_stories = []      # (side, orig_story_id)
    def keep_num(m):
        blk = m.group(0)
        s = numframe_slot(re.match(r'<TextFrame\b[^>]*>', blk).group(0))
        if s is None:
            return blk                      # non-number text frame: leave
        if s != slot:
            return ""
        tag = re.match(r'<TextFrame\b[^>]*>', blk).group(0)
        tx = float(re.search(r'ItemTransform="([^"]+)"', tag).group(1).split()[4])
        story = re.search(r'ParentStory="([^"]+)"', tag).group(1)
        kept_stories.append(("L" if tx < 0 else "R", story))
        return blk
    t = re.sub(r'<TextFrame\b[^>]*>.*?</TextFrame>', keep_num, t, flags=re.S)

    # --- fresh ids (uppercase => never collide with InDesign u<hex> ids) ---
    ren = {}
    ren[re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"', t).group(1)] = f"uCMm{k}"
    pages = re.findall(r'<Page\b[^>]*Self="([^"]+)"', t)
    for i, p in enumerate(pages):
        ren[p] = f"uCMp{i}k{k}"
    for i, rself in enumerate(re.findall(r'<Rectangle\b[^>]*Self="([^"]+)"', t)):
        ren[rself] = f"uCMr{i}k{k}"
    for i, fself in enumerate(re.findall(r'<TextFrame\b[^>]*Self="([^"]+)"', t)):
        ren[fself] = f"uCMf{i}k{k}"
    story_ren = {}
    for side, sid in kept_stories:
        story_ren[sid] = f"uCMs{side}k{k}"
    ren.update(story_ren)

    for old, new in ren.items():
        t = re.sub(rf'"{re.escape(old)}"', f'"{new}"', t)

    # rename + rebase
    t = re.sub(r'(<MasterSpread\b[^>]*?\bName=")[^"]*(")', rf'\g<1>S{k}-{S.xml_escape(title)}\g<2>', t, count=1)
    t = re.sub(r'(<MasterSpread\b[^>]*Self="uCMm%d"[^>]*OverriddenPageItemProps=")[^"]*(")' % k,
               r'\g<1>\g<2>', t)

    # --- clone the two number stories with fresh ids + digit=k ---
    story_files = []
    for old_sid, new_sid in story_ren.items():
        sp = os.path.join(build, "Stories", f"Story_{old_sid}.xml")
        sx = open(sp, encoding="utf-8").read()
        sx = re.sub(rf'"{re.escape(old_sid)}"', f'"{new_sid}"', sx)
        sx = set_digit(sx, str(k))
        story_files.append((f"Story_{new_sid}.xml", sx, new_sid))

    return f"MasterSpread_uCMm{k}.xml", t, story_files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build

    chapters, ordered_pages = S.detect_chapters(build, "titles:lvl2")
    if not chapters:
        raise SystemExit("no chapters found")
    secs = S.compute_sections(chapters, ordered_pages)
    base_self = re.search(r'<MasterSpread\b[^>]*Self="([^"]+)"',
                          master_by_name(build, "B-Base")[1]).group(1)
    _, basetabs_xml = master_by_name(build, "BT-BaseTabs")

    print(f"{len(secs)} chapters; Base={base_self}")
    plan = []
    for i, s in enumerate(secs):
        k = i + 1
        slot = k - 1
        c = s["chapter"]
        # pages this chapter covers, in order
        start = c["page_order"]
        page_selfs = [p["self"] for p in ordered_pages[start:start + s["length"]]]
        fname, mxml, stories = build_chapter_master(build, basetabs_xml, k, slot, c["title"], base_self)
        plan.append(dict(k=k, slot=slot, title=c["title"], fname=fname, mxml=mxml,
                         stories=stories, page_selfs=page_selfs, master_self=f"uCMm{k}"))
        fill = {0: "pure 292", 25: "pure Black"}.get(slot, f"tab_{slot:02d}")
        print(f"  S{k}-{c['title'][:40]:40} slot{slot} fill={fill:10} "
              f"digit={k} pages={page_selfs[0]}..+{len(page_selfs)-1}")

    if args.dry_run:
        print("\n(dry-run: nothing written)")
        # sanity: show the kept items in the first master
        m = plan[0]["mxml"]
        nrect = len(re.findall(r'<Rectangle\b', m))
        nnum = len([1 for tg in re.findall(r'<TextFrame\b[^>]*>', m) if numframe_slot(tg) is not None])
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
