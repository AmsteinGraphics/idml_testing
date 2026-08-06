# DM32 IDML toolchain

Python tooling for inspecting, repairing and generating [IDML](https://www.adobe.com/devnet/indesign/documentation.html)
(InDesign Markup Language) packages, built around the SwissMicros **DM32 print manual**.

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
  manual_kit.swatches       default palette
  manual_kit.tabstops.csv   default tab-strip ink ramp
  reference/                InDesign-authored samples kept for their schema
  derivation/               how the kit was cut from the DM32 manual (provenance)
manuals/
  dm32/
    dm32_print_manual_v1.76.idml       the shipped manual (source of truth)
    dm32_print_manual_v1.76_fixed.idml same, 2 broken oblique links repaired
    dm32.swatches  dm32.tabstops.csv   this manual's config
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

### Shared

| script | what it does | run |
|---|---|---|
| `toolchain/restyle_heading_levels.py` | set which paragraph styles are heading levels 1..N, creating any that are missing | `restyle_heading_levels.py <dir> --levels a,b,c,d` |
| `toolchain/build_manual.py` | run the whole pre-InDesign leg for one submission — the sequence below, in one command | `build_manual.py manuals/<p>/submissions/<f>.idml` |
| `toolchain/standardize_kit.py` | strip a product prefix off the kit's shared design-system objects (`dm32_list` -> `manual_list`, …) | `standardize_kit.py <dir> [--from P] [--to Q]` |
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
        --tabstops template_build.tabstops.csv                   # any N, masters reconciled

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

CI runs exactly this, in two workflows:

- **`build-manual.yml`** — on any change under `manuals/*/submissions/`, or under
  `toolchain/` or `kit/` (which affect every manual). Builds each submission, fails if
  one doesn't validate, uploads the ready files as run artifacts (30-day retention).
  This is the routine check that a submission survives the pipeline.
- **`release-manual.yml`** — on a `v*` tag, or run manually for one submission. Attaches
  the ready files to a GitHub Release, which is permanent and has a direct download URL.
  Release assets live outside the git object database, so promoting a build never puts a
  1.4 MB IDML into history — which is why builds are not committed to a branch instead.

Neither can finish a manual: CI cannot run the JSX. Nothing is written back to the repo —
`manuals/*/out/` is gitignored and no workflow commits or pushes.

Or the same thing stage by stage:

```bash
B=manuals/dm32/build
python3 -c "import zipfile; zipfile.ZipFile('manuals/dm32/submissions/SUB.idml').extractall('$B')"

python3 toolchain/fix_numbering.py      $B   # lvl2/lvl3 -> manual_list, so numbering counts up
python3 toolchain/sectionize.py         $B   # one <Section> per titles:lvl2 chapter
python3 toolchain/configure_chapters.py $B   # rebuild the tab strip for THIS manual's N
python3 toolchain/apply_tabs.py         $B   # S<k> master per chapter, applied to its pages
python3 toolchain/build_xref_boxes.py   $B --jsx   # suppress + log dead links, defer the boxes
python3 toolchain/validate_idml.py      $B
python3 toolchain/repack.py             $B out.idml

# then, in InDesign:
#   open out.idml, run place_xref_boxes.jsx, export IDML
python3 -c "import zipfile; zipfile.ZipFile('out_processed.idml').extractall('$B')"
python3 toolchain/fix_underlines.py     $B   # InDesign reintroduces local underline overrides
python3 toolchain/validate_idml.py      $B
python3 toolchain/repack.py             $B final.idml
```

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

Four levels, top-down: `titles:lvl1` … `titles:lvl4`, numbering `1`, `1.2`, `1.2.3`,
`1.2.3.4`. The style chain runs the other way — `lvl4` is the base style and carries the
`manual_list` numbering list, with `lvl3`, `lvl2`, `lvl1` chained onto it, each overriding
size and spacing. `titles:lvl1` is currently a stylistic copy of `lvl2` (BasedOn it with
no overrides of its own), so it looks identical and will follow if `lvl2` is restyled;
give it its own attributes when it should diverge.

A manual uses as many levels as it needs, **starting at the top**. Nothing is hardcoded
to a particular style:

- The **chapter level** — one tab, one `<Section>` — is the shallowest heading style that
  actually appears in the document (`sectionize.topmost_heading`).
- The **numbering depth** of each style is read from that document's own `Styles.xml`
  (`build_xref_boxes.heading_levels`), not assumed.

That second point matters because a document carries its own copy of the styles. A
submission poured before `lvl1` existed still has `titles:lvl2` at level 1 and numbers
`1.4.4`; one poured from the current kit has it at level 2. Both are computed correctly.

> **Adding a level is not backwards compatible for content.** Existing content re-poured
> into the current kit gains a place and a leading zero — a former `1.4.4` becomes
> `0.1.4.4` — because level 1's counter never advances without a `titles:lvl1` heading.
> Content written against the old hierarchy needs headings at the new top level. The
> already-exported submissions are unaffected: they keep their own three-level styles.

`restyle_heading_levels.py` performs the change and is re-runnable for a fifth level.

## Starting a new manual

The kit and toolchain are already product-neutral, so a new manual is a directory and
two config files:

```bash
mkdir -p manuals/dm42n/submissions
cp kit/manual_kit.swatches      manuals/dm42n/dm42n.swatches       # edit if the palette differs
cp kit/manual_kit.tabstops.csv  manuals/dm42n/dm42n.tabstops.csv   # edit if the ramp differs
```

Pour content into `kit/manual_kit.idml` in InDesign, export IDML to
`manuals/dm42n/submissions/`, then run the forward pipeline against
`manuals/dm42n/build`. Config is found by walking up from the build directory, so
nothing needs to be passed on the command line.

The chapter count is **not** configuration — `configure_chapters.py` takes it from the
content. Neither is the palette hardcoded: the `tabstops.csv` header names the inks and
they are resolved against the document's own `Graphic.xml`, so a manual using different
spots only needs a different header. What is *not* yet parametric is page geometry —
`PAGE_H` / `M_TOP` / `M_BOT` are constants, fine while every manual is this A5 trim.

**Migrating an existing document** built before standardisation: run
`standardize_kit.py` on its unpacked tree first. It renames the design-system objects it
finds and leaves content alone — `dm32_online_manual` is a URL, not a style, and stays.

## Conventions

Per-manual configuration lives **next to** a build directory (never inside it, so it
never gets packed into the `.idml`):

Discovery walks outward, most specific first: `<build>.swatches`, then any `*.swatches`
in the build's parent (`manuals/<product>/<product>.swatches`), then the kit's default.
So a manual directory carries its own config and nothing needs passing on the command
line; `--swatches` / `--tabstops` still override.

- **`<product>.swatches`** — the sanctioned palette, one swatch name per line, `#`
  comments. `validate_idml.py` flags any colour applied to a page item whose swatch
  isn't listed, and treats a mixed ink built only from listed inks as listed;
  `prune_swatches.py` keeps listed swatches even when currently unused.
  The DM32 palette is Black + `PANTONE 292 U`, `PANTONE 130 U`, `PANTONE Warm Gray 1 U`.
- **`<product>.tabstops.csv`** — the header **names the inks** and is resolved against
  the document's own `Graphic.xml`; a column may name an ink in full (`PANTONE 292 U`)
  or short (`292`, `Black`). Each row is a gradient stop giving each ink's percentage.
  Stops are evenly spaced along the strip and the N tabs are tweened between them, with
  a mixed ink's components ordered by the document's `TrapOrder`. DM32 uses four pure
  stops: 292 → Warm Gray 1 → 130 → Black.

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
`<build>.tabstops.csv` is re-tweened across the new N (a stop landing on a single ink is
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
grid is read from the kit rather than assumed.

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
