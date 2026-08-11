#!/usr/bin/env python3
"""Run the pre-InDesign leg of the forward pipeline for one manual.

    build_manual.py manuals/<product>/submissions/<file>.idml [--out DIR] [--keep]

The manual directory is inferred from the path, so config (palette, hierarchy,
in <product>.manual) is found by the usual outward search and nothing else has
to be passed.

THE PIPELINE HAS A HARD BREAK and this script stops at it. Margin boxes cannot be
authored in IDML — InDesign never binds a hand-written anchored frame on import —
so they are created natively by place_xref_boxes.jsx, inside InDesign, by a human.
What this produces is the file to open and run that script on:

    submission -> standardize -> sync -> key markup -> hierarchy -> numbering
               -> sections -> tabs -> dead-link suppression + audit
               -> validate -> <name>.ready.idml
                                                                        |
                        open in InDesign, run place_xref_boxes.jsx, export IDML
                                                                        |
                                                                    (feed back)

THE INPUT MAY BE A FINISHED MANUAL. Refining the book is iterative: edit the
content in InDesign, export IDML, and hand that straight back to this script. A
processed file is detected (margin boxes, per-chapter masters, more than one
section) and normalize_input.py runs first, taking it back to submission state —
boxes off, InDesign's local underline overrides off, orphaned hyperlinks off —
after which every forward stage behaves exactly as it does on a fresh
submission. `--as-submission` skips the check, `--reprocess` forces it.

Exit code 0 means the input survived every stage and validates clean.
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manualconf
import normalize_input as N


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
    ap.add_argument("submission", metavar="INPUT.idml",
                    help="a submission, or a manual this pipeline already produced")
    ap.add_argument("--out", help="output directory (default: the manual's out/)")
    ap.add_argument("--keep", action="store_true", help="keep the unpacked build tree")
    ap.add_argument("--reprocess", action="store_true",
                    help="normalise the input first even if it looks like a submission")
    ap.add_argument("--as-submission", action="store_true",
                    help="never normalise — treat the input as a fresh submission")
    ap.add_argument("--kit", help="sync against this kit .idml instead of kit/manual_kit.idml "
                                  "— try a kit revision against a real manual before "
                                  "committing it")
    args = ap.parse_args()

    sub = os.path.abspath(args.submission)
    if not os.path.exists(sub):
        raise SystemExit(f"no such file: {args.submission}")
    # manuals/<product>/<any>/<file>.idml -> manuals/<product>. The intermediate
    # directory used to have to be `submissions`, which made feeding a finished
    # manual back in impossible without shuffling files; `roundtrips/` and `out/`
    # are equally valid sources now. Config discovery walks outward from the build
    # directory either way, so it lands on the same <product>.manual.
    manual_dir = os.path.dirname(os.path.dirname(sub))
    product = os.path.basename(manual_dir)
    build = os.path.join(manual_dir, "build")
    outdir = args.out or os.path.join(manual_dir, "out")
    name = re.sub(r"\.idml$", "", os.path.basename(sub))
    ready = os.path.join(outdir, f"{name}.ready.idml")

    print(f"manual   : {product}")
    print(f"input    : {os.path.relpath(sub)}")

    if os.path.isdir(build):
        import shutil
        shutil.rmtree(build)
    os.makedirs(build, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    with zipfile.ZipFile(sub) as z:
        z.extractall(build)

    # A finished manual fed back in is taken to submission state first, so every
    # stage below sees the same shape it sees on a fresh pour. Without this the
    # boxes would double up and InDesign's underline overrides would survive.
    if args.as_submission:
        print("\n(--as-submission: input treated as a fresh submission, not normalised)")
    elif args.reprocess or N.is_processed(build):
        print("\n=== input has already been through the pipeline: normalising ===")
        N.normalize(build)

    # idempotent on an already-standard document; migrates a pre-standardisation one
    run("standardize_kit.py", build)
    # AFTER standardize, BEFORE everything else. After, because the kit's masters
    # reference the standard names (manual_head, not dm32_head) and a document
    # still on the old ones has to be renamed first or the transplant pulls in a
    # duplicate. Before, because configure_chapters re-tweens the tab strip the
    # kit hands over to this manual's own ink ramp. Reports drift and changes
    # nothing unless the manual's config declares `sync`.
    run("sync_from_kit.py", build, *(["--kit", args.kit] if args.kit else []))
    # AFTER sync, because it renders into character styles the kit owns and a
    # manual may only just have received them. Forward-only and idempotent: an
    # already-rendered run holds no markup, so a re-run is a no-op and nothing
    # has to convert back. No-op on a manual whose authors type no markup.
    run("apply_key_markup.py", build)
    run("restyle_heading_levels.py", build)   # no-op unless number_from is declared
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
    # config discovery is path-based, so this still resolves after the tree is gone
    if manualconf.load(build)["tab_shows"] == "paragraph_number":
        print("next: open it, run toolchain/place_xref_boxes.jsx AND "
              "toolchain/place_tab_numbers.jsx, then either")
    else:
        print("next: open it, run toolchain/place_xref_boxes.jsx, then either")
    print("  finish_manual.py <export>.idml   to clean up and ship that state, or")
    print("  build_manual.py  <export>.idml   to edit further and run the whole leg again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
