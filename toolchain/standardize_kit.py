#!/usr/bin/env python3
"""Strip a product name off the kit's design-system objects.

The design system is the house standard, not one product's — but the DM32 manual
named several of its shared objects after itself, and every manual derived from
the kit inherits those names. This renames them once, so the next manual isn't
called dm32_anything.

In the DM32 kit that is nine objects:
    NumberingList        dm32_list, dm32_ordered
    CrossReferenceFormat dm32_cross_ref, dm32_cross_par
    TextVariable         dm32_head, dm32_section, dm32_foot_thread

The three object kinds carry identity differently, which is why this renames by
discovered NAME rather than blindly editing tags:

  * CrossReferenceFormat has an opaque Self (u198b) and is referenced by it, so
    only Name changes and nothing else has to move.
  * NumberingList's Self IS its name (NumberingList/dm32_list) and paragraph
    styles point at that string, so Self, Name and every reference change together.
  * TextVariable's Self is dTextVariablen<name>, same situation.

Replacing the discovered names (longest first) covers all three without needing to
know which is which.

    standardize_kit.py <build_dir> [--from dm32_] [--to manual_] [--dry-run]

Run once on the kit, then scrub_metadata.py so the XMP lineage goes too. Renaming
a kit that already has content is fine — references travel with the name — but any
InDesign document already built on the old names will not find the new ones.
"""
import argparse
import glob
import os
import re
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--from", dest="src", default="dm32_", help="prefix to remove")
    ap.add_argument("--to", dest="dst", default="manual_", help="prefix to use instead")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.build, "**", "*.xml"), recursive=True))

    # discover every object Name carrying the prefix, and what kind it is
    found = {}
    for p in files:
        t = open(p, encoding="utf-8").read()
        for m in re.finditer(r'<(\w+)\b[^>]*?\bName="(' + re.escape(args.src) + r'[^"]*)"', t):
            found.setdefault(m.group(2), set()).add(m.group(1))
    if not found:
        print(f"no objects named {args.src}* — nothing to do")
        return 0

    # longest first, so a name that is a prefix of another can't be half-renamed
    renames = sorted(found, key=len, reverse=True)
    print(f"renaming {len(renames)} object(s):")
    for name in sorted(found):
        kinds = ", ".join(sorted(found[name]))
        print(f"  {name:22s} -> {args.dst + name[len(args.src):]:22s} ({kinds})")

    touched, edits = 0, 0
    for p in files:
        t = open(p, encoding="utf-8").read()
        orig = t
        for name in renames:
            new = args.dst + name[len(args.src):]
            edits += t.count(name)
            t = t.replace(name, new)
        if t != orig:
            touched += 1
            if not args.dry_run:
                open(p, "w", encoding="utf-8").write(t)

    verb = "would rewrite" if args.dry_run else "rewrote"
    print(f"{verb} {edits} occurrence(s) across {touched} file(s)")
    if args.dry_run:
        return 0

    # Only the renamed OBJECTS should be gone. Other strings sharing the prefix are
    # content -- image file names, URLs, the product's own name -- and renaming
    # those would be wrong, so report them separately rather than as leftovers.
    stale = sum(open(p, encoding="utf-8").read().count(n) for p in files for n in renames)
    print(f"renamed objects still referenced: {stale}"
          + ("" if stale else "  (metadata.xml is separate — run scrub_metadata.py)"))
    other = {}
    for p in files:
        for m in re.finditer(re.escape(args.src) + r'[A-Za-z0-9_]*', open(p, encoding="utf-8").read()):
            if m.group(0) not in renames:
                other[m.group(0)] = other.get(m.group(0), 0) + 1
    if other:
        top = sorted(other.items(), key=lambda kv: -kv[1])[:5]
        print(f"left alone — content, not design-system objects: "
              + ", ".join(f"{k} x{v}" for k, v in top)
              + (f", +{len(other) - len(top)} more" if len(other) > len(top) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
