---
name: swisskeys-encoding
description: "How DM32 encodes SwissKeys buttons and LCD text — the two lcd_* trees, the three delimiter conventions, and the special-glyph inventory"
metadata: 
  node_type: memory
  type: reference
  originSessionId: ec08b19f-1946-4ee3-931e-87fdc5ed5cbf
  modified: 2026-08-13T22:45:28.267Z
---

Surveyed from `manuals/dm32/dm32_print_manual_v1.76.idml` (2323 stories), re-measured 2026-08-10.
Expensive to re-derive, so recorded here.

**Counting warning:** table cells nest `ParagraphStyleRange` inside `ParagraphStyleRange`, so a
walk that iterates per-PSR counts cell content TWICE (it inflated `btn_normal` from 1440 to 2106).
Iterate `CharacterStyleRange` once from the story root. Any transform has the same trap.

## THREE delimiter conventions, not one

This is the key fact. A transform must apply the right one per style:

| convention | styles | evidence in v1.76 |
|---|---|---|
| wrapped in `‹ ›` | `btn_normal`, `letter_normal` | 1194/1440 and 147/220 (strict both-ends) |
| padded with NBSP | `lcd_normal`, `lcd_table` | 72/91 and 23/24 |
| bare content | `lcd_sk*`, `code_sk`, `btn_or`, `btn_bl` | lcd_sk 28/736 |

Shifted buttons and LCD text carry bare content — `‹ ›` belong to the negative-button font and
the letters font only.

## The lcd_* prefix is TWO unrelated trees

**Tree A — root `code_styles:lcd_normal`, Gintronic Regular 7.5, NBSP-padded labels.** Note this
is byte-identical in appearance to `code_styles:inline_codeblock` — it is the code font wearing an
LCD name, and does NOT match the calculator's real LCD. The user may swap its font later.
- `lcd_normal` (91 runs) — mode annunciators: `␣BIN␣` `␣DEG␣` `␣EQN␣` `␣A..Z␣` `␣RAD␣` `␣GRAD␣`
- `lcd_table` (24) — soft-menu labels `␣New␣` `␣Load␣` `␣Save␣` `␣Info␣`; 24/24 inside table cells
- `lcd_dings` (15) — Wingdings 3, private-use `U+F081`/`U+F082`; overrides font, INHERITS size 7.5
- `lcd_slant` (1) — italic, effectively unused

**Tree B — root `code_styles:lcd_sk`, SwissKeys Raster 10.4, bare content.** The real LCD.
- `lcd_sk` (736) — display text: `RUNNING` `ALL` `Y` `Cn,r`
- `lcd_sk_high` (244) — inverse/cursor: `█` `_` `SQRT` `NULL`
- `lcd_sk_slant` (97) — italic placeholders: `nnnn` `n` `option`
- `lcd_sk_slant_high` (30) — `variable` `label`
- sibling `code_styles:code_sk` (791) — same font/size, program listings, para style `prgm_listing`

Buttons: `btn` (SwissKeys 9.5) → `btn_normal` (Buttons, 1440) → `letter_normal` (Letters, 220),
**SOFT-MENU LABELS** use `code_styles:lcd_inverted`, added to the kit 2026-08-14 (38 char
styles, 25 mixed inks). It is based on `lcd_normal` and overrides only the colours. The
"inverted" look is NOT a fill: `lcd_normal` carries a heavy underline (weight 10.339 at
offset −2.4) and `lcd_inverted` recolours it to `MixedInk/menu_block` (Process Black +
Warm Gray 1 U), so the rule behind the text becomes the block. **Transplanting the style
alone leaves that underline pointing at a swatch the kit lacks** — the swatch has to
travel with it. Markup is `{m:LABEL}`, centred in 5 cells; equal widths depend on the face
being monospaced, which Gintronic is (panose says so; 605 of 608 advances identical).

**THE SHIFT KEY ITSELF** is an EMPTY BUTTON in the shift colour: `U+2039` + four `U+0020` +
`U+203A`, the run styled `shift_orange` (5×) or `shift_blue` (8×) — never `btn_or`/`btn_bl`, which
carry a shifted FUNCTION's name. **The space glyph in the button font is the key body**, so four
spaces draw a blank key and the count sets its width. That is what `shift_orange`/`shift_blue` are
actually for; an earlier note called it "a rare construction on the delimiters", which had the
mechanism right and the meaning wrong. Markup: `<>` and `<2:>`.

`shift_orange`, `shift_blue`; and `btn` → `btn_or` (533) / `btn_bl` (430) which override **only**
FillColor. So "shifted button = original font in the shift colour" is already modelled.

## PRUNED 2026-08-10 — do not expect these to exist

Six styles were defined but had ZERO runs anywhere; removed from `kit/manual_kit.idml`
(42 → 36 character styles), commit on main. They were leftovers from the design-system
development stage per the user:
`lcd_exponent`, `lcd_greek`, `lcd_cursor_block`, `btn_normal_table`, `btn_or_table`, `btn_bl_table`.

The `btn_*_table` variants were never applied — buttons inside tables use plain `btn_normal`
(666 of its runs are in cells). `lcd_table` is NOT dead and stays.

**No rule maps "inside a table" to a style.** Inside cells you find both `lcd_table` (24) and
`lcd_normal` (11), so table-context cannot be inferred — `lcd_table` needs explicit markup.

## Still true, and awkward

**`[C]` is genuinely ambiguous:** `C` appears 67× as `btn_normal` (the Clear key) while single
letters also appear as `letter_normal` (`‹Q›`, `‹A›`, `‹F›`). No rule resolves a bare single
letter — hence the `[[A]]` markup for letter keys.

**Special glyphs needing a mapping table** (non-ASCII actually used):
`Σ • × ÷ ← √ – ± ⅟ ↓ ˣ → ▼ ▲ ² ⎷ Θ π ∫ ↑ σ ° ⭳ ⮀ ⭱ █ ¯ ᴇ χ ≤ ≥ ≠ · … ŷ ȳ Χ`, plus U+2009 THIN
SPACE and U+00A0 NBSP used meaningfully. The map must be keyed PER FONT — Gintronic and SwissKeys
Raster have different repertoires, which is what makes the lcd_normal font swap risky.

**Defects the new font-coverage check found in test1/test2** (real, pre-existing, reported as
WARNINGS so they don't fail the build): `•` U+2022 styled `btn_normal` ×19 — SwissKeys Buttons
has no bullet glyph; and lowercase `e l m n u` styled `letter_normal` ×7 — SwissKeys Letters
carries only 34 codepoints and no lowercase. Both print wrong today. Editorial calls, not
toolchain bugs.

**Two pre-existing defects in v1.76, not caused by this repo:**
- 27 × `U+FFFD` inside `btn_bl` — a glyph lost before this repo existed; those buttons print
  something wrong today.
- One button name is an astral-plane character reference (`&#x1d63a;ˣ`, U+1D63A), so a glyph map
  must handle non-BMP codepoints.

Naming wart: `btn_or`/`btn_bl` are product-specific (orange/blue) inside a product-neutral kit —
agreed to become `btn_shift1`/`btn_shift2` with the colour from config, like the tab ramp.

See [[key-markup-proposal]] for the feature this was surveyed for.
