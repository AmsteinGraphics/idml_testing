#!/usr/bin/env python3
"""Ensure the section-heading paragraph styles are joined to the manual_list list.

The multi-level section numbering only works if EVERY level's paragraph style is
switched on as a numbered list AND points at the shared list. Submissions often
arrive with only the deepest level (titles:lvl4) wired up, so titles:lvl2/lvl3
never count (their level-1/level-2 counters stay at 1 and lvl4's ^1.^2.^3
collapses to 1.1.x). This patches lvl2/lvl3 to match lvl4:
BulletsAndNumberingListType="NumberedList" + AppliedNumberingList -> manual_list.
Their NumberingLevel / NumberingExpression are left as-is (already correct).

Idempotent. Run early, before sectionize/apply_tabs/build_xref_boxes.

    fix_numbering.py <build_dir> [--list manual_list] [--styles titles:lvl2,titles:lvl3]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manualconf


def fix_style(styles_xml, name, list_name):
    m = re.search(r'<ParagraphStyle\b[^>]*?\bName="' + re.escape(name) + r'".*?</ParagraphStyle>',
                  styles_xml, re.S)
    if not m:
        return styles_xml, "not found"
    block = m.group(0)
    new = block
    changed = []

    open_tag = re.match(r'<ParagraphStyle\b[^>]*?>', new).group(0)
    if 'BulletsAndNumberingListType=' not in open_tag:
        new = new.replace(open_tag,
                          open_tag[:-1] + ' BulletsAndNumberingListType="NumberedList">', 1)
        changed.append("+type")
    elif 'BulletsAndNumberingListType="NumberedList"' not in open_tag:
        new = re.sub(r'BulletsAndNumberingListType="[^"]*"',
                     'BulletsAndNumberingListType="NumberedList"', new, count=1)
        changed.append("~type")

    if '<AppliedNumberingList' not in new:
        anl = ('\t\t\t\t<AppliedNumberingList type="object">NumberingList/'
               + list_name + '</AppliedNumberingList>\n\t\t\t</Properties>')
        new = new.replace('</Properties>', anl, 1)
        changed.append("+list")

    if new != block:
        styles_xml = styles_xml.replace(block, new, 1)
    return styles_xml, (",".join(changed) or "already ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--list", default="manual_list")
    ap.add_argument("--styles", default=None,
                    help="default: the manual config's numbered levels, else "
                         "titles:lvl1..lvl3")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Only the levels that actually take part in numbering get joined to the list.
    # Joining a label level (a "Part") would make it advance the top counter and
    # restart the level below inside each part.
    styles = args.styles
    if styles is None:
        conf = manualconf.load(args.build)
        styles = ",".join(conf["numbered_styles"] or
                          ["titles:lvl1", "titles:lvl2", "titles:lvl3"])

    path = os.path.join(args.build, "Resources", "Styles.xml")
    x = open(path, encoding="utf-8").read()
    for name in styles.split(","):
        x, status = fix_style(x, name.strip(), args.list)
        print(f"  {name.strip():14} -> {status}")
    if args.dry_run:
        print("(dry-run: nothing written)")
        return
    open(path, "w", encoding="utf-8").write(x)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
