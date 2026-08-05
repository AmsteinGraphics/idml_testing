#!/usr/bin/env python3
"""Phase 3 — materialise oblique-link margin boxes; suppress + log dead links.

A submission carries underlined trigger words (CharacterStyle/link[_slant] with a
HyperlinkTextSource) already wired by a <Hyperlink> to a destination anchor, but
NO margin boxes, and the section headings carry LIVE dm32_list auto-numbering
(titles:lvl2/3/4). For every underlined word this does one of two things:

  RESOLVABLE (destination is a named anchor present in the document) -> build the
  margin box: a margin story (cross_ref_par / code_styles:cross_ref /
  CrossReferenceSource, format dm32_cross_ref, cached Content = the target's
  computed section number), an anchored <TextFrame
  AppliedObjectStyle="ObjectStyle/cross_ref_block"> inserted as its own character
  range immediately before the word's range, a <Hyperlink> binding the new source
  to the same destination, and designmap registration.

  DEAD (no hyperlink, target not in the document, or a page/TOC anchor — typically
  cross-excerpt links copy-pasted from the full manual) -> SUPPRESS it in place:
  drop the CharacterStyle/link underline, unwrap the HyperlinkTextSource (keeping
  the word text), and remove its <Hyperlink>. Every suppression AND every
  generated box is written to a CSV audit log for eyeballing.

    build_xref_boxes.py <build_dir> [--dry-run] [--log PATH] [--keep-dead]

`--keep-dead` leaves dead links untouched (still logged). Default log path is
<build_dir>.xref_log.csv (a sibling, never packed into the .idml). Templates live
in xref_templates/.
"""
import argparse
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_xref as R
import sectionize as S

HERE = os.path.dirname(os.path.abspath(__file__))
NAMED = {"HyperlinkTextDestination", "ParagraphDestination"}
LEVELS = {"titles:lvl2": 1, "titles:lvl3": 2, "titles:lvl4": 3}

HYPERLINK_TMPL = (
    '\t<Hyperlink Self="{self}" Name="Référence croisée {n}" Source="{src}" '
    'Visible="false" Highlight="None" Width="Thin" BorderStyle="Solid" Hidden="false" '
    'EpubAriaRole="" HypherlinkAltText="" DestinationUniqueKey="{key}">\n'
    '\t\t<Properties>\n\t\t\t<BorderColor type="enumeration">Black</BorderColor>\n'
    '\t\t\t<Destination type="object">{dest}</Destination>\n'
    '\t\t</Properties>\n\t</Hyperlink>\n')


def local(t):
    return t.split("}")[-1]


# Frame attributes introduced after DOMVersion 20.0 that a native 20.0 frame does
# not carry; strip them so the v1.76-sourced template matches the target document.
POST20_FRAME_ATTRS = ["BeforeGroupingLayerPosition", "FlexItemHeightMode", "FlexItemWidthMode",
                      "Locked", "OverprintFill", "OverprintGap", "OverprintStroke"]


def load_templates():
    frame = open(f"{HERE}/xref_templates/box_frame.xml", encoding="utf-8").read()
    story = open(f"{HERE}/xref_templates/margin_story.xml", encoding="utf-8").read()
    return dict(
        frame=frame, story=story,
        frame_self=re.search(r'<TextFrame Self="([^"]+)"', frame).group(1),
        frame_parent=re.search(r'ParentStory="([^"]+)"', frame).group(1),
        story_self=re.search(r'<Story Self="([^"]+)"', story).group(1),
        crs_self=re.search(r'<CrossReferenceSource Self="([^"]+)"', story).group(1),
    )


# --------------------------------------------------------------------------- #
# Live section numbers: walk lvl2/3/4 headings in reading order and map each
# destination anchor to the number of the heading paragraph it sits in.
# --------------------------------------------------------------------------- #
def compute_section_numbers(build):
    chapters, _ = S.detect_chapters(build, "titles:lvl2")
    counters = [0, 0, 0]
    key_to_number = {}
    for c in chapters:
        path = os.path.join(build, "Stories", f"Story_{c['story']}.xml")
        t = ET.fromstring(open(path, encoding="utf-8").read())
        for psr in t.iter():
            if local(psr.tag) != "ParagraphStyleRange":
                continue
            style = psr.get("AppliedParagraphStyle", "").split("/")[-1].replace("%3a", ":")
            lvl = LEVELS.get(style)
            if not lvl:
                continue
            counters[lvl - 1] += 1
            for j in range(lvl, 3):
                counters[j] = 0
            number = ".".join(str(counters[i]) for i in range(lvl))
            for d in psr.iter():
                if local(d.tag) in ("HyperlinkTextDestination", "ParagraphDestination"):
                    k = d.get("DestinationUniqueKey")
                    if k:
                        key_to_number[k] = number
    return key_to_number


def make_margin_story(tmpl, sid, crs, number, n):
    s = tmpl["story"]
    s = s.replace(f'"{tmpl["story_self"]}"', f'"{sid}"')
    s = s.replace(f'Self="{tmpl["crs_self"]}"', f'Self="{crs}"')
    s = re.sub(r'(<CrossReferenceSource\b[^>]*\bName=")[^"]*(")', rf'\g<1>Hyperlien {n}\g<2>', s)
    s = re.sub(r'(<CrossReferenceSource\b.*?<Content>).*?(</Content>)',
               rf'\g<1>{number}\g<2>', s, flags=re.S)
    return s


def make_margin_story_static(tmpl, sid, number):
    """Margin story whose number is PLAIN TEXT (no CrossReferenceSource).

    A live Paragraph-Number cross-reference re-resolves to empty on IDML import
    for these text-anchor destinations; a print manual bakes the numbers anyway,
    so static text is reliable and matches the flattened export state.
    """
    s = tmpl["story"].replace(f'"{tmpl["story_self"]}"', f'"{sid}"')
    # collapse the whole <CrossReferenceSource ...>…<Content>NN</Content>…</…> to the number
    s = re.sub(r'<CrossReferenceSource\b.*?</CrossReferenceSource>',
               f'<Content>{number}</Content>', s, flags=re.S)
    return s


def make_frame(tmpl, frame_self, sid):
    f = tmpl["frame"].replace(f'Self="{tmpl["frame_self"]}"', f'Self="{frame_self}"')
    f = f.replace(f'ParentStory="{tmpl["frame_parent"]}"', f'ParentStory="{sid}"')
    # Keep the template's ParentInterfaceChangeCount verbatim: in a real InDesign
    # file every one of the 56 cross-ref boxes shares the SAME value and they all
    # render, so a shared non-empty value is correct — blanking it breaks binding.
    return f


def dead_reason(h, d):
    if not h:
        return "no-hyperlink"
    if d is None:
        return "target-not-in-document"
    return f"non-named-anchor({d['type']})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", default=None, help="CSV audit log path (default <build>.xref_log.csv)")
    ap.add_argument("--keep-dead", action="store_true", help="do not suppress dead links (still logged)")
    ap.add_argument("--static", action="store_true",
                    help="put the section number in the box as plain text instead of a live "
                         "cross-reference (reliable for print; no auto-update)")
    ap.add_argument("--jsx", action="store_true",
                    help="do NOT author boxes in IDML (InDesign won't bind hand-authored "
                         "anchored frames); only suppress dead links + log. Create the boxes "
                         "afterwards by running place_xref_boxes.jsx in InDesign.")
    args = ap.parse_args()
    build = args.build.rstrip("/\\")
    log_path = args.log or (build + ".xref_log.csv")

    tmpl = load_templates()
    ix = R.load(build)
    key_to_number = compute_section_numbers(build)

    # The templates come from v1.76 (DOMVersion 21.4); the target document may be
    # an older version (test2 is 20.0). A version-mismatched idPkg:Story is not
    # bound to its anchored frame by InDesign — the box renders empty. Rewrite the
    # generated stories to the document's own DOMVersion.
    doc_dom = re.search(r'DOMVersion="([^"]*)"',
                        open(os.path.join(build, "designmap.xml"), encoding="utf-8").read()).group(1)
    tmpl["story"] = re.sub(r'(<idPkg:Story\b[^>]*DOMVersion=")[^"]*(")', rf'\g<1>{doc_dom}\g<2>', tmpl["story"])
    # Only downgrade the v1.76 (21.4) frame to a pre-21 attribute set when the
    # target document is actually older than v21; a 21.x target keeps them.
    if int(doc_dom.split(".")[0]) < 21:
        for attr in POST20_FRAME_ATTRS:
            tmpl["frame"] = re.sub(rf'\s+{attr}="[^"]*"', '', tmpl["frame"], count=1)

    jobs, dead = [], []
    for s in ix.sources.values():
        if s["kind"] != R.WORD:
            continue
        h, d = ix.resolve_source(s)
        if d and d["type"] in NAMED:
            jobs.append(dict(src=s, dest=d, key=h["dest_key"],
                             number=key_to_number.get(h["dest_key"], ""),
                             dest_ref=d["self"]))
        else:
            dead.append(dict(src=s, reason=dead_reason(h, d),
                             key=(h["dest_key"] if h else "")))

    print(f"resolvable oblique links: {len(jobs)}   dead links: {len(dead)}"
          f"   ({'suppress' if not args.keep_dead else 'keep'} + log -> {os.path.basename(log_path)})")
    for j in jobs[:6]:
        print(f"  box  '{j['src']['content'][:30]:30}' -> #{j['number'] or '(live)':8} "
              f"{(j['dest'].get('text') or '')[:34]}")
    for x in dead[:4]:
        print(f"  dead '{x['src']['content'][:30]:30}'  {x['reason']}")
    if args.dry_run:
        print("(dry-run: nothing written)")
        return

    # ---- assign ids + group by body story --------------------------------- #
    # InDesign resolves an anchored frame's ParentStory strictly; ids must be
    # lowercase-hex "u<hex>" like its own (uppercase ids leave the frame unlinked
    # and blank). Mint from a high base that can't collide with existing ids.
    existing = set(re.findall(r'"(u[0-9a-fA-F]+)"', open(os.path.join(build, "designmap.xml"), encoding="utf-8").read()))
    counter = [0x900000]

    def mint():
        while True:
            c = "u%x" % counter[0]
            counter[0] += 1
            if c not in existing:
                existing.add(c)
                return c

    by_story = {}
    for i, j in enumerate(jobs):
        j["id"] = i + 1
        j["sid"] = mint()
        j["frame_self"] = mint()
        j["crs"] = mint()
        j["hl"] = mint()
        by_story.setdefault(j["src"]["story"], []).append(("box", j))
    if not args.keep_dead:
        for x in dead:
            by_story.setdefault(x["src"]["story"], []).append(("dead", x))

    new_story_files, new_story_ids, hyperlinks = [], [], []
    dead_source_ids = set()      # to drop their hyperlinks from designmap
    log_rows = []

    for story_id, items in by_story.items():
        path = os.path.join(build, "Stories", f"Story_{story_id}.xml")
        body = open(path, encoding="utf-8").read()
        splices = []             # (start, end, replacement)

        for kind, obj in items:
            src_self = obj["src"]["self"]
            mm = re.search(rf'<HyperlinkTextSource\b[^>]*Self="{re.escape(src_self)}"', body)
            if not mm:
                print(f"  WARN: source {src_self} not found in {story_id}", file=sys.stderr)
                continue
            cr = body.rfind("<CharacterStyleRange", 0, mm.start())
            cr_gt = body.find(">", cr)

            if kind == "box":
                j = obj
                if args.jsx:
                    # Box creation is deferred to place_xref_boxes.jsx (InDesign
                    # binds anchored frames its DOM creates; IDML-authored ones
                    # import empty). Just record the intended box.
                    log_rows.append(dict(action="jsx-box", word=obj["src"]["content"],
                                         dest_key=j["key"], number=j["number"],
                                         target=(j["dest"].get("text") or ""),
                                         story=story_id, reason="deferred-to-jsx"))
                    continue
                # The box must land inside the OPEN CharacterStyleRange that holds
                # the word (v1.76: frame then HyperlinkTextSource in one range).
                # Some sources are index entries (a HyperlinkTextSource carrying a
                # PageReference) that sit directly under the paragraph, preceded by
                # an empty self-closed CSR — inserting there would orphan the frame,
                # so skip + log those rather than malform the file.
                cr_open_end = body.find(">", cr) + 1
                open_tag = body[cr:cr_open_end]
                between = body[cr_open_end:mm.start()]
                in_open_range = (not open_tag.rstrip().endswith("/>")) and \
                    ("</CharacterStyleRange>" not in between)
                if not in_open_range:
                    log_rows.append(dict(action="skipped", word=obj["src"]["content"],
                                         dest_key=j["key"], number=j["number"],
                                         target=(j["dest"].get("text") or ""),
                                         story=story_id, reason="complex-source-structure"))
                    continue
                frame = make_frame(tmpl, j["frame_self"], j["sid"])
                splices.append((mm.start(), mm.start(), frame + "\n\t\t\t\t"))
                if args.static:
                    ms = make_margin_story_static(tmpl, j["sid"], j["number"])
                else:
                    ms = make_margin_story(tmpl, j["sid"], j["crs"], j["number"], j["id"])
                    hyperlinks.append(HYPERLINK_TMPL.format(self=j["hl"], n=j["id"], src=j["crs"],
                                                            key=j["key"], dest=j["dest_ref"]))
                new_story_files.append((f"Story_{j['sid']}.xml", ms))
                new_story_ids.append(j["sid"])
                log_rows.append(dict(action="box", word=obj["src"]["content"],
                                     dest_key=j["key"], number=j["number"],
                                     target=(j["dest"].get("text") or j["dest"].get("name") or ""),
                                     story=story_id, reason="resolvable"))
            else:  # dead -> suppress
                # 1) de-underline: strip CharacterStyle/link on the wrapping range
                open_tag = body[cr:cr_gt + 1]
                new_open = re.sub(r'AppliedCharacterStyle="CharacterStyle/link(_slant)?"',
                                  'AppliedCharacterStyle="$ID/[No character style]"', open_tag)
                if new_open != open_tag:
                    splices.append((cr, cr_gt + 1, new_open))
                # 2) unwrap the HyperlinkTextSource, keep its inner text
                hm = re.search(rf'<HyperlinkTextSource\b[^>]*Self="{re.escape(src_self)}"[^>]*>(.*?)</HyperlinkTextSource>',
                               body, re.S)
                if hm:
                    splices.append((hm.start(), hm.end(), hm.group(1)))
                dead_source_ids.add(src_self)
                log_rows.append(dict(action="suppressed", word=obj["src"]["content"],
                                     dest_key=obj["key"], number="",
                                     target="", story=story_id, reason=obj["reason"]))

        for start, end, repl in sorted(splices, key=lambda s: s[0], reverse=True):
            body = body[:start] + repl + body[end:]
        open(path, "w", encoding="utf-8").write(body)

    for fn, xml in new_story_files:
        open(os.path.join(build, "Stories", fn), "w", encoding="utf-8").write(xml)

    # ---- designmap: register new stories/hyperlinks, drop dead hyperlinks -- #
    dmp = os.path.join(build, "designmap.xml")
    d = open(dmp, encoding="utf-8").read()
    if new_story_ids:
        srefs = "".join(f'\t<idPkg:Story src="Stories/Story_{sid}.xml" />\n' for sid in new_story_ids)
        d = re.sub(r'(\t<idPkg:Story\b)', srefs + r'\1', d, count=1)
        d = re.sub(r'StoryList="([^"]*)"',
                   lambda m: 'StoryList="' + m.group(1) + ' ' + " ".join(new_story_ids) + '"', d, count=1)
    if hyperlinks:
        joined = "".join(hyperlinks)
        d = re.sub(r'(\t<Hyperlink\b)', joined + r'\1', d, count=1) if "<Hyperlink " in d \
            else d.replace("</Document>", joined + "</Document>")
    if dead_source_ids:
        d = re.sub(r'\t<Hyperlink\b[^>]*Source="([^"]+)"[^>]*>.*?</Hyperlink>\n?',
                   lambda m: "" if m.group(1) in dead_source_ids else m.group(0), d, flags=re.S)
        d = re.sub(r'\t<Hyperlink\b[^>]*Source="([^"]+)"[^>]*/>\n?',
                   lambda m: "" if m.group(1) in dead_source_ids else m.group(0), d)
    open(dmp, "w", encoding="utf-8").write(d)

    # ---- write audit log -------------------------------------------------- #
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["action", "word", "dest_key", "number", "target", "story", "reason"])
        w.writeheader()
        w.writerows(sorted(log_rows, key=lambda r: (r["action"], r["word"].lower())))

    n_supp = sum(1 for r in log_rows if r["action"] == "suppressed")
    if args.jsx:
        n_box = sum(1 for r in log_rows if r["action"] == "jsx-box")
        print(f"\nsuppressed {n_supp} dead links; {n_box} oblique links ready for boxes.")
        print("NEXT: open this file in InDesign and run place_xref_boxes.jsx to create the boxes.")
    else:
        print(f"\ngenerated {len(new_story_ids)} margin boxes; "
              f"{'suppressed ' + str(n_supp) if not args.keep_dead else 'kept ' + str(len(dead))} dead links")
    print(f"audit log: {log_path} ({len(log_rows)} rows)")


if __name__ == "__main__":
    main()
