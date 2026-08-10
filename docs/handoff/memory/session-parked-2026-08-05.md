---
name: session-parked-2026-08-05
description: "Superseded — the DM32 toolchain's open items as of 2026-08-10, after the re-entrancy work"
metadata:
  node_type: memory
  type: project
  originSessionId: b84fab6b-278f-44c5-9fb3-3dc4c4901651
  modified: 2026-08-10T15:21:10.295Z
---

Supersedes the 2026-08-05 park note. See [[toolchain-pivot]], [[oblique-link-structure]], [[section-master-conventions]], [[run-python-via-wsl]].

CLOSED since then (the README is now the source of truth for all of it): the InDesign 2026 crash (uppercase ids + duplicate master identity) is confirmed fixed; the repo was split into `toolchain/` / `kit/` / `manuals/`; chapter count is parametric; and as of 2026-08-10 the pipeline is **re-entrant** — `build_manual.py` accepts its own output, `finish_manual.py` is the ship-this-state exit, and `test_reentrancy.py` enforces the fixpoint in CI.

RESOLVED 2026-08-10: dm42n's shared-story failure is **fixed** — the user re-poured it (commits 7bf9359, 6b0cff2), it builds clean, and CI is green. It also now runs with `sync = masters`, the first manual to opt into kit transplants. If it fails validation again with "N titles:lvl2 headings share a story", that is content to split in InDesign, not a toolchain bug.

STILL OPEN, and not derivable from the code:

- `manual_template_test1.idml`, a *tracked submission*, already carries 56 margin boxes (it came from the old non-JSX path). It builds fine because `build_manual.py` normalises it first, but it is not really a submission — worth re-filing under `roundtrips/` at some point.
- Where finished manuals live: [[final-manual-home-undecided]].

**Why:** a "submission" that behaves like a round-trip looks like a bug in detection when it is just misfiled provenance.

**How to apply:** don't debug normalisation when test1 reports as already-processed — it genuinely is.
