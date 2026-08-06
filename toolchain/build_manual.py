#!/usr/bin/env python3
"""Run the pre-InDesign leg of the forward pipeline for one submission.

    build_manual.py manuals/<product>/submissions/<file>.idml [--out DIR] [--keep]

The manual directory is inferred from the path, so config (<product>.swatches,
<product>.tabstops.csv) is found by the usual outward search and nothing else has
to be passed.

THE PIPELINE HAS A HARD BREAK and this script stops at it. Margin boxes cannot be
authored in IDML — InDesign never binds a hand-written anchored frame on import —
so they are created natively by place_xref_boxes.jsx, inside InDesign, by a human.
What this produces is the file to open and run that script on:

    submission -> standardize -> numbering -> sections -> tab strip -> tabs
               -> dead-link suppression + audit -> validate -> <name>.ready.idml
                                                                        |
                        open in InDesign, run place_xref_boxes.jsx, export IDML
                                                                        |
                                    -> fix_underlines.py -> validate -> repack

Exit code 0 means the submission survived every stage and validates clean.
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, *args, capture=False):
    cmd = [sys.executable, os.path.join(HERE, script), *map(str, args)]
    print(f"\n$ {' '.join(os.path.relpath(c) if os.path.sep in str(c) else str(c) for c in cmd[1:])}",
          flush=True)
    r = subprocess.run(cmd, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None)
    if capture:
        print(r.stdout, end="", flush=True)
    if r.returncode != 0:
        raise SystemExit(f"\n{script} failed (exit {r.returncode})")
    return r.stdout if capture else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submission")
    ap.add_argument("--out", help="output directory (default: the manual's out/)")
    ap.add_argument("--keep", action="store_true", help="keep the unpacked build tree")
    args = ap.parse_args()

    sub = os.path.abspath(args.submission)
    if not os.path.exists(sub):
        raise SystemExit(f"no such submission: {args.submission}")
    # manuals/<product>/submissions/<file>.idml -> manuals/<product>
    manual_dir = os.path.dirname(os.path.dirname(sub))
    if os.path.basename(os.path.dirname(sub)) != "submissions":
        raise SystemExit("expected a path like manuals/<product>/submissions/<file>.idml")
    product = os.path.basename(manual_dir)
    build = os.path.join(manual_dir, "build")
    outdir = args.out or os.path.join(manual_dir, "out")
    name = re.sub(r"\.idml$", "", os.path.basename(sub))
    ready = os.path.join(outdir, f"{name}.ready.idml")

    print(f"manual   : {product}")
    print(f"submission: {os.path.relpath(sub)}")

    if os.path.isdir(build):
        import shutil
        shutil.rmtree(build)
    os.makedirs(build, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(sub) as z:
        z.extractall(build)

    # idempotent on an already-standard document; migrates a pre-standardisation one
    run("standardize_kit.py", build)
    run("fix_numbering.py", build)
    run("sectionize.py", build)
    run("configure_chapters.py", build)
    run("apply_tabs.py", build)
    run("build_xref_boxes.py", build, "--jsx")
    run("validate_idml.py", build)
    run("repack.py", build, ready)

    # the audit log is written as a sibling of the build dir (never packed); keep it
    # alongside the output instead, named for the submission, so it outlives the tree
    log_src = build + ".xref_log.csv"
    log_dst = os.path.join(outdir, f"{name}.xref_log.csv")
    if os.path.exists(log_src):
        os.replace(log_src, log_dst)
        print(f"audit log: {os.path.relpath(log_dst)}")

    if not args.keep:
        import shutil
        shutil.rmtree(build)

    print(f"\nready for InDesign: {os.path.relpath(ready)}")
    print("next: open it, run toolchain/place_xref_boxes.jsx, export IDML, then "
          "fix_underlines.py + validate_idml.py + repack.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
