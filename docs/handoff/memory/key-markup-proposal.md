---
name: key-markup-proposal
description: Agreed design (not yet built) for plain-text markup that the toolchain turns into SwissKeys button/LCD formatting — plus the 3 open questions blocking a start
metadata: 
  node_type: memory
  type: project
  originSessionId: ec08b19f-1946-4ee3-931e-87fdc5ed5cbf
  modified: 2026-08-10T15:57:50.603Z
---

Proposed 2026-08-10, **not yet implemented**. The user wants content poured in InDesign to use plain-text conventions that the toolchain converts into the real character styles, so authors never hand-apply `btn_normal`/`lcd_sk`. Encoding facts this rests on: [[swisskeys-encoding]].

**The convention** (user's idea, extended after surveying v1.76):

| author types | content produced | style |
|---|---|---|
| `[EXIT]` `[9]` | `‹EXIT›` `‹9›` | `btn_normal` |
| `[[A]]` | `‹A›` | `letter_normal` (proposed, see Q1) |
| `<ACOS>` | `ACOS` (no delimiters) | shift colour, per manual |
| `{ALL}` `{1 2/3}` | verbatim | `code_styles:lcd_sk` |
| `{^…}` `{/…}` `{^/…}` | verbatim | `lcd_sk_high` / `_slant` / `_slant_high` |

**Architecture, which matters more than the syntax:** `apply_key_markup.py` runs forward (after `sync_from_kit.py`), and **`normalize_input.py` reverses it** — a `btn_normal` run `‹EXIT›` becomes `[EXIT]` again on the way back in. That is what keeps the pipeline re-entrant: type markup → get real buttons → edit in InDesign → export → feed back → markup reappears → re-transform. Exactly the pattern already used for the oblique-ref margin boxes, and `test_reentrancy.py` will prove convergence the same way.

Other agreed pieces: a `kit/swisskeys.map` glyph table (`name = glyph`, per-manual override, unmapped names pass through so `[EXIT]` needs no entry, refined iteratively); `\[` to escape a literal bracket; never transform inside `code_sk` blocks; new `validate_idml.py` checks for leftover un-transformed markup and for glyphs missing from the map.

**THREE OPEN QUESTIONS — the user had not answered them when the conversation ended:**

1. **Letter keys** — is `[[A]]` acceptable, or should each manual list its letter keys in config? Needed because `[C]` cannot be resolved by rule (Clear key vs letter C).
2. **Second shift colour** — DM42n has one, DM32 has two (orange + blue). `<<NAME>>` for the second, or a prefix like `<b:NAME>`?
3. **`_table` variants** — applied automatically when inside a table, or explicit markup?

**Why:** the design is settled apart from these three; starting without answers means guessing at syntax the user will have to live with in every future pour, and changing it later means rewriting already-poured content.

**How to apply:** on resuming, ask those three first, then build the transform + reverse + map + validation, starting with the unambiguous cases (unshifted buttons, single shift, plain LCD) so the glyph table can be iterated against real output — the user explicitly expects the table to be refined during iteration rather than got right up front.
