#!/usr/bin/env python3
"""Turn plain-text key markup into real SwissKeys character styles.

    apply_key_markup.py <build_dir> [--dry-run] [--map FILE]

Authors pour content in InDesign typing `[EXIT]`, `<ACOS>`, `{ALL}`; this turns
each into the character style the design system actually uses, so nobody hand-
applies `btn_normal` or `lcd_sk`.

    author types        content produced      style
    [EXIT]  [9]         <EXIT>  <9>           btn_normal        (guillemets added)
    [[A]]               <A>                   letter_normal     (guillemets added)
    <ACOS>              ACOS                  btn_or            (shift 1, bare)
    <2:NAME>            NAME                  btn_bl            (shift 2, bare)
    <>                  <    >                shift_orange      (the shift KEY)
    <2:>                <    >                shift_blue        (2nd shift key)
    {ALL}  {1 2/3}      verbatim              lcd_sk            (bare)
    {^...} {/...}       verbatim              lcd_sk_high / _slant
    {^/...}             verbatim              lcd_sk_slant_high
    \\[  \\<  \\{  \\\\ literal character     no_markup

FORWARD ONLY, AND IDEMPOTENT. There is no reverse transform and normalize_input
does not undo this. Markup is write-once: you type it, it renders, and it stays
rendered. Running this again finds no markup in an already-rendered run, so
f(f(x)) = f(x) and the pipeline stays re-entrant without anything converting
back. That matters because markup does not occupy the same space as the final
fonts -- round-tripping it would disturb the layout on every pass.

Two things make idempotence real rather than hopeful:

  * A run already carrying one of the SwissKeys styles is never looked inside, so
    a rendered `<EXIT>` cannot be re-matched.
  * An ESCAPED literal is emitted carrying `no_markup`. Without it, `\\[EXIT\\]`
    would render to the plain text `[EXIT]` and the NEXT run would turn it into a
    button -- the one case where forward-only would not converge.

THREE DELIMITER CONVENTIONS, not one (measured across v1.76, see the notes in
docs/handoff/memory/swisskeys-encoding.md): guillemets belong to the negative
button font and the letters font; the Gintronic annunciator styles are padded
with NBSP; everything else -- shifted buttons, all LCD, program listings --
carries bare content. Inserting guillemets everywhere would be wrong on ~900 runs.

WHAT IS NOT COVERED YET: `lcd_normal` and `lcd_table` (the NBSP-padded
annunciators and soft-menu labels) have no agreed markup, so nothing emits them.
The delimiter rule for them is encoded below, ready for whatever syntax is
chosen. Nothing has been poured with this yet, so the syntax is still cheap to
change; once content exists it is not.
"""
import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_MAP = os.path.join(HERE, "..", "kit", "swisskeys.map")

# Without this, ElementTree reserialises every story with `ns0:` in place of
# `idPkg:` -- still valid XML, but no longer the shape InDesign wrote or the
# shape the rest of this toolchain matches on.
PKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", PKG)

# markup kind -> character style that renders it
TARGET = {
    "btn":    "btn_normal",
    "letter": "letter_normal",
    "shift1": "btn_or",              # becomes btn_shift1 when the kit renames them
    "shift2": "btn_bl",              # ... and btn_shift2, colour from config
    "lcd":    "code_styles:lcd_sk",
    "lcd_h":  "code_styles:lcd_sk_high",
    "lcd_s":  "code_styles:lcd_sk_slant",
    "lcd_sh": "code_styles:lcd_sk_slant_high",
}
NO_MARKUP = "no_markup"

# what wraps the content, per style. Anything absent here is bare.
NBSP = "\u00a0"
DELIMITERS = {
    "btn_normal":             ("\u2039", "\u203a"),
    "letter_normal":          ("\u2039", "\u203a"),
    "code_styles:lcd_normal": (NBSP, NBSP),     # not emitted yet -- no syntax agreed
    "code_styles:lcd_table":  (NBSP, NBSP),     # ditto
}

# Paragraph styles whose content is never markup. A program listing is verbatim
# machine text: brackets and braces in it are the program's, not an author's.
SKIP_PARAGRAPH = {"prgm_listing", "statefile_listing_var2"}

# A run already wearing any SwissKeys-family style is finished work. This is what
# makes the transform idempotent, so it is deliberately broad.
ALREADY_STYLED = re.compile(
    r"^(?:btn|letter_normal|shift_|no_markup|code_styles%3a(?:lcd|code)_?)", re.I)

# Content that would swallow a sentence is much more likely to be prose than
# markup ("[see the note on page 4]"), so a token is bounded and never spans lines.
MAX_TOKEN = 40

TOKEN = re.compile(r"""
      \\(?P<esc>[\[\]<>{}\\])                       # escaped literal
    | \[\[(?P<letter>[^\[\]\n]{1,%(n)d})\]\]        # letter key
    | \[(?P<btn>[^\[\]\n]{1,%(n)d})\]               # button
    | <(?P<sn>[2-9]):(?P<stxt>[^<>\s\n]{0,%(n)d})>  # indexed shift; <2:> is its key
    | <(?P<shift1>[^<>:\s\n]{0,%(n)d})>             # shift 1; <> is the shift key
    | \{\^/(?P<lcd_sh>[^{}\n]{0,%(n)d})\}           # LCD slanted + highlighted
    | \{\^(?P<lcd_h>[^{}\n]{0,%(n)d})\}             # LCD highlighted
    | \{/(?P<lcd_s>[^{}\n]{0,%(n)d})\}              # LCD slanted
    | \{(?P<lcd>[^{}\n]{0,%(n)d})\}                 # LCD
""" % {"n": MAX_TOKEN}, re.X)

TRIGGER = re.compile(r"[\[\]<>{}\\]")


def encode(style):
    """`code_styles:lcd_sk` -> the URL-escaped form IDML uses in attributes."""
    return style.replace(":", "%3a")


def decode(sid):
    return sid.replace("CharacterStyle/", "").replace("%3a", ":")


# --------------------------------------------------------------------------- #
# glyph map
# --------------------------------------------------------------------------- #
def load_map(build, explicit=None):
    """`NAME = glyph` lines. Unmapped names pass through, so `[EXIT]` needs none.

    Discovery walks outward exactly like the .manual config: a map beside the
    build dir, then any *.map in the manual's directory, then the kit's.
    """
    paths = [explicit] if explicit else [
        build.rstrip("/") + ".map",
        *sorted(glob.glob(os.path.join(os.path.dirname(build.rstrip("/")) or ".", "*.map"))),
        KIT_MAP,
    ]
    for p in paths:
        if p and os.path.exists(p):
            table = {}
            for n, raw in enumerate(open(p, encoding="utf-8"), start=1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                if "=" not in line:
                    raise SystemExit(f"{p}:{n}: expected `NAME = glyph`, got {line!r}")
                k, v = (s.strip() for s in line.split("=", 1))
                table[k] = unescape_codepoints(v)
            return table, p
    return {}, None


def unescape_codepoints(value):
    """Allow `U+2009` for characters that are invisible in a text editor.

    A literal thin space in the map file is indistinguishable from a stray one,
    and the first person to tidy the whitespace would silently delete it.
    """
    if not re.fullmatch(r"(?:U\+[0-9A-Fa-f]{4,6}\s*)+", value or ""):
        return value
    return "".join(chr(int(c[2:], 16)) for c in value.split())


# --------------------------------------------------------------------------- #
# the document's own styles decide what can be rendered
# --------------------------------------------------------------------------- #
def available_styles(build):
    p = os.path.join(build, "Resources", "Styles.xml")
    raw = open(p, encoding="utf-8").read()
    return {decode(m) for m in re.findall(r'<CharacterStyle\b[^>]*Self="CharacterStyle/([^"]+)"', raw)}


# --------------------------------------------------------------------------- #
# rendering one token
# --------------------------------------------------------------------------- #
# `<>` is the shift KEY itself, not a function printed above one. v1.76 builds it
# as an EMPTY BUTTON in the shift colour: the two guillemets with four spaces
# between them, the whole run styled shift_orange / shift_blue. The space glyph in
# the button font IS the key body, so four of them give a blank key of that width
# -- which is why this is spaces and not some dedicated symbol. Verified against
# v1.76: U+2039 U+0020 x4 U+203A, 5 orange and 8 blue occurrences, no variants.
SHIFT_KEY_STYLE = {"shift1": "shift_orange", "shift2": "shift_blue"}
SHIFT_KEY_CONTENT = "‹" + " " * 4 + "›"


def shift_symbol_name(kind):
    """Map entry that can override the default blank key, e.g. a wider one."""
    n = kind[len("shift"):]
    return "SHIFT" if n == "1" else "SHIFT" + n


def render(kind, text, glyphs):
    """(style, content) for a matched token; content None if it cannot be built."""
    if kind.startswith("shift") and text == "":
        style = SHIFT_KEY_STYLE.get(kind)
        if style is None:
            return None, None                  # no shift-key style for that index
        return style, glyphs.get(shift_symbol_name(kind), SHIFT_KEY_CONTENT)

    style = TARGET[kind]
    # the glyph table maps KEY NAMES, so it applies to buttons and shifted keys.
    # LCD content is verbatim display text and is never looked up.
    if kind in ("btn", "letter", "shift1", "shift2"):
        text = glyphs.get(text, text)
    lo, hi = DELIMITERS.get(style, ("", ""))
    return style, f"{lo}{text}{hi}"


def classify(m):
    """(kind, text) for a TOKEN match, or ('escape', char)."""
    g = m.groupdict()
    if g["esc"] is not None:
        return "escape", g["esc"]
    for kind, key in (("letter", "letter"), ("btn", "btn"), ("lcd_sh", "lcd_sh"),
                      ("lcd_h", "lcd_h"), ("lcd_s", "lcd_s"), ("lcd", "lcd")):
        if g[key] is not None:
            return kind, g[key]
    if g["sn"] is not None:
        return f"shift{g['sn']}", g["stxt"]
    if g["shift1"] is not None:
        return "shift1", g["shift1"]
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- #
# story surgery
# --------------------------------------------------------------------------- #
def csr_text(csr):
    return "".join(c.text or "" for c in csr if c.tag == "Content")


def only_content(csr):
    """True if the run holds nothing but text -- the safe case for merging."""
    return all(ch.tag == "Content" for ch in csr) and len(csr) > 0


def splittable(csr):
    """True if this run can be cut into several without losing anything.

    A line break is fine: it is a sibling of the text, it survives being carried
    into whichever piece it followed, and no token can span it anyway. A
    HyperlinkTextSource, CrossReferenceSource or anchored TextFrame is NOT fine --
    splitting a range that carries one is precisely how the margin-box work broke,
    and a button is not worth that risk, so those runs are left alone.

    Requiring pure text here was too strict and was the first thing to fail on
    real content: InDesign puts `<Content>` and `<Br/>` in the same run constantly,
    so an author's paragraph ending in a line break was skipped entirely.
    """
    return len(csr) > 0 and all(ch.tag in ("Content", "Br") for ch in csr)


def rebuild(csr, segments):
    """Turn a segment list back into a run sequence.

    Plain text and line breaks accumulate into clones of the original run, so
    everything it carried is preserved; each rendered token becomes its own run.
    """
    out, cur = [], None
    for seg in segments:
        if seg[0] == "run":
            if cur is not None and len(cur):
                out.append(cur)
            cur = None
            out.append(new_run(csr, seg[1], seg[2]))
            continue
        if cur is None:
            cur = ET.Element(csr.tag, dict(csr.attrib))
        if seg[0] == "text":
            if seg[1]:
                ET.SubElement(cur, "Content").text = seg[1]
        else:                                   # a Br or other passenger element
            cur.append(seg[1])
    if cur is not None and len(cur):
        out.append(cur)
    return out


def merge_runs(psr):
    """Collapse adjacent identical-attribute text runs, and their Content nodes.

    InDesign splits a range for its own reasons -- a language boundary or a
    spell-check artefact is enough -- and v1.76 shows real buttons stored as three
    consecutive runs (`<`, `E`, `>`). Typed markup lands the same way, so `[EXIT]`
    can arrive as `[EX` + `IT]` and a per-run match would miss it. Merging first
    is semantically a no-op: same attributes, same order, same text.
    """
    kids = list(psr)
    i = 0
    while i < len(kids) - 1:
        a, b = kids[i], kids[i + 1]
        if (a.tag == b.tag == "CharacterStyleRange" and a.attrib == b.attrib
                and only_content(a) and only_content(b)):
            for ch in list(b):
                a.append(ch)
            psr.remove(b)
            kids.pop(i + 1)
            continue
        i += 1
    # one Content per run, so a token cannot straddle two text nodes
    for csr in psr:
        if csr.tag != "CharacterStyleRange" or not only_content(csr):
            continue
        text = csr_text(csr)
        for ch in list(csr)[1:]:
            csr.remove(ch)
        if len(csr):
            csr[0].text = text


def new_run(model, style, content):
    """A run in InDesign's own shape: the style, and nothing else.

    v1.76's button runs carry AppliedCharacterStyle and at most a ligature switch;
    they do not inherit the surrounding run's local overrides, and they should not
    -- the whole point is that the character style decides the appearance.
    """
    csr = ET.Element("CharacterStyleRange",
                     {"AppliedCharacterStyle": "CharacterStyle/" + encode(style)})
    lang = model.get("AppliedLanguage")
    if lang:
        csr.set("AppliedLanguage", lang)
    c = ET.SubElement(csr, "Content")
    c.text = content
    return csr


def transform_story(path, glyphs, have, stats, problems, dry_run=False):
    raw = open(path, encoding="utf-8").read()
    if not TRIGGER.search(raw):
        return False                                   # fast path: most stories
    head = raw[:raw.index("<idPkg:Story")] if "<idPkg:Story" in raw else ""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        problems.append(f"{os.path.basename(path)}: unparseable ({e})")
        return False

    changed = False
    # Every CharacterStyleRange is a direct child of exactly one ParagraphStyleRange,
    # so visiting PSRs and taking their direct children reaches each run ONCE. Table
    # cells nest a PSR inside a PSR, and a walk that recurses into runs would process
    # cell content twice -- that is what inflated the survey's counts.
    for psr in root.iter("ParagraphStyleRange"):
        pstyle = decode(psr.get("AppliedParagraphStyle", "")).replace("ParagraphStyle/", "")
        if pstyle in SKIP_PARAGRAPH:
            continue
        if not TRIGGER.search("".join(csr_text(c) for c in psr
                                     if c.tag == "CharacterStyleRange")):
            continue
        merge_runs(psr)

        for csr in list(psr):
            if csr.tag != "CharacterStyleRange" or not splittable(csr):
                continue
            sid = csr.get("AppliedCharacterStyle", "").replace("CharacterStyle/", "")
            if ALREADY_STYLED.match(sid):
                continue                               # finished work, never re-entered
            if not TOKEN.search(csr_text(csr)):
                continue

            # Each Content node is walked on its own: a token cannot span a line
            # break, and everything that is not text rides along untouched.
            segments, rendered_any = [], False
            for child in list(csr):
                if child.tag != "Content":
                    segments.append(("elem", child))
                    continue
                text = child.text or ""
                pos = 0
                for m in TOKEN.finditer(text):
                    kind, body = classify(m)
                    if kind == "escape":
                        style, content = NO_MARKUP, body
                    elif kind not in TARGET:
                        problems.append(
                            f"{m.group(0)!r} asks for shift {kind[5:]}, which has no style")
                        continue                       # left as literal text below
                    else:
                        style, content = render(kind, body, glyphs)
                    if style is None or content is None:
                        problems.append(f"{m.group(0)!r} could not be built")
                        continue                       # left as literal text below
                    if style not in have:
                        problems.append(
                            f"{m.group(0)!r} needs character style {style!r}, which this "
                            f"document does not have"
                            + (" -- add `sync = styles` to the manual config"
                               if style != NO_MARKUP else
                               " -- the kit defines it; sync styles or add it by hand"))
                        continue                       # ditto: never silently dropped
                    if m.start() > pos:
                        segments.append(("text", text[pos:m.start()]))
                    segments.append(("run", style, content))
                    stats[kind] = stats.get(kind, 0) + 1
                    rendered_any = True
                    pos = m.end()
                if pos < len(text):
                    segments.append(("text", text[pos:]))
            if not rendered_any:
                continue

            idx = list(psr).index(csr)
            psr.remove(csr)
            for off, el in enumerate(rebuild(csr, segments)):
                psr.insert(idx + off, el)
            changed = True

    if changed and not dry_run:
        open(path, "w", encoding="utf-8").write(head + ET.tostring(root, encoding="unicode"))
    return changed


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--map", help="glyph table (default: outward search, then kit)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    glyphs, map_path = load_map(args.build, args.map)
    have = available_styles(args.build)
    stats, problems, touched = {}, [], 0

    for p in sorted(glob.glob(os.path.join(args.build, "Stories", "*.xml"))):
        if transform_story(p, glyphs, have, stats, problems, args.dry_run):
            touched += 1

    print(f"glyph map  : {os.path.relpath(map_path) if map_path else 'none found'} "
          f"({len(glyphs)} entr{'y' if len(glyphs) == 1 else 'ies'})")
    print(f"stories    : {touched} {'would change' if args.dry_run else 'changed'}")
    total = sum(stats.values())
    if total:
        print("rendered   : " + ", ".join(f"{k} x{v}" for k, v in sorted(stats.items())))
    else:
        print("rendered   : nothing -- no key markup found")
    print(f"tokens     : {total}")

    if problems:
        # de-duplicate: one missing style produces the same line hundreds of times
        seen, uniq = set(), []
        for p in problems:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        print(f"\nPROBLEMS ({len(problems)}, {len(uniq)} distinct):")
        for p in uniq[:20]:
            print("  -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
