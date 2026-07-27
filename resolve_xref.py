#!/usr/bin/env python3
"""Resolve and audit the DM32 manual's cross-reference ("oblique link") system.

The system has two coupled source objects that both point at one destination:
  * underlined word  -> <HyperlinkTextSource>   (character style `link`)
  * margin number    -> <CrossReferenceSource>  (format `dm32_cross_ref`)
Each is bound by a <Hyperlink Source=... DestinationUniqueKey=...> in
designmap.xml to a destination anchor (HyperlinkTextDestination /
HyperlinkPageDestination / ParagraphDestination) identified by DestinationUniqueKey.

Usage:
  python3 resolve_xref.py --report [--limit N] [--csv out.csv]
  python3 resolve_xref.py --from "underlined phrase" | --from u36068
  python3 resolve_xref.py --to   "target heading"    | --to 132
  python3 resolve_xref.py --audit
Options:
  --dir DIR   extracted IDML folder (default: extracted)
"""
import argparse, csv, os, re, sys, xml.etree.ElementTree as ET
from collections import defaultdict


def local(tag):
    return tag.rsplit('}', 1)[-1]


def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


# ---- source / destination classification -------------------------------------
WORD = 'word'      # underlined HyperlinkTextSource
XREF = 'xref'      # margin-number CrossReferenceSource
LINK_STYLES = {'CharacterStyle/link', 'CharacterStyle/link_slant'}


class Index:
    def __init__(self, root):
        self.root = root
        self.sources = {}                      # self_id -> source dict
        self.dests = {}                         # unique_key(str) -> dest dict
        self.hyperlinks = []                    # list of hyperlink dicts
        self.formats = {}                       # format self_id -> name
        self.story_pages = defaultdict(set)     # story_id -> {page names}
        self._build()

    # -- designmap: hyperlinks, page/paragraph destinations, xref formats ------
    def _parse_designmap(self):
        path = os.path.join(self.root, 'designmap.xml')
        for _, el in ET.iterparse(path, events=('end',)):
            t = local(el.tag)
            if t == 'Hyperlink':
                self.hyperlinks.append({
                    'self': el.get('Self'), 'name': el.get('Name'),
                    'source': el.get('Source'),
                    'dest_key': el.get('DestinationUniqueKey'),
                    'hidden': el.get('Hidden') == 'true',
                })
            elif t in ('HyperlinkPageDestination', 'ParagraphDestination'):
                k = el.get('DestinationUniqueKey')
                if k:
                    self.dests.setdefault(k, {
                        'key': k, 'type': t, 'self': el.get('Self'),
                        'name': el.get('Name'), 'story': None,
                        'page': el.get('DestinationPage'), 'text': None})
            elif t == 'CrossReferenceFormat':
                self.formats[el.get('Self')] = el.get('Name')

    # -- spreads: best-effort story -> page-name(s) (spread level) -------------
    def _parse_spreads(self):
        for sub in ('Spreads', 'MasterSpreads'):
            d = os.path.join(self.root, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith('.xml'):
                    continue
                pages, frames = [], []
                for _, el in ET.iterparse(os.path.join(d, fn), events=('end',)):
                    t = local(el.tag)
                    if t == 'Page':
                        pages.append(el.get('Name'))
                    elif t in ('TextFrame', 'Rectangle', 'Polygon', 'Oval'):
                        ps = el.get('ParentStory')
                        if ps:
                            frames.append(ps)
                for ps in frames:
                    self.story_pages[ps].update(p for p in pages if p)

    # -- stories: sources + text destinations, with paragraph context ---------
    def _parse_story(self, path):
        story_id = None
        para_stack = []          # stack of paragraph records (tables nest)
        char_stack = []          # applied character style
        src_stack = []           # open source dicts (capture their Content)
        results_src, results_dst = [], []
        for ev, el in ET.iterparse(path, events=('start', 'end')):
            t = local(el.tag)
            if ev == 'start':
                if t == 'Story' and story_id is None:
                    story_id = el.get('Self')
                elif t == 'ParagraphStyleRange':
                    para_stack.append({'style': el.get('AppliedParagraphStyle'),
                                       'text': [], 'srcs': [], 'dsts': []})
                elif t == 'CharacterStyleRange':
                    char_stack.append(el.get('AppliedCharacterStyle'))
                elif t in ('HyperlinkTextSource', 'CrossReferenceSource'):
                    kind = XREF if t == 'CrossReferenceSource' else WORD
                    s = {'self': el.get('Self'), 'name': el.get('Name'),
                         'kind': kind, 'elem': t, 'story': story_id,
                         'char_style': char_stack[-1] if char_stack else None,
                         'format': el.get('AppliedFormat'),
                         'para_style': para_stack[-1]['style'] if para_stack else None,
                         'content': []}
                    src_stack.append(s)
                    if para_stack:
                        para_stack[-1]['srcs'].append(s)
                elif t in ('HyperlinkTextDestination', 'ParagraphDestination'):
                    d = {'key': el.get('DestinationUniqueKey'), 'type': t,
                         'self': el.get('Self'), 'name': el.get('Name'),
                         'story': story_id}
                    if para_stack:
                        para_stack[-1]['dsts'].append(d)
                    else:
                        results_dst.append((d, None))
            else:  # end
                if t == 'Content':
                    txt = el.text or ''
                    if para_stack:
                        para_stack[-1]['text'].append(txt)
                    if src_stack:
                        src_stack[-1]['content'].append(txt)
                elif t in ('HyperlinkTextSource', 'CrossReferenceSource'):
                    if src_stack:
                        s = src_stack.pop()
                        s['content'] = clean(''.join(s['content']))
                        results_src.append(s)
                elif t == 'CharacterStyleRange':
                    if char_stack:
                        char_stack.pop()
                elif t == 'ParagraphStyleRange':
                    if para_stack:
                        p = para_stack.pop()
                        ptext = clean(''.join(p['text']))
                        for d in p['dsts']:
                            results_dst.append((d, ptext))
                        for s in p['srcs']:
                            s['para_text'] = ptext
                    el.clear()
        for s in results_src:
            s.setdefault('para_text', '')
            self.sources[s['self']] = s
        for d, ptext in results_dst:
            if d['key']:
                self.dests[d['key']] = {'key': d['key'], 'type': d['type'],
                                        'self': d['self'], 'name': d['name'],
                                        'story': d['story'], 'page': None,
                                        'text': ptext}

    def _build(self):
        self._parse_designmap()
        self._parse_spreads()
        sd = os.path.join(self.root, 'Stories')
        for fn in os.listdir(sd):
            if fn.endswith('.xml'):
                self._parse_story(os.path.join(sd, fn))
        # link hyperlinks to their source objects; index by source
        self.hl_by_source = {h['source']: h for h in self.hyperlinks}

    # ---- query helpers -------------------------------------------------------
    def pages_for(self, story_id):
        pg = sorted(self.story_pages.get(story_id, []), key=lambda x: (len(x), x))
        # A story threaded across many frames/spreads (e.g. the body text) can't
        # be pinned to one page without geometry — suppress rather than flood.
        return pg if len(pg) <= 2 else []

    def dest_label(self, key):
        d = self.dests.get(key)
        if not d:
            return f'<missing dest key {key}>'
        loc = ''
        if d.get('story'):
            pg = self.pages_for(d['story'])
            if pg:
                loc = f'  [p.{"/".join(pg)}]'
        head = d.get('text') or d.get('name') or ''
        return f'"{clean(head)[:70]}"{loc}'

    def resolve_source(self, s):
        h = self.hl_by_source.get(s['self'])
        if not h:
            return None, None
        return h, self.dests.get(h['dest_key'])


def load(root):
    if not os.path.isdir(os.path.join(root, 'Stories')):
        sys.exit(f'error: {root!r} has no Stories/ — is it an extracted IDML?')
    return Index(root)


# ---- commands ----------------------------------------------------------------
def cmd_report(ix, limit, csv_path):
    rows = []
    for s in ix.sources.values():
        h, d = ix.resolve_source(s)
        rows.append({
            'kind': s['kind'], 'source_id': s['self'],
            'content': s['content'] or clean(s.get('para_text', ''))[:60],
            'dest_key': h['dest_key'] if h else '',
            'dest': ix.dest_label(h['dest_key']) if h else '<no hyperlink>',
            'story': s['story'],
        })
    rows.sort(key=lambda r: (r['kind'], r['content'].lower()))
    if csv_path:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f'wrote {len(rows)} rows -> {csv_path}')
        return
    shown = rows[:limit] if limit else rows
    for r in shown:
        tag = 'WORD' if r['kind'] == WORD else 'NUM '
        print(f'[{tag}] {r["content"][:48]:48}  ->  {r["dest"]}')
    print(f'\n{len(shown)} of {len(rows)} cross-reference sources shown.')


def cmd_from(ix, query):
    q = query.lower()
    hits = [s for s in ix.sources.values()
            if s['self'] == query or q in (s['content'] or '').lower()
            or q in (s.get('para_text') or '').lower()]
    if not hits:
        print(f'no source matches {query!r}'); return
    for s in hits[:25]:
        kind = 'underlined word' if s['kind'] == WORD else 'margin number'
        h, d = ix.resolve_source(s)
        print(f'\n● {kind}: "{s["content"] or clean(s["para_text"])[:60]}"')
        print(f'   source {s["self"]}  ({s["elem"]}, style {s["char_style"]})  in {s["story"]}')
        if not h:
            print('   ⚠ no <Hyperlink> references this source'); continue
        print(f'   hyperlink {h["self"]}  ->  dest key {h["dest_key"]}')
        if d:
            print(f'   TARGET: {ix.dest_label(h["dest_key"])}  ({d["type"]})')
        else:
            print(f'   ⚠ BROKEN: no destination with key {h["dest_key"]}')
    if len(hits) > 25:
        print(f'\n… {len(hits) - 25} more matches.')


def cmd_to(ix, query):
    q = query.lower()
    keys = [k for k, d in ix.dests.items()
            if k == query or q in (d.get('name') or '').lower()
            or q in (d.get('text') or '').lower()]
    if not keys:
        print(f'no destination matches {query!r}'); return
    for k in keys[:15]:
        print(f'\n◎ destination key {k}: {ix.dest_label(k)}')
        refs = [s for s in ix.sources.values()
                if (h := ix.hl_by_source.get(s['self'])) and h['dest_key'] == k]
        if not refs:
            print('   (nothing points here)')
        for s in refs:
            tag = 'word' if s['kind'] == WORD else 'num '
            print(f'   ← [{tag}] "{s["content"] or clean(s["para_text"])[:50]}"  ({s["story"]})')


def cmd_audit(ix):
    src_ids = set(ix.sources)
    print('=== Cross-reference audit ===\n')

    broken = [h for h in ix.hyperlinks if h['dest_key'] not in ix.dests]
    print(f'Broken links (hyperlink -> missing destination): {len(broken)}')
    for h in broken[:10]:
        s = ix.sources.get(h['source'])
        what = f'"{s["content"]}"' if s else h['source']
        print(f'   {h["self"]}  {what}  -> dead key {h["dest_key"]}')
    if len(broken) > 10:
        print(f'   … +{len(broken) - 10} more')

    dangling = [h for h in ix.hyperlinks if h['source'] and h['source'] not in src_ids]
    print(f'\nHyperlinks whose Source object is missing: {len(dangling)}')
    for h in dangling[:10]:
        print(f'   {h["self"]}  source {h["source"]} not found')

    linked = {h['source'] for h in ix.hyperlinks}
    unlinked = [s for sid, s in ix.sources.items() if sid not in linked]
    print(f'\nSources with no <Hyperlink> (unlinked): {len(unlinked)}')
    for s in unlinked[:10]:
        print(f'   {s["self"]}  [{s["kind"]}] "{s["content"]}"')

    used = {h['dest_key'] for h in ix.hyperlinks}
    orphan = [d for k, d in ix.dests.items() if k not in used]
    print(f'\nDestinations nothing points to (orphans): {len(orphan)}')
    for d in orphan[:10]:
        print(f'   key {d["key"]}  {d["type"]}  "{clean(d.get("text") or d.get("name") or "")[:50]}"')

    # Pairing — only meaningful for NAMED anchors (HyperlinkTextDestination /
    # ParagraphDestination). Links to page anchors are TOC/navigation, not
    # oblique links, so they're counted separately, not flagged.
    named = {'HyperlinkTextDestination', 'ParagraphDestination'}
    by_dest = defaultdict(lambda: {'word': 0, 'xref': 0})
    nav_links = 0
    for s in ix.sources.values():
        h = ix.hl_by_source.get(s['self'])
        if not h:
            continue
        d = ix.dests.get(h['dest_key'])
        if d and d['type'] in named:
            by_dest[h['dest_key']][s['kind']] += 1
        else:
            nav_links += 1
    word_no_num = [k for k, c in by_dest.items() if c['word'] and not c['xref']]
    num_no_word = [k for k, c in by_dest.items() if c['xref'] and not c['word']]
    both = [k for k, c in by_dest.items() if c['word'] and c['xref']]
    print('\n--- Oblique-link pairing (underlined word ⇄ margin number) ---')
    print('    (named-anchor targets only; page-anchor/TOC links excluded)')
    print(f'Complete oblique links (both word AND margin number): {len(both)}')
    print(f'Named-anchor target with word but NO margin number:  {len(word_no_num)}')
    for k in word_no_num[:10]:
        print(f'   key {k}: {ix.dest_label(k)}')
    print(f'Named-anchor target with margin number but NO word:  {len(num_no_word)}')
    for k in num_no_word[:10]:
        print(f'   key {k}: {ix.dest_label(k)}')
    print(f'\nPage-anchor / TOC-style links (not oblique, excluded above): {nav_links}')

    print('\n--- Totals ---')
    kinds = defaultdict(int)
    for s in ix.sources.values():
        kinds[s['kind']] += 1
    print(f'   underlined-word sources : {kinds[WORD]}')
    print(f'   margin-number sources   : {kinds[XREF]}')
    print(f'   hyperlinks              : {len(ix.hyperlinks)}')
    print(f'   destinations            : {len(ix.dests)}')


def cmd_pairing_csv(ix, path):
    """Flat CSV of oblique-link pairing anomalies for editorial review.

    One row per (anomalous named-anchor target, source that DOES point at it),
    so each row shows what exists and what's missing.
    """
    named = {'HyperlinkTextDestination', 'ParagraphDestination'}
    by_dest = defaultdict(lambda: {WORD: [], XREF: []})
    for s in ix.sources.values():
        h = ix.hl_by_source.get(s['self'])
        if not h:
            continue
        d = ix.dests.get(h['dest_key'])
        if d and d['type'] in named:
            by_dest[h['dest_key']][s['kind']].append(s)

    rows = []
    for key, groups in by_dest.items():
        words, nums = groups[WORD], groups[XREF]
        if words and nums:
            continue  # complete oblique link — not an anomaly
        issue = 'missing_margin_number' if words else 'missing_underlined_word'
        present = words or nums
        d = ix.dests.get(key, {})
        for s in present:
            rows.append({
                'issue': issue,
                'dest_key': key,
                'dest_heading': clean(d.get('text') or d.get('name') or ''),
                'dest_story': d.get('story') or '',
                'present_kind': 'underlined_word' if s['kind'] == WORD else 'margin_number',
                'present_source_id': s['self'],
                'present_source_content': s['content'] or clean(s.get('para_text', ''))[:80],
                'present_source_story': s['story'],
                'present_source_style': s['char_style'] or '',
            })
    rows.sort(key=lambda r: (r['issue'], r['dest_heading'].lower()))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    n_num = len({r['dest_key'] for r in rows if r['issue'] == 'missing_margin_number'})
    n_word = len({r['dest_key'] for r in rows if r['issue'] == 'missing_underlined_word'})
    print(f'wrote {len(rows)} rows -> {path}')
    print(f'  {n_num} targets missing a margin number, {n_word} missing an underlined word')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='extracted')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--report', action='store_true')
    g.add_argument('--from', dest='frm', metavar='QUERY')
    g.add_argument('--to', metavar='QUERY')
    g.add_argument('--audit', action='store_true')
    g.add_argument('--pairing-csv', dest='pairing_csv', metavar='PATH')
    ap.add_argument('--limit', type=int, default=40)
    ap.add_argument('--csv')
    a = ap.parse_args()
    ix = load(a.dir)
    if a.report:
        cmd_report(ix, a.limit, a.csv)
    elif a.frm:
        cmd_from(ix, a.frm)
    elif a.to:
        cmd_to(ix, a.to)
    elif a.audit:
        cmd_audit(ix)
    elif a.pairing_csv:
        cmd_pairing_csv(ix, a.pairing_csv)


if __name__ == '__main__':
    main()
