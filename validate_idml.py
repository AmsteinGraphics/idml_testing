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
import os, re, sys, glob
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

problems, checks = [], 0
def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        problems.append(msg)

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
sl = set(dm.get("StoryList", "").split())
check(sl <= story_ids,
      f"StoryList names missing stories: {sorted(sl-story_ids)[:5]}")

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
wl_path = _WL or (lambda p: p if os.path.exists(p) else None)(
    os.path.join(os.path.dirname(D.rstrip("/")) or ".",
                 os.path.basename(D.rstrip("/")) + ".swatches"))
wl_report = "no whitelist -> color check skipped"
if wl_path and os.path.exists(wl_path):
    allow = set()
    for ln in reads(wl_path).splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            allow.add(ln)
    gm = reads(os.path.join(D, "Resources", "Graphic.xml"))
    id2name = {}
    for tag in ("Color", "Tint", "Gradient", "MixedInk", "MixedInkGroup"):
        for m in re.finditer(r'<' + tag + r'\b([^>]*?)/?>', gm):
            sid = re.search(r'\bSelf="([^"]+)"', m.group(1))
            nm = re.search(r'\bName="([^"]*)"', m.group(1))
            if sid:
                id2name[sid.group(1)] = nm.group(1) if nm else ""
    def allowed(cid):
        nm = id2name.get(cid, cid.split("/", 1)[-1])
        return (nm in allow or nm in ("Paper", "Registration", "None")
                or nm.startswith("$ID/") or cid in ("Swatch/None",))
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
print(f"checks run     : {checks}")
if problems:
    print(f"\nPROBLEMS ({len(problems)}):")
    for p in problems[:40]:
        print("  -", p)
    sys.exit(1)
print("\nOK - referential integrity clean")
