#!/usr/bin/env python3
"""Take a finished manual back to submission state, so it can be built again.

    normalize_input.py <build_dir> [--dry-run]

The forward pipeline turns a submission into a manual. This is the inverse leg
that makes the pipeline RE-ENTRANT: run it on the toolchain's own output (with
or without an InDesign round-trip in between) and the forward stages then behave
exactly as they do on a fresh submission. That is what lets the book be refined
iteratively — edit the content in InDesign, export, feed it straight back.

Every forward stage falls into one of three groups, and only the third needs
anything doing here:

  ALREADY IDEMPOTENT — replace their own output wholesale, so a re-run converges
    on its own:
      standardize_kit          renames only what still carries the old prefix
      restyle_heading_levels   sets levels to the configured hierarchy
      fix_numbering            joins heading styles to manual_list
      sectionize               replaces the whole <Section> run in designmap
      configure_chapters       regenerates the strip and reconciles chapter masters
      apply_tabs               purges the previous S<k> master set before minting

  CONVERGENT BY DESIGN — not undone, and not meant to be:
      dead-link suppression    a link whose target isn't in this document had its
                               `link` style and HyperlinkTextSource removed; it is
                               plain text now and no later pass sees it again. The
                               audit log (<name>.xref_log.csv) is the record.

  NEEDS UNDOING — what this script removes:
      margin boxes             the JSX's anchored frames + margin stories + their
                               hyperlinks. build_xref_boxes/the JSX would otherwise
                               add a SECOND box beside every existing one.
      local underline overrides  InDesign splits a `link` range when it anchors an
                               object and leaves a stub carrying Underline*
                               formatting, which defeats the style's orange.
      orphaned hyperlinks      <Hyperlink> entries in designmap whose Source no
                               longer exists in any story.
      legacy duplicate masters InDesign de-duplicates masters that shared an
                               identity (NamePrefix+BaseName) by renaming them —
                               `A-BaseTabs`, `D-BaseTabs` beside `BT-BaseTabs`.
                               Those are chapter masters from a pre-fix build; they
                               no longer answer to the S<k> naming apply_tabs
                               purges, so they are purged here by identity instead.

build_manual.py runs this automatically when it detects a processed input, so
normally you never call it directly.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

BOX_OBJSTYLE = "ObjectStyle/cross_ref_block"
# the kit's own masters, by BaseName. Anything else sharing one of these
# BaseNames is a clone InDesign renamed on import, not a kit master.
KIT_BASENAMES = {"Base", "BaseTabs", "NavTabs", "Contents", "Index", "Notes",
                 "Parent", "Section"}
KIT_MASTER_NAMES = {"B-Base", "BT-BaseTabs", "NT-NavTabs", "C-Contents", "I-Index",
                    "N-Notes", "A-Parent", "Sx-Section"}


def _read(p):
    return open(p, encoding="utf-8").read()


def masters(build):
    """[{path, self, name, prefix, base}] for every master in the tree."""
    out = []
    for f in sorted(glob.glob(os.path.join(build, "MasterSpreads", "*.xml"))):
        m = re.search(r"<MasterSpread\b[^>]*>", _read(f))
        if not m:
            continue
        g = lambda a: (re.search(rf'\b{a}="([^"]*)"', m.group(0)) or [None, ""])[1]
        out.append(dict(path=f, self=g("Self"), name=g("Name"),
                        prefix=g("NamePrefix"), base=g("BaseName")))
    return out


def base_master_self(build):
    """Self id of B-Base — where pages go when their master is purged."""
    for m in masters(build):
        if m["name"] == "B-Base" or m["prefix"] == "B":
            return m["self"]
    return None


def legacy_clone_masters(build):
    """Masters that duplicate a kit master's BaseName without being it.

    A pre-fix build minted chapter masters that kept BaseTabs' NamePrefix and
    BaseName. InDesign 2026 rejects two masters with one identity, so on import
    it renames them — `A-BaseTabs`, `D-BaseTabs`. They are chapter masters, but
    apply_tabs.py purges by NamePrefix="S<k>" and no longer recognises them, so
    they would survive into the rebuilt document as extra tab masters (and make
    "the BaseTabs master" ambiguous for every tool that looks it up by name).
    """
    return [m for m in masters(build)
            if m["base"] in KIT_BASENAMES and m["name"] not in KIT_MASTER_NAMES]


def chapter_masters(build):
    return [m for m in masters(build) if re.fullmatch(r"S\d+", m["prefix"] or "")]


def purge_masters(build, selfs, repoint_to=None, dry_run=False):
    """Delete masters by Self id: file, their stories, designmap refs, StoryList.

    Anything still pointing at one is repointed to `repoint_to` (B-Base) — an
    AppliedMaster naming a master that no longer exists is a dangling reference,
    and InDesign will not open the document. Masters are searched as well as
    spreads: a master can be based on another master, and the clones a pre-fix
    build left behind are exactly the ones other masters inherit from.

    Shared with apply_tabs.py, which purges the previous S<k> set on every run so
    a re-run converges instead of minting a second set beside the first.
    """
    selfs = [s for s in selfs if s]
    if not selfs:
        return dict(masters=0, stories=0, repointed=0)
    by_self = {m["self"]: m for m in masters(build)}
    story_ids = set()
    for s in selfs:
        m = by_self.get(s)
        if not m:
            continue
        story_ids |= set(re.findall(r'ParentStory="([^"]+)"', _read(m["path"])))
    doomed = {m["path"] for m in (by_self.get(s) for s in selfs) if m}
    referrers = [p for p in glob.glob(os.path.join(build, "Spreads", "*.xml"))
                 + glob.glob(os.path.join(build, "MasterSpreads", "*.xml"))
                 if p not in doomed]
    repointed = 0
    if dry_run:
        for sp in referrers:
            sx = _read(sp)
            repointed += sum(sx.count(f'AppliedMaster="{s}"') for s in selfs)
        return dict(masters=len(selfs), stories=len(story_ids), repointed=repointed)

    for p in doomed:
        if os.path.exists(p):
            os.remove(p)
    for sid in story_ids:
        p = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(p):
            os.remove(p)

    if repoint_to:
        for sp in referrers:
            sx = _read(sp)
            new = sx
            for s in selfs:
                new = new.replace(f'AppliedMaster="{s}"', f'AppliedMaster="{repoint_to}"')
            if new != sx:
                repointed += sum(sx.count(f'AppliedMaster="{s}"') for s in selfs)
                open(sp, "w", encoding="utf-8").write(new)

    dmp = os.path.join(build, "designmap.xml")
    d = _read(dmp)
    for s in selfs:
        d = re.sub(r'[ \t]*<idPkg:MasterSpread\b[^>]*MasterSpread_%s\.xml"[^>]*/>\s*\n?'
                   % re.escape(s), "", d)
    for sid in story_ids:
        d = re.sub(r'[ \t]*<idPkg:Story\b[^>]*Story_%s\.xml"[^>]*/>\s*\n?'
                   % re.escape(sid), "", d)
    sl = re.search(r'StoryList="([^"]*)"', d)
    if sl:
        keep = [x for x in sl.group(1).split() if x not in story_ids]
        d = re.sub(r'StoryList="[^"]*"', 'StoryList="' + " ".join(keep) + '"', d, count=1)
    open(dmp, "w", encoding="utf-8").write(d)
    return dict(masters=len(selfs), stories=len(story_ids), repointed=repointed)


TAB_NUMBER_PARA = "ParagraphStyle/foot_and_tabs%3atab_right"


def tab_number_overrides(build):
    """[(spread path, frame story id)] for every page-level tab number.

    With `tab_shows = paragraph_number`, place_tab_numbers.jsx overrides the
    chapter master's tab frame on each page and writes that page's running
    number into it -- it has to, because one master serves a whole chapter while
    the number changes page by page.

    Those overrides are page content, not master content, so apply_tabs.py's
    purge of the previous S<k> master set does not touch them: they would survive
    into the rebuilt document carrying numbers computed for the OLD pagination,
    which is worse than carrying none. Detected by the frame's paragraph style,
    the same handle the JSX uses.
    """
    out = []
    for sp in sorted(glob.glob(os.path.join(build, "Spreads", "*.xml"))):
        sx = _read(sp)
        if "OverriddenPageItemProps" not in sx:
            continue
        for m in re.finditer(r'<TextFrame\b[^>]*>', sx):
            tag = m.group(0)
            if "OverriddenPageItemProps" not in tag:
                continue
            sid = re.search(r'ParentStory="([^"]+)"', tag)
            if not sid:
                continue
            story = os.path.join(build, "Stories", f"Story_{sid.group(1)}.xml")
            if os.path.exists(story) and TAB_NUMBER_PARA in _read(story):
                out.append((sp, sid.group(1)))
    return out


def drop_tab_number_overrides(build, dry_run=False):
    """Remove them: the frames, their stories, and their designmap registration."""
    hits = tab_number_overrides(build)
    if not hits or dry_run:
        return len(hits)
    by_spread = {}
    for sp, sid in hits:
        by_spread.setdefault(sp, []).append(sid)

    for sp, sids in by_spread.items():
        sx = _read(sp)
        for sid in sids:
            # the frame, whether it closes normally or is self-closed
            sx = re.sub(r'[ \t]*<TextFrame\b[^>]*ParentStory="%s"[^>]*>.*?</TextFrame>\s*\n?'
                        % re.escape(sid), "", sx, flags=re.S)
            sx = re.sub(r'[ \t]*<TextFrame\b[^>]*ParentStory="%s"[^>]*/>\s*\n?'
                        % re.escape(sid), "", sx)
        open(sp, "w", encoding="utf-8").write(sx)

    story_ids = {sid for _, sid in hits}
    for sid in story_ids:
        p = os.path.join(build, "Stories", f"Story_{sid}.xml")
        if os.path.exists(p):
            os.remove(p)

    dmp = os.path.join(build, "designmap.xml")
    d = _read(dmp)
    for sid in story_ids:
        d = re.sub(r'[ \t]*<idPkg:Story\b[^>]*Story_%s\.xml"[^>]*/>\s*\n?'
                   % re.escape(sid), "", d)
    sl = re.search(r'StoryList="([^"]*)"', d)
    if sl:
        keep = [x for x in sl.group(1).split() if x not in story_ids]
        d = re.sub(r'StoryList="[^"]*"', 'StoryList="' + " ".join(keep) + '"', d, count=1)
    open(dmp, "w", encoding="utf-8").write(d)
    return len(hits)


def drop_orphan_hyperlinks(build, dry_run=False):
    """Remove <Hyperlink> entries whose Source is in no story.

    InDesign leaves these behind when a source range is deleted, and
    validate_idml.py counts them as dangling references.
    """
    dmp = os.path.join(build, "designmap.xml")
    d = _read(dmp)
    live = set()
    for p in glob.glob(os.path.join(build, "Stories", "*.xml")):
        live |= set(re.findall(
            r'<(?:HyperlinkTextSource|CrossReferenceSource|HyperlinkPageItemSource)\b'
            r'[^>]*Self="([^"]+)"', _read(p)))
    dead = [s for s in re.findall(r'<Hyperlink\b[^>]*Source="([^"]+)"', d) if s not in live]
    if not dead or dry_run:
        return len(dead)
    ds = set(dead)
    d = re.sub(r'[ \t]*<Hyperlink\b[^>]*Source="([^"]+)"[^>]*>.*?</Hyperlink>\s*\n?',
               lambda m: "" if m.group(1) in ds else m.group(0), d, flags=re.S)
    d = re.sub(r'[ \t]*<Hyperlink\b[^>]*Source="([^"]+)"[^>]*/>\s*\n?',
               lambda m: "" if m.group(1) in ds else m.group(0), d)
    open(dmp, "w", encoding="utf-8").write(d)
    return len(dead)


# --------------------------------------------------------------------------- #
# Detection — what marks does this tree already carry?
# --------------------------------------------------------------------------- #
def detect(build):
    boxes = sum(_read(p).count(BOX_OBJSTYLE)
                for p in glob.glob(os.path.join(build, "Stories", "*.xml")))
    d = _read(os.path.join(build, "designmap.xml"))
    return dict(
        boxes=boxes,
        chapter_masters=len(chapter_masters(build)),
        legacy_masters=len(legacy_clone_masters(build)),
        sections=len(re.findall(r"<Section\b", d)),
        underlines=sum(1 for p in glob.glob(os.path.join(build, "Stories", "*.xml"))
                       if re.search(r'<CharacterStyleRange\b[^>]*\bUnderline', _read(p))),
        tab_numbers=len(tab_number_overrides(build)),
    )


def is_processed(build):
    """Has the forward pipeline (or the JSX) already run on this tree?

    Any one of these is conclusive: a submission comes out of the kit with no
    margin boxes, no per-chapter masters and a single default section.
    """
    m = detect(build)
    return bool(m["boxes"] or m["chapter_masters"] or m["legacy_masters"]
                or m["sections"] > 1 or m["tab_numbers"])


def describe(marks):
    bits = []
    if marks["boxes"]:
        bits.append(f'{marks["boxes"]} margin box(es)')
    if marks["chapter_masters"]:
        bits.append(f'{marks["chapter_masters"]} chapter master(s)')
    if marks["legacy_masters"]:
        bits.append(f'{marks["legacy_masters"]} legacy clone master(s)')
    if marks["sections"] > 1:
        bits.append(f'{marks["sections"]} sections')
    if marks["underlines"]:
        bits.append(f'local underlines in {marks["underlines"]} story file(s)')
    if marks.get("tab_numbers"):
        bits.append(f'{marks["tab_numbers"]} page tab number(s)')
    return ", ".join(bits) or "nothing"


# --------------------------------------------------------------------------- #
def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script), *map(str, args)]
    print(f"\n$ {script} {' '.join(map(str, args))}", flush=True)
    r = subprocess.run(cmd, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{script} failed (exit {r.returncode})")


def normalize(build, dry_run=False):
    marks = detect(build)
    print(f"input carries: {describe(marks)}")
    if not is_processed(build) and not marks["underlines"] and not marks["tab_numbers"]:
        print("already in submission state — nothing to undo")
        return marks

    # 1. margin boxes: frames, their margin stories, their hyperlinks. Must go
    #    before build_xref_boxes/the JSX runs again, which would otherwise place
    #    a second box beside each existing one.
    if marks["boxes"]:
        run("strip_xref_boxes.py", build, *(["--dry-run"] if dry_run else []))

    # 2. legacy clone masters, purged by identity rather than by S<k> name
    legacy = legacy_clone_masters(build)
    if legacy:
        for m in legacy:
            print(f"  legacy clone master {m['name']!r} (BaseName {m['base']!r}) -> purge")
        r = purge_masters(build, [m["self"] for m in legacy],
                          repoint_to=base_master_self(build), dry_run=dry_run)
        print(f"  {'would purge' if dry_run else 'purged'} {r['masters']} master(s), "
              f"{r['stories']} story(ies), repointing {r['repointed']} page(s) to B-Base")

    # 3. local underline overrides left by InDesign anchoring the boxes
    run("fix_underlines.py", build, *(["--dry-run"] if dry_run else []))

    # 4. hyperlinks whose source no longer exists
    n = drop_orphan_hyperlinks(build, dry_run=dry_run)
    if n:
        print(f"  {'would drop' if dry_run else 'dropped'} {n} orphaned hyperlink(s)")

    # 5. per-page tab numbers the JSX placed. They were computed against the OLD
    #    pagination, and the forward leg cannot correct them -- only InDesign can,
    #    by running place_tab_numbers.jsx again on the rebuilt document.
    n = drop_tab_number_overrides(build, dry_run=dry_run)
    if n:
        print(f"  {'would drop' if dry_run else 'dropped'} {n} page tab number(s) "
              f"— re-run place_tab_numbers.jsx after opening the rebuilt file")

    if not dry_run:
        left = detect(build)
        # Sections and chapter masters are left standing on purpose: sectionize.py
        # replaces the whole <Section> run and apply_tabs.py purges the previous
        # S<k> set before minting its own, so removing them here would be work the
        # forward leg immediately redoes.
        print(f"\nnormalised. Left for the forward leg to replace: "
              f"{describe(dict(left, boxes=0, legacy_masters=0, underlines=0))}")
    return marks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--detect", action="store_true",
                    help="report what the tree carries and exit (0 = submission state)")
    args = ap.parse_args()

    if args.detect:
        marks = detect(args.build)
        print(describe(marks))
        return 1 if is_processed(args.build) else 0
    normalize(args.build, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
