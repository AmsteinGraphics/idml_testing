# Round-trips

Files that came **back** from InDesign after `place_xref_boxes.jsx` ran — not
submissions. They already have sections, tabs and margin boxes, so the forward
pipeline must not be re-run on them; `submissions/` is what CI builds.

`manual_template_test2_jsx_processed.idml` is kept because it is not reproducible
here (it needs InDesign) and because it is the evidence for the underline rule:
three `CharacterStyle/link` ranges came back carrying a local
`<UnderlineColor type="string">Text Color</UnderlineColor>`, which defeats the
style's PANTONE 130 U orange. That is what `fix_underlines.py` strips and what
check 10 in `validate_idml.py` enforces.
