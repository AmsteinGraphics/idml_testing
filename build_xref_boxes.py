#!/usr/bin/env python3
"""Phase 3 — materialise oblique-link margin boxes from underlined words.

A submission carries underlined trigger words (CharacterStyle/link[_slant] with a
HyperlinkTextSource) already wired by a <Hyperlink> to a named destination anchor,
but NO margin boxes. For every such word whose destination resolves to a named
anchor PRESENT in the document, this creates the margin paragraph-number box:

  * a margin story  (cross_ref_par / code_styles:cross_ref / CrossReferenceSource,
    format dm32_cross_ref, cached Content = target section number),
  * an anchored <TextFrame AppliedObjectStyle="ObjectStyle/cross_ref_block">
    inserted inline into the word's link range (InDesign positions it via the
    object style — no composition geometry needed),
  * a <Hyperlink> binding the new CrossReferenceSource -> the same destination,
  * designmap registration (idPkg:Story + StoryList).

Words whose destination is not in the document (dead cross-excerpt links, page/TOC
anchors) are skipped and reported. Templates live in xref_templates/.

    build_xref_boxes.py <build_dir> [--dry-run]
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_xref as R

HERE = os.path.dirname(os.path.abspath(__file__))
NAMED = {"HyperlinkTextDestination", "ParagraphDestination"}

HYPERLINK_TMPL = (
    '\t<Hyperlink Self="{self}" Name="Référence croisée {n}" Source="{src}" '
    'Visible="false" Highlight="None" Width="Thin" BorderStyle="Solid" Hidden="false" '
    'EpubAriaRole="" HypherlinkAltText="" DestinationUniqueKey="{key}">\n'
    '\t\t<Properties>\n\t\t\t<BorderColor type="enumeration">Black</BorderColor>\n'
    '\t\t\t<Destination type="object">{dest}</Destination>\n'
    '\t\t</Properties>\n\t</Hyperlink>\n')


def load_templates():
    frame = open(f"{HERE}/xref_templates/box_frame.xml", encoding="utf-8").read()
    story = open(f"{HERE}/xref_templates/margin_story.xml", encoding="utf-8").read()
    # template ids to be substituted
    t = dict(
        frame=frame, story=story,
        frame_self=re.search(r'<TextFrame Self="([^"]+)"', frame).group(1),
        frame_parent=re.search(r'ParentStory="([^"]+)"', frame).group(1),
        story_self=re.search(r'<Story Self="([^"]+)"', story).group(1),
        crs_self=re.search(r'<CrossReferenceSource Self="([^"]+)"', story).group(1),
    )
    return t


def section_number(text, name):
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)*)", text or "")
    if m:
        return m.group(1)
    return (name or "").strip() or "?"


def make_margin_story(tmpl, sid, crs, number, n):
    s = tmpl["story"]
    s = s.replace(f'"{tmpl["story_self"]}"', f'"{sid}"')
    s = s.replace(f'Self="{tmpl["crs_self"]}"', f'Self="{crs}"')
    s = re.sub(r'(<CrossReferenceSource\b[^>]*\bName=")[^"]*(")', rf'\g<1>Hyperlien {n}\g<2>', s)
    s = re.sub(r'(<CrossReferenceSource\b.*?<Content>).*?(</Content>)',
               rf'\g<1>{number}\g<2>', s, flags=re.S)
    return s


def make_frame(tmpl, frame_self, sid):
    f = tmpl["frame"]
    f = f.replace(f'Self="{tmpl["frame_self"]}"', f'Self="{frame_self}"')
    f = f.replace(f'ParentStory="{tmpl["frame_parent"]}"', f'ParentStory="{sid}"')
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build = args.build
    tmpl = load_templates()
    ix = R.load(build)

    # collect work: underlined-word sources -> named destination present
    jobs = []           # dict(source, story, dest, number, name)
    dead = []
    for s in ix.sources.values():
        if s["kind"] != R.WORD:
            continue
        h, d = ix.resolve_source(s)
        if not h:
            continue
        if d and d["type"] in NAMED:
            jobs.append(dict(src=s, dest=d, key=h["dest_key"],
                             number=section_number(d.get("text"), d.get("name")),
                             dest_ref=d["self"]))
        else:
            dead.append(s)

    print(f"resolvable oblique links: {len(jobs)}   dead/non-named (skipped): {len(dead)}")
    for j in jobs[:8]:
        print(f"  '{j['src']['content'][:32]:32}' -> #{j['number']:8} {(j['dest'].get('text') or '')[:38]}")
    if args.dry_run:
        print("(dry-run: nothing written)")
        return

    # group jobs by body story so we can do all insertions in one pass
    by_story = {}
    for i, j in enumerate(jobs):
        j["id"] = i + 1
        j["sid"] = f"uXBs{j['id']}"
        j["frame_self"] = f"uXBf{j['id']}"
        j["crs"] = f"uXBc{j['id']}"
        j["hl"] = f"uXBh{j['id']}"
        by_story.setdefault(j["src"]["story"], []).append(j)

    new_story_files, new_story_ids, hyperlinks = [], [], []
    for story_id, sjobs in by_story.items():
        path = os.path.join(build, "Stories", f"Story_{story_id}.xml")
        body = open(path, encoding="utf-8").read()
        inserts = []           # (pos, text)
        for j in sjobs:
            src_self = j["src"]["self"]
            mm = re.search(rf'<HyperlinkTextSource\b[^>]*Self="{re.escape(src_self)}"', body)
            if not mm:
                print(f"  WARN: source {src_self} not found in body {story_id}", file=sys.stderr)
                continue
            # The box is its OWN CharacterStyleRange sibling placed immediately
            # BEFORE the word's range (matching InDesign's own structure) — the
            # anchored frame must be a well-formed child of a character range or
            # the CrossReferenceSource anchor won't bind and the xref stays empty.
            cr = body.rfind("<CharacterStyleRange", 0, mm.start())
            frame = make_frame(tmpl, j["frame_self"], j["sid"])
            box_csr = ('<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/link">\n'
                       '\t\t\t\t' + frame + '\n\t\t\t</CharacterStyleRange>\n\t\t\t')
            inserts.append((cr, box_csr))
            # margin story + hyperlink
            ms = make_margin_story(tmpl, j["sid"], j["crs"], j["number"], j["id"])
            wrapped = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                       + ms[ms.find("<idPkg:Story") if "<idPkg:Story" in ms else 0:]) \
                if not ms.lstrip().startswith("<?xml") else ms
            new_story_files.append((f"Story_{j['sid']}.xml", wrapped))
            new_story_ids.append(j["sid"])
            hyperlinks.append(HYPERLINK_TMPL.format(self=j["hl"], n=j["id"], src=j["crs"],
                                                    key=j["key"], dest=j["dest_ref"]))
        for pos, text in sorted(inserts, reverse=True):
            body = body[:pos] + text + body[pos:]
        open(path, "w", encoding="utf-8").write(body)

    for fn, xml in new_story_files:
        open(os.path.join(build, "Stories", fn), "w", encoding="utf-8").write(xml)

    # designmap: story refs, StoryList, hyperlinks
    dmp = os.path.join(build, "designmap.xml")
    d = open(dmp, encoding="utf-8").read()
    srefs = "".join(f'\t<idPkg:Story src="Stories/Story_{sid}.xml" />\n' for sid in new_story_ids)
    d = re.sub(r'(\t<idPkg:Story\b)', srefs + r'\1', d, count=1)
    d = re.sub(r'StoryList="([^"]*)"',
               lambda m: 'StoryList="' + m.group(1) + ' ' + " ".join(new_story_ids) + '"', d, count=1)
    # insert hyperlinks just before the first existing <Hyperlink, else before </Document>
    joined = "".join(hyperlinks)
    if "<Hyperlink " in d:
        d = re.sub(r'(\t<Hyperlink\b)', joined + r'\1', d, count=1)
    else:
        d = d.replace("</Document>", joined + "</Document>")
    open(dmp, "w", encoding="utf-8").write(d)

    print(f"\ngenerated {len(new_story_ids)} margin boxes "
          f"({len(new_story_ids)} stories + frames + hyperlinks)")


if __name__ == "__main__":
    main()
