#!/usr/bin/env python3
"""Make the kit authoritative: push kit design changes into a document.

    sync_from_kit.py <build_dir>                 # report drift, change nothing
    sync_from_kit.py <build_dir> --masters       # transplant the kit's masters
    sync_from_kit.py <build_dir> --all [--dry-run]

Pouring content into `kit/manual_kit.idml` gives a document that owns a COMPLETE
PRIVATE COPY of the design system — its own masters, styles, swatches, text
variables. Nothing links it back. So editing the kit afterwards changes what the
next pour inherits and nothing else, and every manual already in flight silently
keeps the old design. This is what closes that gap.

Opt in per manual, in <product>.manual:

    sync = masters              # or: masters, styles, swatches

With nothing declared this only reports, which is why build_manual.py can run it
on every build.

WHY THIS IS NOT A FILE COPY. A document page that overrides a master item stores
the MASTER ITEM'S id in the page's OverrideList — B-Base's two running-head
frames are overridden on 18 pages each in DM42n, 36 references to two ids. Drop
in the kit's master with its own ids and every one of those overrides points at
nothing. So the transplant is identity-preserving: kit items are matched to the
document's by tag and position, the DOCUMENT's ids are kept, and only genuinely
new items get minted ones. Anything still referenced that would disappear is a
hard error, not a warning.

WHAT COMES WITH IT. A master is not self-contained: it references styles,
swatches and text variables by id. Those are pulled across when the document
lacks them, or the transplanted master renders against definitions that aren't
there. Fonts are reported, never transplanted — that is a licensing question.

NOT TOUCHED: masters named S<k>, which apply_tabs.py generates per chapter from
the content, and everything that is content rather than design.
"""
import argparse
import glob
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_KIT = os.path.join(ROOT, "kit", "manual_kit.idml")

sys.path.insert(0, HERE)
import manualconf

# Attribute values that are, or contain, object ids we may have to rewrite.
ATTR = re.compile(r'\b([A-Za-z][\w:.-]*)="([^"]*)"')


def remap(xml, mapping):
    """Rewrite every id in `mapping`, in ONE pass over attribute values.

    One pass matters: kit and document ids overlap (both descend from the same
    original file), so a sequential old->new substitution can rewrite an id that
    an earlier substitution just produced. Doing it inside a single scan makes
    each token map exactly once.

    Space-separated list attributes are handled token by token, because ids live
    in OverrideList and StoryList as well as in Self and ParentStory.
    """
    if not mapping:
        return xml

    def one(m):
        name, val = m.group(1), m.group(2)
        if " " in val:
            toks = val.split(" ")
            if any(t in mapping for t in toks):
                return f'{name}="' + " ".join(mapping.get(t, t) for t in toks) + '"'
            return m.group(0)
        return f'{name}="{mapping[val]}"' if val in mapping else m.group(0)

    return ATTR.sub(one, xml)


def self_sequence(xml):
    """[(tag, self)] for every element inside a master that carries a Self, in
    document order — the sequence the kit and the document are matched on."""
    return [(m.group(1), m.group(2))
            for m in re.finditer(r'<(\w+)\b[^>]*?\bSelf="([^"]+)"', xml)]


def layers(designmap_xml):
    """[(Self, Name)] in designmap order, which is the layer stacking order."""
    return [(m.group(1), m.group(2)) for m in
            re.finditer(r'<Layer\b[^>]*?\bSelf="([^"]+)"[^>]*?\bName="([^"]*)"',
                        designmap_xml)]


def map_layers(build, kit, mint, report, dry_run):
    """{kit layer Self: this document's layer Self}, matched by NAME.

    Layers are the reference a master makes most often — every page item carries
    ItemLayer — and the ids do not agree between two documents cut from the same
    original: the kit's `foot` is ub8 where a poured document's is uba, and every
    guide layer is offset the same way. Left unmapped, a transplanted item names a
    layer that does not exist here, and InDesign drops all of them onto the first
    layer. That is how ten `guide_*` layers arrive flattened into `foot`.

    A layer the kit has and the document does not is created, so a new guide layer
    in the kit arrives as a layer rather than as loose items.
    """
    dp = os.path.join(build, "designmap.xml")
    d = open(dp, encoding="utf-8").read()
    k_dm = kit.read("designmap.xml")
    k_layers, d_layers = layers(k_dm), layers(d)
    by_name = {n: s for s, n in d_layers}

    mapping, created = {}, []
    for k_self, name in k_layers:
        if name in by_name:
            mapping[k_self] = by_name[name]
        else:
            new = mint()
            mapping[k_self] = new
            blk = block_for(k_dm, "Layer", k_self)
            if blk:
                created.append((name, blk.replace(f'Self="{k_self}"', f'Self="{new}"')))

    if created:
        report.append(f"    + {len(created)} layer(s): "
                      + ", ".join(n for n, _ in created))
        if not dry_run:
            # keep them with the other layers, so stacking order stays sane
            last = None
            for m in re.finditer(r'[ \t]*<Layer\b[^>]*?(?:/>|</Layer>)[ \t]*\n?', d):
                last = m
            add = "".join(b for _, b in created)
            d = d[:last.end()] + add + d[last.end():] if last else \
                d.replace("</Document>", add + "</Document>")
            open(dp, "w", encoding="utf-8").write(d)

    moved = sum(1 for k, v in mapping.items() if k != v)
    if moved:
        report.append(f"    {moved} layer id(s) differ between kit and document — "
                      f"remapped by name")
    return mapping


def frame_stories(xml):
    """{item Self: the story it owns} for every element carrying a ParentStory."""
    out = {}
    for m in re.finditer(r"<\w+\b([^>]*)>", xml):
        s = re.search(r'\bSelf="([^"]+)"', m.group(1))
        p = re.search(r'\bParentStory="([^"]+)"', m.group(1))
        if s and p:
            out[s.group(1)] = p.group(1)
    return out


def master_head(xml):
    o = re.search(r"<MasterSpread\b[^>]*>", xml)
    if not o:
        return None
    g = lambda a: (re.search(rf'\b{a}="([^"]*)"', o.group(0)) or [None, ""])[1]
    return dict(self=g("Self"), name=g("Name"), prefix=g("NamePrefix"), base=g("BaseName"))


# --------------------------------------------------------------------------- #
class Kit:
    """The kit .idml, read straight out of the zip."""

    def __init__(self, path):
        if not os.path.exists(path):
            raise SystemExit(f"kit not found: {path}")
        self.path = path
        self.z = zipfile.ZipFile(path)

    def read(self, name):
        return self.z.read(name).decode("utf-8")

    def has(self, name):
        return name in self.z.namelist()

    def masters(self):
        out = {}
        for n in sorted(x for x in self.z.namelist() if x.startswith("MasterSpreads/")):
            t = self.read(n)
            h = master_head(t)
            if h:
                out[(h["prefix"], h["base"])] = dict(xml=t, **h)
        return out

    def story(self, sid):
        n = f"Stories/Story_{sid}.xml"
        return self.read(n) if self.has(n) else None


def doc_masters(build):
    out = {}
    for f in sorted(glob.glob(os.path.join(build, "MasterSpreads", "*.xml"))):
        t = open(f, encoding="utf-8").read()
        h = master_head(t)
        if h:
            out[(h["prefix"], h["base"])] = dict(path=f, xml=t, **h)
    return out


def overridden_ids(build):
    """{master item id: how many document pages override it}.

    These are the ids that must survive a transplant. An OverrideList is pairs of
    (master item, the local object overriding it); the master side is every other
    token starting at 0.
    """
    out = {}
    for f in glob.glob(os.path.join(build, "Spreads", "*.xml")):
        for m in re.finditer(r'OverrideList="([^"]*)"', open(f, encoding="utf-8").read()):
            toks = m.group(1).split()
            for i in toks[0::2]:
                out[i] = out.get(i, 0) + 1
    return out


def minter(build, extra_text=""):
    seen = set()
    for f in glob.glob(os.path.join(build, "**", "*.xml"), recursive=True):
        seen |= set(re.findall(r'"(u[0-9a-fA-F]+)"', open(f, encoding="utf-8").read()))
    seen |= set(re.findall(r'"(u[0-9a-fA-F]+)"', extra_text))
    n = [0xA00000]

    def mint():
        while True:
            c = "u%x" % n[0]          # lowercase only: uppercase crashes InDesign 2026
            n[0] += 1
            if c not in seen:
                seen.add(c)
                return c
    return mint


# --------------------------------------------------------------------------- #
# Dependencies a transplanted master drags in
# --------------------------------------------------------------------------- #
STYLE_REF = re.compile(r'\bApplied(?:Paragraph|Character|Object|Table|Cell)Style="([^"]+)"')
COLOR_REF = re.compile(r'\b(?:Fill|Stroke|Gap)Color="((?:Color|MixedInk|Gradient|Swatch)/[^"]+)"')
TVAR_REF = re.compile(r'\bAssociatedTextVariable="([^"]+)"')


def defined_ids(xml, tags):
    out = set()
    for tag in tags:
        out |= set(re.findall(rf'<{tag}\b[^>]*?\bSelf="([^"]+)"', xml))
    return out


def block_for(xml, tag, self_id):
    """The whole <tag Self="self_id"> … </tag> element, self-closing or not."""
    m = re.search(rf'[ \t]*<{tag}\b[^>]*?\bSelf="{re.escape(self_id)}"[^>]*?/>[ \t]*\n?', xml)
    if m:
        return m.group(0)
    m = re.search(rf'[ \t]*<{tag}\b[^>]*?\bSelf="{re.escape(self_id)}".*?</{tag}>[ \t]*\n?',
                  xml, re.S)
    return m.group(0) if m else None


def pull_dependencies(build, kit, added_xml, report, dry_run):
    """Copy in whatever the transplanted markup references and the document lacks.

    A master is not self-contained. Left alone, a frame whose AppliedObjectStyle
    or FillColor names something absent renders wrong or refuses to import — and
    a text variable is the case that started this: its definition lives in
    designmap.xml while its use lives in a master's story, so bringing the master
    without the definition brings half a feature.
    """
    sp = os.path.join(build, "Resources", "Styles.xml")
    gp = os.path.join(build, "Resources", "Graphic.xml")
    dp = os.path.join(build, "designmap.xml")
    styles, graphic, dmap = (open(p, encoding="utf-8").read() for p in (sp, gp, dp))
    k_styles = kit.read("Resources/Styles.xml")
    k_graphic = kit.read("Resources/Graphic.xml")
    k_dmap = kit.read("designmap.xml")

    added = {"styles": [], "colours": [], "text variables": [], "fonts": []}

    # --- styles, following BasedOn / NextStyle so a chain arrives whole --------
    STYLE_TAGS = ("ParagraphStyle", "CharacterStyle", "ObjectStyle", "TableStyle", "CellStyle")
    have = defined_ids(styles, STYLE_TAGS)
    queue = [s for s in set(STYLE_REF.findall(added_xml)) if s not in have]
    while queue:
        sid = queue.pop()
        if sid in have:
            continue
        tag = sid.split("/", 1)[0]
        blk = block_for(k_styles, tag, sid)
        if blk is None:
            report.append(f"    ! {sid} referenced but not in the kit either")
            have.add(sid)
            continue
        have.add(sid)
        added["styles"].append(sid)
        styles = styles.replace("</idPkg:Styles>", blk + "</idPkg:Styles>")
        for dep in re.findall(r"<(?:BasedOn|NextStyle)[^>]*>([^<]+)<", blk):
            if dep not in have:
                queue.append(dep.strip())

    # --- colours: a MixedInk also needs its ColorGroupSwatch in designmap ------
    have_c = defined_ids(graphic, ("Color", "MixedInk", "Gradient", "Swatch", "Ink"))
    for ref in sorted(set(COLOR_REF.findall(added_xml))):
        if ref in have_c or ref.startswith("Swatch/"):
            continue
        tag = ref.split("/", 1)[0]
        blk = block_for(k_graphic, tag, ref)
        if blk is None:
            report.append(f"    ! {ref} referenced but not in the kit either")
            continue
        added["colours"].append(ref)
        graphic = graphic.replace("</idPkg:Graphic>", blk + "</idPkg:Graphic>")
        if tag == "MixedInk":
            cgs = re.search(rf'[ \t]*<ColorGroupSwatch\b[^>]*SwatchItemRef="{re.escape(ref)}"'
                            rf'[^>]*/>[ \t]*\n?', k_dmap)
            if cgs and 'SwatchItemRef="%s"' % ref not in dmap:
                dmap = re.sub(r"(</ColorGroup>)", cgs.group(0) + r"\1", dmap, count=1)

    # --- text variables: the definition is in designmap, the use is in a story -
    have_v = set(re.findall(r'<TextVariable\b[^>]*?\bSelf="([^"]+)"', dmap))
    for ref in sorted(set(TVAR_REF.findall(added_xml))):
        if ref in have_v:
            continue
        blk = block_for(k_dmap, "TextVariable", ref)
        if blk is None:
            report.append(f"    ! text variable {ref} referenced but not in the kit either")
            continue
        added["text variables"].append(ref)
        dmap = dmap.replace("</Document>", blk + "</Document>")

    # --- fonts are reported, never transplanted -------------------------------
    have_f = set(re.findall(r'<FontFamily\b[^>]*?\bName="([^"]*)"',
                            open(os.path.join(build, "Resources", "Fonts.xml"),
                                 encoding="utf-8").read())) \
        if os.path.exists(os.path.join(build, "Resources", "Fonts.xml")) else set()
    for fam in sorted(set(re.findall(r'<AppliedFont[^>]*>([^<]+)<', added_xml))):
        if have_f and fam not in have_f:
            added["fonts"].append(fam)

    for kind, items in added.items():
        if items:
            report.append(f"    + {len(items)} {kind}: "
                          + ", ".join(x.split("/", 1)[-1] for x in items[:6])
                          + (" …" if len(items) > 6 else ""))
    if added["fonts"]:
        report.append("    ! fonts above are NOT transplanted — install/licence them "
                      "and add to the document in InDesign")
    if not dry_run:
        for p, t in ((sp, styles), (gp, graphic), (dp, dmap)):
            open(p, "w", encoding="utf-8").write(t)
    return added


# --------------------------------------------------------------------------- #
def plan_master(k_master, d_master, mint):
    """Work out one master's id mapping WITHOUT writing anything.

    Planning is separated from writing because a master's references are not all
    local. Three kinds cross the file boundary, and every one of them was a bug
    found the hard way:

      ItemLayer      -> a Layer in designmap. The commonest reference of all —
                        every page item has one — and the ids do not agree between
                        two documents cut from the same original.
      AppliedMaster  -> another master, when one is based on another.
      OverrideList   -> items belonging to ANOTHER master, when a master overrides
                        what it inherits.

    So no master can be rewritten until every master's mapping is known. The
    per-master part is positional: the Nth <TextFrame> of the kit master becomes
    the Nth <TextFrame> of the document's, which is predictable and explains itself
    in the report. Items the kit adds get fresh ids; items it no longer has go.
    """
    k_seq, d_seq = self_sequence(k_master["xml"]), self_sequence(d_master["xml"])
    pos = {}
    for tag, sid in d_seq:
        pos.setdefault(tag, []).append(sid)
    used = {t: 0 for t in pos}

    mapping, minted = {}, 0
    for tag, sid in k_seq:
        i = used.get(tag, 0)
        if tag in pos and i < len(pos[tag]):
            mapping[sid] = pos[tag][i]
            used[tag] = i + 1
        else:
            mapping[sid] = mint()
            minted += 1
    kept = set(mapping.values())
    dropped_items = [s for _, s in d_seq if s not in kept]

    # Stories are matched THROUGH the frames that own them, not by id: a story id
    # is a reference, never a Self inside the master, so keying it off the item map
    # would never match and every build would mint a fresh set — churning StoryList
    # and the designmap on a run that changed nothing. Going via the owning frame
    # keeps a frame's story id stable, which is what makes this idempotent.
    k_fs, d_fs = frame_stories(k_master["xml"]), frame_stories(d_master["xml"])
    d_stories = set(d_fs.values())
    story_map, claimed = {}, set()
    for k_item, k_story in k_fs.items():
        if k_story in story_map:
            continue
        d_story = d_fs.get(mapping.get(k_item))
        # never let two kit stories land on one document story: a story belongs to
        # exactly one frame chain, and sharing it corrupts the document
        if d_story and d_story not in claimed:
            story_map[k_story] = d_story
            claimed.add(d_story)
    for k_story in sorted(set(k_fs.values())):
        story_map.setdefault(k_story, mint())
    mapping.update(story_map)

    new_ids = [v for v in story_map.values() if v not in d_stories]
    dropped_stories = sorted(d_stories - set(story_map.values()))

    return dict(mapping=mapping, story_map=story_map, new_ids=new_ids,
                dropped_stories=dropped_stories, items=len(k_seq), minted=minted,
                dropped_items=len(dropped_items))


def write_master(build, kit, plan, k_master, d_master, gmap, report, dry_run):
    """Rewrite one master and its stories using the GLOBAL id map."""
    new_master = remap(k_master["xml"], gmap)
    # the document keeps its own master Self, so every AppliedMaster pointing at
    # it — on pages and on masters based on it — is untouched by construction
    new_master = re.sub(r'(<MasterSpread\b[^>]*?\bSelf=")[^"]*(")',
                        rf'\g<1>{d_master["self"]}\g<2>', new_master, count=1)

    story_files = []
    for k_sid, d_sid in sorted(plan["story_map"].items()):
        sx = kit.story(k_sid)
        if sx is None:
            report.append(f"    ! kit story {k_sid} missing from the kit package")
            continue
        story_files.append((d_sid, remap(sx, gmap)))

    report.append(f"  {d_master['name']}: {plan['items']} items "
                  f"({plan['minted']} new, {plan['dropped_items']} dropped), "
                  f"{len(story_files)} stories ({len(plan['new_ids'])} new, "
                  f"{len(plan['dropped_stories'])} dropped)")

    if not dry_run:
        open(d_master["path"], "w", encoding="utf-8").write(new_master)
        for sid, sx in story_files:
            open(os.path.join(build, "Stories", f"Story_{sid}.xml"), "w",
                 encoding="utf-8").write(sx)
        for sid in plan["dropped_stories"]:
            p = os.path.join(build, "Stories", f"Story_{sid}.xml")
            if os.path.exists(p):
                os.remove(p)
    return new_master + "".join(x for _, x in story_files)


def register_stories(build, new_ids, dropped_ids):
    dp = os.path.join(build, "designmap.xml")
    d = open(dp, encoding="utf-8").read()
    for sid in dropped_ids:
        d = re.sub(r'[ \t]*<idPkg:Story\b[^>]*Story_%s\.xml"[^>]*/>\s*\n?'
                   % re.escape(sid), "", d)
    if new_ids:
        refs = "".join(f'\t<idPkg:Story src="Stories/Story_{s}.xml" />\n' for s in new_ids)
        d = re.sub(r"(\t<idPkg:Story\b)", refs + r"\1", d, count=1) if "<idPkg:Story" in d \
            else d.replace("</Document>", refs + "</Document>")
    m = re.search(r'StoryList="([^"]*)"', d)
    if m:
        keep = [s for s in m.group(1).split() if s not in set(dropped_ids)]
        d = re.sub(r'StoryList="[^"]*"',
                   'StoryList="' + " ".join(keep + list(new_ids)) + '"', d, count=1)
    open(dp, "w", encoding="utf-8").write(d)


# --------------------------------------------------------------------------- #
def sync(build, kit_path=DEFAULT_KIT, parts=(), dry_run=False, force=False):
    kit = Kit(kit_path)
    K, D = kit.masters(), doc_masters(build)
    report = [f"kit: {os.path.relpath(kit_path)}"]

    # S<k> masters are generated per chapter by apply_tabs.py from the content;
    # the kit has none and must never be allowed to imply deleting them
    generated = {k for k in D if re.fullmatch(r"S\d+", k[0] or "")}
    matched = sorted(set(K) & set(D))
    kit_only = sorted(set(K) - set(D))
    doc_only = sorted(set(D) - set(K) - generated)

    report.append(f"masters: {len(matched)} matched, {len(kit_only)} kit-only, "
                  f"{len(doc_only)} document-only, {len(generated)} generated (untouched)")
    for k in kit_only:
        report.append(f"  + kit has {k[0]}-{k[1]}, this document does not")
    for k in doc_only:
        report.append(f"  - document has {k[0]}-{k[1]}, the kit does not (left alone)")

    if "masters" not in parts:
        report.append("  (reporting only — declare `sync = masters` in the manual's "
                      "config to transplant)")
        return report, False

    before = overridden_ids(build)
    mint = minter(build, kit.read("designmap.xml"))

    # ---- PLAN: every mapping resolved before a single file is rewritten ------
    # Masters reference each other (AppliedMaster), each other's items
    # (OverrideList on an inherited item) and the document's layers (ItemLayer).
    # Rewriting one master at a time with only its own map left all three
    # pointing at kit ids — which is how ten guide_* layers ended up flattened
    # into `foot`: the layer named there did not exist, so InDesign put every
    # orphaned item on the first layer it had.
    gmap = {K[k]["self"]: D[k]["self"] for k in matched}
    gmap.update(map_layers(build, kit, mint, report, dry_run))
    plans = {}
    for key in matched:
        p = plan_master(K[key], D[key], mint)
        plans[key] = p
        gmap.update(p["mapping"])

    # ---- WRITE --------------------------------------------------------------
    added_xml, new_ids, dropped_ids = "", [], []
    for key in matched:
        added_xml += write_master(build, kit, plans[key], K[key], D[key], gmap,
                                  report, dry_run)
        new_ids += plans[key]["new_ids"]
        dropped_ids += plans[key]["dropped_stories"]

    # An override whose master item vanished is a page pointing into empty space.
    # Refuse rather than produce it: the fix is a human decision about whether the
    # override was still wanted, not something to guess at.
    if not dry_run:
        alive = set()
        for f in glob.glob(os.path.join(build, "MasterSpreads", "*.xml")):
            alive |= {s for _, s in self_sequence(open(f, encoding="utf-8").read())}
        lost = {i: n for i, n in before.items() if i not in alive}
        if lost and not force:
            raise SystemExit(
                "transplant would orphan page overrides:\n  "
                + "\n  ".join(f"{i} is overridden on {n} page(s) and no longer exists"
                              for i, n in sorted(lost.items()))
                + "\nThe kit master no longer has the item those pages override. Either "
                  "keep the item\nin the kit, or clear the overrides in InDesign first. "
                  "--force proceeds anyway.")
        if lost:
            report.append(f"  ! FORCED: {sum(lost.values())} page override(s) orphaned")

    if not dry_run:
        register_stories(build, new_ids, dropped_ids)
    pull_dependencies(build, kit, added_xml, report, dry_run)
    if before:
        report.append(f"  {len(before)} overridden master item(s) preserved "
                      f"({sum(before.values())} page overrides)")
    return report, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--kit", default=DEFAULT_KIT)
    ap.add_argument("--masters", action="store_true", help="transplant the kit's masters")
    ap.add_argument("--all", action="store_true", help="everything syncable")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="proceed even if page overrides would be orphaned")
    args = ap.parse_args()

    parts = list(manualconf.load(args.build)["sync"])
    if args.masters or args.all:
        parts = sorted(set(parts) | ({"masters"} if args.masters else manualconf.SYNCABLE))
    report, changed = sync(args.build, args.kit, parts, args.dry_run, args.force)
    print("\n".join(report))
    if changed and not args.dry_run:
        print("synced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
