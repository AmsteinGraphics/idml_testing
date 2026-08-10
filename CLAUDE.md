# CLAUDE.md

Instructions for Claude Code working in this repo.

## Resuming

If you are starting fresh — new machine, new session, no prior context — read
`docs/handoff/README.md` first. It records where the work stopped, what the next task is,
and the questions that were left open. The notes under `docs/handoff/memory/` hold the
decisions and dead ends that the code cannot tell you.

## What this repo is

A toolchain that turns an InDesign IDML submission into a finished print manual: sections,
tab strip, per-chapter masters, and oblique cross-reference margin boxes. `README.md` is
the reference; `GUIDE.md` is the same thing for the user, in three steps.

- `toolchain/` — the Python scripts and the one JSX that runs inside InDesign.
- `kit/` — `manual_kit.idml`, the hand-authored empty template everything derives from.
- `manuals/<product>/` — per-product submissions, config (`<product>.manual`), round-trips.

## Working rules

- **The pipeline is re-entrant, and must stay that way.** `build_manual.py` accepts its own
  output; `test_reentrancy.py` enforces the fixpoint in CI. Any new transform needs its
  reverse in `normalize_input.py`, or it breaks that property.
- **Anchored objects cannot be authored in IDML.** Hand-built anchored frames do not bind
  to their story on import — this was established exhaustively, and cost a lot of time.
  Anything anchored goes through `place_xref_boxes.jsx`, natively in InDesign. See
  `docs/handoff/memory/oblique-link-structure.md` before revisiting it.
- **IDML ids must be lowercase hex** (`u<hex>`). Uppercase ids break the frame-to-story link.
- Submissions arrive in authoring state with `dm32_list` numbering already active. The
  toolchain generates on top of that; it does not activate or flatten numbering.
- Chapter count is parametric — read it from the content, never assume 26.

## Running the scripts

This repo may live inside WSL while Claude Code runs on the Windows host. If so, a bare
`python3` hits the Windows App Execution Alias stub instead of an interpreter; go through
WSL, and see `docs/handoff/memory/run-python-via-wsl.md` for the two harness gotchas that
come with it. On a native Linux or macOS machine none of that applies.

## Repo hygiene

`manuals/*/build/` and `manuals/*/out/` are gitignored working trees, reproducible from the
tracked inputs. The exception worth knowing about: `<name>.final.idml` in `out/` is **not**
reproducible by CI, because producing it requires InDesign. It currently has no tracked
home — raise this with the user before one gets lost.
