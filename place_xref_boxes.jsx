/*  place_xref_boxes.jsx  —  DM32 oblique-ref margin boxes
 *
 *  Run in InDesign on a manual produced by the toolchain (sections + tabs
 *  applied, dead cross-references already suppressed). For every underlined
 *  oblique-ref word it creates a native anchored margin box holding a LIVE
 *  cross-reference (format dm32_cross_ref) to that word's target.
 *
 *  REBUILD: re-running removes every existing margin box first, then recreates
 *  the whole set.
 *
 *  This build is INSTRUMENTED: on error it reports which step failed, and it
 *  tries several cross-reference API forms so the first run tells us which one
 *  this InDesign version supports.
 */
#target "indesign"

(function () {
    if (app.documents.length === 0) { alert("Open the manual document first."); return; }
    var doc = app.activeDocument;

    var FORMAT = "dm32_cross_ref", OBJSTYLE = "cross_ref_block",
        PARA = "cross_ref_par", CHAR = "link";
    var WIDTH_MM = 10.00, HEIGHT_MM = 3.64;      // requested box size

    var fmt = doc.crossReferenceFormats.itemByName(FORMAT);
    var objStyle = doc.objectStyles.itemByName(OBJSTYLE);
    var paraStyle = doc.paragraphStyles.itemByName(PARA);
    var linkStyle = doc.characterStyles.itemByName(CHAR);
    if (!fmt.isValid)      { alert("Cross-reference format '" + FORMAT + "' not found."); return; }
    if (!objStyle.isValid) { alert("Object style '" + OBJSTYLE + "' not found."); return; }

    // work in millimetres so geometry matches the spec
    var savedH = doc.viewPreferences.horizontalMeasurementUnits,
        savedV = doc.viewPreferences.verticalMeasurementUnits;
    doc.viewPreferences.horizontalMeasurementUnits = MeasurementUnits.MILLIMETERS;
    doc.viewPreferences.verticalMeasurementUnits = MeasurementUnits.MILLIMETERS;

    // ---- 1. REBUILD: remove existing boxes + their xrefs ----
    function isBox(fr) { try { return fr.isValid && fr.appliedObjectStyle.name === OBJSTYLE; } catch (e) { return false; } }
    var removed = 0, frames = doc.textFrames.everyItem().getElements();
    for (var f = frames.length - 1; f >= 0; f--) if (isBox(frames[f])) { try { frames[f].remove(); removed++; } catch (e) {} }
    var hls0 = doc.hyperlinks.everyItem().getElements();
    for (var h = hls0.length - 1; h >= 0; h--) {
        try { var s = hls0[h].source; if (s === null || !s.isValid || s.constructor.name === "CrossReferenceSource") hls0[h].remove(); }
        catch (e) { try { hls0[h].remove(); } catch (e2) {} }
    }

    // ---- helper: create the cross-reference, trying known API forms ----
    function addCrossRef(boxIP, dest) {
        var tried = [];
        // form A: document-level collection
        try { var a = doc.crossReferenceSources.add(boxIP, fmt); doc.hyperlinks.add(a, dest); return "A"; }
        catch (e) { tried.push("A:" + e); }
        // form B: insertion-point collection, format only
        try { var b = boxIP.crossReferenceSources.add(fmt); doc.hyperlinks.add(b, dest); return "B"; }
        catch (e) { tried.push("B:" + e); }
        // form C: paragraph-text-source style (source = the box text)
        try { var c = doc.paragraphDestinations; } catch (e) {}
        throw new Error(tried.join(" | "));
    }

    // ---- 2. CREATE ----
    var links = doc.hyperlinks.everyItem().getElements();
    var made = 0, skipped = 0, errors = [], step = "";
    for (var i = 0; i < links.length; i++) {
        var src, dest;
        try {
            step = "read-link";
            src = links[i].source; dest = links[i].destination;
            if (!src || !dest) { skipped++; continue; }
            if (src.constructor.name !== "HyperlinkTextSource") { skipped++; continue; }
            if (dest.constructor.name !== "HyperlinkTextDestination") { skipped++; continue; }
            step = "src-text";
            var srcText = src.sourceText;
            if (linkStyle.isValid && srcText.appliedCharacterStyle !== linkStyle) { skipped++; continue; }

            step = "add-frame";
            var ip = srcText.insertionPoints[0];
            var frame = ip.textFrames.add();

            step = "size";
            var b = frame.geometricBounds;            // [y1,x1,y2,x2] (mm)
            frame.geometricBounds = [b[0], b[1], b[0] + HEIGHT_MM, b[1] + WIDTH_MM];

            step = "objstyle";
            frame.appliedObjectStyle = objStyle;

            step = "para-style";
            if (paraStyle.isValid) { try { frame.parentStory.paragraphs[0].appliedParagraphStyle = paraStyle; } catch (e) {} }

            step = "xref";
            var boxIP = frame.parentStory.insertionPoints[0];
            var form = addCrossRef(boxIP, dest);

            made++;
        } catch (e) {
            errors.push("[" + step + "] " + (src && src.name ? src.name : "?") + " :: " + e);
        }
    }
    try { doc.crossReferenceSources.everyItem().update(); } catch (e) {}

    doc.viewPreferences.horizontalMeasurementUnits = savedH;
    doc.viewPreferences.verticalMeasurementUnits = savedV;

    var msg = "Oblique-ref margin boxes (rebuild)\n  removed: " + removed
            + "\n  created: " + made + "\n  skipped: " + skipped;
    if (errors.length) msg += "\n  errors: " + errors.length + "\n  " + errors.slice(0, 6).join("\n  ");
    alert(msg);
})();
