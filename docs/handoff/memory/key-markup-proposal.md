---
name: key-markup-proposal
description: "Agreed design for plain-text key markup — syntax settled, architecture is FORWARD-ONLY and idempotent (no reverse transform). Ready to build."
metadata: 
  node_type: memory
  type: project
  originSessionId: ec08b19f-1946-4ee3-931e-87fdc5ed5cbf
  modified: 2026-08-10T19:45:58.440Z
---

Agreed 2026-08-10, **not yet implemented**. Authors pour content in InDesign using plain-text
conventions that the toolchain converts into real SwissKeys character styles, so nobody
hand-applies `btn_normal`/`lcd_sk`. Encoding facts it rests on: [[swisskeys-encoding]].

## ARCHITECTURE — forward-only and idempotent (changed 2026-08-10, user's insight)

The original design had `apply_key_markup.py` forward and `normalize_input.py` reversing it.
**That was wrong.** The property needed is not invertibility but IDEMPOTENCE:

> the transform consumes `[EXIT]` and emits a `‹EXIT›` run styled `btn_normal`. Run it again and
> there is no `[EXIT]` left to match. `f(f(x)) = f(x)`.

So markup is **write-once**: typed, rendered, and it stays rendered. The rendered IDML is the
state and the feedback; nothing converts back. The user asked for this explicitly — markup should
be definitive, and it doesn't occupy the same space as the final fonts, so round-tripping it would
keep disturbing layout. `normalize_input.py` stays out of key markup entirely.

Benefits: kills the fragile half (recovering `[EXIT]` from `‹EXIT›` required guessing whether the
guillemets were author-typed), and `[C]` ambiguity bites once instead of twice.
`test_reentrancy.py` asserts idempotence rather than round-trip equality.

Keep a reverse as an OPTIONAL repair flag (`--to-markup`), never a pipeline stage.

**Two wrinkles that must be handled:**
1. **Escapes break idempotence unless marked.** `\[EXIT\]` renders to literal text `[EXIT]`, which
   the next run would happily turn into a button. Fix: escaped literals carry a `no_markup`
   character style, and the transform never looks inside runs already carrying a target style.
2. **InDesign splits runs.** `[EXIT]` can land across two `CharacterStyleRange`s. Match on
   concatenated paragraph text and map back to ranges.

## The syntax (user approved all of it 2026-08-10)

| author types | content produced | style |
|---|---|---|
| `[EXIT]` `[9]` | `‹EXIT›` `‹9›` | `btn_normal` |
| `[[A]]` | `‹A›` | `letter_normal` |
| `<ACOS>` | `ACOS` bare | shift 1 colour |
| `<2:NAME>` | `NAME` bare | shift 2 colour (DM32 only; DM42n has one shift) |
| `{ALL}` `{1 2/3}` | verbatim, bare | `code_styles:lcd_sk` |
| `{^…}` `{/…}` `{^/…}` | verbatim | `lcd_sk_high` / `_slant` / `_slant_high` |

Resolved questions: letter keys use explicit `[[A]]` (a per-manual config list would be a global
rule, and `[C]` proves it would be wrong somewhere). Second shift is indexed `<2:NAME>` not
`<<NAME>>` — indexing scales and lets `btn_or`/`btn_bl` become `btn_shift1`/`btn_shift2` with the
colour from config.

**`_table` variants: EXPLICIT, not automatic.** I first recommended auto-applying them inside
tables; the data killed that. The `btn_*_table` styles had zero runs and are now pruned. `lcd_table`
survives but cannot be inferred from context — cells contain both `lcd_table` (24) and `lcd_normal`
(11).

Remember the THREE delimiter conventions ([[swisskeys-encoding]]): `‹ ›` for btn_normal/
letter_normal, NBSP padding for lcd_normal/lcd_table, bare for everything else.

## Other agreed pieces

`kit/swisskeys.map` glyph table (`name = glyph`, per-manual override, unmapped names pass through
so `[EXIT]` needs no entry, refined iteratively — the user expects to iterate it, not get it right
up front). Keyed PER FONT, because a font swap changes the available repertoire. Never transform
inside `code_sk` program listings.

## Validation to build alongside (user asked for sanity checks)

1. **Font coverage** — every codepoint must exist in the style's *resolved* font. Would have caught
   the 27 `U+FFFD` in `btn_bl`, and is the safety net for the planned `lcd_normal` font swap.
2. **Delimiter conformance** — warn (with counts, not errors — there's a legitimate ~17% tail) on
   `btn_normal` without `‹ ›`, `lcd_normal`/`lcd_table` without NBSP, `lcd_sk*` with delimiters.
3. **Inheritance blast radius** — on a kit style change, report every style inheriting the changed
   property. `lcd_slant`/`lcd_table` inherit lcd_normal's font; `lcd_dings` inherits its SIZE.
4. **Dead styles** — report defined-but-unused so they are a decision, not a surprise.
5. **PUA containment** — `U+F0xx` outside `lcd_dings` means a silent font substitution.
6. **Leftover markup** — un-transformed `[...]`/`{...}` surviving a build.

**How to apply:** start with the unambiguous cases (unshifted buttons, single shift, plain LCD) so
the glyph table can be iterated against real output.
