#!/usr/bin/env python3
"""Remove unused swatches from an extracted IDML's Resources/Graphic.xml.

Mirrors InDesign's "Delete Unused Swatches": a swatch is removed only if it is
referenced NOWHERE in the package (content, styles, or another swatch) AND is
not protected. Protected = InDesign structural swatches ([None]/[Paper]/[Black]/
[Registration] and any $ID-managed default) PLUS the project's sanctioned
palette from the swatch whitelist (kept even when currently unused). Cascades to
a fixed point, so an unused gradient can free its now-unreferenced stop colors.

Usage: python3 prune_swatches.py [dir] [--dry-run] [--swatches FILE]
       (default dir: template_build; whitelist auto-found at <dir>.swatches)
"""
import os, re, sys, glob

DIR, DRY, WL = "template_build", "--dry-run" in sys.argv, None
args = sys.argv[1:]
for i, a in enumerate(args):
    if a == "--swatches" and i + 1 < len(args):
        WL = args[i + 1]
    elif not a.startswith("-") and args[i-1] != "--swatches":
        DIR = a

GRAPHIC = os.path.join(DIR, "Resources", "Graphic.xml")
def reads(f): return open(f, encoding="utf-8").read()

# ---- load the project swatch whitelist (sanctioned palette) ----------------
def find_whitelist(d, explicit):
    if explicit:
        return explicit
    cand = os.path.join(os.path.dirname(d.rstrip("/")) or ".",
                        os.path.basename(d.rstrip("/")) + ".swatches")
    return cand if os.path.exists(cand) else None

wl_path = find_whitelist(DIR, WL)
whitelist = set()
if wl_path and os.path.exists(wl_path):
    for ln in reads(wl_path).splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            whitelist.add(ln)

STRUCTURAL = {"Black", "Paper", "Registration", "None"}
def protected(name):
    return name in STRUCTURAL or name.startswith("$ID/") or name in whitelist

# ---- swatch definitions in Graphic.xml -------------------------------------
SWATCH_TAGS = ("Color", "Tint", "Gradient", "MixedInk", "MixedInkGroup")
all_files = glob.glob(os.path.join(DIR, "**", "*.xml"), recursive=True)

def swatch_defs():
    g, defs = reads(GRAPHIC), {}
    for tag in SWATCH_TAGS:
        for m in re.finditer(r'<' + tag + r'\b([^>]*?)/?>', g):
            attrs = m.group(1)
            sid = re.search(r'\bSelf="([^"]+)"', attrs)
            if not sid:
                continue
            nm = re.search(r'\bName="([^"]*)"', attrs)
            defs[sid.group(1)] = (nm.group(1) if nm else "", tag)
    return defs

def refcount(sid):
    needle = '"' + sid + '"'
    return sum(reads(f).count(needle) for f in all_files) - 1   # minus own Self=

# ---- iterate removal to a fixed point --------------------------------------
removed = []
while True:
    defs = swatch_defs()
    batch = [sid for sid, (nm, _) in defs.items()
             if not protected(nm) and refcount(sid) <= 0]
    if not batch:
        break
    g = reads(GRAPHIC)
    for sid in batch:
        nm, tag = defs[sid]
        g2 = re.sub(r'[ \t]*<' + tag + r'\b[^>]*\bSelf="' + re.escape(sid) + r'"[^>]*/>\r?\n?', '', g)
        if g2 == g:
            g2 = re.sub(r'[ \t]*<' + tag + r'\b[^>]*\bSelf="' + re.escape(sid) +
                        r'"[^>]*>.*?</' + tag + r'>\r?\n?', '', g, flags=re.S)
        g = g2
        removed.append((sid, nm, tag))
    if DRY:
        break
    open(GRAPHIC, "w", encoding="utf-8").write(g)

# ---- report ----------------------------------------------------------------
print(f"dir       : {DIR}")
print(f"whitelist : {wl_path or '(none found)'}  -> {sorted(whitelist) or '[]'}")
print(f"{'WOULD REMOVE' if DRY else 'REMOVED'} {len(removed)} unused swatch(es):")
for sid, nm, tag in removed:
    print(f"  - {tag:9s} {nm or '(unnamed)':24s} [{sid}]")
gone = {r[0] for r in removed}
print("\nKEPT:")
for sid, (nm, tag) in sorted(swatch_defs().items(), key=lambda x: (x[1][1], x[1][0])):
    if DRY and sid in gone:
        continue
    why = "structural" if (nm in STRUCTURAL or nm.startswith("$ID/")) else \
          ("whitelist" if nm in whitelist else "referenced")
    print(f"  · {tag:9s} {nm or '(unnamed)':24s} [{why}]")
