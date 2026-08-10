---
name: final-manual-home-undecided
description: "Open decision: finished manuals (.final.idml) have no tracked home — raise it when the user produces one they care about"
metadata: 
  node_type: memory
  type: project
  originSessionId: ec08b19f-1946-4ee3-931e-87fdc5ed5cbf
  modified: 2026-08-10T15:20:46.201Z
---

Deliberately deferred on 2026-08-10, with the user's explicit request that I remember it because they probably won't: **there is no permanent home for a finished manual.**

`finish_manual.py` writes `<name>.final.idml` into `manuals/<product>/out/`, which is gitignored. So the actual deliverable — the only artifact CI can never reproduce, because it needs InDesign to run `place_xref_boxes.jsx` — lives untracked, unbacked-up, and indistinguishable from a throwaway build. Clearing the folder or re-cloning loses it.

**Why it was deferred rather than solved:** the right structure depends on facts not yet known — whether finals need sharing or only archiving, whether each should be pinned to a version, and whether the real deliverable turns out to be PDF/X rather than IDML. A tracked `manuals/<product>/final/` directory full of IDMLs would be the wrong build if the handover is a PDF.

**How to apply:** when the user mentions producing, sending, printing or archiving a finished manual, raise this before they lose one. The stopgaps already documented in GUIDE.md are: copy it outside the repo, or `gh release create v1.0 <file>.final.idml` (a release can hold a file CI cannot build). Solving it properly is a directory plus a few lines of workflow — small, so there is no urgency, only the risk of an untracked file going missing.

Related: [[open-items-2026-08-10]], [[toolchain-pivot]].
