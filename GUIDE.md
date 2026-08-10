# Making a manual — the short version

This is the everyday guide. It assumes you know InDesign and nothing about the code.
The full technical reference is [README.md](README.md).

---

## What this thing is for

You write and lay out the manual in InDesign. But a few jobs are miserable by hand and
have to be redone every time the content moves:

- numbering the headings, and keeping the numbers right when a chapter is inserted;
- giving every chapter its own **thumb tab** down the page edge, in the right colour, at
  the right height, on the right pages;
- telling InDesign where each chapter starts (a **section**), so page numbering and the
  running heads follow;
- placing the little **orange margin numbers** next to underlined cross-reference words,
  and pointing each one at the right target.

The toolchain does exactly those four things. It does not touch your words, your
pictures, or your layout.

**One rule to remember:** each chapter must be its own text story. If two chapter
headings live in the same story, the second one gets no tab and no section, and the tool
will say so.

---

## The three steps

```
   1. InDesign            2. the toolchain            3. InDesign
   ─────────────          ────────────────            ───────────
   pour content    ──►    numbering, sections,   ──►  run one script:
   into the kit,          tabs, cross-ref             the margin boxes
   export IDML            bookkeeping                 appear
                                                            │
                                                            ▼
                                                    ship it, or go
                                                    round again
```

### Step 1 — In InDesign

Open `kit/manual_kit.idml`. It is the blank house style: fonts, colours, masters, the
heading levels, everything — no content. Pour your text in, apply the heading styles
(`titles:lvl1` … `titles:lvl4`), underline your cross-reference words with the `link`
character style, and export as IDML.

Save the export into `manuals/<your-product>/submissions/`.

### Step 2 — Run one command

```bash
python3 toolchain/build_manual.py manuals/dm32/submissions/your-file.idml
```

It prints what it did and stops with either:

- **`ready for InDesign: …/your-file.ready.idml`** — good, go to step 3; or
- **a list of problems** — nothing was produced. See *When it complains* below.

### Step 3 — Back in InDesign

Open the `.ready.idml` file. Run `toolchain/place_xref_boxes.jsx`
(*File ▸ Scripts*, double-click it). A dialog tells you how many margin boxes it made.

That step has to happen inside InDesign — margin boxes are the one thing that only
InDesign can create properly. Everything else is automatic.

Now export IDML again. You have two choices, and this is the important bit:

| You want to… | Run | You get |
|---|---|---|
| **Ship this** | `python3 toolchain/finish_manual.py your-export.idml` | `your-file.final.idml` — tidied up, boxes kept |
| **Keep editing** | `python3 toolchain/build_manual.py your-export.idml` | a fresh `.ready.idml` — go back to step 3 |

---

## Going round again

This is the part that is new, and the reason you can work iteratively.

**You can feed a finished manual straight back in.** Edit the text in InDesign, add a
chapter, re-pour a section, export, and hand that file to `build_manual.py` again. It
recognises a file it has already worked on and cleans up after itself first — old margin
boxes off, old chapter tabs off, old sections off — then rebuilds all of it from the
content as it now stands.

So you never have to think about "has this been processed?". Just run it.

Two things you should know about the loop:

- **Boxes are always rebuilt, never added to.** That is why the old ones come off first.
  If they didn't, you would get two boxes next to every word, then three.
- **A cross-reference whose target isn't in the document gets switched off, once.** The
  underline is removed and the word stays as plain text. It is written to the audit file
  (`*.xref_log.csv`) next to the output so you can look through them. It does not come
  back on a later run — if one was switched off wrongly, fix the link in InDesign.

---

## If you change the kit

The kit (`kit/manual_kit.idml`) is a **mould, not a master document**. Pouring content
into it gives you a file that owns a complete private copy of the design — its own
masters, styles, colours. After that the two are unrelated files.

So if you change a master in the kit — say you add a text variable to the running title
on B-Base — **nothing that already exists notices.** New pours get it. Manuals in flight
keep the old design, quietly, forever.

To make a kit change reach a manual, add one line to that manual's `.manual` file:

```
sync = masters
```

From then on, every build re-transplants the kit's masters into that manual, so the kit is
genuinely the source of truth. Without the line you still get a report of what has drifted
apart — it just doesn't change anything.

Three things worth knowing before you switch it on:

- **Your page overrides survive.** If you've overridden a master item on a page (a running
  head with custom text, say), that keeps working — the transplant deliberately preserves
  the identity of every item a page points at. If a kit change would break one, the build
  stops and tells you which, rather than doing it.
- **What the master needs comes with it.** New styles, colours and text variables the
  master references are brought across automatically. **Fonts are not** — the build tells
  you which are missing and you install and add them yourself.
- **Your tabs and chapter masters are untouched.** Those are generated from your content
  every build; the kit has no opinion about them.

To try a kit change before committing it:

```bash
python3 toolchain/build_manual.py manuals/dm32/submissions/f.idml --kit /path/to/trial-kit.idml
```

## Getting the built file

Every time something is pushed to the repository, the build is published to an address
that never changes:

```
https://github.com/AmsteinGraphics/idml_testing/releases/download/latest/dm32.ready.idml
https://github.com/AmsteinGraphics/idml_testing/releases/download/latest/dm42n.ready.idml
```

Paste it into a browser and it downloads. Or:

```bash
python3 toolchain/fetch_build.py          # everything, into downloads/
python3 toolchain/fetch_build.py dm32     # just one
```

One file per manual, named after the product — bookmark it, it is the same one tomorrow.
If a manual has several submissions, the one published is the most recently updated; the
others are still in the repo and rebuild on demand.

> **Export IDML, not InDesign's own format.** `.indd` is what the Save dialog offers by
> default, but the toolchain reads and writes IDML only, and a `.indd` is roughly ten
> times the size. They are ignored by the repository now, so saving one by accident is
> harmless — it just won't do anything.

---

## When it complains

The tool stops rather than producing something subtly wrong. What you'll see:

**"4 `titles:lvl2` heading(s) share a story with another"**
Two or more chapters are in one text flow. Split them in InDesign so each chapter starts
its own story. (This is what currently blocks the DM42n manual.)

**"tab strip has N slots but M chapters were detected"**
Rare — it means the strip and the content disagree. Run
`python3 toolchain/configure_chapters.py <build dir>`, which the message will name.

**"N margin boxes are already in this document"**
You told it to treat a finished file as fresh content. Drop the `--as-submission` flag
and let it clean up normally.

**"more than one BT-BaseTabs master"**
The file has duplicate masters, usually from an old version of the toolchain. Run
`python3 toolchain/normalize_input.py <build dir>` first.

**"transplant would orphan page overrides"**
You have `sync = masters` on, and the kit no longer has an item that some of your pages
override. It names the item and how many pages. Either put it back in the kit, or clear
those overrides in InDesign — the tool won't guess which you meant.

**Underline warnings**
Underlines must come from a character style, never from local formatting — otherwise the
orange rule quietly turns black. Most are cleaned automatically. If it says it *left some
alone*, it is because removing them would change what prints, and that is your call.

---

## Starting a new manual

```bash
mkdir -p manuals/dm42n/submissions
cp kit/manual_kit.manual manuals/dm42n/dm42n.manual
```

Then edit `dm42n.manual` — it is a short list of settings:

```
swatch    = Black                 # the inks this manual may use
swatch    = PANTONE 130 U
levels    = 4                     # how many heading levels it uses
tab_level = 2                     # which level gets a thumb tab
number_from = 2                   # first level that takes a number
sync      = masters               # optional: keep the kit's masters authoritative
tab_stop  = PANTONE 130 U         # the tab colours, top of the strip…
tab_stop  = Black                 # …to the bottom; the rest are blended
```

The **chapter count is not a setting**. It is however many chapters your content has, and
the tab strip is rebuilt to match every time.

---

## The commands, all of them

| Command | What it's for |
|---|---|
| `build_manual.py FILE.idml` | the main one — submission *or* a file coming back round |
| `finish_manual.py FILE.idml` | tidy up an InDesign export and call it done |
| `fetch_build.py` | download the current build |
| `resolve_xref.py --audit` | report on the cross-reference system |
| `sync_from_kit.py DIR` | what has drifted from the kit (`build_manual.py` runs it for you) |

Two more take an *unpacked* folder rather than an `.idml`, so they're for when something
has gone wrong and you're poking at the innards:
`normalize_input.py DIR --detect` ("has this been through the mill?") and
`validate_idml.py DIR` (check without changing). `build_manual.py` runs the second one
for you anyway.

Everything else in `toolchain/` is a single stage that `build_manual.py` already runs, or
a one-time repair. You should not need them day to day.
