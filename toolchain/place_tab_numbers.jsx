/*  place_tab_numbers.jsx  —  running section number on every thumb tab
 *
 *  Run in InDesign on a manual produced by the toolchain with
 *  `tab_shows = paragraph_number` in <product>.manual, so apply_tabs.py has left
 *  the tab-number frames empty.
 *
 *  THE RULE, from the manual's author:
 *      the number on page P's tab is that of the LAST NUMBERED HEADING OF ANY
 *      LEVEL that begins on or before P.
 *  So a page showing the head of 2.3.2 gets "2.3.2"; a page showing only the
 *  body of 5.6.3 gets "5.6.3" because that heading began earlier; and a page
 *  under a lvl3 section that has not reached a lvl4 yet gets the 2-part "x.x".
 *  The short number falls out of the rule -- there is no special case for it.
 *
 *  WHY THIS CANNOT BE A TEXT VARIABLE. A running-header variable matches ONE
 *  paragraph style. This rule needs whichever of lvl2/lvl3/lvl4 is deepest so
 *  far, which changes page to page. Pointed at lvl4 alone, a page with no lvl4
 *  falls back to the previous lvl4 -- a stale number from an earlier section,
 *  wrong in a way that looks plausible on a proof. A variable also inserts the
 *  heading's TEXT (number AND title); numberingResultNumber gives the number
 *  alone, which is what a tab has room for.
 *
 *  WHY IT CANNOT BE THE PYTHON TOOLCHAIN. The answer depends on what is visible
 *  on a page, and only InDesign knows that -- the same limit that forces one
 *  story per chapter.
 *
 *  OVERRIDES. The tab frame lives on the chapter master and one master serves
 *  the whole chapter, so a per-page number means overriding that frame on each
 *  page. normalize_input.py removes those overrides when the file is fed back in.
 *
 *  REBUILD: re-running clears every number it previously placed, then refills.
 *
 *  INSTRUMENTED: the numbering API is untested here, exactly as the cross-
 *  reference API was, so the first run reports what it found and what it could
 *  not read rather than failing silently.
 */
#target "indesign"

(function () {
    if (app.documents.length === 0) { alert("Open the manual document first."); return; }
    var doc = app.activeDocument;

    var TAB_LEAF = "tab_right";                 // foot_and_tabs:tab_right
    var MIN_LEVEL = 2;                          // lvl1 is a Part label and never counts

    var log = [], placed = 0, cleared = 0, noNumber = 0, noFrame = 0;
    var seenStyles = {}, scanned = 0, matchedHeads = 0;

    // ---- helpers -----------------------------------------------------------
    // These styles live inside style GROUPS ($ID/titles, $ID/foot_and_tabs), and
    // the DOM may report a grouped style's name as the leaf ("lvl2") or as the
    // full path ("titles:lvl2") -- the IDML carries the path, InDesign often does
    // not. Comparing against one spelling silently matched nothing and produced
    // "no numbered headings found" with no clue why. Match on the LEAF, which is
    // the same either way, and nothing else in this kit collides with it:
    // "standard_olist_lvl2" and "toc:toc_lvl2" both fail /^lvl\d+$/.
    function leafName(style) {
        try {
            var n = String(style.name);
            var i = n.lastIndexOf(":");
            return i >= 0 ? n.substring(i + 1) : n;
        } catch (e) { return ""; }
    }

    function paraStyleLeaf(p) {
        try { return leafName(p.appliedParagraphStyle); } catch (e) { return ""; }
    }

    function headingLevel(leaf) {
        var m = /^lvl(\d+)$/.exec(leaf);
        return m ? parseInt(m[1], 10) : 0;
    }

    function startPageOf(para) {
        // the page the heading BEGINS on -- its first character's frame
        try {
            var frames = para.characters[0].parentTextFrames;
            if (!frames || frames.length === 0) return null;
            var pg = frames[0].parentPage;
            return (pg && pg.isValid) ? pg : null;
        } catch (e) { return null; }
    }

    // The composed list number, WITHOUT the heading text. Which property carries
    // it is version-dependent and untested here, so try the known spellings and
    // record which one answered -- the first run tells us rather than us guessing.
    var numberForm = null;
    function numberOf(para) {
        var forms = [
            ["numberingResultNumber", function (p) { return p.numberingResultNumber; }],
            ["numberingResultString", function (p) { return p.numberingResultString; }],
            ["bulletOrNumber",        function (p) { return p.bulletOrNumber; }]
        ];
        for (var i = 0; i < forms.length; i++) {
            // once a form has answered, stay with it instead of re-probing 300 times
            if (numberForm !== null && forms[i][0] !== numberForm) continue;
            try {
                var v = forms[i][1](para);
                if (v !== undefined && v !== null && String(v) !== "") {
                    var s = String(v).replace(/^\s+/, "").replace(/[\s.]+$/, "");
                    if (s !== "") { numberForm = forms[i][0]; return s; }
                }
            } catch (e) {
                if (log.length < 12) log.push(forms[i][0] + ": " + e);
            }
        }
        return null;
    }

    // The tab frames are EMPTY by design under tab_shows = paragraph_number --
    // apply_tabs.py clears them precisely so this script can fill them. An empty
    // story can expose no paragraphs at all, so reading paragraphs[0] to identify
    // the frame threw for every one of them and found nothing. An insertion point
    // exists even in an empty story, so ask that first and keep the others as
    // fallbacks. Duck-typed rather than `instanceof TextFrame`, which is one more
    // assumption than this needs.
    var frameStylesSeen = {};
    function frameParaLeaf(item) {
        var tries = [
            function () { return item.insertionPoints[0].appliedParagraphStyle; },
            function () { return item.parentStory.insertionPoints[0].appliedParagraphStyle; },
            function () { return item.parentStory.paragraphs[0].appliedParagraphStyle; },
            function () { return item.paragraphs[0].appliedParagraphStyle; }
        ];
        for (var i = 0; i < tries.length; i++) {
            try {
                var st = tries[i]();
                if (st && st.isValid) return leafName(st);
            } catch (e) {}
        }
        return "";
    }

    function isTabFrame(item) {
        var leaf = frameParaLeaf(item);
        if (leaf) frameStylesSeen[leaf] = (frameStylesSeen[leaf] || 0) + 1;
        return leaf === TAB_LEAF;
    }

    // ---- 1. REBUILD: drop the overrides a previous run left ----------------
    var spreads = doc.spreads.everyItem().getElements();
    for (var s = 0; s < spreads.length; s++) {
        var items = spreads[s].pageItems.everyItem().getElements();
        for (var i = items.length - 1; i >= 0; i--) {
            try {
                if (items[i].overridden && isTabFrame(items[i])) {
                    items[i].removeOverride();
                    cleared++;
                }
            } catch (e) {}
        }
    }

    // ---- 2. every numbered heading, and the page it begins on --------------
    // Walked per story; each entry keeps the page's documentOffset so the list can
    // be ordered by position in the book rather than by the order stories happen
    // to be stored in.
    var heads = [];
    var stories = doc.stories.everyItem().getElements();
    for (var st = 0; st < stories.length; st++) {
        var paras;
        try { paras = stories[st].paragraphs.everyItem().getElements(); }
        catch (e) { continue; }
        for (var p = 0; p < paras.length; p++) {
            scanned++;
            var leaf = paraStyleLeaf(paras[p]);
            if (leaf) seenStyles[leaf] = (seenStyles[leaf] || 0) + 1;
            var lvl = headingLevel(leaf);
            if (lvl < MIN_LEVEL) continue;
            matchedHeads++;
            var pg = startPageOf(paras[p]);
            if (pg === null) continue;                  // overset or unplaced
            var num = numberOf(paras[p]);
            if (num === null) { noNumber++; continue; }
            heads.push({ offset: pg.documentOffset, order: p, level: lvl, number: num });
        }
    }
    heads.sort(function (a, b) {
        return (a.offset - b.offset) || (a.order - b.order);
    });

    if (heads.length === 0) {
        // Say WHICH half failed. "Found nothing" on its own sent the last run
        // hunting for a numbering problem when the real fault was style matching.
        var msg = "No tab numbers could be worked out.\n\n"
                + "paragraphs scanned: " + scanned + "\n"
                + "matching a heading style (lvl" + MIN_LEVEL + "+): " + matchedHeads + "\n"
                + "of those, number unreadable: " + noNumber + "\n\n";
        if (matchedHeads === 0) {
            msg += "No paragraph uses a style whose name ends in lvl2/lvl3/lvl4, so the\n"
                 + "style names are not what this script expects. Styles actually seen:\n\n";
            var names = [], k;
            for (k in seenStyles) if (seenStyles.hasOwnProperty(k)) names.push(k);
            names.sort();
            for (var q = 0; q < Math.min(names.length, 25); q++) {
                msg += "  " + names[q] + " x" + seenStyles[names[q]] + "\n";
            }
            if (names.length > 25) msg += "  ... and " + (names.length - 25) + " more\n";
        } else {
            msg += "The headings are there but their list numbers read as empty, so\n"
                 + "numbering is INACTIVE or already flattened to plain text.\n"
                 + "titles:lvl2/3/4 must be joined to manual_list as a NumberedList.\n";
            if (log.length) msg += "\n" + log[0];
        }
        alert(msg);
        return;
    }

    // ---- 3. fill each page's tab ------------------------------------------
    var pages = doc.pages.everyItem().getElements();
    var hi = 0, current = null;
    for (var pi = 0; pi < pages.length; pi++) {
        var page = pages[pi];
        // advance through every heading that begins on or before this page
        while (hi < heads.length && heads[hi].offset <= page.documentOffset) {
            current = heads[hi];
            hi++;
        }
        if (current === null) continue;                 // front matter, before ch.1

        // the tab frame comes from the page's applied master
        var master = null;
        try { master = page.appliedMaster; } catch (e) {}
        if (!master || !master.isValid) continue;

        var target = null;
        // allPageItems, not pageItems: the latter returns only top-level items and
        // this kit is known to nest frames inside groups. Costs nothing here.
        var mitems;
        try { mitems = master.allPageItems; }
        catch (e) { mitems = master.pageItems.everyItem().getElements(); }
        for (var m = 0; m < mitems.length; m++) {
            if (!isTabFrame(mitems[m])) continue;
            // a master spread has two pages; take the frame on this page's side
            try {
                if (mitems[m].parentPage && mitems[m].parentPage.side !== page.side) continue;
            } catch (e) {}
            target = mitems[m];
            break;
        }
        if (target === null) { noFrame++; continue; }

        try {
            var ov = target.override(page);
            ov.parentStory.contents = current.number;
            placed++;
        } catch (e) {
            log.push("page " + page.name + ": override/fill failed: " + e);
        }
    }

    // ---- 4. report ---------------------------------------------------------
    var msg = "Tab numbers placed: " + placed
            + "\nheadings found: " + heads.length
            + "\nnumber read via: " + (numberForm || "-")
            + "\nprevious overrides cleared: " + cleared;
    if (noFrame) {
        msg += "\npages with no tab frame on their master: " + noFrame;
        if (placed === 0) {
            // no frame recognised anywhere: show what the master frames DO look
            // like, so the next run is a diagnosis and not another guess
            msg += "\n\nparagraph styles found on master page items:\n";
            var fnames = [], fk;
            for (fk in frameStylesSeen) if (frameStylesSeen.hasOwnProperty(fk)) fnames.push(fk);
            fnames.sort();
            if (fnames.length === 0) {
                msg += "  (none readable — no page item exposed a paragraph style)\n";
            }
            for (var z = 0; z < Math.min(fnames.length, 20); z++) {
                msg += "  " + fnames[z] + " x" + frameStylesSeen[fnames[z]] + "\n";
            }
            msg += "\nexpected leaf name: " + TAB_LEAF + "\n";
        }
    }
    if (noNumber) msg += "\nheadings whose number could not be read: " + noNumber
                       + "  (numbering may be inactive or flattened)";
    if (log.length) {
        msg += "\n\nfirst problems:\n";
        for (var L = 0; L < Math.min(log.length, 6); L++) msg += "  " + log[L] + "\n";
    }
    alert(msg);
})();
