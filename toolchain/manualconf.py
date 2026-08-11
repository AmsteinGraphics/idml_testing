#!/usr/bin/env python3
"""Per-manual configuration: `<product>.manual`, next to the build directory.

One file for the decisions that belong to a manual rather than to the kit or the
toolchain. Lives beside the build dir, never inside it, so it is not packed into
the .idml. Discovery walks outward: `<build>.manual`, then any `*.manual` in the
build's parent (manuals/<product>/<product>.manual), then the kit's default.

    # Sanctioned palette — Black plus up to three spots, Black mandatory.
    swatch = Black
    swatch = PANTONE 292 U

    # How many of titles:lvl1..lvl4 this manual uses, counting from the top.
    levels = 4

    # Which heading level carries a thumb tab and an InDesign section.
    tab_level = 2

    # The first level that takes part in numbering. Levels above it are unnumbered
    # labels, so the level below counts straight through them rather than
    # restarting: Part 1 ends at section 4, Part 2 opens at section 5.
    number_from = 2

    # Tab-strip ink ramp, top of the strip to the bottom. A bare ink name is that
    # ink at 100%; mixes are "PANTONE 292 U 60%, Black 40%".
    tab_stop = PANTONE 292 U
    tab_stop = Black

`key = value`, `#` comments, blank lines ignored. `swatch` and `tab_stop` repeat.

WHY tab_level EXISTS: the tab level cannot be inferred. DM42n has 5 lvl1 parts and
23 lvl2 sections, and the tabs belong on lvl2 — taking the topmost level would
give 5 tabs. It is an editorial decision, so it is declared.

WHY levels EXISTS: not to fix numbering — content that starts at lvl1 already
numbers correctly, since the counters start at the top. It is a declaration the
validator enforces, catching content that SKIPS the top level (which is what
produces a leading zero: "0.1.4") or uses a level deeper than the manual claims.

Both are optional. With neither, the toolchain falls back to reading the document:
the chapter level becomes the shallowest heading present, and numbering depth
comes from the document's own styles.
"""
import glob
import os
import re

KIT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "kit", "manual_kit.manual")

# What `sync = ...` accepts. See sync_from_kit.py.
SYNCABLE = {"masters", "styles", "swatches"}

# What `tab_shows = ...` accepts.
#
#   chapter_digit     the chapter's ordinal, baked into the master by apply_tabs.
#                     One number per chapter, identical on every page of it.
#   paragraph_number  the running section number of the last numbered heading that
#                     begins on or before the page -- "2.3.2", dropping to "2.3"
#                     on a page that has not reached a lvl4 yet. It varies per
#                     page, so it CANNOT live on the chapter master and cannot be
#                     computed here: what is visible on a page is known only once
#                     InDesign has composed the text. apply_tabs leaves the frame
#                     empty and place_tab_numbers.jsx fills it.
TAB_SHOWS = {"chapter_digit", "paragraph_number"}


def candidates(build, suffix=".manual"):
    b = build.rstrip("/")
    parent = os.path.dirname(b) or "."
    return [b + suffix] + sorted(glob.glob(os.path.join(parent, "*" + suffix))) + \
           [os.path.splitext(KIT_DEFAULT)[0] + suffix]


def parse_stop(value, where):
    """One tab-strip gradient stop: {ink name: percentage}.

    `PANTONE 292 U` is that ink at 100%; `PANTONE 292 U 60%, Black 40%` is a mix.
    Naming the inks inline replaces the old tabstops.csv, where percentages were
    positional under a header row and silently wrong if the columns were reordered.
    Percentages are per-ink and independent — they need not sum to 100.
    """
    mix = {}
    for term in value.split(","):
        term = term.strip()
        if not term:
            continue
        m = re.match(r'^(.*?)\s+(\d+(?:\.\d+)?)\s*%$', term)
        name, pct = (m.group(1).strip(), float(m.group(2))) if m else (term, 100.0)
        if not name:
            raise SystemExit(f"{where}: tab_stop term {term!r} has no ink name")
        if not 0 <= pct <= 100:
            raise SystemExit(f"{where}: {name} at {pct}% is outside 0..100")
        mix[name] = mix.get(name, 0.0) + pct
    if not mix:
        raise SystemExit(f"{where}: empty tab_stop")
    return mix


def load(build, explicit=None):
    """{swatches, levels, tab_level, tab_stops, chapter_style, heading_styles, path}."""
    conf = dict(swatches=[], levels=None, tab_level=None, number_from=None,
                tab_stops=[], sync=[], tab_shows="chapter_digit", path=None)

    path = explicit
    if path and not os.path.exists(path):
        raise SystemExit(f"config not found: {path}")
    if not path:
        path = next((p for p in candidates(build) if os.path.exists(p)), None)

    if path:
        conf["path"] = path
        for n, raw in enumerate(open(path, encoding="utf-8"), start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise SystemExit(f"{path}:{n}: expected `key = value`, got {line!r}")
            k, v = (s.strip() for s in line.split("=", 1))
            if k == "swatch":
                conf["swatches"].append(v)
            elif k == "tab_stop":
                conf["tab_stops"].append(parse_stop(v, f"{path}:{n}"))
            elif k in ("levels", "tab_level", "number_from"):
                if not v.isdigit():
                    raise SystemExit(f"{path}:{n}: {k} must be a number, got {v!r}")
                conf[k] = int(v)
            elif k == "tab_shows":
                if v not in TAB_SHOWS:
                    raise SystemExit(f"{path}:{n}: tab_shows {v!r} is not one of "
                                     f"{', '.join(sorted(TAB_SHOWS))}")
                conf["tab_shows"] = v
            elif k == "sync":
                # Which parts of the kit are authoritative for this manual, i.e.
                # re-transplanted on every build so a kit change reaches it. Opt-in:
                # a document owns a private copy of the whole design system, and
                # overwriting it is not something to do to a manual by surprise.
                for part in (x.strip() for x in v.split(",")):
                    if not part:
                        continue
                    if part not in SYNCABLE:
                        raise SystemExit(f"{path}:{n}: sync {part!r} is not one of "
                                         f"{', '.join(sorted(SYNCABLE))}")
                    if part not in conf["sync"]:
                        conf["sync"].append(part)
            else:
                raise SystemExit(f"{path}:{n}: unknown key {k!r} "
                                 f"(expected swatch, tab_stop, levels, tab_level, "
                                 f"number_from, tab_shows, sync)")
    else:
        # a pre-consolidation manual may still carry the palette on its own
        legacy = next((p for p in candidates(build, ".swatches") if os.path.exists(p)), None)
        if legacy:
            conf["path"] = legacy
            for raw in open(legacy, encoding="utf-8"):
                s = raw.split("#", 1)[0].strip()
                if s:
                    conf["swatches"].append(s)

    lv, tab, nf = conf["levels"], conf["tab_level"], conf["number_from"]
    if lv is not None and not 1 <= lv <= 4:
        raise SystemExit(f"{conf['path']}: levels must be 1..4, got {lv}")
    if tab is not None:
        if tab < 1:
            raise SystemExit(f"{conf['path']}: tab_level must be >= 1, got {tab}")
        if lv is not None and tab > lv:
            raise SystemExit(f"{conf['path']}: tab_level {tab} is deeper than the "
                             f"{lv} level(s) this manual declares")

    if nf is not None:
        if nf < 1:
            raise SystemExit(f"{conf['path']}: number_from must be >= 1, got {nf}")
        if lv is not None and nf > lv:
            raise SystemExit(f"{conf['path']}: number_from {nf} is deeper than the "
                             f"{lv} level(s) this manual declares")

    conf["heading_styles"] = [f"titles:lvl{i}" for i in range(1, (lv or 4) + 1)]
    conf["chapter_style"] = f"titles:lvl{tab}" if tab else None
    # Levels above number_from are unnumbered labels — "Part 1: Getting Started" —
    # and take no part in the counting, so sections run straight through the parts
    # instead of restarting inside each one.
    conf["numbered_styles"] = conf["heading_styles"][(nf - 1):] if nf else None
    conf["unnumbered_styles"] = conf["heading_styles"][:(nf - 1)] if nf else []
    return conf
