#!/usr/bin/env python3
"""Referential-integrity sanitizer for an extracted IDML folder.

Catches the failure classes that make InDesign reject an IDML: malformed XML,
designmap package refs pointing at missing files, ParentStory / AppliedMaster /
Section-PageStart / text-frame-thread references that don't resolve, and stories
present on disk but not declared in the designmap (or vice-versa).

Usage: python3 validate_idml.py [dir] [--swatches FILE]   (default: template_build)
Exit code 0 = clean, 1 = problems found.

If a swatch whitelist is found (explicit --swatches FILE, else "<dir>.swatches"
next to the dir), any color APPLIED to a page item whose swatch name is not in
the whitelist (structural None/Paper/Registration/$ID always allowed) is flagged
-- enforcing the per-project "only these colors, never more" rule.
"""
import os, re, sys, glob, urllib.parse
import xml.etree.ElementTree as ET

_pos = [a for a in sys.argv[1:] if not a.startswith("-")]
D = _pos[0] if _pos else "template_build"
_WL = None
if "--swatches" in sys.argv:
    _i = sys.argv.index("--swatches")
    if _i + 1 < len(sys.argv):
        _WL = sys.argv[_i + 1]
PKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
def local(t): return t.split('}', 1)[1] if '}' in t else t
def reads(f): return open(f, encoding="utf-8").read()

problems, warnings, checks = [], [], 0
def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        problems.append(msg)

def warn(cond, msg):
    """Report, but do not fail the build.

    Everything `check` fails on is STRUCTURAL — a dangling reference or malformed
    XML, something that stops InDesign opening the document, and something the
    toolchain either caused or can fix. A warning is a CONTENT defect: real, worth
    a human's attention, but an editorial call on someone's text. Failing the
    build for those would mean a fixture's pre-existing debt blocks every unrelated
    change, and the honest response to "19 bullets are styled as buttons" is to
    look at them, not to stop the pipeline.
    """
    global checks
    checks += 1
    if not cond:
        warnings.append(msg)

# ---- 1. every XML well-formed ---------------------------------------------
xmls = glob.glob(os.path.join(D, "**", "*.xml"), recursive=True)
for f in xmls:
    try:
        ET.parse(f)
    except ET.ParseError as e:
        problems.append(f"malformed XML: {os.path.relpath(f, D)}: {e}")
checks += len(xmls)

# ---- 2. mimetype present ---------------------------------------------------
check(os.path.exists(os.path.join(D, "mimetype")), "missing mimetype")

# ---- collect ids from layout + stories ------------------------------------
def selfs(files, tag):
    out = {}
    for f in files:
        for m in re.finditer(r'<' + tag + r'\b[^>]*\bSelf="([^"]+)"', reads(f)):
            out[m.group(1)] = f
    return out

spreads = glob.glob(os.path.join(D, "Spreads", "*.xml"))
masters = glob.glob(os.path.join(D, "MasterSpreads", "*.xml"))
stories = glob.glob(os.path.join(D, "Stories", "*.xml"))
layout  = spreads + masters

story_ids  = {re.search(r'Story_(.+)\.xml$', p).group(1) for p in stories}
page_ids   = set(selfs(layout, "Page"))
master_ids = set(selfs(masters, "MasterSpread"))
# any element Self in layout (for text-frame thread resolution)
frame_ids  = set()
for f in layout:
    frame_ids |= set(re.findall(r'\bSelf="([^"]+)"', reads(f)))

# ---- 3. designmap package refs resolve ------------------------------------
dm = ET.parse(os.path.join(D, "designmap.xml")).getroot()
dm_story_refs, dm_spread_refs = set(), set()
for ch in dm:
    if ch.tag == f"{{{PKG}}}Story":
        src = ch.get("src");
        check(os.path.exists(os.path.join(D, src)), f"designmap Story ref missing file: {src}")
        dm_story_refs.add(re.search(r'Story_(.+)\.xml$', src).group(1))
    elif ch.tag in (f"{{{PKG}}}Spread", f"{{{PKG}}}MasterSpread",
                    f"{{{PKG}}}Graphic", f"{{{PKG}}}Fonts", f"{{{PKG}}}Styles",
                    f"{{{PKG}}}Preferences", f"{{{PKG}}}Tags", f"{{{PKG}}}BackingStory"):
        src = ch.get("src")
        check(os.path.exists(os.path.join(D, src)), f"designmap ref missing file: {src}")
        if ch.tag == f"{{{PKG}}}Spread":
            dm_spread_refs.add(src)

# ---- 4. story set: disk == designmap declarations -------------------------
check(dm_story_refs == story_ids,
      f"story mismatch: on-disk-not-declared={sorted(story_ids-dm_story_refs)[:5]} "
      f"declared-not-on-disk={sorted(dm_story_refs-story_ids)[:5]}")
# StoryList also names stories that don't live in Stories/: the XML BackingStory
# (XML/BackingStory.xml) holds the XML root element and is declared via
# idPkg:BackingStory, not idPkg:Story. Counting only Stories/*.xml reports it as
# dangling -- v1.76 itself trips that (ub0), as does the kit (u98).
other_story_ids = set()
for ch in dm:
    if ch.tag == f"{{{PKG}}}BackingStory":
        p = os.path.join(D, ch.get("src"))
        if os.path.exists(p):
            other_story_ids |= set(re.findall(r'<XmlStory\b[^>]*\bSelf="([^"]+)"', reads(p)))
sl = set(dm.get("StoryList", "").split())
check(sl <= (story_ids | other_story_ids),
      f"StoryList names missing stories: {sorted(sl - story_ids - other_story_ids)[:5]}")

# ---- 5. ParentStory refs resolve ------------------------------------------
bad_parent = set()
for f in layout:
    for sid in re.findall(r'ParentStory="([^"]+)"', reads(f)):
        if sid not in story_ids:
            bad_parent.add(sid)
check(not bad_parent, f"ParentStory -> missing story: {sorted(bad_parent)[:5]}")

# ---- 6. AppliedMaster refs resolve ----------------------------------------
bad_master = set()
for f in layout:
    for mid in re.findall(r'AppliedMaster="([^"]+)"', reads(f)):
        if mid not in ("n", "") and mid not in master_ids:
            bad_master.add(mid)
check(not bad_master, f"AppliedMaster -> missing master: {sorted(bad_master)[:5]}")

# ---- 6b. ItemLayer refs resolve -------------------------------------------
# The commonest reference in the file — every page item carries one — and the
# one that fails most quietly: InDesign does not reject an item naming a layer
# that isn't there, it silently puts it on the first layer. That is what a
# master transplant did to ten guide_* layers, flattening every guide onto
# `foot`, and nothing here noticed because nothing looked.
layer_ids = {m.group(1) for m in
             re.finditer(r'<Layer\b[^>]*?\bSelf="([^"]+)"', reads(os.path.join(D, "designmap.xml")))}
bad_layer = {}
for f in layout:
    for lid in re.findall(r'ItemLayer="([^"]+)"', reads(f)):
        if lid not in layer_ids:
            bad_layer[lid] = bad_layer.get(lid, 0) + 1
check(not bad_layer,
      f"ItemLayer -> missing layer (items land on the first layer, silently): "
      f"{sorted(bad_layer.items(), key=lambda kv: -kv[1])[:5]}")

# ---- 7. Section PageStart resolves ----------------------------------------
for ch in dm:
    if local(ch.tag) == "Section":
        ps = ch.get("PageStart")
        check(ps in page_ids, f"Section PageStart -> missing page: {ps}")

# ---- 8. text-frame threads resolve (no dangling Next/Previous) -------------
bad_thread = set()
for f in layout:
    for ref in re.findall(r'(?:Next|Previous)TextFrame="([^"]+)"', reads(f)):
        if ref not in ("n", "") and ref not in frame_ids:
            bad_thread.add(ref)
check(not bad_thread, f"text-frame thread -> missing frame: {sorted(bad_thread)[:5]}")

# ---- 9. swatch whitelist: no off-palette color applied to page items -------
# Per-manual config sits next to the build dir, so with the repo split into
# toolchain / kit / manuals a build at manuals/<product>/build finds its whitelist
# one level up as manuals/<product>/<product>.swatches. The kit's own file is the
# last resort, which is where a new manual starts.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manualconf
_conf = manualconf.load(D, _WL)
wl_path = _conf["path"] if _conf["swatches"] else None
wl_report = "no whitelist -> color check skipped"
if wl_path and os.path.exists(wl_path):
    allow = set(_conf["swatches"])
    gm = reads(os.path.join(D, "Resources", "Graphic.xml"))
    id2name = {}
    for tag in ("Color", "Tint", "Gradient", "MixedInk", "MixedInkGroup"):
        for m in re.finditer(r'<' + tag + r'\b([^>]*?)/?>', gm):
            sid = re.search(r'\bSelf="([^"]+)"', m.group(1))
            nm = re.search(r'\bName="([^"]*)"', m.group(1))
            if sid:
                id2name[sid.group(1)] = nm.group(1) if nm else ""
    # A mixed ink built only from sanctioned inks is itself sanctioned -- the
    # generated tab swatches (tab_00..) are tweens of the palette, so listing them
    # individually would mean re-listing the whitelist every time N changes.
    mixed_ok = set()
    for m in re.finditer(r'<MixedInk\b([^>]*?)/?>', gm):
        sid = re.search(r'\bSelf="([^"]+)"', m.group(1))
        il = re.search(r'\bInkList="([^"]*)"', m.group(1))
        if not sid or not il:
            continue
        names = []
        for x in il.group(1).split():
            x = urllib.parse.unquote(x)
            for pre in ("Ink/", "$ID/"):
                if x.startswith(pre):
                    x = x[len(pre):]
            names.append("Black" if x == "Process Black" else x)
        if names and all(x in allow for x in names):
            mixed_ok.add(sid.group(1))

    def allowed(cid):
        nm = id2name.get(cid, cid.split("/", 1)[-1])
        return (nm in allow or nm in ("Paper", "Registration", "None")
                or nm.startswith("$ID/") or cid in ("Swatch/None",)
                or cid in mixed_ok)
    COLOR_ATTRS = ("FillColor", "StrokeColor", "GradientFillColor",
                   "UnderlineColor", "StrikeThroughColor")
    offenders = {}   # name -> count (applied on page items only, not style defs)
    for f in layout + stories:
        t = reads(f)
        for attr in COLOR_ATTRS:
            for cid in re.findall(attr + r'="([^"]+)"', t):
                if not allowed(cid):
                    nm = id2name.get(cid, cid)
                    offenders[nm] = offenders.get(nm, 0) + 1
    check(not offenders,
          f"off-palette colors applied (not in {os.path.basename(wl_path)}): "
          + ", ".join(f"{k} x{v}" for k, v in sorted(offenders.items())))
    wl_report = f"{os.path.basename(wl_path)}: {sorted(allow)} -> " + \
                ("clean" if not offenders else f"{len(offenders)} off-palette")

# ---- 10. underline must be style-driven, never local formatting ------------
# Underline belongs to a character style (`link`, `code_styles:lcd_*`) and
# nowhere else. Two things break that: an INLINE underline (Underline="true" on
# an unstyled range) and a style plus a LOCAL OVERRIDE (CharacterStyle/link
# together with Underline="false") -- the style says underline, the local
# formatting says don't, and they drift apart from then on. InDesign
# reintroduces these on export, so this is re-checked after every round-trip.
# IDML splits these across TWO places: scalars are open-tag ATTRIBUTES
# (Underline, UnderlineWeight, ...) while object-valued ones are <Properties>
# CHILD ELEMENTS (<UnderlineColor>) -- e.g. a link-styled range carrying
# UnderlineColor="Text Color", which defeats the style's PANTONE 130 U orange.
# Checking attributes alone silently misses the colour.
UL_ATTR = re.compile(r'\bUnderline[A-Za-z]*="')
UL_CHILD = re.compile(r'<Underline[A-Za-z]*\b')
RANGE_OPEN = re.compile(r'<(CharacterStyleRange|ParagraphStyleRange)\b([^>]*?)(/?)>')
PROPS_AT = re.compile(r'\s*<Properties>(.*?)</Properties>', re.S)  # .match(t, pos), no slicing
ul_empty, ul_text = [], []
for f in stories + layout:
    t = reads(f)
    if "Underline" not in t:
        continue
    for m in RANGE_OPEN.finditer(t):
        tag, attrs, selfclose = m.group(1), m.group(2), m.group(3)
        pm = None if selfclose else PROPS_AT.match(t, m.end())
        if not UL_ATTR.search(attrs) and not (pm and UL_CHILD.search(pm.group(1))):
            continue
        # style ranges don't nest inside themselves, so the next close is ours
        end = t.find(f"</{tag}>", m.end()) if not selfclose else m.end()
        body = t[m.end():end] if end > 0 else ""
        txt = "".join(re.findall(r'<Content>(.*?)</Content>', body, re.S))
        st = re.search(r'AppliedCharacterStyle="([^"]+)"', attrs)
        rec = (os.path.relpath(f, D), (st.group(1) if st else "-"), txt.strip())
        # only a bare Underline="true|false" toggle on real text changes what
        # prints; Underline* geometry alone is inert residue
        (ul_text if txt.strip() and re.search(r'\bUnderline="', attrs)
         else ul_empty).append(rec)
check(not (ul_empty or ul_text),
      f"local underline formatting (must come from a character style only): "
      f"{len(ul_empty)} strippable, {len(ul_text)} contradicting a style on live text"
      + (" -- run fix_underlines.py" if not ul_text else
         " -- the live ones need a human call, see fix_underlines.py")
      + "".join(f"\n      {p}: {s} {txt[:40]!r}" for p, s, txt in (ul_text + ul_empty)[:6]))

# ---- 10b. InDesign's factory link style must never be applied --------------
# $ID/Hyperlink is reserved, undeletable, and present in every IDML: blue
# Color/Hyperlink (process CMYK 86/57/0/16) with a default-weight underline.
# Applying it is always wrong here -- the house oblique-link rule is
# CharacterStyle/link (0.375pt, PANTONE 130 U, overprint). It's the default an
# author gets by creating a hyperlink without applying `link`, and on black text
# the swatch check in 9 wouldn't catch it. Reported, never auto-fixed: swapping
# it for `link` is a semantic call (it may be a genuine URL, not an oblique ref).
HL_STYLE = 'AppliedCharacterStyle="CharacterStyle/$ID/Hyperlink"'
hl_hits = []
for f in stories + layout:
    t = reads(f)
    if HL_STYLE not in t:
        continue
    for m in re.finditer(re.escape(HL_STYLE) + r'[^>]*?>(.*?)</CharacterStyleRange>', t, re.S):
        txt = "".join(re.findall(r'<Content>(.*?)</Content>', m.group(1), re.S)).strip()
        hl_hits.append((os.path.relpath(f, D), txt))
check(not hl_hits,
      f"InDesign's factory $ID/Hyperlink style applied to {len(hl_hits)} range(s) "
      f"-- blue process-CMYK, not the house CharacterStyle/link (PANTONE 130 U)"
      + "".join(f"\n      {p}: {(repr(txt[:50]) if txt else '(empty range)')}"
                for p, txt in hl_hits[:6]))

# ---- 10c. heading hierarchy matches what the manual declares ---------------
# Only runs when the manual declares `levels`. Numbering itself is correct as long
# as content starts at lvl1 -- the counters start at the top -- so what this
# catches is content that SKIPS the top level, which is what puts a leading zero
# in front of every number ("0.1.4"), and content reaching deeper than declared.
if _conf["levels"]:
    declared = _conf["levels"]
    used = {}
    for f in stories:
        t = reads(f)
        for m in re.finditer(r'AppliedParagraphStyle="ParagraphStyle/titles%3alvl(\d)"', t):
            used[int(m.group(1))] = used.get(int(m.group(1)), 0) + 1
    # The leading-zero test only concerns levels that COUNT, so it looks at the
    # numbered ones. The tab test must not: a tab can sit on a label level above
    # number_from -- tabs on the 23 chapters, numbering starting a level deeper --
    # and reading the filtered set there reported 23 present headings as absent.
    present = dict(used)
    first = _conf["number_from"] or 1
    if used:
        used = {k: v for k, v in used.items() if k >= first}
    if used:
        top, deepest = min(used), max(used)
        check(top == first,
              f"content skips heading level(s) {first}..{top - 1}: the shallowest used is "
              f"titles:lvl{top}, so every number gets a leading zero "
              f"(a '1.4' would render '{'0.' * (top - 1)}1.4'). Tag the top-level "
              f"headings titles:lvl1, or drop `levels` from "
              f"{os.path.basename(_conf['path'] or 'the manual config')}.")
        check(deepest <= declared,
              f"content uses titles:lvl{deepest} but the manual declares only "
              f"{declared} level(s); raise `levels` or restyle those headings")
    tab = _conf["tab_level"]
    if tab:
        check(tab in present or not present,
              f"tab_level is {tab} but no titles:lvl{tab} heading appears in the "
              f"content, so there would be no tabs (levels present: "
              f"{sorted(present) or 'none'})")

# ---- 10d. master identity must be unique -----------------------------------
# A master is identified by NamePrefix + BaseName, not by Name. Two masters
# claiming the same identity is what crashed InDesign 2026 on open, and it is
# what re-running the pipeline over its own output produces: apply_tabs.py mints
# a second S1..SN set beside the first. Cheap to check, fatal to miss.
ident = {}
for f in masters:
    m = re.search(r'<MasterSpread\b[^>]*>', reads(f))
    if not m:
        continue
    pre = re.search(r'\bNamePrefix="([^"]*)"', m.group(0))
    base = re.search(r'\bBaseName="([^"]*)"', m.group(0))
    if pre and base:
        ident.setdefault((pre.group(1), base.group(1)), []).append(os.path.basename(f))
dup_ident = {k: v for k, v in ident.items() if len(v) > 1}
check(not dup_ident,
      f"{len(dup_ident)} duplicate master identit(ies) — InDesign identifies a master "
      f"by NamePrefix+BaseName: "
      + ", ".join(f"{p}-{b} x{len(v)}" for (p, b), v in list(dup_ident.items())[:4])
      + (" ..." if len(dup_ident) > 4 else ""))

# ---- 10e. one story per chapter --------------------------------------------
# Chapter detection is per STORY, not per heading, because a mid-story heading's
# page cannot be known without composing the text. A story holding several
# chapter headings therefore yields one chapter, and the extras get no tab and no
# section — the count just comes up short with nothing said.
_chap = _conf["chapter_style"]
if _chap:
    _enc = _chap.replace(":", "%3a")
    crowded = {}
    for f in stories:
        raw = reads(f)
        if _enc not in raw:
            continue
        n = 0
        for m in re.finditer(r'<ParagraphStyleRange\b[^>]*AppliedParagraphStyle='
                             r'"ParagraphStyle/' + re.escape(_enc) + r'"[^>]*>(.*?)'
                             r'</ParagraphStyleRange>', raw, re.S):
            body = m.group(1)
            n += len([x for x in re.split(r'<Br\b[^>]*/>', body)
                      if re.search(r'<Content>\s*\S', x)])
        if n > 1:
            sid = re.search(r'<Story\b[^>]*Self="([^"]+)"', raw)
            crowded[sid.group(1) if sid else os.path.basename(f)] = n
    check(not crowded,
          f"{sum(v - 1 for v in crowded.values())} '{_chap}' heading(s) share a story "
          f"with another, so they get no tab and no section (one story per chapter): "
          + ", ".join(f"{k} holds {v}" for k, v in list(crowded.items())[:4])
          + (" ..." if len(crowded) > 4 else ""))

# ---- 10f. every character must exist in the font its style resolves to -----
# IDML records font NAMES, never coverage, so a character the font has no glyph
# for is invisible in the XML and only shows up on paper. v1.76 carries 27 x
# U+FFFD inside btn_bl from a glyph lost years ago, and those buttons print
# something wrong today with nothing having ever said so.
#
# Key markup raises the stakes: an author now types [SIGMA] and the toolchain
# inserts the glyph, so a bad map entry becomes a missing glyph rather than a
# typo somebody spots. It is also the safety net for changing lcd_normal's font.
#
# The licensed fonts are not on a CI runner, so a font that cannot be found is
# REPORTED, never failed -- an unverifiable check must not turn every build red.
import fontcov

def _unescape(s):
    s = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"') \
            .replace("&apos;", "'").replace("&amp;", "&")

# InDesign's own spacing characters are not glyphs and are routinely absent from
# a cmap while still setting correctly, so they are not evidence of anything.
_IGNORE = set(range(0x00, 0x21)) | {0xA0, 0x2028, 0x2029, 0xFEFF} | set(range(0x2000, 0x200C))

_font_of = fontcov.resolve_fonts(os.path.join(D, "Resources", "Styles.xml"))
_doc_fonts = os.path.join(os.path.dirname(os.path.abspath(D.rstrip("/"))), "Document Fonts")
_CSR = re.compile(r'<CharacterStyleRange\b([^>]*[^/])>(.*?)</CharacterStyleRange>', re.S)
_missing, _absent_fonts, _replacement = {}, set(), []
_checked_chars = 0
for f in stories:
    t = reads(f)
    for m in _CSR.finditer(t):
        attrs, body = m.group(1), m.group(2)
        sm = re.search(r'AppliedCharacterStyle="CharacterStyle/([^"]+)"', attrs)
        style = sm.group(1).replace("%3a", ":") if sm else ""
        txt = _unescape("".join(re.findall(r'<Content>(.*?)</Content>', body, re.S)))
        if not txt:
            continue
        if "�" in txt:
            _replacement.append((style, txt.strip()[:40]))
        fam = _font_of.get(style)
        if not fam:
            continue
        cov = fontcov.coverage(fam, [_doc_fonts])
        if cov is None:
            _absent_fonts.add(fam)
            continue
        for ch in txt:
            o = ord(ch)
            if o in _IGNORE or o == 0xFFFD:
                continue
            _checked_chars += 1
            if o not in cov:
                _missing[(style, fam, ch)] = _missing.get((style, fam, ch), 0) + 1

warn(not _replacement,
     f"U+FFFD replacement character in {len(_replacement)} run(s) -- a glyph was lost "
     f"before this document reached here, and those characters print wrong: "
     + "; ".join(f"{s} {t!r}" for s, t in _replacement[:4]))
warn(not _missing,
      f"{len(_missing)} character(s) have no glyph in the font their style resolves to: "
      + "; ".join(f"{ch!r} (U+{ord(ch):04X}) in {st} -> {fam} x{n}"
                  for (st, fam, ch), n in sorted(_missing.items(), key=lambda kv: -kv[1])[:6]))
font_report = (f"{_checked_chars} char(s) checked"
               + (f"; NOT INSTALLED, unverified: {', '.join(sorted(_absent_fonts))}"
                  if _absent_fonts else "; all fonts present"))

# ---- 11. no leftover Hyperlinks pointing nowhere (content graph gone) ------
n_hl = sum(1 for ch in dm if local(ch.tag) == "Hyperlink")
n_pd = sum(1 for ch in dm if local(ch.tag) == "HyperlinkPageDestination")
# informational, not a failure:
# ---------------------------------------------------------------------------
print(f"dir            : {D}")
print(f"xml files      : {len(xmls)} parsed")
print(f"stories        : {len(story_ids)} on disk, {len(dm_story_refs)} declared")
print(f"spreads/masters: {len(spreads)}/{len(masters)}")
print(f"residual hyperlinks/page-dests in designmap: {n_hl}/{n_pd}")
print(f"swatch check   : {wl_report}")
print(f"font coverage  : {font_report}")
print(f"checks run     : {checks}")
if warnings:
    print(f"\nWARNINGS ({len(warnings)}) — content to look at, not a build failure:")
    for w in warnings[:20]:
        print("  !", w)
if problems:
    print(f"\nPROBLEMS ({len(problems)}):")
    for p in problems[:40]:
        print("  -", p)
    sys.exit(1)
print("\nOK - referential integrity clean"
      + (f" ({len(warnings)} warning(s) above)" if warnings else ""))
