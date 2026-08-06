#!/usr/bin/env python3
"""Build a BLANK-KIT template from an extracted IDML.

Keeps the full skeleton (all styles, colors, fonts, XML tags, cross-reference
formats, every MasterSpread, an empty Index engine) and strips all content:
  - Stories -> only the ones the masters + one blank donor spread reference.
  - Spreads -> one blank donor spread (Spread_u7973e: 2 pages, no frames).
  - designmap -> Hyperlinks, HyperlinkPageDestinations, index Topics, the
    InCopy Assignment, and the placed-index InstanceList entry all removed;
    Sections collapsed to one pointing at the donor page.

Usage: python3 make_template.py [src_dir] [build_dir]
Then:  python3 repack.py <build_dir> manual_template.idml

The mimetype/META-INF/Resources/MasterSpreads/XML trees are copied verbatim.
Nothing here hand-authors InDesign geometry: the one surviving spread and the
114 surviving stories are real InDesign output, only the designmap is rewritten.
"""
import os, re, sys, glob, shutil
import xml.etree.ElementTree as ET

SRC   = sys.argv[1] if len(sys.argv) > 1 else "extracted"
BUILD = sys.argv[2] if len(sys.argv) > 2 else "template_build"
DONOR_SPREAD = "Spread_u7973e"     # 2 blank pages, zero frames
DONOR_PAGE   = "u79767"            # its first page (Section PageStart target)

PKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", PKG)
def local(t): return t.split('}', 1)[1] if '}' in t else t
def reads(f): return open(f, encoding="utf-8").read()

# ---- 1. fresh copy ---------------------------------------------------------
if os.path.exists(BUILD):
    shutil.rmtree(BUILD)
shutil.copytree(SRC, BUILD)

# ---- 2. transitive story closure from masters + donor ----------------------
def story_file(sid):
    p = os.path.join(BUILD, "Stories", f"Story_{sid}.xml")
    return p if os.path.exists(p) else None

seed = set()
for f in glob.glob(os.path.join(BUILD, "MasterSpreads", "*.xml")) + \
         [os.path.join(BUILD, "Spreads", f"{DONOR_SPREAD}.xml")]:
    seed |= set(re.findall(r'ParentStory="([^"]+)"', reads(f)))

keep_stories, frontier = set(), set(seed)
while frontier:
    s = frontier.pop()
    if s in keep_stories:
        continue
    keep_stories.add(s)
    p = story_file(s)
    if p:
        frontier |= set(re.findall(r'ParentStory="([^"]+)"', reads(p))) - keep_stories

# ---- 3. delete non-kept stories & non-donor spreads ------------------------
removed_stories = removed_spreads = 0
for p in glob.glob(os.path.join(BUILD, "Stories", "Story_*.xml")):
    sid = re.search(r'Story_(.+)\.xml$', p).group(1)
    if sid not in keep_stories:
        os.remove(p); removed_stories += 1
for p in glob.glob(os.path.join(BUILD, "Spreads", "Spread_*.xml")):
    if f"{DONOR_SPREAD}" not in os.path.basename(p):
        os.remove(p); removed_spreads += 1

# ---- 4. rewrite designmap.xml ----------------------------------------------
dm_path = os.path.join(BUILD, "designmap.xml")
# preserve the exact original header (XML decl + <?aid ...?> PI) verbatim;
# ElementTree drops processing instructions, and InDesign needs the aid PI.
raw = reads(dm_path)
header = raw[:raw.index("<Document")]

tree = ET.parse(dm_path)
root = tree.getroot()

# 4a. prune the root StoryList attribute to surviving stories
sl = [t for t in root.get("StoryList", "").split() if t in keep_stories]
root.set("StoryList", " ".join(sl))

DROP_TAGS = {"Hyperlink", "HyperlinkPageDestination", "Assignment"}
kept_spread_ref = f"Spreads/{DONOR_SPREAD}.xml"

new_children, seen_section, stats = [], False, {}
for ch in list(root):
    tag, ns = local(ch.tag), (ch.tag.split('}', 1)[0].strip('{') if '}' in ch.tag else "")
    drop = False

    if tag in DROP_TAGS:
        drop = True
    elif tag == "Index":
        for t in list(ch):            # empty the topic tree, keep the engine
            ch.remove(t)
    elif tag == "Section":
        if seen_section:
            drop = True               # collapse to a single section
        else:
            seen_section = True
            ch.set("PageStart", DONOR_PAGE)
            ch.set("Name", ""); ch.set("Marker", "")
    elif ns == PKG and tag == "Spread":
        drop = ch.get("src") != kept_spread_ref
    elif ns == PKG and tag == "Story":
        sid = re.search(r'Story_(.+)\.xml$', ch.get("src", "")).group(1)
        drop = sid not in keep_stories
    elif tag == "Properties":
        il = ch.find("InstanceList")   # drop the placed-index reference
        if il is not None:
            for inst in list(il):
                il.remove(inst)

    if drop:
        stats[tag] = stats.get(tag, 0) + 1
    else:
        new_children.append(ch)

root[:] = new_children

body = ET.tostring(root, encoding="unicode")
with open(dm_path, "w", encoding="utf-8") as fh:
    fh.write(header + body + "\n")

# ---- 5. report -------------------------------------------------------------
print(f"build dir     : {BUILD}")
print(f"kept stories  : {len(keep_stories)}   (removed {removed_stories})")
print(f"kept spreads  : 1 [{DONOR_SPREAD}]   (removed {removed_spreads})")
print(f"kept masters  : {len(glob.glob(os.path.join(BUILD,'MasterSpreads','*.xml')))}")
print("designmap removed nodes:", {k: v for k, v in sorted(stats.items())})
print("Note: META-INF/metadata.xml kept as-is (carries DM32 XMP history).")
