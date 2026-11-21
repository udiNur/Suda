#!/usr/bin/env python3
"""End to end: symmetry and alignment, measured (the owner, suda-fixes m85: "note the symmetry: where the V sits
and where e.g. Escape sits ... I would like fixes like this and checks like these too"; suda-fixes task 26).

Layout is read with getBoundingClientRect, never with pixel snapshots (those break on fonts):
- what sits on one line in a row, a chip, a button or a header shares one vertical centre, within 1 px;
- a key cap written beside words (Esc on "נקה בחירה", the key of a notice's action, End on the pill) sits inside
  its control as the words do on the other side: the same distance from the edge, its own gap between them, centred;
- the check mark of a chosen row is a drawn mark centred in its box (it was a font glyph that sat low and to the side);
- right to left: what leads a row is on the right (the place number, the words before their key cap, the message before
  its action), and what ends it on the left.
An icon is measured by its drawing (the shapes inside the svg), so an icon centred in its button means its ink is.
At the cover (360), a 390 phone, the foldable inner screen (750) and the desktop (1280), dark and light.
The same harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

COVER, INNER, DESK = SIZES
PHONE = ('phone', 390, 844)
ALL = (COVER, PHONE, INNER, DESK)
TOL = 1.0


def mirrored(x):
    """A left to right page read as its mirror: every rectangle ({l, r, cx, ...}) flipped across x=0, so a check
    written for right to left measures it the same way (widths, gaps and centres keep their sizes)."""
    if isinstance(x, list):
        return [mirrored(v) for v in x]
    if not isinstance(x, dict):
        return x
    out = {k: mirrored(v) for k, v in x.items()}
    if {'l', 'r', 'cx'} <= out.keys():
        out.update(l=-x['r'], r=-x['l'], cx=-x['cx'])
    return out

# Rectangles of what the eye sees: the box of an element, the line of a text node, the drawing inside an svg.
PROBE = r"""window.__sym=window.__sym||(()=>{
const R=r=>r&&({l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.right-r.left,h:r.bottom-r.top,cx:(r.left+r.right)/2,cy:(r.top+r.bottom)/2});
const shown=e=>{if(!e||!e.getClientRects().length)return false;const s=getComputedStyle(e);return s.visibility!=='hidden'&&s.display!=='none';};
const SHAPES='use,path,circle,rect,line,polyline,polygon,ellipse';
function ink(n){
  if(!n)return null;
  if(n.nodeType===3){const g=document.createRange();g.selectNodeContents(n);const r=g.getBoundingClientRect();return r.width?R(r):null;}
  if(n instanceof SVGSVGElement){let u=null;for(const s of n.querySelectorAll(SHAPES)){const r=s.getBoundingClientRect();if(!r.width&&!r.height)continue;
    u=u?{left:Math.min(u.left,r.left),top:Math.min(u.top,r.top),right:Math.max(u.right,r.right),bottom:Math.max(u.bottom,r.bottom)}:{left:r.left,top:r.top,right:r.right,bottom:r.bottom};}return R(u);}
  return shown(n)?R(n.getBoundingClientRect()):null;
}
// inside the border: where padding and content are
function inner(e){const r=e.getBoundingClientRect(),s=getComputedStyle(e);return R({left:r.left+parseFloat(s.borderLeftWidth),right:r.right-parseFloat(s.borderRightWidth),top:r.top+parseFloat(s.borderTopWidth),bottom:r.bottom-parseFloat(s.borderBottomWidth)});}
// the words of an element: its text and what holds text, without its key cap or its icon
function words(e){let u=null;for(const n of e.childNodes){if(n.nodeType===3?!n.textContent.trim():(n.nodeType!==1||n.matches('kbd,svg')))continue;const r=ink(n);if(!r)continue;
  u=u?{left:Math.min(u.left,r.l),top:Math.min(u.top,r.t),right:Math.max(u.right,r.r),bottom:Math.max(u.bottom,r.b)}:{left:r.l,top:r.t,right:r.r,bottom:r.b};}
  return R(u);}
function get(sel,root){const all=[...(root||document).querySelectorAll(sel)].filter(shown);return all;}
return {R,ink,inner,words,get,shown};
})();'ok'"""


class Symmetry(test_e2e.Suda):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for tid, title, state in (('sy-a', 'Weekly report', 'on-owner'), ('sy-b', 'משימות', 'on-owner'),
                                  ('sy-c', 'מכונת build חזקה ומוצפנת עבורנו', 'on-owner'),
                                  ('sy-d', 'Sync: מכשירים לא מופיעים + מדריך setup', 'on-owner'), ('sy-e', 'Billing', 'working')):
            cls.ok('new', tid, title, '--state', state, '--note', 'בונה משהו ארוך מספיק כדי להיחתך בשורה', '--by', 'e2e')
            cls.ok('say', tid, '--from', 'fork', 'דוח: ' + tid)
        cls.ok('urgent', 'sy-a')
        for i in range(30):
            cls.ok('say', 'sy-a', '--from', 'fork', 'שורה %d\n\nעוד טקסט כדי שתהיה גלילה' % i)

    # ── the page and the measures ────────────────────────────────────────────

    def show(self, size, theme='dark', hash=''):
        self.open(size, hash)
        self.browser.wait('JSON.stringify(synced)', what='the page in sync')
        self.browser.eval('(()=>{document.documentElement.dataset.theme=%s;return "ok"})()' % json.dumps(theme))
        self.browser.eval(PROBE)

    def js(self, body):
        """`body` is the inside of a function with __sym's helpers in scope; it returns a value made JSON here. On a
        left to right page (an English installation) every rectangle comes back mirrored, so each check, written in
        reading order for right to left, measures the page in its own direction."""
        self.browser.eval(PROBE)
        got = self.browser.eval('JSON.stringify((()=>{const {R,ink,inner,words,get,shown}=__sym;%s})())' % body)
        ltr = self.browser.eval('JSON.stringify(getComputedStyle(document.body).direction)') == 'ltr'
        return mirrored(got) if ltr else got

    def choose(self, *ids):
        self.browser.eval('(()=>{bulkSet(%s);return "ok"})()' % json.dumps(list(ids)))
        self.browser.wait('JSON.stringify(document.querySelectorAll("#channels .ch.picked").length===%d)' % len(ids), what='the rows chosen')

    def same_middle(self, a, b, what):
        self.assertLessEqual(abs(a['cy'] - b['cy']), TOL, '%s: vertical centres %.1f and %.1f' % (what, a['cy'], b['cy']))

    def centred_in(self, part, box, what, axis='both'):
        if axis in ('both', 'x'):
            self.assertLessEqual(abs(part['cx'] - box['cx']), TOL, '%s: %.1f from the middle across' % (what, part['cx'] - box['cx']))
        if axis in ('both', 'y'):
            self.assertLessEqual(abs(part['cy'] - box['cy']), TOL, '%s: %.1f from the middle down' % (what, part['cy'] - box['cy']))

    def even_gaps(self, rects, what):
        """Side by side on one line: the same gap between each two, within 1 px."""
        lines = []
        for r in sorted(rects, key=lambda r: r['cy']):           # one line: boxes that overlap down the page
            if lines and r['t'] < lines[-1][-1]['b'] - 1:
                lines[-1].append(r)
            else:
                lines.append([r])
        for line in lines:
            line.sort(key=lambda r: r['l'])
            gaps = [b['l'] - a['r'] for a, b in zip(line, line[1:])]
            if len(gaps) > 1:
                self.assertLessEqual(max(gaps) - min(gaps), TOL, what + ': gaps %s' % [round(g, 1) for g in gaps])

    def scrolled_up(self):
        """Far from the end of the thread, where the pill shows. The thread first settles (whole, not a summary, and
        drawn): a page still opening it brings the view back to the end. Asked again on every poll until it holds."""
        self.browser.wait('JSON.stringify(synced&&!!thread("sy-a")&&!thread("sy-a").partial&&document.querySelectorAll("#log .msg").length>20)',
                          what='the whole thread drawn')
        self.browser.wait('(()=>{scroller.scrollTop=0;scroller.dispatchEvent(new Event("scroll"));return JSON.stringify(!document.querySelector("#jump").hidden)})()',
                          what='the pill')

    def notice(self):
        """A notice of this test with an action and its key, alone on the screen (the page's own notices go first)."""
        self.browser.eval('(()=>{for(const t of document.querySelectorAll(".toast"))t.remove();toast("נסגר","בטל",()=>{},60000,"U");'
                          '[...document.querySelectorAll(".toast")].at(-1).id="sym-toast";return "ok"})()')

    def key_cap(self, sel, what):
        """Words and a key cap in one control: the words lead and the cap ends (right to left: the cap on the left;
        left to right, as on the English page, js() mirrors the page: on the right); each stands as far from its edge
        as the other, with a gap of their own, all on one centre line."""
        got = self.js('const b=get(%s)[0];if(!b)return null;const k=b.querySelector("kbd");'
                      'return {box:inner(b),words:words(b),kbd:k&&shown(k)?ink(k):null,dir:getComputedStyle(b).direction}' % json.dumps(sel))
        self.assertTrue(got, what + ': not on the screen (%s)' % sel)
        box, w, k = got['box'], got['words'], got['kbd']
        self.assertTrue(w and k, what + ': words and a key cap')
        self.assertLess(k['r'], w['l'], what + ': the key cap comes after the words')
        gap = w['l'] - k['r']
        self.assertGreaterEqual(gap, 4, what + ': a gap between the words and the cap (%.1f)' % gap)
        self.assertLessEqual(gap, 10, what + ': the cap stays with its words (%.1f)' % gap)
        outer_words, outer_cap = box['r'] - w['r'], k['l'] - box['l']
        self.assertLessEqual(abs(outer_words - outer_cap), TOL,
                             what + ': the cap is %.1f from its edge, the words %.1f from theirs' % (outer_cap, outer_words))
        self.centred_in(k, box, what + ': the key cap', 'y')
        line = self.js('const s=getComputedStyle(get(%s)[0]);return {btn:s.textDecorationLine,flex:s.display}' % json.dumps(sel))
        self.assertFalse('underline' in line['btn'] and 'flex' in line['flex'], what + ': an underline of a flex control would run under the key cap too')
        self.centred_in(w, box, what + ': the words', 'y')

    # ── what the owner pointed at (m85) ──────────────────────────────────────

    def test_the_check_of_a_chosen_row_is_drawn_in_the_middle_of_its_box(self):
        for size in ALL:
            for theme in ('dark', 'light'):
                with self.subTest(size=size[0], theme=theme):
                    self.show(size, theme)
                    self.choose('sy-c', 'sy-d')
                    got = self.js('return get("#channels .ch.picked").map(b=>{const s=b.querySelector(".slot"),t=s.querySelector("svg.tick");'
                                  'return {id:b.dataset.id,slot:inner(s),tick:t?ink(t):null,glyph:getComputedStyle(s,"::after").content}})')
                    self.assertEqual(sorted(g['id'] for g in got), ['sy-c', 'sy-d'])
                    for g in got:
                        self.assertTrue(g['tick'], '%s: the check is a drawn mark, not a letter of a font (%s)' % (g['id'], g['glyph']))
                        self.assertIn(g['glyph'], ('none', 'normal'), 'no second check written over it')
                        self.centred_in(g['tick'], g['slot'], g['id'] + ': the check in its box')
                        share = g['tick']['w'] / g['slot']['w']
                        self.assertTrue(0.3 <= share <= 0.7, '%s: the drawing of the check (without its stroke) spans %.0f%% of its box' % (g['id'], share * 100))

    def test_esc_sits_in_its_button_as_the_words_do_on_the_other_side(self):
        for size in (INNER, DESK):
            with self.subTest(size=size[0]):
                self.show(size)
                self.choose('sy-c', 'sy-d')
                self.key_cap('#bulk [data-bulk=clear]', 'נקה בחירה + Esc')

    def test_the_key_of_a_notice_and_of_the_pill_sit_like_esc(self):
        for size in (INNER, DESK):
            with self.subTest(size=size[0]):
                self.show(size, hash='sy-a')
                self.browser.wait('JSON.stringify(view.ch==="sy-a"&&!!document.querySelector("#input").offsetParent)', what='the thread')
                self.notice()
                self.key_cap('#sym-toast .text-btn', 'the action of a notice + its key')
                toast = self.js('const t=get("#sym-toast")[0];return {box:inner(t),msg:ink(t.querySelector("span")),act:ink(t.querySelector(".text-btn"))}')
                self.same_middle(toast['msg'], toast['act'], 'a notice: its words and its action')
                self.assertLess(toast['act']['r'], toast['msg']['l'], 'right to left the action ends the notice, on the left')
                self.scrolled_up()
                self.key_cap('#jump', 'the pill + End')
        for size in (COVER, PHONE):         # a touch screen hides the key caps: the words alone are centred
            with self.subTest(size=size[0]):
                self.show(size, hash='sy-a')
                self.browser.wait('JSON.stringify(view.ch==="sy-a"&&!!document.querySelector("#input").offsetParent)', what='the thread')
                self.scrolled_up()
                self.notice()
                for sel in ('#jump', '#sym-toast .text-btn'):
                    got = self.js('const b=get(%s)[0];return {box:inner(b),words:words(b),cap:get("kbd",b).length}' % json.dumps(sel))
                    self.assertEqual(got['cap'], 0, sel + ': no key cap on a touch screen')
                    self.centred_in(got['words'], got['box'], sel + ': its words alone')

    # ── the rest of the page: guards, so it stays aligned ────────────────────

    def test_list_rows_and_the_top_of_the_list_share_a_centre_line(self):
        for size in ALL:
            with self.subTest(size=size[0]):
                self.show(size)
                got = self.js('return {rows:get("#channels .ch").slice(0,6).map(b=>({id:b.dataset.id,box:inner(b),slot:ink(b.querySelector(".slot")),'
                              'text:ink(b.querySelector(".ch-text")),side:ink(b.querySelector(".ch-side"))})),'
                              'head:["h1","#you-count","#live"].map(s=>ink(get(".side-head "+s)[0])).filter(Boolean),'
                              'tools:get(".side-tools > *").map(x=>({box:inner(x),svg:ink(x.querySelector("svg"))}))}')
                self.assertTrue(got['rows'])
                for r in got['rows']:
                    self.same_middle(r['slot'], r['text'], r['id'] + ': the place and the words')
                    self.same_middle(r['side'], r['text'], r['id'] + ': the time and the words')
                    self.assertGreater(r['slot']['l'], r['text']['r'], r['id'] + ': right to left the place number leads the row')
                    self.assertLess(r['side']['r'], r['text']['l'], r['id'] + ': and the time ends it, on the left')
                for x in got['head'][1:]:
                    self.same_middle(x, got['head'][0], 'the top of the list')
                for x in got['tools'][1:]:
                    self.same_middle(x['box'], got['tools'][0]['box'], 'the row of tools over the list')
                self.even_gaps([x['box'] for x in got['tools']], 'the row of tools over the list')
                for x in got['tools']:
                    if x['svg'] and x['box']['w'] < 60:
                        self.centred_in(x['svg'], x['box'], 'an icon button over the list')
                # a row is padded alike on both sides
                for r in got['rows']:
                    self.assertLessEqual(abs((r['box']['r'] - r['slot']['r']) - (r['side']['l'] - r['box']['l'])), TOL,
                                         r['id'] + ': the row is padded alike on its two sides')

    def test_the_head_of_a_thread_and_the_reply_tools_are_centred(self):
        for size in ALL:
            with self.subTest(size=size[0]):
                self.show(size, hash='sy-a')
                self.browser.wait('JSON.stringify(view.ch==="sy-a"&&!!document.querySelector("#input").offsetParent)', what='the thread')
                got = self.js('const icons=s=>get(s).map(b=>({id:b.id,box:inner(b),svg:ink(b.querySelector("svg"))}));'
                              'return {head:icons(".head > button.icon"),tools:icons(".box-btns > button"),'
                              'title:ink(get("#h-title")[0]),back:get("#back").length?ink(get("#back svg")[0]):null,'
                              'badge:get("#back-badge").length?ink(get("#back-badge")[0]):null}')
                self.assertTrue(got['head'] and got['tools'])
                for b in got['head'] + got['tools']:
                    if b['id'] == 'back' and got['badge']:
                        self.same_middle(got['badge'], b['svg'], 'Back: its arrow and the count of the others')
                        self.assertLess(got['badge']['r'], b['svg']['l'] + TOL, 'right to left the arrow leads Back, the count follows on its left')
                        continue
                    self.centred_in(b['svg'], b['box'], '#%s: its icon in its button' % b['id'])
                heads = [b for b in got['head'] if b['id'] != 'back']
                for b in heads[1:]:
                    self.same_middle(b['box'], heads[0]['box'], '#%s and #%s' % (b['id'], heads[0]['id']))
                for b in got['tools'][1:]:
                    self.same_middle(b['box'], got['tools'][0]['box'], 'the buttons of the reply box')
                if got['back']:
                    self.assertGreater(got['back']['l'], got['title']['r'], 'right to left Back is on the right of the title')

    def test_the_chips_of_the_chosen_and_the_sheet_on_the_phone_line_up(self):
        for size in (INNER, DESK):
            with self.subTest(size=size[0]):
                self.show(size)
                self.choose('sy-b', 'sy-c', 'sy-d')
                chips = self.js('return get("#bulk .bulk-picked .pk").map(c=>({box:inner(c),slot:ink(c.querySelector(".slot")),'
                                'words:ink(c.querySelector("bdi")),x:ink(c.querySelector(".pk-x svg"))}))')
                self.assertEqual(len(chips), 3)
                for c in chips:
                    for part in ('slot', 'words', 'x'):
                        self.centred_in(c[part], c['box'], 'a chosen chip: its ' + part, 'y')
                    self.assertGreater(c['slot']['l'], c['words']['r'], 'right to left the number leads the chip')
                    self.assertLess(c['x']['r'], c['words']['l'], 'and the x ends it')
                    self.assertLessEqual(abs((c['box']['r'] - c['slot']['r']) - (c['x']['l'] - c['box']['l'])), TOL,
                                         'a chosen chip: as much room right of the number as left of the x')
                self.even_gaps([c['box'] for c in chips], 'the chosen chips')
                for row in self.js('return get("#bulk .bact .row").map(r=>get(".btn",r).map(b=>inner(b)))'):
                    self.even_gaps(row, 'the buttons of an action')
                top = self.js('const t=get("#bulk .bulk-top")[0];return [ink(t.querySelector("h2")),inner(t.querySelector("[data-bulk=clear]"))]')
                self.same_middle(top[0], top[1], 'the count and its button')
        for size in (COVER, PHONE):
            with self.subTest(size=size[0]):
                self.show(size)
                self.choose('sy-c', 'sy-d')
                got = self.js('const s=get("#bulk-sheet")[0];return {top:[...s.querySelector(".bs-top").children].map(ink),'
                              'chips:get("#bulk-sheet .bulk-chip").map(c=>({box:inner(c),words:words(c)}))}')
                for x in got['top'][1:]:
                    self.same_middle(x, got['top'][0], 'the top of the sheet')
                for c in got['chips']:
                    self.centred_in(c['words'], c['box'], 'a chip of the sheet', 'y')
                self.even_gaps([c['box'] for c in got['chips']], 'the chips of the sheet')

    def test_the_slash_list_dialogs_and_notices_line_up(self):
        for size in (COVER, INNER, DESK):
            with self.subTest(size=size[0]):
                self.show(size, hash='sy-a')
                self.browser.wait('JSON.stringify(view.ch==="sy-a"&&!!document.querySelector("#input").offsetParent)', what='the thread')
                self.browser.fill('#input', '/')
                self.browser.wait('JSON.stringify(!document.querySelector("#slash").hidden)', what='the slash list')
                got = self.js('return get("#slash .sl-row, #slash .sl-head, #slash .sl-chip").slice(0,8).map(r=>({box:inner(r),parts:[...r.children].map(ink).filter(Boolean)}))')
                self.assertTrue(got)
                for r in got:
                    for p in r['parts']:
                        if p['h'] < r['box']['h']:
                            self.centred_in(p, r['box'], 'a row of the slash list', 'y')
                self.browser.fill('#input', '')
                for name, opener in (('switcher', 'openSwitcher()'), ('help', 'showHelp()'), ('topic', 'showTopic()'), ('notify', 'openNotify()')):
                    self.browser.eval('(()=>{%s;return "ok"})()' % opener)
                    self.browser.wait('JSON.stringify(!document.querySelector("#%s").hidden)' % name, what=name)
                    top = self.js('const t=get("#%s .dialog-top")[0];return {parts:[...t.children].map(ink).filter(Boolean),'
                                  'close:(b=>b&&{box:inner(b),svg:ink(b.querySelector("svg"))})(t.querySelector("button.icon"))}' % name)
                    for p in top['parts'][1:]:
                        self.same_middle(p, top['parts'][0], name + ': the top of the dialog')
                    self.centred_in(top['close']['svg'], top['close']['box'], name + ': the x in its button')
                    self.browser.eval('(()=>{for(const o of document.querySelectorAll(".overlay"))o.hidden=true;return "ok"})()')
                self.browser.eval('(()=>{toast("הודעה לבדיקה","בטל",()=>{},60000,"U");return "ok"})()')
                toast = self.js('const t=get(".toast")[0];const a=t.querySelector(".text-btn");return {box:inner(t),msg:ink(t.querySelector("span")),act:inner(a),words:words(a)}')
                self.same_middle(toast['msg'], toast['act'], 'a notice: its words and its action')
                self.centred_in(toast['words'], toast['act'], 'the word of the action in its button', 'y')


def load_tests(loader, tests, pattern):
    """Only the measures of this file: the scenarios of test_e2e.Suda run in their own file."""
    return unittest.TestSuite(Symmetry(name) for name in sorted(vars(Symmetry)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
