# DM32 IDML toolchain

Python tooling for inspecting, repairing and generating [IDML](https://www.adobe.com/devnet/indesign/documentation.html)
(InDesign Markup Language) packages, built around the SwissMicros **DM32 print manual**.

Two jobs:

1. **Audit the shipped manual** — resolve and check its "oblique link" cross-reference
   system (underlined word + margin paragraph number pointing at one anchor).
2. **Derive a reusable blank template** — keep the whole design skeleton (styles,
   colours, masters, fonts, XML tags, cross-reference and index engines), strip all
   content, and regenerate the numbered thumb-tab index natively for any chapter count.

Everything is plain `python3` with the standard library only. No InDesign and no
`unzip` are required to build; InDesign is only needed to *visually* verify output.

---

## Layout

| | |
|---|---|
| `dm32_print_manual_v1.76.idml` | the shipped manual (source of truth) |
| `dm32_print_manual_v1.76_fixed.idml` | same, with 2 broken oblique links repaired (dest keys 208, 119) |
| `manual_template.idml` | canonical blank-kit template, 26 chapters — tabs still use the external `.ai` |
| `manual_template_masters_proof.idml` | 26-ch, native mixed-ink tabs, `.ai` dependency removed |
| `manual_template_tab18_proof.idml` | 18-ch parametric build, numbered tabs on both pages (latest) |
| `manual_template_example_mixed_ink.idml` | InDesign-authored mixed-ink swatch sample (schema reference) |
| `*.py` | the toolchain, see below |
| `template_build.swatches`, `template_build.tabstops.csv` | per-project config (see *Conventions*) |
| `missing_underline_verified.csv`, `pairing_anomalies.csv` | cross-reference audit output |
| `tab_gradient_v2.00.svg` | export of the original tab artwork, used to decode the gradient |

Unpacked working trees (`extracted/`, `template_build*/`) are **not tracked** — they are
build products of the archives above. Recreate the input tree with:

```bash
python3 -c "import zipfile; zipfile.ZipFile('dm32_print_manual_v1.76_fixed.idml').extractall('extracted')"
```

> The `extracted/` tree used during development corresponds to the **`_fixed`** archive,
> not the pristine original — they differ only in `designmap.xml`. Unpack
> `dm32_print_manual_v1.76.idml` instead if you want the untouched original.

---

## Toolchain

| script | what it does | run |
|---|---|---|
| `make_template.py` | strip content → blank kit: all styles / masters / colours / tags kept, one blank donor spread, 114 master-referenced stories | `make_template.py extracted template_build` |
| `scrub_metadata.py` | reset XMP — drop History/Ingredients/Manifest/thumbnails/DerivedFrom, fresh UUID lineage so derived manuals aren't fingerprinted as the source | `scrub_metadata.py template_build/META-INF/metadata.xml` |
| `prune_swatches.py` | InDesign-style "delete unused swatches"; protects structural swatches + the sanctioned palette, cascades to a fixed point | `prune_swatches.py template_build [--dry-run]` |
| `prune_styles.py` | report/remove styles dead in the **full manual** (not the empty template) with closure over every style-reference edge | `prune_styles.py template_build --ref extracted --dry-run` |
| `bake_masters.py` | recolour every tab in every tab master from the placed `.ai` to native mixed-ink swatches, preserving geometry, bleed and master filiation | `bake_masters.py template_build template_build_masters` |
| `make_18ch.py` | derive an 18-chapter template: prune masters, respace + recolour tabs, mirror tab+number onto both pages, write digits 1–18 | `make_18ch.py` |
| `validate_idml.py` | referential-integrity check + swatch-whitelist enforcement; exit 0 = clean | `validate_idml.py <dir> [--swatches FILE]` |
| `repack.py` | folder → valid IDML (`mimetype` first and stored, rest deflated) | `repack.py <dir> <out.idml>` |
| `resolve_xref.py` | cross-reference resolver / auditor | `resolve_xref.py --audit` |
| `bake_tab_strip.py`, `tab_strip.py` | earlier tab-strip proof and compute-only ink table — superseded by `bake_masters.py` | — |

### Build pipeline

From a freshly unpacked `extracted/`:

```bash
python3 make_template.py extracted template_build
python3 scrub_metadata.py template_build/META-INF/metadata.xml   # 1.9 MB -> 83 KB
python3 prune_swatches.py template_build                         # drops Cyan/Magenta/Yellow
python3 repack.py template_build manual_template.idml            # canonical blank kit (tabs via .ai)

python3 bake_masters.py template_build template_build_masters    # native tabs, .ai gone
python3 repack.py template_build_masters manual_template_masters_proof.idml

python3 make_18ch.py                                             # -> manual_template_tab18_proof.idml

python3 validate_idml.py template_build_masters                  # validate any build dir
```

### Auditing cross-references

```bash
python3 resolve_xref.py --audit                  # summary of links, breaks, orphans
python3 resolve_xref.py --report --csv out.csv   # full pairing dump
python3 resolve_xref.py --from "underlined phrase"
python3 resolve_xref.py --to   "target heading"
```

Baseline for v1.76: 190 complete oblique links, 3 broken, 20 orphan destinations,
1678 page/TOC links. The 46 "margin number without underlined word" hits were
cross-checked and are **not** defects — see `missing_underline_verified.csv`.

---

## Conventions

Per-manual configuration lives **next to** a build directory (never inside it, so it
never gets packed into the `.idml`):

- **`<build>.swatches`** — the sanctioned palette, one swatch name per line, `#` comments.
  `validate_idml.py` flags any colour applied to a page item whose swatch isn't listed;
  `prune_swatches.py` keeps listed swatches even when currently unused. The file is
  auto-discovered as `<dir>.swatches`, so derived build dirs need either their own copy
  or an explicit `--swatches template_build.swatches` (otherwise the colour check is
  silently skipped).
  The DM32 palette is Black + `PANTONE 292 U`, `PANTONE 130 U`, `PANTONE Warm Gray 1 U`.
- **`<build>.tabstops.csv`** — header `Black,292,130,Warm Gray 1`, then one row per
  gradient stop giving each ink's percentage. Stops are evenly spaced along the tab
  strip and the N tabs are tweened per-channel between them. DM32 uses four pure stops:
  292 → Warm Gray 1 → 130 → Black.

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
wouldn't render. Native tabs *do* render, so `make_18ch.py` re-bases each chapter master
onto `Base` and clears its override list: each master then owns exactly one tab and one
number, mirrored onto both pages of the facing spread.

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
- On a template, "unused" ≠ removable. Style-usage analysis can't distinguish an
  intentionally idle design-system style from junk — all 13 styles flagged dead in v1.76
  turned out to be deliberate, and were kept.

## Status

Done: broken-link repair · blank-kit template (opens in InDesign) · metadata scrub ·
swatch prune · style analysis · native mixed-ink tabs at N=26 with the `.ai` fully
removed · 18-chapter parametric build with numbered tabs on both pages.

Open:

- Fold the native tab bake into the canonical `manual_template.idml`, which still
  references the `.ai`.
- The mirrored right-page tab number reuses the right-aligned `foot_and_tabs:tab_right`
  style; a left-aligned variant may look better.
- Generalise `make_18ch.py` (a hardcoded N=18 instance) into a real
  `configure_chapters.py` driven by a chapter-title manifest.
