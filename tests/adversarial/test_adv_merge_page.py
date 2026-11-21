#!/usr/bin/env python3
"""Hostile review of the page side of merging (task 113). Each test asserts the CORRECT outcome: a failure is a hole.
Same harness as test_e2e_merge.py."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

HAS = 'JSON.stringify(!!document.querySelector(%s))'
# Holds every merge POST of the page until window.__release() is called; counts them.
HOLD = r'''(()=>{window.__merges=0;let wait=[];window.__release=()=>{for(const w of wait)w();wait=[];return "ok";};
const real=window.fetch;window.fetch=function(url,opts){
  if(opts&&opts.method==='POST'&&String(opts.body||'').includes('"op":"merge"')){window.__merges++;
    return new Promise(res=>wait.push(res)).then(()=>real.call(this,url,opts));}
  return real.apply(this,arguments);};return "ok";})()'''


class AdvMerge(test_e2e.Suda):

    def fresh(self, src, dst):
        self.ok('new', dst, 'יעד ' + dst, '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('new', src, 'מקור ' + src, '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('say', src, '--from', 'fork', 'השורה הראשונה של המקור ' + src)
        self.ok('task', 'add', src, 'משימה שעוברת', '--owner', 'e2e')

    def ask(self, size, src, dst):
        """Up to the question 'למזג את X לתוך Y?' with the focus as the page leaves it."""
        self.open_thread(size, src, 'מקור ' + src)
        self.browser.eval('(()=>{startMerge(%s);return "ok"})()' % json.dumps(src))
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the picker')
        self.browser.fill('#sw-query', dst)
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row")?.dataset.id===%s)' % json.dumps(dst), what='the target')
        self.browser.press('Enter')
        self.browser.wait(HAS % json.dumps('#merge-ok'), what='the question')

    def active(self):
        return self.browser.eval('JSON.stringify(document.activeElement&&(document.activeElement.id||document.activeElement.tagName))')

    def test_adv_typing_in_the_search_box_while_asked_never_lands_a_key_on_merge(self):
        self.needs('merge')
        self.fresh('av-src1', 'av-dst1')
        self.ask(SIZES[2], 'av-src1', 'av-dst1')
        self.browser.eval('(()=>{document.querySelector("#sw-query").focus();return "ok"})()')
        self.browser.press('a')
        focus = self.active()
        self.browser.press('Space')
        time.sleep(1.5)
        self.assertFalse(self.thread('av-src1').get('merged_into'), 'typing "a " in the search box merged the thread')
        self.assertEqual(focus, 'sw-query', 'one letter typed in the search box sent the focus to "מזג"')

    def test_adv_a_live_redraw_while_asked_does_not_move_the_focus_onto_merge(self):
        self.needs('merge')
        self.fresh('av-src2', 'av-dst2')
        self.ask(SIZES[2], 'av-src2', 'av-dst2')
        self.browser.eval('(()=>{document.querySelector("#merge-back").focus();render();return "ok"})()')   # a live update
        self.assertEqual(self.active(), 'merge-back', 'a live redraw moved the focus from "חזרה" to "מזג"')
        self.browser.press('Enter')
        time.sleep(1.5)
        self.assertFalse(self.thread('av-src2').get('merged_into'), 'Enter on "חזרה" (after a live update) merged')

    def test_adv_a_live_redraw_while_the_merge_is_on_its_way_never_sends_it_twice(self):
        self.needs('merge')
        self.fresh('av-src3', 'av-dst3')
        self.ask(SIZES[0], 'av-src3', 'av-dst3')
        self.browser.eval(HOLD)
        self.browser.click('#merge-ok')
        self.browser.eval('(()=>{render();return "ok"})()')               # a live update while the line is slow
        again = self.browser.eval('JSON.stringify((()=>{const b=document.querySelector("#merge-ok");return !!b&&!b.disabled})())')
        if again:
            self.browser.click('#merge-ok')
        self.browser.eval('window.__release()')
        self.until(lambda: self.thread('av-src3').get('merged_into') == 'av-dst3', what='the merge')
        time.sleep(1.5)
        sent = self.browser.eval('JSON.stringify(window.__merges)')
        where = self.browser.eval('JSON.stringify([view.ch,view.sw||false])')
        print('\n  double-send: enabled again=%s posts=%s view=%s' % (again, sent, where))
        self.assertEqual(sent, 1, 'two merge posts')
        self.assertEqual(where, ['av-dst3', False])
        self.assertFalse(again, 'a live redraw gave back an enabled "מזג" while the merge was on its way')

    def test_adv_a_merge_on_its_way_does_not_close_the_next_switcher(self):
        self.needs('merge')
        self.fresh('av-src4', 'av-dst4')
        self.ask(SIZES[2], 'av-src4', 'av-dst4')
        self.browser.eval(HOLD)
        self.browser.click('#merge-ok')
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#switcher").hidden)', what='Esc')
        self.browser.eval('(()=>{openSwitcher();return "ok"})()')         # an ordinary ⌘K
        self.browser.eval('window.__release()')
        self.until(lambda: self.thread('av-src4').get('merged_into') == 'av-dst4', what='the merge')
        time.sleep(1.5)
        self.assertFalse(self.browser.eval('JSON.stringify(document.querySelector("#switcher").hidden)'),
                         'the late answer of a merge he left closed the ordinary switcher he opened after')

    def test_adv_the_merge_block_learns_that_the_source_was_reopened(self):
        self.fresh('av-src5', 'av-dst5')
        self.ok('merge', 'av-src5', '--into', 'av-dst5')
        self.open_thread(SIZES[2], 'av-dst5', 'יעד av-dst5')
        self.browser.wait(HAS % json.dumps('#log .merge-block'), what='the merge block')
        self.ok('reopen', 'av-src5')
        self.browser.wait('JSON.stringify(!!thread("av-src5")&&!mergedInto(thread("av-src5")))', timeout=20, what='the page hears of the reopening')
        time.sleep(1)
        facts = self.browser.eval('JSON.stringify(document.querySelector("#log .merge-block .mb-facts").innerText)')
        self.assertIn('נפתח מחדש מאז', facts, 'the merge block in the open target never learns the source was reopened')

    def test_adv_a_hostile_history_entry_does_not_leave_the_block_loading(self):
        self.fresh('av-src6', 'av-dst6')
        self.ok('merge', 'av-src6', '--into', 'av-dst6')
        self.open_thread(SIZES[2], 'av-dst6', 'יעד av-dst6')
        self.browser.wait(HAS % json.dumps('#log .merge-block'), what='the merge block')
        self.browser.eval(r'''(()=>{const real=window.fetch;window.fetch=function(url){
          if(String(url).startsWith('full/av-src6'))return Promise.resolve(new Response(JSON.stringify({messages:[null,{from:'fork',ts:1,text:'שורה תקינה'}]})));
          return real.apply(this,arguments);};return "ok"})()''')
        self.browser.click('#log .merge-block [data-act=history]')
        time.sleep(1.5)
        hist = self.browser.eval('JSON.stringify(document.querySelector("#log .merge-block .mb-history").innerText)')
        self.assertIn('שורה תקינה', hist, 'one odd entry in full/<src>.json leaves the history at "טוען…" for good')

    def test_adv_a_moved_from_of_the_wrong_shape_is_not_shown_as_undefined(self):
        self.fresh('av-src7', 'av-dst7')
        self.ok('merge', 'av-src7', '--into', 'av-dst7')
        self.open_thread(SIZES[2], 'av-dst7', 'יעד av-dst7')
        self.browser.eval('(()=>{const t=thread("av-dst7");for(const k of t.tasks)k.moved_from="x";renderTasks(t);return "ok"})()')
        text = self.browser.eval('JSON.stringify(document.querySelector("#tasks")?.textContent||"")')
        self.assertNotIn('undefined', text)

    def test_adv_phone_back_after_merging_from_the_details(self):
        self.needs('merge')
        self.fresh('av-src8', 'av-dst8')
        self.open(SIZES[0])
        self.browser.wait(HAS % json.dumps('.ch[data-id=av-src8]'), what='the list')
        self.browser.click('.ch[data-id=av-src8]')
        self.browser.wait('JSON.stringify(view.ch==="av-src8")', what='the source')
        self.browser.click('#info')
        self.browser.wait(HAS % json.dumps('#details [data-act=merge]'), what='the merge button')
        self.browser.click('#details [data-act=merge]')
        self.browser.wait('JSON.stringify(!document.querySelector("#switcher").hidden)', what='the picker')
        self.browser.click('#sw-results .sw-row[data-id=av-dst8]')
        self.browser.wait(HAS % json.dumps('#merge-ok'), what='the question')
        box = self.browser.eval('JSON.stringify((()=>{const r=document.querySelector(".merge-ask").getBoundingClientRect();return [r.left,r.right,innerWidth]})())')
        self.assertGreaterEqual(box[0], 0)
        self.assertLessEqual(box[1], box[2])
        self.browser.click('#merge-ok')
        self.browser.wait('JSON.stringify(view.ch==="av-dst8"&&document.querySelector("#switcher").hidden)', what='the target')
        self.assertIn('מוזג לתוך', self.browser.eval('JSON.stringify(document.body.innerText)'))
        self.browser.eval('(()=>{history.back();return "ok"})()')
        time.sleep(1)
        where = self.browser.eval('JSON.stringify([view.ch,view.details||false,view.sw||false])')
        print('\n  after Back:', where)
        self.assertNotEqual(where[2], True, 'Back after merging reopened the switcher')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in AdvMerge.__dict__:
        setattr(AdvMerge, _name, None)

if __name__ == '__main__':
    unittest.main()
