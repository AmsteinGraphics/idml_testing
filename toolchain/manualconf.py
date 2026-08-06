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

`key = value`, `#` comments, blank lines ignored. `swatch` may repeat.

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

KIT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "kit", "manual_kit.manual")


def candidates(build, suffix=".manual"):
    b = build.rstrip("/")
    parent = os.path.dirname(b) or "."
    return [b + suffix] + sorted(glob.glob(os.path.join(parent, "*" + suffix))) + \
           [os.path.splitext(KIT_DEFAULT)[0] + suffix]


def load(build, explicit=None):
    """{swatches, levels, tab_level, chapter_style, heading_styles, path}."""
    conf = dict(swatches=[], levels=None, tab_level=None, path=None)

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
            elif k in ("levels", "tab_level"):
                if not v.isdigit():
                    raise SystemExit(f"{path}:{n}: {k} must be a number, got {v!r}")
                conf[k] = int(v)
            else:
                raise SystemExit(f"{path}:{n}: unknown key {k!r} "
                                 f"(expected swatch, levels, tab_level)")
    else:
        # a pre-consolidation manual may still carry the palette on its own
        legacy = next((p for p in candidates(build, ".swatches") if os.path.exists(p)), None)
        if legacy:
            conf["path"] = legacy
            for raw in open(legacy, encoding="utf-8"):
                s = raw.split("#", 1)[0].strip()
                if s:
                    conf["swatches"].append(s)

    lv, tab = conf["levels"], conf["tab_level"]
    if lv is not None and not 1 <= lv <= 4:
        raise SystemExit(f"{conf['path']}: levels must be 1..4, got {lv}")
    if tab is not None:
        if tab < 1:
            raise SystemExit(f"{conf['path']}: tab_level must be >= 1, got {tab}")
        if lv is not None and tab > lv:
            raise SystemExit(f"{conf['path']}: tab_level {tab} is deeper than the "
                             f"{lv} level(s) this manual declares")

    conf["heading_styles"] = [f"titles:lvl{i}" for i in range(1, (lv or 4) + 1)]
    conf["chapter_style"] = f"titles:lvl{tab}" if tab else None
    return conf
