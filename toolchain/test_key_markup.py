#!/usr/bin/env python3
"""Prove apply_key_markup.py renders what it should -- and only once.

    test_key_markup.py            (exit 0 = pass)

IDEMPOTENCE IS THE POINT. There is no reverse transform: markup is typed once,
rendered, and stays rendered, so the guarantee the pipeline leans on is that a
second pass changes nothing. Without a test that property rots silently -- the
transform would keep working while quietly re-rendering its own output, and the
damage would only surface as doubled guillemets in a proof.

The escape case is the one that would break it: `\\[EXIT\\]` renders to the plain
text `[EXIT]`, which a second pass would turn into a button unless the brackets
came out carrying `no_markup`. That is the whole reason the style exists, so it
is tested explicitly rather than trusted.

Builds its fixture from the real kit, so it also fails if the kit stops carrying
a style the transform renders into.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "kit", "manual_kit.idml")

STORY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="20.0">
\t<Story Self="utest01" AppliedTOCStyle="n" TrackChanges="false">
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Press [EXIT] then [[A]] and [SIGMA].</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Shifted &lt;ACOS&gt; and &lt;2:MEAN&gt; show {ALL} {^HI} {/it} {^/both}.</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Escaped \\[EXIT\\] stays literal.</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Split [EX</Content>
\t\t\t</CharacterStyleRange>
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>IT] across runs.</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/btn_normal">
\t\t\t\t<Content>‹EXIT›</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Press [ENTER] then &lt;OFF&gt; and &lt;sk&gt; to stop.</Content>
\t\t\t\t<Br />
\t\t\t\t<Br />
\t\t\t\t<Content>A second line with [STO] after the break.</Content>
\t\t\t\t<Br />
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/prgm_listing">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/code_styles%3acode_sk">
\t\t\t\t<Content>01 LBL [A]</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">
\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">
\t\t\t\t<Content>Prose where a &lt; b and c &gt; d must survive.</Content>
\t\t\t</CharacterStyleRange>
\t\t</ParagraphStyleRange>
\t</Story>
</idPkg:Story>
"""

fails = []


def want(cond, label):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        fails.append(label)


def main():
    work = tempfile.mkdtemp(prefix="keymarkup_")
    try:
        with zipfile.ZipFile(KIT) as z:
            z.extractall(work)
        story = os.path.join(work, "Stories", "Story_utest01.xml")
        open(story, "w", encoding="utf-8").write(STORY)

        def run():
            r = subprocess.run([sys.executable, os.path.join(HERE, "apply_key_markup.py"), work],
                               text=True, capture_output=True)
            print(r.stdout.rstrip())
            if r.stderr.strip():
                print("STDERR:", r.stderr.strip())
            return r.returncode

        print("=== pass 1 " + "=" * 56)
        rc1 = run()
        out = open(story, encoding="utf-8").read()

        def styled(style, content):
            return re.search(
                r'<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/'
                + re.escape(style) + r'"[^>]*>\s*<Content>' + re.escape(content)
                + r'</Content>', out) is not None

        print("\n--- rendering ---")
        want(styled("btn_normal", "‹EXIT›"), "[EXIT] -> btn_normal, guillemets added")
        want(styled("letter_normal", "‹A›"), "[[A]] -> letter_normal, guillemets added")
        want(styled("btn_normal", "‹Σ›"), "[SIGMA] -> glyph map applied")
        want(styled("btn_or", "ACOS"), "<ACOS> -> shift 1, bare")
        want(styled("btn_bl", "MEAN"), "<2:MEAN> -> shift 2, bare")
        want(styled("code_styles%3alcd_sk", "ALL"), "{ALL} -> lcd_sk, bare")
        want(styled("code_styles%3alcd_sk_high", "HI"), "{^HI} -> lcd_sk_high")
        want(styled("code_styles%3alcd_sk_slant", "it"), "{/it} -> lcd_sk_slant")
        want(styled("code_styles%3alcd_sk_slant_high", "both"), "{^/both} -> lcd_sk_slant_high")

        print("\n--- escapes, splits, and what must NOT change ---")
        want(styled("no_markup", "["), "escaped bracket carries no_markup")
        want(out.count("‹EXIT›") >= 3, "run split mid-token was merged and rendered")
        # the shape that broke first on real content: InDesign routinely puts
        # <Content> and <Br/> in one run, and requiring pure text skipped it whole
        want(styled("btn_normal", "‹ENTER›") and styled("btn_or", "OFF")
             and styled("btn_or", "sk"),
             "run mixing Content with Br still renders")
        want(styled("btn_normal", "‹⭳›"),
             "markup after a line break renders, glyph map applied ([STO])")
        want(out.count("<Br />") == 3, "every line break survived the split")
        want("01 LBL [A]" in out, "program listing left verbatim")
        want("a &lt; b and c &gt; d" in out, "prose with < and > untouched")
        want("idPkg:Story" in out and "ns0:" not in out, "idPkg namespace preserved")

        print("\n=== pass 2 (idempotence) " + "=" * 42)
        rc2 = run()
        want(open(story, encoding="utf-8").read() == out,
             "second pass byte-identical -- f(f(x)) == f(x)")
        want(rc1 == 0 and rc2 == 0, f"both passes exit 0 (got {rc1}, {rc2})")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
