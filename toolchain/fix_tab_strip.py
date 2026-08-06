#!/usr/bin/env python3
"""One-time migration: put BT-BaseTabs' tab strip back in order.

BT-BaseTabs should carry a complete numbered strip -- 26 slots x 2 pages = 52
number frames. `dm32_print_manual_v1.76.idml` ships with one of them missing from
the grid: slot 25's right-page number (frame u25f77) sits at ty=792.19, exactly
one strip height (26 x 20.7233 = 538.80pt) below its home at ty=253.39, roughly
495pt off the bottom of the page. Every template derived from the manual
inherited it -- manual_template, manual_template_masters_proof and the forward
pipeline's kit manual_template_nosection all carry a 51/52 strip.

Left alone it does two kinds of damage. apply_tabs.py can't classify the frame
(it computes to slot 51), so it used to copy it into every chapter master still
pointing at the original's story, leaving N unthreaded frames sharing one story.
And a 26-chapter manual would come out with no right-page number on chapter 26,
because the frame apply_tabs.py needs for that slot isn't on the strip.

Run this ONCE per kit, then repack. Afterwards apply_tabs.py refuses any kit whose
strip is still incomplete rather than correcting it on every run.

    fix_tab_strip.py <build_dir> [--dry-run]

A frame's x tells us which page it belongs to; the single gap in the 52-slot grid
tells us which slot. Idempotent: a complete strip is left untouched.
"""
import argparse
import sys

import apply_tabs as A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path, xml = A.master_by_name(args.build, "BT-BaseTabs")
    fixed, log = A.repair_strip(xml)
    if not log:
        print("BT-BaseTabs strip already complete - nothing to do")
        return 0
    for msg in log:
        print(("would fix: " if args.dry_run else "fixed: ") + msg)
    if not args.dry_run:
        open(path, "w", encoding="utf-8").write(fixed)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
