---
name: section-master-conventions
description: How chapters map to InDesign Sections and per-chapter S<N>-<Title> master spreads in the DM32 manual
metadata: 
  node_type: memory
  type: reference
  originSessionId: b84fab6b-278f-44c5-9fb3-3dc4c4901651
---

Proven structure in the shipped manual (`dm32_print_manual_v1.76_fixed.idml`), to be reproduced by the forward toolchain (see [[toolchain-pivot]]):

- **One InDesign `<Section>` per chapter** in designmap.xml. Attrs that matter: `Marker="<chapter title>"` (the heading text, sans number), `PageStart="<page Self where chapter begins>"`, `Length="<page count>"`, `ContinueNumbering="true"`. Shipped manual has 28 sections.
- **One master spread per chapter, named `S<N>-<Title>`** (e.g. `S5-Entering and displaying numbers`). Each owns its single tab + chapter-number, applied to all that chapter's pages. Base masters (B-Base, BT-BaseTabs, NT-NavTabs, Sx-Section, C-Contents, I-Index, N-Notes) + ~26 chapter masters ≈ 32 total.
- Tab colour/number: **SEQUENTIAL** (user decision 2026-08-04) — the Kth chapter in reading order uses mixed-ink swatch `tab_0K` at vertical slot K, renumbered from 1, regardless of the number printed in the heading text. (The test book is chapters 5–7 by heading, but its tabs are 1/2/3.) Section `Marker`/master title still come from the heading title text. tab_01..24 pre-baked in the kit.

Page-of-chapter mapping (no InDesign needed): each chapter is its own threaded story. The story's HEAD text frame (the one with `PreviousTextFrame="n"`) sits on the chapter's start page. Associate a frame to a page geometrically: pick the page on the frame's spread whose x-extent (page ItemTransform tx + GeometricBounds x1..x2) contains the frame's ItemTransform tx. IMPORTANT: iterate spread elements with `.iter()` (frames can be nested in groups), not direct children only.
