#!/usr/bin/env python3
"""Prove the pipeline is a fixpoint: its own output rebuilds to the same thing.

    test_reentrancy.py [INPUT.idml] [-n 3]

Runs build_manual.py on a file, feeds the result back in, and repeats. From the
second generation on, the structural fingerprint must not move — same stories,
same masters by name, same sections, hyperlinks, boxes, link ranges and tab
swatches. Anything that drifts is something the loop adds without removing, and
it compounds: two chapter master sets, two boxes per word, a strip per run.

The default input is the tracked InDesign round-trip, which is the hardest case
in the repo — it carries every mark normalize_input.py has to undo, including
two masters InDesign renamed to break a duplicate identity.

Generation 1 is allowed to differ from generation 2: it is the one that strips
what InDesign left. Convergence is 2 == 3.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT = os.path.join(ROOT, "manuals", "dm32", "roundtrips",
                       "manual_template_test2_jsx_processed.idml")


def fingerprint(idml):
    """What must be identical between generations — names and counts, never ids.

    Self ids are minted fresh on every run by design (they only have to be unique
    and lowercase-hex), so comparing them would fail on a pipeline that is working
    perfectly. Masters are compared by Name, which is the stable identity.
    """
    z = zipfile.ZipFile(idml)
    names = z.namelist()
    read = lambda n: z.read(n).decode("utf-8")
    stories = [n for n in names if n.startswith("Stories/")]
    d = read("designmap.xml")
    masters = []
    for m in (n for n in names if n.startswith("MasterSpreads/")):
        o = re.search(r"<MasterSpread\b[^>]*>", read(m))
        masters.append((re.search(r'Name="([^"]*)"', o.group(0)) or [None, "?"])[1])
    return dict(
        stories=len(stories),
        masters=sorted(masters),
        sections=len(re.findall(r"<Section\b", d)),
        hyperlinks=len(re.findall(r"<Hyperlink\b", d)),
        boxes=sum(read(s).count("ObjectStyle/cross_ref_block") for s in stories),
        link_ranges=sum(read(s).count("CharacterStyle/link") for s in stories),
        text_sources=sum(read(s).count("<HyperlinkTextSource") for s in stories),
        tab_swatches=len(re.findall(r'MixedInk/tab_\d+"', read("Resources/Graphic.xml"))),
    )


def show(fp, label):
    print(f"  {label}: {fp['stories']} stories, {len(fp['masters'])} masters, "
          f"{fp['sections']} sections, {fp['hyperlinks']} hyperlinks, {fp['boxes']} boxes, "
          f"{fp['link_ranges']} link ranges, {fp['tab_swatches']} tab swatches")


def diff(a, b):
    return [f"{k}: {a[k]!r} -> {b[k]!r}" for k in a if a[k] != b[k]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default=DEFAULT)
    ap.add_argument("-n", type=int, default=3, help="generations to run (>= 3)")
    ap.add_argument("--config", help="a .manual to use (default: the input's own)")
    ap.add_argument("--kit", help="build against this kit — check a kit revision keeps "
                                  "the pipeline convergent before committing it")
    ap.add_argument("--sync", action="store_true",
                    help="declare `sync = masters` for the run, so the kit transplant is "
                         "exercised even though no tracked manual opts into it")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    if not os.path.exists(src):
        raise SystemExit(f"no such file: {src}")
    if args.n < 3:
        raise SystemExit("need at least 3 generations to see a fixpoint")

    tmp = tempfile.mkdtemp(prefix="reentrancy-")
    try:
        # a self-contained manual directory, so the real manuals/ tree is untouched
        sub = os.path.join(tmp, "submissions")
        os.makedirs(sub)
        conf = args.config or next(
            (os.path.join(os.path.dirname(os.path.dirname(src)), f)
             for f in os.listdir(os.path.dirname(os.path.dirname(src)))
             if f.endswith(".manual")), None)
        if conf:
            shutil.copy(conf, os.path.join(tmp, "t.manual"))
        if args.sync:
            # opting in here rather than in a tracked manual: syncing masters is a
            # decision about a real book, but the transplant still has to be proved
            # convergent, and this is the fixture that carries everything awkward
            with open(os.path.join(tmp, "t.manual"), "a", encoding="utf-8") as f:
                f.write("\nsync = masters\n")
        shutil.copy(src, os.path.join(sub, "g0.idml"))

        prints = []
        for i in range(args.n):
            print(f"\n=== generation {i + 1} ===")
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "build_manual.py"),
                 os.path.join(sub, f"g{i}.idml"), "--out", os.path.join(tmp, "out")]
                + (["--kit", os.path.abspath(args.kit)] if args.kit else []),
                text=True, capture_output=True)
            if r.returncode != 0:
                print(r.stdout[-4000:])
                print(r.stderr[-2000:], file=sys.stderr)
                raise SystemExit(f"generation {i + 1} failed to build")
            for line in r.stdout.splitlines():
                if re.search(r"normalis|purged|legacy clone|input carries|suppressed \d+ dead", line):
                    print("  " + line.strip())
            ready = os.path.join(tmp, "out", f"g{i}.ready.idml")
            shutil.copy(ready, os.path.join(sub, f"g{i + 1}.idml"))
            fp = fingerprint(ready)
            prints.append(fp)
            show(fp, f"gen {i + 1}")

        print()
        drift = 0
        for i in range(1, len(prints) - 1):
            d = diff(prints[i], prints[i + 1])
            if d:
                drift += 1
                print(f"DRIFT gen {i + 1} -> gen {i + 2}:")
                for line in d:
                    print("  " + line)
        if drift:
            print("\nNOT a fixpoint — the loop adds something it does not remove.")
            return 1
        print(f"converged: generations 2..{len(prints)} are structurally identical")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
