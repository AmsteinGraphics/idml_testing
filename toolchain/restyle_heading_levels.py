#!/usr/bin/env python3
"""Set the heading hierarchy: which paragraph styles are levels 1..N.

    restyle_heading_levels.py <build_dir> --levels titles:lvl1,titles:lvl2,... \
                              [--model titles:lvl2] [--dry-run]

`--levels` is the hierarchy top-down. Each style gets NumberingLevel = its
position and a NumberingExpression with that many places, so the last level of a
four-level list numbers x.x.x.x. A style in the list that doesn't exist yet is
created as a stylistic copy of `--model`: BasedOn the model with no visual
overrides of its own, so it looks identical and stays that way if the model is
restyled — override it later to make it diverge.

The DM32 kit shipped a three-level hierarchy (titles:lvl2/3/4 at levels 1/2/3,
lvl4 being the base style that carries the numbering list, lvl3 and lvl2 chained
onto it). Adding a level above means every existing level shifts down one.

    BEWARE: a document that does NOT use the new top level numbers with a leading
    zero — level 1's counter never advances, so a former "1.4.4" becomes "0.1.4.4".
    Adding a level to a shared kit is not backwards compatible; content written
    against the old hierarchy has to gain headings at the new top level.

Expression format matches what InDesign writes: "^1 ", "^1.^2 ", "^1.^2.^3 ", …
"""
import argparse
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manualconf

STYLE_RE = r'<ParagraphStyle\b[^>]*\bSelf="ParagraphStyle/%s"[^>]*?(?:/>|>.*?</ParagraphStyle>)'


def enc(name):
    return name.replace(":", "%3a")


def expression(level):
    return ".".join(f"^{i}" for i in range(1, level + 1)) + " "


def set_attr(tag, n, v):
    if re.search(rf'\b{n}="', tag):
        return re.sub(rf'\b{n}="[^"]*"', f'{n}="{v}"', tag)
    close = "/>" if tag.endswith("/>") else ">"
    return tag[:-len(close)] + f' {n}="{v}"' + close


def find(styles, name):
    return re.search(STYLE_RE % re.escape(enc(name)), styles, re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--levels",
                    help="comma-separated paragraph style names, top level first "
                         "(default: the manual config's numbered_styles)")
    ap.add_argument("--unnumbered", default="",
                    help="comma-separated styles to REMOVE from numbering "
                         "(default: the config's levels above number_from)")
    ap.add_argument("--config", help="explicit <product>.manual path")
    ap.add_argument("--model", help="style to copy when creating a missing one "
                                    "(default: the first level that already exists)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    unnumbered = [s.strip() for s in args.unnumbered.split(",") if s.strip()]
    if args.levels:
        levels = [s.strip() for s in args.levels.split(",") if s.strip()]
    else:
        conf = manualconf.load(args.build, args.config)
        levels = conf["numbered_styles"]
        if not levels:
            print("manual config declares no number_from — leaving the document's "
                  "own hierarchy alone")
            return 0
        unnumbered = unnumbered or conf["unnumbered_styles"]
    if not levels:
        raise SystemExit("--levels is empty")

    path = os.path.join(args.build, "Resources", "Styles.xml")
    styles = open(path, encoding="utf-8").read()

    model = args.model or next((n for n in levels if find(styles, n)), None)
    if model is None or not find(styles, model):
        raise SystemExit(f"model style {model!r} not found — nothing to copy from")

    created, changed = [], []
    for i, name in enumerate(levels, start=1):
        m = find(styles, name)
        if not m:
            mm = find(styles, model)
            block = (
                f'<ParagraphStyle Self="ParagraphStyle/{enc(name)}" Name="{name}" '
                f'Imported="false" NextStyle="ParagraphStyle/{enc(name)}" '
                f'SplitDocument="false" EmitCss="true" '
                f'StyleUniqueId="{uuid.uuid4()}" IncludeClass="true" '
                f'ExtendedKeyboardShortcut="0 0 0" EpubAriaRole="" '
                f'EmptyNestedStyles="true" EmptyLineStyles="true" '
                f'EmptyGrepStyles="true" KeyboardShortcut="0 0" '
                f'NumberingLevel="{i}" NumberingExpression="{expression(i)}">\n'
                f'\t\t\t\t<Properties>\n'
                f'\t\t\t\t\t<BasedOn type="object">ParagraphStyle/{enc(model)}</BasedOn>\n'
                f'\t\t\t\t\t<PreviewColor type="enumeration">Nothing</PreviewColor>\n'
                f'\t\t\t\t</Properties>\n'
                f'\t\t\t</ParagraphStyle>')
            # insert as the model's sibling so it lands in the same style group
            styles = styles[:mm.end()] + "\n\t\t\t" + block + styles[mm.end():]
            created.append((name, i))
            continue
        tag = re.match(r'<ParagraphStyle\b[^>]*?(?:/>|>)', m.group(0)).group(0)
        new = set_attr(set_attr(tag, "NumberingLevel", i),
                       "NumberingExpression", expression(i))
        if new != tag:
            old_lvl = re.search(r'\bNumberingLevel="([^"]*)"', tag)
            changed.append((name, old_lvl.group(1) if old_lvl else "-", i))
            styles = styles[:m.start()] + new + m.group(0)[len(tag):] + styles[m.end():]

    # Take the label levels OUT of the numbering. A level that stays in the list
    # keeps advancing its counter and prefixing its own number; removing it is what
    # makes the level below run straight through instead of restarting under it.
    detached = []
    for name in unnumbered:
        m = find(styles, name)
        if not m:
            continue
        blk = m.group(0)
        tag = re.match(r'<ParagraphStyle\b[^>]*?(?:/>|>)', blk).group(0)
        new = re.sub(r'\s*\bNumbering(?:Level|Expression)="[^"]*"', "", tag)
        new = re.sub(r'\s*\bBulletsAndNumberingListType="[^"]*"', "", new)
        body = re.sub(r'[ \t]*<AppliedNumberingList\b[^>]*>.*?</AppliedNumberingList>\s*\n?',
                      "", blk[len(tag):], flags=re.S)
        if new + body != blk:
            styles = styles[:m.start()] + new + body + styles[m.end():]
            detached.append(name)

    for name, lvl in created:
        print(f"created {name:16s} level {lvl}  expression {expression(lvl)!r}  "
              f"(stylistic copy of {model})")
    for name, was, now in changed:
        print(f"moved   {name:16s} level {was} -> {now}  expression {expression(now)!r}")
    for name in detached:
        print(f"unnumber {name:16s} removed from the numbered list (label only)")
    if not created and not changed and not detached:
        print("hierarchy already matches — nothing to do")
    if args.dry_run:
        print("(dry-run: nothing written)")
        return 0
    if created or changed or detached:
        open(path, "w", encoding="utf-8").write(styles)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
