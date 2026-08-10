# DM32 IDML toolchain

Python tooling for inspecting, repairing and generating [IDML](https://www.adobe.com/devnet/indesign/documentation.html)
(InDesign Markup Language) packages, built around the SwissMicros **DM32 print manual**.

> **Just want to make a manual?** Read [GUIDE.md](GUIDE.md) — three steps, six commands,
> no XML. This file is the reference for how and why it works.

Three jobs:

1. **Audit the shipped manual** — resolve and check its "oblique link" cross-reference
   system (underlined word + margin paragraph number pointing at one anchor).
2. **Derive a reusable blank template** — keep the whole design skeleton (styles,
   colours, masters, fonts, XML tags, cross-reference and index engines), strip all
   content, and regenerate the numbered thumb-tab index natively for any chapter count.
3. **Produce a manual from a submission** — take content poured into the kit and wire up
   what the design system needs: section numbering, one InDesign section per chapter,
   a per-chapter thumb tab, and the oblique-reference margin boxes.

Everything is plain `python3` with the standard library only. No InDesign and no
`unzip` are required to build; InDesign is only needed to *visually* verify output.

---

## Layout

The repo separates what stays put from what changes per manual:

```
toolchain/          the tools — one source of truth, shared by every manual
kit/
  manual_kit.idml           the house blank: styles, masters, colours, tags,
                            cross-reference + index engines. 7 masters, native
                            mixed-ink tabs, no chapter masters, no content.
  manual_kit.manual         default config: palette, hierarchy, tab ink ramp
  reference/                InDesign-authored samples kept for their schema
  derivation/               how the kit was cut from the DM32 manual (provenance)
manuals/
  dm32/
    dm32_print_manual_v1.76.idml       the shipped manual (source of truth)
    dm32_print_manual_v1.76_fixed.idml same, 2 broken oblique links repaired
    dm32.manual                        this manual's config
    submissions/                       content poured into the kit, from InDesign
    audit/                             cross-reference audit output
    build/                             working tree (not tracked)
```

**The kit and the toolchain are the standard; a manual is an instance of it.** That is
why there is one repo rather than one per manual: a copied toolchain drifts, and the
copy that keeps a fixed bug is the one you find out about last. If you later need
manuals in separate repos, `toolchain/` + `kit/` split off as their own and each manual
pins a version — the directory boundary is already the right seam.

Working trees are build products and are not tracked. Recreate one with:

```bash
python3 -c "import zipfile; zipfile.ZipFile('manuals/dm32/submissions/SUBMISSION.idml').extractall('manuals/dm32/build')"
```

> The `extracted/` tree used when the kit was derived corresponds to the **`_fixed`**
> archive, not the pristine original — they differ only in `designmap.xml`.

---

## Toolchain

### Deriving the template

| script | what it does | run |
|---|---|---|
| `toolchain/make_template.py` | strip content → blank kit: all styles / masters / colours / tags kept, one blank donor spread, 114 master-referenced stories | `make_template.py extracted template_build` |
| `toolchain/scrub_metadata.py` | reset XMP — drop History/Ingredients/Manifest/thumbnails/DerivedFrom, fresh UUID lineage so derived manuals aren't fingerprinted as the source | `scrub_metadata.py template_build/META-INF/metadata.xml` |
| `toolchain/prune_swatches.py` | InDesign-style "delete unused swatches"; protects structural swatches + the sanctioned palette, cascades to a fixed point | `prune_swatches.py template_build [--dry-run]` |
| `toolchain/prune_styles.py` | report/remove styles dead in the **full manual** (not the empty template) with closure over every style-reference edge | `prune_styles.py template_build --ref extracted --dry-run` |
| `toolchain/bake_masters.py` | recolour every tab in every tab master from the placed `.ai` to native mixed-ink swatches, preserving geometry, bleed and master filiation | `bake_masters.py template_build template_build_masters` |
| `bake_tab_strip.py`, `tab_strip.py` | earlier tab-strip proof and compute-only ink table — superseded by `bake_masters.py` | — |

### Producing a manual

| script | what it does | run |
|---|---|---|
| `toolchain/fix_numbering.py` | join `titles:lvl2`/`lvl3` to the `manual_list` numbered list so multi-level section numbering counts up | `fix_numbering.py <dir>` |
| `toolchain/sectionize.py` | detect chapters (`titles:lvl2` headings), locate each one's first page geometrically, write one `<Section>` per chapter | `sectionize.py <dir> [--dry-run]` |
| `toolchain/configure_chapters.py` | rebuild the thumb-tab strip for N chapters — **any N**, defaulting to the number detected in the document; also reconciles any existing chapter masters to N | `configure_chapters.py <dir> [--n N]` |
| `toolchain/apply_tabs.py` | build one `S<k>-<title>` master per chapter owning a single tab + number on both pages, and apply it to that chapter's pages | `apply_tabs.py <dir> [--dry-run]` |
| `toolchain/build_xref_boxes.py` | materialise oblique-link margin boxes; suppress dead links in place and log every decision to CSV | `build_xref_boxes.py <dir> --jsx [--log F]` |
| `place_xref_boxes.jsx` | create the margin boxes **natively in InDesign** (hand-authored anchored frames never bind on import); rebuilds on re-run | run in InDesign |
| `toolchain/strip_xref_boxes.py` | inverse of `build_xref_boxes.py` — remove all margin boxes to manufacture a boxless submission | `strip_xref_boxes.py <dir> [--dry-run]` |
| `toolchain/normalize_input.py` | take a finished manual back to submission state so the forward leg can run again — this is what makes the pipeline re-entrant | `normalize_input.py <dir> [--detect] [--dry-run]` |
| `toolchain/finish_manual.py` | close the loop: underline cleanup + validate + repack on an export that has its boxes, **keeping** them | `finish_manual.py <export>.idml` |
| `toolchain/fetch_build.py` | download the current CI build from its fixed URL | `fetch_build.py [product ...] [--list]` |

### Shared

| script | what it does | run |
|---|---|---|
| `toolchain/restyle_heading_levels.py` | apply the configured heading hierarchy — set levels 1..N, create missing styles, and take label levels out of the numbering | `restyle_heading_levels.py <dir>` |
| `toolchain/build_manual.py` | run the whole pre-InDesign leg for one submission — the sequence below, in one command | `build_manual.py manuals/<p>/submissions/<f>.idml` |
| `toolchain/standardize_kit.py` | strip a product prefix off the kit's shared design-system objects (`dm32_list` -> `manual_list`, …) | `standardize_kit.py <dir> [--from P] [--to Q]` |
| `toolchain/sync_from_kit.py` | push kit design changes into a document that was poured before them — identity-preserving master transplant | `sync_from_kit.py <dir> [--masters] [--dry-run]` |
| `toolchain/test_reentrancy.py` | prove the pipeline is a fixpoint on its own output | `test_reentrancy.py [INPUT] [--sync] [--kit F]` |
| `toolchain/fix_tab_strip.py` | one-time migration: put BT-BaseTabs' off-strip tab number back on the grid | `fix_tab_strip.py <dir> [--dry-run]` |
| `toolchain/fix_underlines.py` | enforce style-driven underlines — strip local `Underline*` formatting left by an InDesign round-trip | `fix_underlines.py <dir> [--dry-run] [--force]` |
| `toolchain/validate_idml.py` | referential-integrity check + swatch-whitelist + underline enforcement; exit 0 = clean | `validate_idml.py <dir> [--swatches FILE]` |
| `toolchain/repack.py` | folder → valid IDML (`mimetype` first and stored, rest deflated) | `repack.py <dir> <out.idml>` |
| `toolchain/resolve_xref.py` | cross-reference resolver / auditor | `resolve_xref.py --audit` |

### Template build pipeline

From a freshly unpacked `extracted/`:

```bash
python3 toolchain/make_template.py extracted template_build
python3 toolchain/scrub_metadata.py template_build/META-INF/metadata.xml   # 1.9 MB -> 83 KB
python3 toolchain/prune_swatches.py template_build                         # drops Cyan/Magenta/Yellow
python3 toolchain/repack.py template_build manual_template.idml            # canonical blank kit (tabs via .ai)

python3 toolchain/bake_masters.py template_build template_build_masters    # native tabs, .ai gone
python3 toolchain/repack.py template_build_masters manual_template_masters_proof.idml

python3 toolchain/configure_chapters.py template_build_18 --n 18 \
        --config manuals/dm32/dm32.manual                        # any N, masters reconciled

python3 toolchain/validate_idml.py template_build_masters                  # validate any build dir
```

### Forward content production

The kit is **`kit/manual_kit.idml`** — 7 masters, native mixed-ink tabs, no `.ai`, no
chapter masters (`apply_tabs.py` generates those per chapter). A submission is that kit
with content poured in: it arrives with underlined trigger words already wired to
destination anchors, but no margin boxes, no sections, no tabs, and usually only
`titles:lvl4` joined to the numbered list.

One command for the whole pre-InDesign leg:

```bash
python3 toolchain/build_manual.py manuals/dm32/submissions/SUB.idml
# -> manuals/dm32/out/SUB.ready.idml  + SUB.xref_log.csv
```

Or the same thing stage by stage:

```bash
B=manuals/dm32/build
python3 -c "import zipfile; zipfile.ZipFile('manuals/dm32/submissions/SUB.idml').extractall('$B')"

python3 toolchain/normalize_input.py    $B   # only if the input has been built before
python3 toolchain/standardize_kit.py    $B   # migrate a pre-standardisation document
python3 toolchain/restyle_heading_levels.py $B   # apply number_from (no-op if undeclared)
python3 toolchain/fix_numbering.py      $B   # join the numbered levels to manual_list
python3 toolchain/sectionize.py         $B   # one <Section> per titles:lvl2 chapter
python3 toolchain/configure_chapters.py $B   # rebuild the tab strip for THIS manual's N
python3 toolchain/apply_tabs.py         $B   # S<k> master per chapter, applied to its pages
python3 toolchain/build_xref_boxes.py   $B --jsx   # suppress + log dead links, defer the boxes
python3 toolchain/validate_idml.py      $B
python3 toolchain/repack.py             $B out.idml

# then, in InDesign: open out.idml, run place_xref_boxes.jsx, export IDML
python3 toolchain/finish_manual.py      out_processed.idml   # -> out.final.idml
```

## The loop: refining a book

**The pipeline eats its own output.** Once a manual has been through InDesign you can
export it and hand the export straight back to `build_manual.py` — edit content, add a
chapter, re-pour a section, rebuild. Two ways out of an InDesign export, and the only
difference is what happens to the margin boxes:

```
                submission.idml
                      |
      build_manual.py |                     <-- normalises first if the input
                      v                         has been through here before
                 ready.idml
                      |
    InDesign: place_xref_boxes.jsx, export IDML
                      |
        +-------------+--------------+
        |                            |
 finish_manual.py            build_manual.py
   keeps the boxes             strips them and rebuilds
        |                            |
   final.idml                   ready.idml  ---> back to InDesign
   (ship this)                  (revise again)
```

`build_manual.py` detects a processed input (margin boxes, per-chapter masters, more
than one section) and runs `normalize_input.py` on it first. `--as-submission` skips the
check; `--reprocess` forces it; `normalize_input.py <dir> --detect` reports without
changing anything. The input no longer has to sit in `submissions/` — a file in
`roundtrips/` or `out/` works, and config discovery still lands on the same
`<product>.manual`.

Three groups of forward stages, and only the third needs undoing:

- **Already idempotent** — they replace their own output wholesale, so a re-run
  converges by itself: `standardize_kit` renames only what still carries the old prefix,
  `restyle_heading_levels` and `fix_numbering` set styles to the configured hierarchy,
  `sectionize` replaces the whole `<Section>` run, `configure_chapters` regenerates the
  strip and reconciles chapter masters to N, `apply_tabs` purges the previous `S<k>` set
  before minting its own.
- **Convergent by design, not undone** — a dead link (one whose target isn't in this
  document) had its `link` style and `HyperlinkTextSource` removed on the first pass. It
  is plain text now and no later pass sees it again. The audit log is the record. If a
  suppression was wrong, fix the underlying link in InDesign; re-pouring won't resurrect it.
- **Undone by `normalize_input.py`** — the margin boxes (frames, their margin stories,
  their hyperlinks), the local `Underline*` overrides InDesign leaves when it anchors an
  object, `<Hyperlink>` entries whose source no longer exists, and any master InDesign
  renamed to break a duplicate identity (`A-BaseTabs`, `D-BaseTabs` beside `BT-BaseTabs`
  — chapter masters from a pre-fix build, which no longer answer to the `S<k>` name
  `apply_tabs` purges).

Boxes are the one thing that *must* be undone: neither `build_xref_boxes.py` nor the JSX
looks for a box that already exists, so a second pass would place a second box beside
every word. `build_xref_boxes.py` now refuses a document that still has them rather than
doubling up.

This is enforced, not asserted:

```bash
python3 toolchain/test_reentrancy.py        # runs in CI on every build
```

It builds the tracked InDesign round-trip
(`manuals/dm32/roundtrips/manual_template_test2_jsx_processed.idml` — 25 boxes, 2 renamed
clone masters, 3 stale sections, 3 underline overrides), feeds the result back in, and
repeats. Generation 1 is allowed to differ, since that is the pass that strips what
InDesign left; from generation 2 on the fingerprint must not move — same story count,
same 11 masters *by name*, same sections, hyperlinks, link ranges and tab swatches. Self
ids are deliberately not compared: they are minted fresh every run and only have to be
unique and lowercase-hex.

That test is the tripwire for the failure mode that doesn't announce itself. A stage that
adds instead of replacing never errors; it just leaves two of everything next time round.

## Changing the kit after manuals exist

Pouring content into `kit/manual_kit.idml` produces a document that owns a **complete
private copy** of the design system — its own masters, styles, swatches, text variables.
Nothing links it back. Exactly one thing in the kit is read at build time:

```
toolchain/manualconf.py:49    kit/manual_kit.manual
```

So the two halves of the kit behave completely differently:

- **`manual_kit.manual` (config)** — the last fallback in config discovery, read on every
  build. Change the palette or `number_from` there and it reaches every manual that
  doesn't override it, immediately.
- **`manual_kit.idml` (design)** — never opened by anything. Edit a master and it changes
  what the *next* pour inherits. Nothing already in flight notices.

That gap is real and measurable. `manual_template_test2.idml` is missing `titles:lvl1` and
still names its text variables `dm32_head`; DM42n matches the current kit exactly. Both
build, because the toolchain reads each document's own `Styles.xml` rather than assuming
the kit's.

`sync_from_kit.py` closes it. Opt in per manual:

```
sync = masters              # in <product>.manual; or: masters, styles, swatches
```

With nothing declared it reports drift and changes nothing, which is why
`build_manual.py` can run it on every build. It sits **after `standardize_kit`** (the kit's
masters name `manual_head`, so a document still on `dm32_head` has to be renamed first)
and **before `configure_chapters`** (which re-tweens the strip the kit hands over to this
manual's own ink ramp — otherwise the kit's 292 ramp would land in a manual that has no
292).

### Why it is not a file copy

A document page that overrides a master item stores **the master item's id** in the page's
`OverrideList`. B-Base's two running-head frames are overridden on 18 pages each in DM42n
— 36 references to two ids. Drop in the kit's master with its own ids and every one of
those points at nothing.

So the transplant is identity-preserving: kit items are matched to the document's by tag
and position, the **document's** ids are kept, and only genuinely new items get minted
ones. Afterwards every id that any page overrides must still exist, or it is a hard error
naming them — `--force` to proceed anyway.

Two more things that are not obvious:

- **Cross-master references.** A master can be based on another master, so `AppliedMaster`
  points out of the file. The whole kit→document master map is resolved *before* any
  transplant runs; without that, B-Base arrives pointing at a kit id this document has
  never heard of.
- **Stories are matched through their frames**, not by id — a story id is a reference,
  never a `Self` inside the master. Keying it off the item map never matches, so every
  build would mint a fresh set and churn `StoryList` on a run that changed nothing. Going
  via the owning frame is what makes this idempotent, and it also stops two frame chains
  ending up sharing one story.

### What comes with a master

A master is not self-contained. Whatever it references and the document lacks is pulled
across, or it renders against definitions that aren't there: paragraph/character/object
styles (following `BasedOn` and `NextStyle` so a chain arrives whole), colours and mixed
inks (a `MixedInk` also needs its `ColorGroupSwatch` in designmap), and **text variables**
— the case worth spelling out, because a variable's *definition* lives in `designmap.xml`
while its *use* lives in a master's story, so bringing the master alone brings half a
feature.

Fonts are **reported, never transplanted** — that is a licensing question, not a file
operation.

Never touched: masters named `S<k>`, which `apply_tabs.py` generates per chapter from the
content, and anything that is content rather than design.

`build_manual.py --kit OTHER.idml` builds against a different kit, so a kit revision can be
tried against a real manual before it is committed. `test_reentrancy.py --sync --kit F`
checks it stays convergent.

### Getting the build: a fixed URL

Every push to `main` republishes the builds under a rolling **`latest`** tag, so each
manual has one address that never changes and needs no login (the repo is public):

```
https://github.com/AmsteinGraphics/idml_testing/releases/download/latest/dm32.ready.idml
https://github.com/AmsteinGraphics/idml_testing/releases/download/latest/dm42n.ready.idml
```

Paste it into a browser, `curl -L -O` it, or:

```bash
python3 toolchain/fetch_build.py            # every manual -> downloads/
python3 toolchain/fetch_build.py dm32       # just one
python3 toolchain/fetch_build.py --list     # what the release currently holds
```

The file is named after the **product**, not the submission, which is what keeps the URL
fixed — a manual with several submissions aliases the one most recently touched in git,
and the others stay reachable under their own names on the same release. The tag is
force-moved to the commit that was built, so `latest` always means current `main`.

CI runs the same `build_manual.py` you do, in two workflows:

- **`build-manual.yml`** — on any change under `manuals/*/submissions/`, or under
  `toolchain/` or `kit/` (which affect every manual). Builds each submission, fails if
  one doesn't validate, refreshes the `latest` release, and still uploads a run artifact
  as the per-run record (30 days) — which is all a pull request gets, since a PR must not
  be able to redefine what `latest` points at.
- **`release-manual.yml`** — on a `v*` tag, or run manually. Attaches the ready files to a
  *named*, permanent release: `latest` is the moving target, a `v*` release is a state you
  chose to keep.

Release assets live outside the git object database, so republishing a 1.4 MB IDML on
every push never grows the clone — which is why builds are not committed to a branch
instead. Neither workflow can finish a manual: CI cannot run the JSX. Nothing is written
back to the repo except the tag; `manuals/*/out/`, `dist/` and `downloads/` are gitignored.

Order matters: `fix_numbering` must run before `sectionize` (section markers come from
the numbered headings), `configure_chapters` needs the chapters detected, and
`apply_tabs` needs both the sections and a strip with one slot per chapter — it refuses a
strip that is incomplete or the wrong size, naming the tool to run. `configure_chapters`
supersedes `fix_tab_strip` on this path: it regenerates the strip whole, so an inherited
off-strip frame simply ceases to exist. `fix_tab_strip` remains for repairing a legacy
26-slot kit you want to keep as-is.

Things learned the hard way:

- **Margin boxes cannot be authored in IDML.** A hand-written anchored `<TextFrame>`
  never binds on import — InDesign drops or misplaces it. They have to be created
  natively, hence `--jsx` plus `place_xref_boxes.jsx`. Re-running the script rebuilds the
  whole set, so it's safe to iterate.
- **A master lookup by name must be unambiguous.** `apply_tabs.py` and
  `configure_chapters.py` used to take the first master matching "BaseTabs", which meant
  that on a file carrying the renamed clones one tool rebuilt one strip while the other
  read a different one. Both now refuse rather than choose.
- **Uppercase hex `Self` ids crash InDesign 2026** and break anchor binding. Mint
  lowercase only.
- **A master is identified by `NamePrefix` + `BaseName`**, not `Name`. Cloning a master
  and renaming only `Name` leaves duplicate identities, which InDesign 2026 rejects.
- **A story belongs to exactly one frame chain.** Cloning a frame without cloning its
  story leaves two unthreaded frames sharing it, which corrupts the document.
- **Dead links get suppressed, not dropped.** Cross-excerpt links copied from the full
  manual point at anchors that aren't in this document; `build_xref_boxes.py` unwraps the
  `HyperlinkTextSource`, removes the `link` style, keeps the word, and logs every case to
  `<build>.xref_log.csv` for eyeballing. `--keep-dead` leaves them alone.

For the 3-chapter test submission: 26 boxes built, 30 dead links suppressed.

### Auditing cross-references

```bash
python3 toolchain/resolve_xref.py --audit                  # summary of links, breaks, orphans
python3 toolchain/resolve_xref.py --report --csv out.csv   # full pairing dump
python3 toolchain/resolve_xref.py --from "underlined phrase"
python3 toolchain/resolve_xref.py --to   "target heading"
```

Baseline for v1.76: 190 complete oblique links, 3 broken, 20 orphan destinations,
1678 page/TOC links. The 46 "margin number without underlined word" hits were
cross-checked and are **not** defects — see `missing_underline_verified.csv`.

---

## The heading hierarchy

Four levels, top-down: `titles:lvl1` … `titles:lvl4`. By default `lvl1` is an unnumbered
label and the rest number `1`, `1.2`, `1.2.3`. The style chain runs the other way — `lvl4` is the base style and carries the
`manual_list` numbering list, with `lvl3`, `lvl2`, `lvl1` chained onto it, each overriding
size and spacing. `titles:lvl1` is currently a stylistic copy of `lvl2` (BasedOn it with
no overrides of its own), so it looks identical and will follow if `lvl2` is restyled;
give it its own attributes when it should diverge.

A manual uses as many levels as it needs, **starting at the top**, and declares two
things in `<product>.manual`:

- **`tab_level`** — which level carries a thumb tab and an InDesign `<Section>`. This
  cannot be inferred and is an editorial call: DM42n has 5 `lvl1` parts and 23 `lvl2`
  sections, and the tabs belong on `lvl2` — taking the topmost level would give 5 tabs.
  Undeclared, the shallowest level present is used.
- **`number_from`** — the first level that takes part in numbering. Levels above it
  are unnumbered labels and do not advance any counter, so the level below runs
  straight through them instead of restarting inside each one. DM42n sets
  `number_from = 2`: `lvl1` is `Part 1: Getting Started`, a label, while `lvl2`
  sections count 1…23 across the whole book — Part 1 ends at section 4 and Part 2
  opens at section 5. Undeclared, the document's own hierarchy is left alone.
- **`levels`** — how many levels the manual uses. This does *not* fix numbering: content
  starting at `lvl1` already numbers correctly, because the counters start at the top.
  It lets `validate_idml.py` catch content that **skips** the top level (the actual cause
  of a leading zero) or reaches deeper than declared.

Neither is required. Without them the toolchain reads the document: the chapter level
becomes the shallowest heading present, and **numbering depth comes from that document's
own `Styles.xml`** rather than being assumed — which is what keeps already-exported
three-level submissions numbering `1.4.4` rather than `0.1.4.4`.

That second point matters because a document carries its own copy of the styles. A
submission poured before `lvl1` existed still has `titles:lvl2` at level 1 and numbers
`1.4.4`; one poured from the current kit has it at level 2. Both are computed correctly.

**The kit's default is `number_from = 2`:** `titles:lvl1` is an unnumbered Part label,
and `lvl2`/`lvl3`/`lvl4` are numbering levels 1/2/3 — the same depths the DM32 manual
always used. So content written against the pre-`lvl1` hierarchy still numbers `1.4.4`
when re-poured, and a manual that adds Parts gets them as labels without disturbing the
section numbering underneath. A manual that genuinely wants its top level numbered sets
`number_from = 1`.

`restyle_heading_levels.py` performs the change and is re-runnable for a fifth level.

## Starting a new manual

The kit and toolchain are already product-neutral, so a new manual is a directory and
two config files:

```bash
mkdir -p manuals/dm42n/submissions
cp kit/manual_kit.manual manuals/dm42n/dm42n.manual   # then edit: palette, levels,
                                                      # tab_level, tab ink ramp
```

Pour content into `kit/manual_kit.idml` in InDesign, export IDML to
`manuals/dm42n/submissions/`, then run the forward pipeline against
`manuals/dm42n/build`. Config is found by walking up from the build directory, so
nothing needs to be passed on the command line.

The chapter count is **not** configuration — `configure_chapters.py` takes it from the
content. Neither is the palette hardcoded: `tab_stop` lines name their inks and they are
resolved against the document's own `Graphic.xml`, so a manual using different spots
only needs different stops. What is *not* yet parametric is page geometry —
`PAGE_H` / `M_TOP` / `M_BOT` are constants, fine while every manual is this A5 trim.

**Migrating an existing document** built before standardisation: run
`standardize_kit.py` on its unpacked tree first. It renames the design-system objects it
finds and leaves content alone — `dm32_online_manual` is a URL, not a style, and stays.

## Conventions

Per-manual configuration lives **next to** a build directory (never inside it, so it
never gets packed into the `.idml`):

Discovery walks outward, most specific first: `<build>.manual`, then any `*.manual` in
the build's parent (`manuals/<product>/<product>.manual`), then the kit's default. So a
manual directory carries its own config and nothing needs passing on the command line;
`--swatches` / `--config` still override.

- **`<product>.manual`** — `key = value`, `#` comments, `swatch` may repeat:

  ```
  swatch = Black              # sanctioned palette; Black plus up to 3 spots
  swatch = PANTONE 292 U
  levels = 4                  # how many of titles:lvl1..lvl4 this manual uses
  tab_level = 2               # which level carries a thumb tab and a section
  ```

  `validate_idml.py` flags any applied colour not listed (a mixed ink built only from
  listed inks counts as listed); `prune_swatches.py` keeps listed swatches even when
  unused. Both `levels` and `tab_level` are optional — see *The heading hierarchy*.
  `tab_stop` lines are the tab-strip ink ramp, top of the strip to the bottom. A bare
  ink name is that ink at 100%; a mix is `PANTONE 292 U 60%, Black 40%`. Inks are
  resolved against the document's own `Graphic.xml` and may be named in full
  (`PANTONE 292 U`) or short (`292`, `Black`). Stops are evenly spaced along the strip
  and the N tabs tween between them, with a mixed ink's components ordered by the
  document's `TrapOrder`. DM32 uses four pure stops: 292 → Warm Gray 1 → 130 → Black.

## Underlines are style-driven, always

Underline comes from a character style — `link` / `link_slant` for oblique-reference
trigger words, `code_styles:lcd_*` for LCD text — and from nowhere else. No
`CharacterStyleRange` may carry its own `Underline*` attribute. That rules out both
failure modes: an *inline* underline (`Underline="true"` on an unstyled range) and a
style plus a *local override* (`CharacterStyle/link` together with `Underline="false"`),
where the style says underline, the local formatting says don't, and the two drift
apart from then on.

There are four underline signatures in the design system, all style-defined:

| cat | weight / offset | colour | styles | role |
|---|---|---|---|---|
| **1** | 0.375 / +1.5, overprint | **PANTONE 130 U** | `link`, `link_slant` | the orange oblique-link rule |
| 2 | 10.339 / −2.4 | PANTONE Warm Gray 1 U | `code_styles:lcd_*` (7) | LCD background |
| 3 | 10.339 / −3.66 | PANTONE Warm Gray 1 U | `code_styles:lcd_sk*` (4) | LCD background |
| 4 | auto | text colour | `$ID/Hyperlink` | unused |

Categories 2 and 3 are not rules: a 10 pt bar raised *into* the text is a uniform fill
behind it, black on grey, simulating the calculator's LCD. Only category 1 is an
underline in the traditional sense. Within each category the underline is identical —
the styles differ only in font, size and slant. `link_slant` is `BasedOn link` and
declares no underline properties of its own, so it inherits all four; the two are
visually indistinguishable. `fix_underlines.py --category N` restricts to one signature.

Category 4 is not a design decision — `$ID/Hyperlink` is InDesign's factory link style,
reserved and undeletable, present in every IDML and applied nowhere in this one. It is
what an author gets by creating a hyperlink *without* applying `link`: blue
`Color/Hyperlink` (process CMYK 86/57/0/16) with a default-weight underline, i.e. a
process separation in a four-spot-ink document. Since on black text the swatch check
wouldn't catch it, **check 10b flags any range that applies it**. It is reported, never
auto-fixed — swapping it for `link` is a semantic call, as it may be a genuine URL rather
than an oblique reference.

**Underline properties live in two places, and both must be cleaned.** Scalars are
open-tag attributes (`Underline`, `UnderlineWeight`, `UnderlineOffset`); object-valued
ones are `<Properties>` child elements (`<UnderlineColor type="object">Color/PANTONE 130
U</UnderlineColor>`). An attribute-only scan silently misses the colour — and the
override InDesign leaves behind on a `link` range is exactly `<UnderlineColor
type="string">Text Color</UnderlineColor>`, which defeats the style's orange.

This is enforced as check 10 in `validate_idml.py` and repaired by `fix_underlines.py`.
The toolchain already obeys it by construction — `build_xref_boxes.py` suppresses a dead
link by swapping the *style* to `$ID/[No character style]`, never by writing
`Underline="false"`. **InDesign is what reintroduces it:** inserting an anchored object
splits a `link`-styled range and leaves an empty stub carrying a full override block
(`Underline="false" UnderlineOffset="-9999" …`). Since the forward pipeline ends in
"open in InDesign, run the JSX, re-export", run `fix_underlines.py` after every
round-trip, before `repack.py`.

Only a bare `Underline="true|false"` toggle on a range that *holds text* can change what
prints, so that is the one case `fix_underlines.py` reports and leaves alone — the fix
there is a judgment call (drop the override and the word becomes underlined, or drop the
style and it becomes plain). Empty ranges and `Underline*` geometry with no toggle are
inert and stripped by default.

## The chapter count is the manual's, not the toolchain's

26 (v1.76) and 18 were instances, never the rule — the next manual has
whatever chapter count its content has. `configure_chapters.py` makes that the operating
assumption: it defaults N to the chapters actually detected in the document and rebuilds
the strip for it, and `apply_tabs.py` **reads** N, pitch and the number origin from the
strip rather than assuming them.

The strip is *generated* from templates, not pruned from a fixed grid — the old
the retired `make_18ch.py` could only shrink 26 down, never grow past it. One tab rectangle and one number frame per
page act as templates; N of each are emitted at `pitch = box_height / N`, each number
frame gets its own story carrying digit 1…N, and the ink ramp from
the configured `tab_stop` ramp is re-tweened across the new N (a stop landing on a single ink is
emitted as a plain `Color/` + `FillTint`, which is what makes an unmixed spot print
solid). Verified at N = 1, 2, 5, 12, 26, 34, 47: exact tiling — first tab top at `Y0`,
last tab bottom at `Y0 + box_height`, zero-width seams.

A side effect worth knowing: a *generated* 26-slot strip uses pitch 19.8947 and tiles the
margin box exactly, where the inherited one uses 20.7233 from the `.ai` artwork —
26 × 20.7233 = 538.8 pt against a 517.26 pt box, so the original strip always overflowed.
That is why `read_grid()` **measures** the pitch (median gap between consecutive number
frames) instead of computing `box_height / N`.

Physical limits are a design decision, not enforced: ~26 tabs fit comfortably, ~40 forces
tabs under 14 pt, and past that you want grouped or two-level tabs.

## The tab strip

The numbered thumb-tab index down the outer page edge is the only part of the design
coupled to the chapter count. It was originally a linked Illustrator file
(`tab_gradient_v2.00.ai`) placed on every tab master — an absolute local path, so a
missing link on any other machine, and artwork that had to be redrawn whenever the
chapter count changed.

`bake_masters.py` replaces it with native InDesign objects: one mixed-ink swatch per
tab, rectangles tiling the margin box, spot-accurate and fully parametric. Every tab in
every master is recoloured (78 rectangles across 27 masters), leaving zero references to
the `.ai` and no residual `<Link>` elements.

Geometry worth knowing (points, spread coordinates):

- Page 419.5276 × 595.2756 (A5 portrait); margins T 22.1701, B 55.8425, L 49.6063, R 35.4331.
- Margin-box top `Y0 = M_TOP − PAGE_H/2 = −275.468`; tab pitch = box height / N
  (≈ 20.7233 at N=26, 28.7368 at N=18).
- Tab x-extent: left page −436.54…−391.18, right page is the mirror (negate x).
  Width 45.36, ~17 pt of bleed past the trim.
- Masters: `Base` = `ud5`, `BaseTabs` = `u1dc4d`, `NavTabs` = `u54843`; chapter masters
  `u1e21d` (slot 0) … `u26448` (slot 25). Donor spread `u7973e`.

In the original file each chapter master inherited the full strip from `BaseTabs` and
hid it with per-master overrides — a workaround for an InDesign bug where inherited tabs
wouldn't render. Native tabs *do* render, so `configure_chapters.py` re-bases each chapter master
onto `Base` and clears its override list: each master then owns exactly one tab and one
number, mirrored onto both pages of the facing spread.

### The strip was one frame short

`BT-BaseTabs` carries the full numbered strip: 26 slots × 2 pages = 52 number frames.
`dm32_print_manual_v1.76.idml` ships with 51 of them on the grid. Slot 25's right-page
number (`u25f77`) sits at ty=792.19 — exactly one strip height (26 × 20.7233 = 538.80 pt)
below its home at ty=253.39, about 495 pt off the bottom of the page. Every template
derived from the manual inherited it.

It caused two failures. `apply_tabs.py` computes slot 51 for it, couldn't classify it,
and copied it into every chapter master still pointing at the original's story — leaving
N unthreaded frames sharing one story, which corrupts the document. And a 26-chapter
manual would get no right-page number on chapter 26, since the frame for that slot isn't
on the strip.

All three templates have been migrated (52/52). `fix_tab_strip.py` is the one-time repair
for any other kit or in-flight document; a frame's x gives the page, the single gap in the
grid gives the slot. `apply_tabs.py` now **refuses** a kit whose strip is incomplete rather
than correcting it on every run — the kit is the thing that should be right.

## IDML gotchas

Collected the hard way; all of these will silently produce a file InDesign rejects:

- `mimetype` must be the **first** zip entry and **stored** uncompressed (`repack.py`).
- Master page items close with `</MasterSpread>`, not `</Spread>`.
- Preserve the `<?aid?>` processing instruction when editing `designmap.xml` / `Styles.xml`
  with ElementTree.
- Spaces in ink and colour references are URL-encoded: `Ink/PANTONE%20292%20U`.
- A mixed-ink swatch needs **two** edits — the `<MixedInk>` in `Resources/Graphic.xml`
  *and* a matching `<ColorGroupSwatch>` in `designmap.xml`, cross-linked by id.
- `open(p,'w').write(open(p).read())` truncates the file before the inner read runs.
  Read into a variable first.
- Style and range properties are split across **attributes and `<Properties>` children**:
  scalars are attributes, object references (colours, `BasedOn`) are child elements.
  Reading only the opening tag will tell you a style sets no colour when it plainly does.
- Anchoring a scan with `pattern.match(text[pos:])` copies the rest of the file on every
  match — O(n²) on the manual's body stories. Use `pattern.match(text, pos)`.
- On a template, "unused" ≠ removable. Style-usage analysis can't distinguish an
  intentionally idle design-system style from junk — all 13 styles flagged dead in v1.76
  turned out to be deliberate, and were kept.

## Status

Done: repo split into toolchain / kit / manuals · design-system objects renamed off the
product (`dm32_*` -> `manual_*`) and the kit's XMP scrubbed · tab palette driven by the
tabstops header instead of hardcoded inks · broken-link repair · blank-kit template (opens in InDesign) · metadata scrub ·
swatch prune · style analysis · native mixed-ink tabs with the `.ai` fully removed ·
forward content pipeline (sections, tabs, oblique-ref boxes via JSX) · tab strip repaired
to 52/52 across all templates · style-driven underline enforcement · **InDesign 2026 crash
fixed and confirmed** (duplicate master identity + frames sharing a story) · **chapter
count fully parametric** — the strip is generated for whatever N the content has, and the
grid is read from the kit rather than assumed · **the pipeline is re-entrant** — its own
output, InDesign round-trip included, is valid input, verified as a fixpoint · **every
build of `main` lands on a fixed download URL** instead of a run artifact.

Open:

- Fold the native tab bake into the canonical `manual_template.idml`, which still
  references the `.ai`.
- The mirrored right-page tab number reuses the right-aligned `foot_and_tabs:tab_right`
  style; a left-aligned variant may look better.
- `configure_chapters.py` rebuilds the strip but doesn't rename anything from a
  chapter-title manifest; titles still come from the detected `titles:lvl2` headings.
- Page geometry (`PAGE_H` / `M_TOP` / `M_BOT`) is still constant in `apply_tabs.py` and
  `configure_chapters.py`. Fine while every manual shares this A5 trim; a different trim
  would need it read from the document's `MarginPreference`.
- `kit/derivation/` keeps the three intermediate templates the kit was cut from. They are
  provenance, not inputs — nothing in the pipeline reads them.
