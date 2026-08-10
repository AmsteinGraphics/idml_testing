# Round-trips

Files that came **back** from InDesign after `place_xref_boxes.jsx` ran. They
already have sections, tabs and margin boxes, so they are not submissions — but
they are valid input:

```bash
python3 toolchain/build_manual.py  manuals/dm32/roundtrips/FILE.idml   # revise + rebuild
python3 toolchain/finish_manual.py manuals/dm32/roundtrips/FILE.idml   # keep the boxes, ship
```

`build_manual.py` detects the marks and runs `normalize_input.py` first — see
"The loop: refining a book" in the top-level README. CI still builds only
`submissions/`, because that is where new content arrives.

`manual_template_test2_jsx_processed.idml` doubles as the re-entrancy fixture: it
is the one file in the repo carrying everything the loop has to undo (25 margin
boxes, 3 local underline overrides, and two chapter masters InDesign renamed to
`A-BaseTabs` / `D-BaseTabs` when it broke their duplicate identity).

It is kept because it is not reproducible
here (it needs InDesign) and because it is the evidence for the underline rule:
three `CharacterStyle/link` ranges came back carrying a local
`<UnderlineColor type="string">Text Color</UnderlineColor>`, which defeats the
style's PANTONE 130 U orange. That is what `fix_underlines.py` strips and what
check 10 in `validate_idml.py` enforces.
