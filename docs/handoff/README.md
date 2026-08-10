# Handoff — resuming this work on another machine

This directory exists so that a fresh Claude Code session, on a computer that has never
seen this project, can pick the work up from a clone alone. Everything here is context
that is **not** derivable from the code: decisions, dead ends, and the state of the
conversation when it stopped.

For what the toolchain *is* and how to run it, read `README.md` and `GUIDE.md` at the repo
root instead. This file does not repeat them.

## Read these, in this order

1. `../../GUIDE.md` — the three-step workflow, in the user's terms.
2. `../../README.md` — the toolchain reference, and its own `## Status` section for
   open engineering items.
3. `memory/MEMORY.md` — the index of the notes below, one line each.
4. `memory/key-markup-proposal.md` — **this is the next task**, see below.

## Where the work stopped (2026-08-10)

The pipeline is finished and healthy: re-entrant, CI-green, `dm42n` builds clean and is
the first manual to opt into kit transplants (`sync = masters`). Nothing is broken.

The **next task** is the key-markup feature: authors type `[EXIT]`, `<ACOS>`, `{ALL}` in
plain text and the toolchain converts them into the real SwissKeys character styles, with
`normalize_input.py` reversing the transform so the pipeline stays re-entrant. The design
is agreed. It is **not** started — no `apply_key_markup.py` exists.

**Three questions were open and unanswered when the session ended.** They are listed in
`memory/key-markup-proposal.md`, and they gate the syntax, not the architecture:

1. Letter keys — is `[[A]]` acceptable, or should each manual list its letter keys in
   config? (`[C]` cannot be resolved by rule: Clear key vs letter C.)
2. Second shift colour — `<<NAME>>`, or a prefix like `<b:NAME>`? DM32 has two shift
   colours, DM42n has one.
3. `_table` style variants — automatic inside a table, or explicit markup?

Ask those three before writing code. The encoding facts the feature rests on are in
`memory/swisskeys-encoding.md` — that survey cost a full pass over 2323 stories in
`manuals/dm32/dm32_print_manual_v1.76.idml` and is expensive to re-derive.

## Also open, and easy to lose

- **Finished manuals have no permanent home** (`memory/final-manual-home-undecided.md`).
  `finish_manual.py` writes `<name>.final.idml` into the gitignored `manuals/<product>/out/`.
  That file is the one artifact CI can never rebuild, because it needs InDesign to run
  `place_xref_boxes.jsx`. The user asked to be reminded before one goes missing.
- `manuals/dm32/submissions/manual_template_test1.idml` is really a round-trip, not a
  submission — misfiled provenance, not a detection bug.

## Re-seeding the memory notes

`memory/` here is a verbatim copy of a Claude Code auto-memory directory — frontmatter,
`[[wikilinks]]` and all. To make a new session load them as memories rather than as
documents, copy the contents into that machine's memory directory for this project:

```
~/.claude/projects/<mangled-project-path>/memory/
```

The `<mangled-project-path>` is the project's absolute path with separators replaced by
dashes, so it differs per machine — let Claude Code create the directory once, then copy
these files in beside the `MEMORY.md` it wrote. Merge the index rather than overwriting it
if one already exists.

Reading them straight from this directory works too; it just doesn't survive into later
sessions automatically.

## A caveat on the notes

They are point-in-time observations, dated in their frontmatter, not live state. Several
predate work that has since closed them out — `session-parked-2026-08-05.md` in particular
exists to record what its own predecessor got wrong. Where a note describes code, verify
against the code before relying on it. Where it records a *decision* or a *dead end*
(most of `oblique-link-structure.md`), it is the only record there is.

`memory/run-python-via-wsl.md` is specific to the machine this work was done on — a Windows
host driving a repo inside WSL. On a native Linux or macOS machine, ignore it and call
`python3` directly.
