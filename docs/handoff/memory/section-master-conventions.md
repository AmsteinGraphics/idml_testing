---
name: section-master-conventions
description: How chapters map to InDesign Sections and per-chapter S<N>-<Title> master spreads in the DM32 manual
metadata: 
  node_type: memory
  type: reference
  originSessionId: b84fab6b-278f-44c5-9fb3-3dc4c4901651
  modified: 2026-08-11T02:32:01.536Z
---

Proven structure in the shipped manual (`dm32_print_manual_v1.76_fixed.idml`), to be reproduced by the forward toolchain (see [[toolchain-pivot]]):

- **One InDesign `<Section>` per chapter** in designmap.xml. Attrs that matter: `Marker="<chapter title>"` (the heading text, sans number), `PageStart="<page Self where chapter begins>"`, `Length="<page count>"`, `ContinueNumbering="true"`. Shipped manual has 28 sections.
- **One master spread per chapter, named `S<N>-<Title>`** (e.g. `S5-Entering and displaying numbers`). Each owns its single tab + chapter-number, applied to all that chapter's pages. Base masters (B-Base, BT-BaseTabs, NT-NavTabs, Sx-Section, C-Contents, I-Index, N-Notes) + ~26 chapter masters ≈ 32 total.
- Tab colour/number: **SEQUENTIAL** (user decision 2026-08-04) — the Kth chapter in reading order uses mixed-ink swatch `tab_0K` at vertical slot K, renumbered from 1, regardless of the number printed in the heading text. (The test book is chapters 5–7 by heading, but its tabs are 1/2/3.) Section `Marker`/master title still come from the heading title text. tab_01..24 pre-baked in the kit.

## Tab numbers: `tab_shows` (added 2026-08-11)

`chapter_digit` (default) bakes the chapter ordinal into the master, as before.
`paragraph_number` puts the RUNNING section number on the tab, per the DM42n author's rule:

> page P's tab shows the number of the last numbered heading of ANY level that begins on
> or before P — "2.3.2", dropping to the 2-part "2.3" where no lvl4 has been reached yet.

**This cannot be a text variable and cannot be Python.** A running-header variable matches
ONE paragraph style, but which level applies changes page to page; pointed at lvl4 alone, a
page with no lvl4 falls back to the previous lvl4 — a stale number from an earlier section,
wrong in a way that looks plausible. A variable also emits number AND title; the tab has
room for the number only. And Python cannot know what is visible on a page — the same limit
that forces one story per chapter. So `place_tab_numbers.jsx` does it inside InDesign, using
`numberingResultNumber` (the composed number without the heading text). Second instance of
the [[oblique-link-structure]] lesson: if it depends on composition, it belongs in JSX.

The number differs per page while one master serves a whole chapter, so the JSX OVERRIDES
the master tab frame on each page. `normalize_input.drop_tab_number_overrides` removes those
on the way back in — they were computed against the old pagination, and keeping them is worse
than keeping none. Untestable without InDesign; the removal half is covered by synthesising
the override.

dm42n's real hierarchy: lvl1 parts (unnumbered), lvl2 chapters x, lvl3 sections x.x, lvl4
paragraphs x.x.x → `levels = 4`, `number_from = 2`, `tab_level = 2`, `tab_shows =
paragraph_number`. Its 31 lvl2 headings each own a story, which is what makes tab_level=2
the only workable choice.

Page-of-chapter mapping (no InDesign needed): each chapter is its own threaded story. The story's HEAD text frame (the one with `PreviousTextFrame="n"`) sits on the chapter's start page. Associate a frame to a page geometrically: pick the page on the frame's spread whose x-extent (page ItemTransform tx + GeometricBounds x1..x2) contains the frame's ItemTransform tx. IMPORTANT: iterate spread elements with `.iter()` (frames can be nested in groups), not direct children only.
