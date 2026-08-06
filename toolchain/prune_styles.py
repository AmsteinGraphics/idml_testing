#!/usr/bin/env python3
"""Remove styles that are dead in the FULL manual from a template's Styles.xml.

"Unused" is computed against a reference doc (the complete manual, default
`extracted/`), NOT against the near-empty template -- otherwise the entire
authoring design system (which the template exists to carry) would be deleted.

A style is KEPT if it is: applied to content anywhere in the reference doc,
referenced by any non-style element (designmap cross-ref formats, TOC, index,
preferences, numbering/bullet styles), reachable via a reference edge from any
kept style (BasedOn / NextStyle / nested / GREP / object->para / table->cell /
cell->para -- all captured generically by matching the style's Self id), or an
InDesign-managed default ($ID/...). Everything else is genuine cruft and removed.

Usage: python3 prune_styles.py [target_dir] [--ref REF_DIR] [--dry-run]
       (default target: template_build ; ref: extracted)
"""
import os, re, sys, glob, copy
import xml.etree.ElementTree as ET

TARGET, REF, DRY = "template_build", "extracted", "--dry-run" in sys.argv
a = sys.argv[1:]
for i, x in enumerate(a):
    if x == "--ref" and i + 1 < len(a):
        REF = a[i + 1]
    elif not x.startswith("-") and (i == 0 or a[i-1] != "--ref"):
        TARGET = x

PKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", PKG)
STYLE_TAGS = ("ParagraphStyle", "CharacterStyle", "ObjectStyle", "TableStyle", "CellStyle")
STYLE_REF = re.compile(r'"((?:Paragraph|Character|Object|Table|Cell)Style/[^"]+)"')
def local(t): return t.split('}', 1)[1] if '}' in t else t
def reads(f): return open(f, encoding="utf-8").read()

STYLES = os.path.join(TARGET, "Resources", "Styles.xml")
raw = reads(STYLES)
header = raw[:raw.index("<idPkg:Styles")]
tree = ET.parse(STYLES)
root = tree.getroot()
parent = {c: p for p in root.iter() for c in p}

# style definitions in the template's Styles.xml
defs = {}   # Self -> (name, tag, element)
for el in root.iter():
    if local(el.tag) in STYLE_TAGS and el.get("Self"):
        defs[el.get("Self")] = (el.get("Name", ""), local(el.tag), el)
all_ids = set(defs)

def protected(sid, name):
    return "$ID/" in sid or name.startswith("$ID/")

# ---- seed: applied/referenced outside style definitions --------------------
seed = {sid for sid, (nm, _, _) in defs.items() if protected(sid, nm)}

# (a) every file in the reference doc EXCEPT its Styles.xml
ref_styles = os.path.join(REF, "Resources", "Styles.xml")
ext_blob = []
for f in glob.glob(os.path.join(REF, "**", "*.xml"), recursive=True):
    if os.path.abspath(f) == os.path.abspath(ref_styles):
        continue
    ext_blob.append(reads(f))
seed |= {m for m in STYLE_REF.findall("".join(ext_blob)) if m in all_ids}

# (b) non-style elements INSIDE Styles.xml (TOCStyle, PageNumberStyle, groups,
#     numbering/bullet styles) -- copy root, strip removable style defs, scan
skel = copy.deepcopy(root)
sp = {c: p for p in skel.iter() for c in p}
for el in list(skel.iter()):
    if local(el.tag) in STYLE_TAGS and el.get("Self") and el in sp:
        sp[el].remove(el)
seed |= {m for m in STYLE_REF.findall(ET.tostring(skel, encoding="unicode")) if m in all_ids}

# ---- closure over reference edges between style definitions -----------------
kept, frontier = set(seed), set(seed)
while frontier:
    sid = frontier.pop()
    if sid not in defs:
        continue
    for m in STYLE_REF.findall(ET.tostring(defs[sid][2], encoding="unicode")):
        if m in all_ids and m not in kept:
            kept.add(m); frontier.add(m)

removed = sorted(all_ids - kept)

# ---- apply removal ---------------------------------------------------------
if not DRY:
    for sid in removed:
        el = defs[sid][2]
        if el in parent:
            parent[el].remove(el)
    with open(STYLES, "w", encoding="utf-8") as fh:
        fh.write(header + ET.tostring(root, encoding="unicode") + "\n")

# ---- report ----------------------------------------------------------------
from collections import Counter
print(f"target: {TARGET}   ref: {REF}   ({'DRY-RUN' if DRY else 'pruned'})")
print(f"styles: {len(all_ids)} defined | kept {len(kept)} | remove {len(removed)}")
by = Counter(defs[s][1] for s in removed)
print("remove by type:", dict(by) or "{}")
for sid in removed:
    nm, tag, _ = defs[sid]
    print(f"  - {tag:14s} {nm or '(unnamed)':32s} [{sid}]")
