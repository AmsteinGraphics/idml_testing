#!/usr/bin/env python3
"""Remove all oblique-link margin boxes, leaving a boxless 'submission'.

Inverse of build_xref_boxes.py — used to manufacture test input from a file that
already has boxes, and to normalise a resubmission. Removes:
  * every anchored <TextFrame AppliedObjectStyle="ObjectStyle/cross_ref_block">
    embedded in a body story (the margin box),
  * each such frame's margin story file (its ParentStory),
  * the <Hyperlink> in designmap binding that box's <CrossReferenceSource>,
  * the margin story's idPkg:Story ref + StoryList entry.
Leaves the underlined word (CharacterStyle/link + HyperlinkTextSource), its
Hyperlink->destination, and all destinations untouched.

    strip_xref_boxes.py <build_dir> [--dry-run]
"""
import argparse
import glob
import os
import re

BOX_OBJSTYLE = 'ObjectStyle/cross_ref_block'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build

    frame_re = re.compile(
        r'<TextFrame\b[^>]*AppliedObjectStyle="' + re.escape(BOX_OBJSTYLE) + r'"[^>]*>.*?</TextFrame>',
        re.S)

    margin_stories = []          # story ids that back a margin box
    removed_frames = 0
    story_edits = {}             # path -> new text
    for p in glob.glob(os.path.join(build, "Stories", "*.xml")):
        t = open(p, encoding="utf-8").read()
        if BOX_OBJSTYLE not in t:
            continue
        def drop(m):
            nonlocal removed_frames
            blk = m.group(0)
            ps = re.search(r'ParentStory="([^"]+)"', blk)
            if ps:
                margin_stories.append(ps.group(1))
            removed_frames += 1
            return ""
        t2 = frame_re.sub(drop, t)
        story_edits[p] = t2

    # collect the CrossReferenceSource ids that live in those margin stories
    crs_ids = []
    margin_files = []
    for sid in margin_stories:
        mp = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(mp):
            margin_files.append(mp)
            mx = open(mp, encoding="utf-8").read()
            crs_ids += re.findall(r'<CrossReferenceSource Self="([^"]+)"', mx)

    # designmap: drop the box hyperlinks + margin story registration
    dmp = os.path.join(build, "designmap.xml")
    d = open(dmp, encoding="utf-8").read()
    crs_set = set(crs_ids)
    def drop_hl(m):
        return "" if m.group(1) in crs_set else m.group(0)
    d2 = re.sub(r'<Hyperlink\b[^>]*Source="([^"]+)"[^>]*/>', drop_hl, d)
    # also handle <Hyperlink ...>...</Hyperlink> block form
    d2 = re.sub(r'<Hyperlink\b[^>]*Source="([^"]+)"[^>]*>.*?</Hyperlink>',
                lambda m: "" if m.group(1) in crs_set else m.group(0), d2, flags=re.S)
    removed_hl = len(re.findall(r'<Hyperlink\b', d)) - len(re.findall(r'<Hyperlink\b', d2))
    for sid in margin_stories:
        d2 = re.sub(rf'\s*<idPkg:Story src="Stories/Story_{re.escape(sid)}\.xml" />', '', d2)
    sl = re.search(r'StoryList="([^"]*)"', d2)
    if sl:
        keep = [x for x in sl.group(1).split() if x not in set(margin_stories)]
        d2 = re.sub(r'StoryList="[^"]*"', 'StoryList="' + " ".join(keep) + '"', d2, count=1)

    print(f"margin boxes (frames): {removed_frames}")
    print(f"margin stories:        {len(margin_files)}")
    print(f"box hyperlinks:        {removed_hl}")
    if args.dry_run:
        print("(dry-run: nothing written)")
        return
    for p, t in story_edits.items():
        open(p, "w", encoding="utf-8").write(t)
    for mp in margin_files:
        os.remove(mp)
    open(dmp, "w", encoding="utf-8").write(d2)
    print("stripped.")


if __name__ == "__main__":
    main()
