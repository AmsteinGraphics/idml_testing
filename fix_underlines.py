#!/usr/bin/env python3
"""Enforce style-driven underlines: strip local Underline* formatting.

Underline belongs to a character style and nowhere else. In the DM32 design
system there are four underline signatures, all style-defined:

  cat 1  link, link_slant          0.375pt, offset +1.5, PANTONE 130 U, overprint
                                   -> the orange oblique-link rule
  cat 2  code_styles:lcd_* (7)     10.339pt, offset -2.4, PANTONE Warm Gray 1 U
  cat 3  code_styles:lcd_sk_* (4)  10.339pt, offset -3.66, PANTONE Warm Gray 1 U
                                   -> cats 2/3 are a thick bar across the text: an
                                      LCD background, not a rule
  cat 4  $ID/Hyperlink             defaults (unused)

Two things break "style only", and both survive an InDesign round-trip:

  * an INLINE underline    -- Underline="true" on a range with no character style;
  * a style + LOCAL OVERRIDE -- e.g. AppliedCharacterStyle="CharacterStyle/link"
    carrying UnderlineColor="Text Color", which defeats the style's orange.

IDML stores these in TWO places and both must be cleaned: scalar properties are
open-tag ATTRIBUTES (Underline, UnderlineWeight, UnderlineOffset, ...) while
object-valued ones are <Properties> CHILD ELEMENTS (<UnderlineColor>,
<UnderlineGapColor>). Attribute-only cleaning silently leaves the colour behind.

InDesign is the reintroducer: inserting an anchored object splits a link-styled
range and leaves an empty stub holding an override block. Since the forward
pipeline ends in "open in InDesign, run place_xref_boxes.jsx, re-export", run
this after every round-trip, before repack.py.

SAFETY: appearance can only change where a range HOLDS TEXT *and* its underline
is actually visible -- i.e. a local Underline="true", or an underlining character
style that no local Underline="false" cancels. Dropping an override there flips
what prints, and the right resolution depends on intent: drop the override, or
drop the *style* the way build_xref_boxes.py does when it suppresses a dead link.
Those are reported and left alone unless --force. Everything else is stripped by
default, because it cannot change appearance: an empty range has no text to
underline, and underline properties on a range whose style doesn't underline are
inert residue from formatting that was already cleared.

    fix_underlines.py <build_dir> [--dry-run] [--force] [--category N]

--category restricts to one signature (1 = the orange oblique-link rule).
Idempotent. Pairs with check 10 in validate_idml.py.
"""
import argparse
import glob
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

UL_ATTR = re.compile(r'\s*\bUnderline[A-Za-z]*="[^"]*"')
UL_TOGGLE = re.compile(r'\bUnderline="(true|false)"')
UL_CHILD = re.compile(r'[ \t]*<Underline[A-Za-z]*\b[^>]*?(?:/>|>.*?</Underline[A-Za-z]*>)\s*\n?', re.S)
RANGE_OPEN = re.compile(r'<(CharacterStyleRange|ParagraphStyleRange)\b([^>]*?)(/?)>')
# matched with .match(t, pos) so it anchors at the range's end without slicing
# the remainder of the file (that turns a big story into O(n^2))
PROPS_AT = re.compile(r'(\s*)<Properties>(.*?)</Properties>', re.S)

# signature -> category, keyed on (weight, offset)
CATEGORY = {("0.375", "1.5"): 1, ("10.339", "-2.4"): 2, ("10.339", "-3.66"): 3}


def loc(t):
    return t.split("}")[-1]


def underlining_styles(build):
    """Self-ids of character/paragraph styles whose effective Underline is true,
    resolving BasedOn and reading BOTH attributes and <Properties> children."""
    path = os.path.join(build, "Resources", "Styles.xml")
    if not os.path.exists(path):
        return set(), {}
    root = ET.parse(path).getroot()
    raw = {}
    for el in root.iter():
        if loc(el.tag) not in ("ParagraphStyle", "CharacterStyle") or not el.get("Self"):
            continue
        props = {k: v for k, v in el.attrib.items() if k.startswith("Underline")}
        based = el.get("BasedOn")
        for p in el:
            if loc(p.tag) != "Properties":
                continue
            for c in p:
                n = loc(c.tag)
                if n.startswith("Underline") and c.text:
                    props[n] = c.text.strip()
                elif n == "BasedOn" and c.text:
                    based = c.text.strip()
        raw[el.get("Self")] = (based, props)

    def resolve(sid, seen=None):
        seen = seen or set()
        if sid not in raw or sid in seen:
            return {}
        seen.add(sid)
        based, props = raw[sid]
        out = dict(resolve(based, seen) if based else {})
        out.update(props)
        return out

    on, cats = set(), {}
    for sid in raw:
        p = resolve(sid)
        if p.get("Underline") == "true":
            on.add(sid)
            cats[sid] = CATEGORY.get((p.get("UnderlineWeight"), p.get("UnderlineOffset")))
    return on, cats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="also strip overrides that are visibly in effect (changes appearance)")
    ap.add_argument("--category", type=int, choices=(1, 2, 3, 4),
                    help="restrict to one underline signature (1 = orange oblique-link rule)")
    args = ap.parse_args()

    ul_styles, cats = underlining_styles(args.build)
    files = sorted(glob.glob(os.path.join(args.build, "Stories", "*.xml")) +
                   glob.glob(os.path.join(args.build, "Spreads", "*.xml")) +
                   glob.glob(os.path.join(args.build, "MasterSpreads", "*.xml")))

    fixed, skipped, touched = [], [], 0
    for path in files:
        t = open(path, encoding="utf-8").read()
        if "Underline" not in t:
            continue
        rel = os.path.relpath(path, args.build)
        splices = []
        for m in RANGE_OPEN.finditer(t):
            attrs, selfclose = m.group(2), m.group(3)

            # object-valued underline props live in the range's own <Properties>
            pm = None if selfclose else PROPS_AT.match(t, m.end())
            has_child = bool(pm and UL_CHILD.search(pm.group(2)))
            if not UL_ATTR.search(attrs) and not has_child:
                continue

            sid = re.search(r'AppliedCharacterStyle="([^"]+)"', attrs)
            sid = sid.group(1) if sid else None
            style = urllib.parse.unquote(sid.split("/", 1)[-1]) if sid else "(no character style)"

            toggle = UL_TOGGLE.search(attrs)
            toggle = toggle.group(1) if toggle else None
            styled = sid in ul_styles
            visible = toggle == "true" or (toggle is None and styled)

            cat = cats.get(sid)
            if cat is None:                      # inline: classify by its own geometry
                w = re.search(r'UnderlineWeight="([^"]*)"', attrs)
                o = re.search(r'UnderlineOffset="([^"]*)"', attrs)
                cat = CATEGORY.get((w.group(1) if w else None, o.group(1) if o else None))
            if args.category and cat != args.category:
                continue

            end = t.find(f"</{m.group(1)}>", m.end()) if not selfclose else m.end()
            txt = "".join(re.findall(r'<Content>(.*?)</Content>',
                                     t[m.end():end] if end > 0 else "", re.S)).strip()

            rec = (rel, style, txt, cat)
            if txt and visible and not args.force:
                skipped.append(rec)
                continue

            splices.append((m.start(2), m.end(2), UL_ATTR.sub("", attrs)))
            if has_child:
                inner = UL_CHILD.sub("", pm.group(2))
                # drop a <Properties> block left with nothing in it
                repl = (pm.group(1) + f"<Properties>{inner}</Properties>"
                        if inner.strip() else "")
                splices.append((pm.start(), pm.end(), repl))
            fixed.append(rec)
        if splices:
            for start, end, repl in sorted(splices, key=lambda s: s[0], reverse=True):
                t = t[:start] + repl + t[end:]
            if not args.dry_run:
                open(path, "w", encoding="utf-8").write(t)
            touched += 1

    scope = f" (category {args.category} only)" if args.category else ""
    verb = "would strip" if args.dry_run else "stripped"
    print(f"{verb} local underline formatting from {len(fixed)} range(s) "
          f"in {touched} file(s){scope}")
    for rel, style, txt, cat in fixed[:20]:
        print(f"  - cat {cat or '?'}  {rel}: {style} "
              f"{repr(txt[:40]) if txt else '(empty range)'}")
    if len(fixed) > 20:
        print(f"    ... and {len(fixed) - 20} more")
    if skipped:
        print(f"\nLEFT ALONE - {len(skipped)} range(s) hold text with the underline visibly "
              f"in effect,\nso dropping the override would change what prints. Decide per "
              f"case: remove the\noverride (reverts to the style) or remove the style (as "
              f"build_xref_boxes.py does for\ndead links). Re-run with --force to drop them.")
        for rel, style, txt, cat in skipped[:20]:
            print(f"  - cat {cat or '?'}  {rel}: {style} {txt[:60]!r}")


if __name__ == "__main__":
    main()
