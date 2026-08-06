#!/usr/bin/env python3
"""Detect chapters in a poured IDML tree and (re)write one InDesign Section per chapter.

Phase 1 of the forward toolchain (see README "Forward content production").

A chapter is any story whose heading paragraph carries the chapter paragraph style
(default `titles:lvl2`). Each chapter is its own threaded story; its head text frame
(PreviousTextFrame="n") sits on the chapter's first page. We locate that page
geometrically, then replace the document's Section list in designmap.xml with one
<Section> per chapter: Marker=<title>, PageStart=<page Self>, Length=<page count>.

    sectionize.py <build_dir> [--chapter-style titles:lvl2] [--dry-run]

String surgery (not ElementTree) is used on designmap.xml so the leading <?aid?>
processing instruction is preserved verbatim (see README IDML gotchas).
"""
import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET


def local(tag):
    return tag.split("}")[-1]


def content_text(el):
    return "".join(c.text or "" for c in el.iter() if local(c.tag) == "Content")


# --------------------------------------------------------------------------- #
# Geometry: map each spread's text frames to the page they sit on.
# --------------------------------------------------------------------------- #
def load_layout(build):
    """Return (ordered_pages, frames_by_story).

    ordered_pages: list of page dicts in designmap spread order, each
        {self, name, master, spread, tx, bounds:[y1,x1,y2,x2]}.
    frames_by_story: {story_self: [frame dicts]}, frame = {self, prev, tx, spread}.
    """
    dm = open(os.path.join(build, "designmap.xml"), encoding="utf-8").read()
    spread_files = re.findall(r'idPkg:Spread src="Spreads/(Spread_[^"]+)"', dm)

    ordered_pages = []
    pages_by_spread = {}
    frames_by_story = {}
    for sf in spread_files:
        t = ET.fromstring(open(os.path.join(build, "Spreads", sf), encoding="utf-8").read())
        spread = next(e for e in t.iter() if local(e.tag) == "Spread")
        for el in spread.iter():
            tag = local(el.tag)
            if tag == "Page":
                it = el.get("ItemTransform", "1 0 0 1 0 0").split()
                gb = [float(v) for v in el.get("GeometricBounds", "0 0 0 0").split()]
                p = dict(self=el.get("Self"), name=el.get("Name"),
                         master=el.get("AppliedMaster"), spread=sf,
                         tx=float(it[4]), bounds=gb)
                ordered_pages.append(p)
                pages_by_spread.setdefault(sf, []).append(p)
            elif tag == "TextFrame":
                it = el.get("ItemTransform", "1 0 0 1 0 0").split()
                frames_by_story.setdefault(el.get("ParentStory"), []).append(
                    dict(self=el.get("Self"), prev=el.get("PreviousTextFrame", "n"),
                         tx=float(it[4]), spread=sf))
    return ordered_pages, frames_by_story, pages_by_spread


def page_for_frame(fr, pages_by_spread):
    cand = pages_by_spread.get(fr["spread"], [])
    if not cand:
        return None
    if len(cand) == 1:
        return cand[0]
    for p in cand:
        x1, x2 = p["tx"] + p["bounds"][1], p["tx"] + p["bounds"][3]
        lo, hi = min(x1, x2), max(x1, x2)
        if lo - 1 <= fr["tx"] <= hi + 1:
            return p
    return min(cand, key=lambda p: abs(p["tx"] - fr["tx"]))


# --------------------------------------------------------------------------- #
# Chapter detection
# --------------------------------------------------------------------------- #
# The heading hierarchy, top-down. A manual uses as many levels as it needs,
# starting at the top -- so the chapter level is the shallowest one that actually
# appears, not a fixed style. That keeps three-level content working after a
# fourth level was added to the kit above it.
HEADING_LEVELS = ["titles:lvl1", "titles:lvl2", "titles:lvl3", "titles:lvl4"]


def topmost_heading(build, candidates=None):
    """The shallowest heading style that appears in the document = its chapter level."""
    used = set()
    for s in glob.glob(os.path.join(build, "Stories", "*.xml")):
        raw = open(s, encoding="utf-8").read()
        for name in (candidates or HEADING_LEVELS):
            if f'AppliedParagraphStyle="ParagraphStyle/{name.replace(":", "%3a")}"' in raw:
                used.add(name)
    for name in (candidates or HEADING_LEVELS):
        if name in used:
            return name
    return (candidates or HEADING_LEVELS)[0]


def chapter_style_for(build):
    """The heading level that carries a tab and a section.

    `tab_level` in the manual's config wins, because this is an editorial choice
    that cannot be inferred: DM42n has 5 lvl1 parts and 23 lvl2 sections and wants
    the tabs on lvl2, where taking the topmost level would give 5 tabs. Without a
    declaration, fall back to the shallowest level actually present.
    """
    import manualconf
    declared = manualconf.load(build)["chapter_style"]
    return declared or topmost_heading(build)


def detect_chapters(build, chapter_style=None):
    if chapter_style is None:
        chapter_style = chapter_style_for(build)
    style_self = "ParagraphStyle/" + chapter_style.replace(":", "%3a")
    ordered_pages, frames_by_story, pages_by_spread = load_layout(build)
    page_index = {p["self"]: i for i, p in enumerate(ordered_pages)}

    chapters = []
    for s in glob.glob(os.path.join(build, "Stories", "*.xml")):
        raw = open(s, encoding="utf-8").read()
        if f'AppliedParagraphStyle="{style_self}"' not in raw:
            continue
        t = ET.fromstring(raw)
        story_self = next(e for e in t.iter()
                          if local(e.tag) == "Story" and e.get("Self")).get("Self")
        head_text = None
        for psr in t.iter():
            if local(psr.tag) == "ParagraphStyleRange" and \
                    psr.get("AppliedParagraphStyle", "").endswith(chapter_style.replace(":", "%3a")):
                head_text = content_text(psr).strip()
                break
        frames = frames_by_story.get(story_self, [])
        head = next((f for f in frames if f["prev"] == "n"), None)
        page = page_for_frame(head, pages_by_spread) if head else None
        if page is None:
            print(f"  WARN: no start page found for story {story_self} ({head_text!r})", file=sys.stderr)
            continue
        num, title = split_heading(head_text)
        chapters.append(dict(story=story_self, number=num, title=title,
                             heading=head_text, page=page,
                             page_order=page_index[page["self"]]))
    chapters.sort(key=lambda c: c["page_order"])

    return chapters, ordered_pages


def warn_crowded_stories(build, chapter_style):
    """Report chapter headings that share a story. Called from the CLI only —
    four tools call detect_chapters, and the warning should be said once."""
    extra = count_extra_headings(build, chapter_style)
    if not extra:
        return
    lost = sum(extra.values())
    print(f"  WARNING: {lost} chapter heading(s) share a story with another and will "
          f"NOT get their own tab or section.", file=sys.stderr)
    for sid, n in list(extra.items())[:5]:
        print(f"           story {sid} holds {n + 1} '{chapter_style}' headings",
              file=sys.stderr)
    print(f"           the model is one story per section — split them in InDesign, "
          f"or lower tab_level.", file=sys.stderr)


def paragraphs_in(psr):
    """The paragraphs inside a ParagraphStyleRange — it can hold several, split by <Br/>."""
    cur, out = [], []
    for e in psr.iter():
        tag = local(e.tag)
        if tag == "Content":
            cur.append(e.text or "")
        elif tag == "Br":
            out.append("".join(cur).strip())
            cur = []
    out.append("".join(cur).strip())
    return [o for o in out if o]


def count_extra_headings(build, chapter_style):
    """{story: how many chapter headings BEYOND the first} for stories holding several."""
    enc = chapter_style.replace(":", "%3a")
    extra = {}
    for p in glob.glob(os.path.join(build, "Stories", "*.xml")):
        raw = open(p, encoding="utf-8").read()
        if enc not in raw:
            continue
        n = 0
        for psr in ET.fromstring(raw).iter():
            if local(psr.tag) != "ParagraphStyleRange":
                continue
            if psr.get("AppliedParagraphStyle", "").endswith(enc):
                n += len(paragraphs_in(psr))
        if n > 1:
            sid = re.search(r'<Story\b[^>]*Self="([^"]+)"', raw)
            extra[sid.group(1) if sid else os.path.basename(p)] = n - 1
    return extra


def split_heading(text):
    """'5 Entering and displaying numbers' -> ('5', 'Entering and displaying numbers')."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)\s+(.*)", text or "")
    if m:
        return m.group(1), m.group(2).strip()
    return "", (text or "").strip()


# --------------------------------------------------------------------------- #
# Section block generation
# --------------------------------------------------------------------------- #
def compute_sections(chapters, ordered_pages):
    total = len(ordered_pages)
    starts = [c["page_order"] for c in chapters]
    secs = []
    for i, c in enumerate(chapters):
        end = starts[i + 1] if i + 1 < len(chapters) else total
        secs.append(dict(chapter=c, length=end - starts[i],
                         page_start_self=c["page"]["self"],
                         page_start_name=c["page"]["name"]))
    return secs


def mint_ids(n, existing):
    ids, k = [], 0x9F0001
    while len(ids) < n:
        cand = "u%x" % k
        if cand not in existing:
            ids.append(cand)
        k += 1
    return ids


def render_sections(secs, existing_ids, reuse_first=None):
    total_alt = sum(s["length"] for s in secs)
    new_ids = mint_ids(len(secs), existing_ids)
    lines, alt_remaining = [], total_alt
    for i, s in enumerate(secs):
        self_id = reuse_first if (i == 0 and reuse_first) else new_ids[i]
        alt_layout = "A5 V" if i == 0 else ""
        marker = xml_escape(s["chapter"]["title"])
        lines.append(
            f'\t<Section Self="{self_id}" Length="{s["length"]}" '
            f'AlternateLayoutLength="{alt_remaining}" AlternateLayout="{alt_layout}" '
            f'Name="" ContinueNumbering="true" IncludeSectionPrefix="false" '
            f'Marker="{marker}" PageStart="{s["page_start_self"]}" SectionPrefix="">')
        lines.append('\t\t<Properties>')
        lines.append('\t\t\t<PageNumberStyle type="enumeration">Arabic</PageNumberStyle>')
        lines.append('\t\t</Properties>')
        lines.append('\t</Section>')
        alt_remaining -= s["length"]
    return "\n".join(lines)


def xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def rewrite_designmap(build, sections_xml):
    path = os.path.join(build, "designmap.xml")
    dm = open(path, encoding="utf-8").read()
    # Replace the contiguous run of <Section>...</Section> blocks with ours.
    first = dm.find("<Section ")
    last = dm.rfind("</Section>")
    if first == -1 or last == -1:
        raise SystemExit("no <Section> block found in designmap.xml")
    # extend 'first' back to its leading tab, 'last' forward to end of line
    line_start = dm.rfind("\n", 0, first) + 1
    line_end = dm.find("\n", last)
    new_dm = dm[:line_start] + sections_xml + dm[line_end:]
    open(path, "w", encoding="utf-8").write(new_dm)


def existing_self_ids(build):
    dm = open(os.path.join(build, "designmap.xml"), encoding="utf-8").read()
    return set(re.findall(r'Self="([^"]+)"', dm))


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--chapter-style", default=None,
                    help="default: the shallowest heading level present")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chapters, ordered_pages = detect_chapters(args.build, args.chapter_style)
    warn_crowded_stories(args.build, args.chapter_style or chapter_style_for(args.build))
    if not chapters:
        raise SystemExit(f"no chapters found (style {args.chapter_style})")
    secs = compute_sections(chapters, ordered_pages)

    print(f"{len(secs)} chapters across {len(ordered_pages)} pages "
          f"(marker style {args.chapter_style}):")
    for i, s in enumerate(secs, 1):
        c = s["chapter"]
        print(f"  [{i}] p{s['page_start_name']:>2} +{s['length']:>2}pp  "
              f"n={c['number'] or '-':<4} {c['title']}")

    existing = existing_self_ids(args.build)
    reuse = re.search(r'<Section Self="([^"]+)"',
                      open(os.path.join(args.build, "designmap.xml"), encoding="utf-8").read())
    sections_xml = render_sections(secs, existing, reuse_first=reuse.group(1) if reuse else None)

    if args.dry_run:
        print("\n--- generated <Section> block (dry-run, not written) ---")
        print(sections_xml)
        return
    rewrite_designmap(args.build, sections_xml)
    print(f"\nwrote {len(secs)} sections to {args.build}/designmap.xml")


if __name__ == "__main__":
    main()
