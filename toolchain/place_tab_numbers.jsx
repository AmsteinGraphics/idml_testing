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

    var TAB_PARA = "foot_and_tabs:tab_right";   // the tab-number frame's paragraph style
    var HEAD_PREFIX = "titles:lvl";             // numbered headings: lvl2, lvl3, lvl4
    var MIN_LEVEL = 2;                          // lvl1 is a Part label and never counts

    var log = [], placed = 0, cleared = 0, noNumber = 0, noFrame = 0;

    // ---- helpers -----------------------------------------------------------
    function paraStyleName(p) {
        try { return p.appliedParagraphStyle.name; } catch (e) { return ""; }
    }

    function headingLevel(name) {
        // "titles:lvl3" -> 3, anything else -> 0
        if (name.indexOf(HEAD_PREFIX) !== 0) return 0;
        var n = parseInt(name.substring(HEAD_PREFIX.length), 10);
        return isNaN(n) ? 0 : n;
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

    function numberOf(para) {
        // the composed list number, WITHOUT the heading text
        try {
            var n = para.numberingResultNumber;
            if (n !== undefined && n !== null && String(n) !== "") {
                return String(n).replace(/^\s+|[\s. ]+$/g, "");
            }
        } catch (e) { log.push("numberingResultNumber failed: " + e); }
        return null;
    }

    function isTabFrame(item) {
        try {
            if (!(item instanceof TextFrame)) return false;
            var ps = item.parentStory.paragraphs[0].appliedParagraphStyle.name;
            return ps === TAB_PARA;
        } catch (e) { return false; }
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
            var lvl = headingLevel(paraStyleName(paras[p]));
            if (lvl < MIN_LEVEL) continue;
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
        alert("No numbered headings with a resolvable list number were found.\n\n"
              + "Numbering must be ACTIVE (titles:lvl2/3/4 joined to manual_list).\n"
              + (log.length ? log[0] : ""));
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
        var mitems = master.pageItems.everyItem().getElements();
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
            + "\nprevious overrides cleared: " + cleared;
    if (noFrame)  msg += "\npages with no tab frame on their master: " + noFrame;
    if (noNumber) msg += "\nheadings whose number could not be read: " + noNumber
                       + "  (numbering may be inactive or flattened)";
    if (log.length) {
        msg += "\n\nfirst problems:\n";
        for (var L = 0; L < Math.min(log.length, 6); L++) msg += "  " + log[L] + "\n";
    }
    alert(msg);
})();
