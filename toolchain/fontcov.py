#!/usr/bin/env python3
"""Which characters can a font actually print?

    fontcov.py [build_dir]      # report what is installed and what is missing

IDML records font NAMES, never coverage, so a character the font has no glyph for
looks perfectly fine in the XML and prints as a blank or a substitute. That is not
hypothetical here: v1.76 carries 27 x U+FFFD inside `btn_bl`, a glyph that was
lost before this repo existed, and those buttons print something wrong today.

It matters more now for two reasons. Key markup lets an author name a glyph
(`[SIGMA]`) and get it inserted automatically, so a wrong or unmapped name turns
into a missing glyph rather than a typing mistake somebody notices. And
`lcd_normal` is on Gintronic while the real LCD styles are on SwissKeys Raster;
if that font is ever swapped, every character in those runs has to exist in the
new font, and nothing else would tell you which ones don't.

The font files are the only source of truth, so this parses them: the sfnt table
directory, the `name` table for the family, and `cmap` for the character map
(format 4 and format 12, which is everything modern). Standard library only.

DEGRADES ON PURPOSE. The SwissKeys and Gintronic fonts are licensed and are not
on a CI runner, so a font that cannot be found is REPORTED, not failed -- an
unverifiable check must not turn every build red. Run it on the machine that has
the fonts and it verifies for real.
"""
import os
import re
import struct
import sys

# Where fonts live, including the Windows tree as WSL sees it -- this repo is
# edited from Windows and built inside WSL, and the licensed fonts are installed
# on the Windows side only.
FONT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
    "/mnt/c/Windows/Fonts", "C:/Windows/Fonts",
    os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts",
    os.path.expandvars("$LOCALAPPDATA/Microsoft/Windows/Fonts"),
]
EXTS = (".ttf", ".otf", ".ttc", ".otc")


# --------------------------------------------------------------------------- #
# sfnt
# --------------------------------------------------------------------------- #
def _tables(buf, base=0):
    """tag -> (offset, length) from the table directory at `base`."""
    if len(buf) < base + 12:
        return {}
    num = struct.unpack_from(">H", buf, base + 4)[0]
    out = {}
    for i in range(num):
        p = base + 12 + i * 16
        if p + 16 > len(buf):
            break
        tag, _, off, ln = struct.unpack_from(">4sLLL", buf, p)
        out[tag.decode("latin-1")] = (off, ln)
    return out


def _offsets(buf):
    """Every font in the file: a .ttc holds several."""
    if buf[:4] == b"ttcf":
        n = struct.unpack_from(">L", buf, 8)[0]
        return list(struct.unpack_from(f">{n}L", buf, 12))
    return [0]


def _names(buf, tbl):
    """Family names this font answers to (nameID 1 and 16)."""
    if "name" not in tbl:
        return set()
    off, _ = tbl["name"]
    if off + 6 > len(buf):
        return set()
    count, str_off = struct.unpack_from(">HH", buf, off + 2)
    found = set()
    for i in range(count):
        p = off + 6 + i * 12
        if p + 12 > len(buf):
            break
        plat, enc, _lang, nid, ln, o = struct.unpack_from(">HHHHHH", buf, p)
        if nid not in (1, 16):
            continue
        s = buf[off + str_off + o: off + str_off + o + ln]
        try:
            txt = s.decode("utf-16-be" if plat == 3 else "latin-1", "ignore")
        except Exception:
            continue
        txt = txt.strip("\x00 ").strip()
        if txt:
            found.add(txt)
    return found


def _cmap(buf, tbl):
    """The set of codepoints the font maps to a real glyph."""
    if "cmap" not in tbl:
        return set()
    base, _ = tbl["cmap"]
    if base + 4 > len(buf):
        return set()
    n = struct.unpack_from(">H", buf, base + 2)[0]
    best, best_score = None, -1
    for i in range(n):
        p = base + 4 + i * 8
        if p + 8 > len(buf):
            break
        plat, enc, off = struct.unpack_from(">HHL", buf, p)
        # prefer full Unicode (3,10) over BMP (3,1) over anything else
        score = {(3, 10): 3, (0, 4): 3, (0, 6): 3, (3, 1): 2, (0, 3): 2}.get((plat, enc), 1)
        if score > best_score:
            best, best_score = base + off, score
    if best is None or best + 2 > len(buf):
        return set()

    fmt = struct.unpack_from(">H", buf, best)[0]
    chars = set()
    if fmt == 4:
        seg2 = struct.unpack_from(">H", buf, best + 6)[0]
        seg = seg2 // 2
        ends = struct.unpack_from(f">{seg}H", buf, best + 14)
        starts = struct.unpack_from(f">{seg}H", buf, best + 16 + seg2)
        deltas = struct.unpack_from(f">{seg}h", buf, best + 16 + 2 * seg2)
        ro_at = best + 16 + 3 * seg2
        ranges = struct.unpack_from(f">{seg}H", buf, ro_at)
        for i in range(seg):
            if starts[i] > ends[i] or starts[i] == 0xFFFF:
                continue
            for c in range(starts[i], min(ends[i], 0xFFFE) + 1):
                if ranges[i] == 0:
                    gid = (c + deltas[i]) & 0xFFFF
                else:
                    gp = ro_at + i * 2 + ranges[i] + (c - starts[i]) * 2
                    if gp + 2 > len(buf):
                        continue
                    gid = struct.unpack_from(">H", buf, gp)[0]
                    if gid:
                        gid = (gid + deltas[i]) & 0xFFFF
                if gid:
                    chars.add(c)
    elif fmt == 12:
        ngroups = struct.unpack_from(">L", buf, best + 12)[0]
        for i in range(min(ngroups, 20000)):
            p = best + 16 + i * 12
            if p + 12 > len(buf):
                break
            s, e, _g = struct.unpack_from(">LLL", buf, p)
            if e - s > 0x20000:          # a pathological range; take the start of it
                e = s + 0x20000
            chars.update(range(s, e + 1))
    return chars


# --------------------------------------------------------------------------- #
_INDEX = None


def index(extra_dirs=()):
    """family name (casefolded) -> set of codepoints. Built once."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    _INDEX = {}
    for d in list(extra_dirs) + FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in sorted(files):
                if not f.lower().endswith(EXTS):
                    continue
                path = os.path.join(root, f)
                try:
                    with open(path, "rb") as fh:
                        buf = fh.read()
                    for base in _offsets(buf):
                        tbl = _tables(buf, base)
                        fams = _names(buf, tbl)
                        if not fams:
                            continue
                        cov = _cmap(buf, tbl)
                        if not cov:
                            continue
                        for fam in fams:
                            k = fam.casefold()
                            _INDEX[k] = _INDEX.get(k, set()) | cov
                except Exception:
                    continue          # an unreadable font is not a document problem
    return _INDEX


def coverage(family, extra_dirs=()):
    """Codepoints `family` can print, or None if the font is not installed."""
    return index(extra_dirs).get((family or "").casefold())


# --------------------------------------------------------------------------- #
# character style -> the font it actually resolves to
# --------------------------------------------------------------------------- #
def resolve_fonts(styles_xml):
    """{style name: font family}, following BasedOn until a font is set.

    A style that sets no font inherits one -- `lcd_sk_high` gets SwissKeys Raster
    from `lcd_sk`, three of the Gintronic styles get theirs from `lcd_normal` --
    so reading only the style's own AppliedFont answers None for most of them.
    """
    raw = open(styles_xml, encoding="utf-8").read()
    own, based, names = {}, {}, {}
    # BOTH forms, self-closing first. A style with no properties is written
    # `<CharacterStyle ... />`, and matching only the paired form made the regex
    # run on to the NEXT `</CharacterStyle>` and hand that style's body to this
    # one -- which is how `$ID/[No character style]` came out as Wingdings 3,
    # borrowing the definition of `dings` that follows it in the file.
    for m in re.finditer(r'<CharacterStyle\b[^>]*?Self="CharacterStyle/([^"]+)"[^>]*?/>'
                         r'|<CharacterStyle\b[^>]*?Self="CharacterStyle/([^"]+)"[^>]*?>'
                         r'((?:(?!<CharacterStyle\b).)*?)</CharacterStyle>', raw, re.S):
        sid = m.group(1) or m.group(2)
        body = m.group(3) or ""
        names[sid] = sid.replace("%3a", ":")
        f = re.search(r"<AppliedFont[^>]*>([^<]+)</AppliedFont>", body)
        b = re.search(r"<BasedOn[^>]*>([^<]+)</BasedOn>", body)
        if f:
            own[sid] = f.group(1).strip()
        if b:
            based[sid] = b.group(1).strip().replace("CharacterStyle/", "")

    def walk(sid, seen=None):
        seen = seen or set()
        while sid and sid not in seen:
            seen.add(sid)
            if sid in own:
                return own[sid]
            sid = based.get(sid)
        return None

    return {names[s]: walk(s) for s in names}


def main():
    build = sys.argv[1] if len(sys.argv) > 1 else "template_build"
    styles = os.path.join(build, "Resources", "Styles.xml")
    fonts = resolve_fonts(styles)
    wanted = sorted({f for f in fonts.values() if f})
    idx = index([os.path.join(os.path.dirname(build.rstrip("/")), "Document Fonts")])
    print(f"font families indexed on this machine: {len(idx)}")
    for fam in wanted:
        cov = coverage(fam)
        print(f"  {fam:<28} {'not installed' if cov is None else str(len(cov)) + ' codepoints'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
