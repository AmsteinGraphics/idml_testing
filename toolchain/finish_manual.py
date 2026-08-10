#!/usr/bin/env python3
"""Close the loop on a manual that has come back from InDesign with its boxes.

    finish_manual.py <export>.idml [--out DIR]   ->  <name>.final.idml

The forward leg stops at the InDesign break; place_xref_boxes.jsx creates the
margin boxes natively; this is what turns that export into a shippable file:

    fix_underlines.py  -> validate_idml.py -> repack.py

It KEEPS the boxes. That is the whole difference from handing the same export to
build_manual.py, which strips them and rebuilds the manual from scratch so the
content can be revised. Two exits from the same file:

    export.idml --finish_manual--> final.idml        ship this state
    export.idml --build_manual--> ready.idml         revise, run the JSX again

Underline cleanup is the reason this is not just repack.py. Anchoring an object
splits the `link` character-style range and leaves a stub carrying local
Underline* formatting, which defeats the style's PANTONE 130 U orange — see
"Underlines are style-driven, always" in the README.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import normalize_input as N


def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script), *map(str, args)]
    print(f"\n$ {script} {' '.join(map(str, args))}", flush=True)
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        raise SystemExit(f"\n{script} failed (exit {r.returncode})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export", metavar="EXPORT.idml",
                    help="IDML exported from InDesign after place_xref_boxes.jsx ran")
    ap.add_argument("--out", help="output directory (default: the manual's out/)")
    ap.add_argument("--keep", action="store_true", help="keep the unpacked build tree")
    args = ap.parse_args()

    src = os.path.abspath(args.export)
    if not os.path.exists(src):
        raise SystemExit(f"no such file: {args.export}")
    manual_dir = os.path.dirname(os.path.dirname(src))
    product = os.path.basename(manual_dir)
    build = os.path.join(manual_dir, "build")
    outdir = args.out or os.path.join(manual_dir, "out")
    name = re.sub(r"\.idml$", "", os.path.basename(src))
    name = re.sub(r"\.(ready|final)$", "", name)
    final = os.path.join(outdir, f"{name}.final.idml")

    print(f"manual   : {product}")
    print(f"export   : {os.path.relpath(src)}")

    if os.path.isdir(build):
        shutil.rmtree(build)
    os.makedirs(build, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(build)

    marks = N.detect(build)
    print(f"carries  : {N.describe(marks)}")
    if not marks["boxes"]:
        print("\nWARNING: no oblique-ref margin boxes in this file. If the JSX was meant "
              "to have run,\n         it did not — check for its alert in InDesign.")

    run("fix_underlines.py", build)
    # orphaned hyperlinks are InDesign's, not ours: it drops a source range and
    # leaves the <Hyperlink> pointing at nothing, which validate counts as dangling
    n = N.drop_orphan_hyperlinks(build)
    if n:
        print(f"dropped {n} orphaned hyperlink(s)")
    run("validate_idml.py", build)
    run("repack.py", build, final)

    if not args.keep:
        shutil.rmtree(build)

    print(f"\nfinal: {os.path.relpath(final)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
