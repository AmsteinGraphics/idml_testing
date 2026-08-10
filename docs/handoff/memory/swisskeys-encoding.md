---
name: swisskeys-encoding
description: "How DM32 v1.76 actually encodes SwissKeys buttons and LCD text — styles, which carry ‹ › delimiters, and the special-glyph inventory"
metadata: 
  node_type: memory
  type: reference
  originSessionId: ec08b19f-1946-4ee3-931e-87fdc5ed5cbf
  modified: 2026-08-10T15:57:31.834Z
---

Surveyed from `manuals/dm32/dm32_print_manual_v1.76.idml` on 2026-08-10 (2323 stories). Expensive to re-derive, so recorded here. All these character styles exist in `kit/manual_kit.idml` and in the DM42n submission too.

| style | font | runs in v1.76 | content wrapped in `‹ ›`? |
|---|---|---|---|
| `btn_normal` | SwissKeys Buttons (negative, white on black) | 1430 | **1348 yes** |
| `letter_normal` | SwissKeys **Letters** | 215 | **192 yes** |
| `btn_or` / `btn_bl` | inherit SwissKeys, set only a fill colour | 479 / 405 | **0 — never** |
| `code_styles:lcd_sk` / `_high` / `_slant` / `_slant_high` | SwissKeys Raster | 699 / 224 / 96 / 30 | 0 |
| `code_styles:code_sk` | SwissKeys Raster (program listings) | 791 | 0 |

Also present: `btn_normal_table`, `btn_or_table`, `btn_bl_table` (table-sized variants), `shift_orange`, `shift_blue` (used only ~20× each, on the `‹`/`›` delimiters themselves in a rare construction).

**THE KEY FACT: `‹ ›` are not universal delimiters.** They belong to the negative button font and the letter font only. Shifted buttons and LCD text carry bare content. Any transform must insert them for `btn_normal`/`letter_normal` and never for the others.

**Style chain** (already correct for what the toolchain needs): `btn` (SwissKeys) → `btn_normal` (Buttons) → `letter_normal` (Letters), `shift_orange`, `shift_blue`; and `btn` → `btn_or`, `btn_bl` which override **only** FillColor. So "shifted button = original font in the shift colour" is already modelled — a one-shift manual like DM42n needs one such style.

**`[C]` is genuinely ambiguous:** `C` appears 67× as `btn_normal` (the Clear key) while single letters also appear as `letter_normal` (`‹Q›`, `‹A›`, `‹F›`). No rule can resolve a bare single letter.

**Special glyphs needing a mapping table** (non-ASCII actually used):
`Σ • × ÷ ← √ – ± ⅟ ↓ ˣ → ▼ ▲ ² ⎷ Θ π ∫ ↑ σ ° ⭳ ⮀ ⭱ █ ¯ ᴇ χ ≤ ≥ ≠ · … ŷ ȳ Χ`, plus U+2009 THIN SPACE and U+00A0 NBSP used meaningfully for spacing.

**Two pre-existing defects found in v1.76, not caused by this repo:**
- 27 × `U+FFFD` REPLACEMENT CHARACTER inside `btn_bl` — a glyph lost before this repo existed; those buttons print something wrong today.
- One button name is stored as an astral-plane character reference (`&#x1d63a;ˣ`, U+1D63A), so any glyph map must handle non-BMP codepoints rather than assuming one char per glyph.

Naming wart: `btn_or` / `btn_bl` are product-specific (orange/blue) inside a kit that is otherwise product-neutral — candidates for `btn_shift1`/`btn_shift2` with the colour from config, the way the tab ramp works.

See [[key-markup-proposal]] for the feature this was surveyed for.
