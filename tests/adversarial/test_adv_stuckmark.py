#!/usr/bin/env python3
"""Hostile review of suda-fixes 55 (19554c8): outside the thread, a message of his that failed is said.

The change: stuckOf(list) over `optimistic`, a red "לא נשלח" (.stuck-mark) in the thread's row (rowNode, the same
row on the phone's list), its words in the mark's title and in the row's aria-label, and tabTitle() puts ⚠️ first in
the tab's title while any thread that still exists has a failed message of his.

Every test states the SAFE outcome, so a FAIL is a hole; the ones named test_held_* are attacks that did not get
through. The harness of test_adv_send_page (a wire that refuses a reply by its words). Nothing binds beyond loopback.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_adv_send_page
from test_e2e import SIZES

# Anything on the screen (or said to a screen reader) that tells him a message of his did not go.
SAID = ('JSON.stringify([...document.querySelectorAll("#channels .stuck-mark,#tower-go,#space-side,#space-rail button,.space-sq,#channels .sec-head")]'
        '.filter(x=>x.offsetParent&&!x.closest("[hidden]")).some(x=>/לא נשלח/.test((x.textContent||"")+" "+(x.getAttribute("aria-label")||"")+" "+(x.title||""))))')
TAB = 'JSON.stringify(document.title)'


def mark_of(tid):
    return ('(()=>{const row=document.querySelector("#channels .ch[data-id=%s]");const m=row&&row.querySelector(".stuck-mark");'
            'return JSON.stringify({row:!!row,mark:m?m.textContent:"",shown:!!(m&&m.offsetParent),label:row?row.getAttribute("aria-label")||"":"",tab:document.title});})()' % tid)


class AdvStuckMark(test_adv_send_page.AdvSend):
    """Only the scenarios of this file: the ones of the harness run in their own files."""

    def topic_of(self, tid, title, state='working'):
        self.ok('new', tid, title, '--state', state, '--note', 'בודקים', '--by', 'e2e')

    def fail_one(self, tid, title, size=SIZES[2]):
        """Thread `tid` on the screen: a reply of his the server refuses."""
        self.show(tid, title, size)
        text = 'נדחית: ' + tid
        self.rule('refuse', text=text, reason='לא עכשיו')
        self.write(text)
        self.browser.wait('(()=>{const row=' + test_adv_send_page.ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()',
                          what='the reply failed')
        return text

    def go(self, tid):
        self.browser.eval('(()=>{openChannel(%s);return "ok";})()' % json.dumps(tid))
        self.browser.wait('JSON.stringify(view.ch===%s)' % json.dumps(tid), what='thread ' + tid + ' on the screen')

    def said(self):
        return self.browser.eval(SAID)

    # ══ holes ════════════════════════════════════════════════════════════════

    def test_a_failed_message_the_server_has_after_all_is_not_marked_on_its_row_nor_in_the_tab(self):
        """Hole (minor): stuckOf reads `optimistic` as it is, and only localOf() (the open thread's drawing) or a
        run of sendAgain lets go of a failed message the state already holds. A failed message that did reach the
        server after all (a try the page gave up on that landed late; it was taken in another device's state) keeps
        the red "לא נשלח" on the row of a thread he is not in, and ⚠️ in the tab, after the state shows it arrived:
        sendAgain is not run on a reading while nothing waits (waitingReplies), so it stays until he opens the
        thread or the line flaps. The row says the opposite of what the thread shows the moment he opens it."""
        a, b = 'stk-held-a', 'stk-held-b'
        self.topic_of(a, 'הודעה שנכשלה והגיעה בכל זאת')
        self.topic_of(b, 'נושא אחר')
        text = self.fail_one(a, 'הודעה שנכשלה והגיעה בכל זאת')
        cid = self.mine(a)[0]['cid']
        self.go(b)
        self.browser.wait('(()=>{const s=JSON.parse(%s);return s.mark?JSON.stringify(s):"";})()' % mark_of(a), what='the mark on the row')
        self.no_rules()
        self.post({'op': 'reply', 'thread': a, 'text': text, 'cid': cid})        # the same message, by its cid: it is there now
        self.browser.wait('JSON.stringify(!!thread(%s)&&thread(%s).messages.some(m=>m.cid===%s))' % (json.dumps(a), json.dumps(a), json.dumps(cid)),
                          timeout=20, what='the state on the page holds it')
        time.sleep(1.5)
        got = self.browser.eval(mark_of(a))
        self.assertEqual(got['mark'], '', 'the row says "not sent" of a message the server holds: %s' % got)
        self.assertFalse(got['tab'].startswith('⚠️'), 'the tab warns of a message the server holds: %r' % got['tab'])

    def test_a_failed_message_in_the_towers_thread_is_said_when_the_tower_is_only_its_icon(self):
        """Hole (important): the tower's thread with nothing new for him is not a row at all (towerQuiet): only
        the icon #tower-go beside the search, whose label stays "המגדל: אין בו חדש". Right after he writes to the
        tower the turn is off him, so the tower is quiet almost always when a reply of his to it fails. He goes to
        another thread: the red "לא נשלח" is nowhere in the list, the icon still says nothing new, and only ⚠️ in
        the tab's title says something, without saying where."""
        self.topic_of('tower', 'מגדל, תפעול')
        other = 'stk-tower-b'
        self.topic_of(other, 'נושא ליד המגדל')
        self.fail_one('tower', 'מגדל, תפעול')
        self.go(other)
        self.browser.wait('JSON.stringify(!$("tower-go").hidden||!!document.querySelector("#channels .ch[data-id=tower]"))', what='the tower in the list or its icon')
        quiet = self.browser.eval('JSON.stringify(!$("tower-go").hidden)')
        self.assertTrue(self.browser.eval(TAB).startswith('⚠️'))
        self.assertTrue(self.said(), 'a reply of his to the tower failed and the list says nothing (the tower is only its icon: %s; its label: %r)'
                        % (quiet, self.browser.eval('JSON.stringify($("tower-go").getAttribute("aria-label"))')))

    def test_a_failed_message_in_a_folded_section_is_said_by_the_section(self):
        """Hole (important): a folded section shows only the thread on the screen (foldedRows). He folded "עובדים
        על זה" (or the archive, or "מוזגו", folded at first); a reply of his in a thread there fails, and he goes to
        another thread: the row with "לא נשלח" is not drawn, and the section's head counts only what is new
        (sec-new). Nothing in the list says which thread holds his messages; only ⚠️ in the tab."""
        a, b = 'stk-fold-a', 'stk-fold-b'
        self.topic_of(a, 'בקטע מקופל')
        self.topic_of(b, 'עליך, בקטע פתוח', state='on-owner')
        self.fail_one(a, 'בקטע מקופל')
        self.browser.eval('(()=>{setFold("working",true);return "ok";})()')
        self.addCleanup(lambda: self.browser.eval('(()=>{try{setFold("working",false)}catch(e){};return "ok";})()'))
        self.go(b)
        time.sleep(1)
        self.assertTrue(self.browser.eval(TAB).startswith('⚠️'))
        self.assertTrue(self.said(), 'a reply in a folded section failed and nothing in the list says so: %s' % self.browser.eval(mark_of(a)))

    def test_a_failed_reply_in_a_thread_he_then_archived_is_said_by_the_list(self):
        """Hole (important), the same hole with no fold of his own: the archive is folded at first
        (FOLDED_FIRST), as are "נודניק" and "מוזגו". He writes a last reply and archives the thread from its head
        right away; the reply is refused. The thread is in the folded archive: the row with "לא נשלח" is not
        drawn and the archive's head says nothing of it, so the reply he thinks he sent, and anything behind it,
        is never said in the list."""
        a, b = 'stk-arch-a', 'stk-arch-b'
        self.topic_of(a, 'מילה אחרונה וארכיון')
        self.topic_of(b, 'נושא אחר', state='on-owner')
        self.fail_one(a, 'מילה אחרונה וארכיון')
        self.ok('close', a)
        self.browser.wait('JSON.stringify(thread(%s).status!=="open")' % json.dumps(a), timeout=20, what='the thread archived on the page')
        self.go(b)
        time.sleep(1)
        self.assertTrue(self.browser.eval(TAB).startswith('⚠️'))
        self.assertTrue(self.said(), 'a reply in an archived thread failed and nothing in the list says so: %s' % self.browser.eval(mark_of(a)))

    def test_a_failed_message_in_another_space_is_said_somewhere_in_this_one(self):
        """Hole (important): the list shows only the threads of the space he is in (sidebar filters by
        currentSpace). He wrote in a thread of space "תמיכה", the reply failed, and he went to the main space
        (the rail, or ⌘K to a main thread): ⚠️ stays in the tab's title, while no row, no tile of the rail and no
        square says there is anything of his in the other space. He cannot tell which thread to open."""
        self.ok('space', 'add', 'stksup', 'תמיכה', '--prefix', 'stks-')
        self.addCleanup(lambda: self.cli('space', 'rm', 'stksup'))
        a, b = 'stks-a', 'stk-main-b'
        self.topic_of(a, 'טיקט בתמיכה')
        self.topic_of(b, 'נושא במרחב הראשי')
        self.fail_one(a, 'טיקט בתמיכה')
        self.go(b)
        self.browser.wait('JSON.stringify(currentSpace()==="main"&&!document.querySelector("#channels .ch[data-id=%s]"))' % a, what='the main space in the list')
        self.assertTrue(self.browser.eval(TAB).startswith('⚠️'))
        self.assertTrue(self.said(), 'a reply in another space failed: the tab warns and nothing on the screen says where')

    def test_a_reply_that_failed_in_another_tab_is_marked_in_this_tabs_list_and_title(self):
        """Hole (minor): two tabs of the board. In the first he is in thread B; in the second he writes in thread
        A and the reply is refused. The first tab takes in another tab's failed message only for a thread where it
        has messages of his or that is on its screen (outboxChanged); A is neither, so its row in the first tab has
        no "לא נשלח" and its title no ⚠️ (a reload of the same tab would show both: the outbox is read whole at a
        load). The tab he looks at says nothing is stuck."""
        a, b = 'stk-tabs-a', 'stk-tabs-b'
        self.topic_of(a, 'נכשלה בלשונית השנייה')
        self.topic_of(b, 'פתוח בלשונית הראשונה')
        self.show(b, 'פתוח בלשונית הראשונה', SIZES[2])
        first_tab = next(t['tabId'] for t in json.loads(self.browser.run('tab', 'list', '--json').stdout)['data']['tabs'] if t['active'])
        self.browser.run('tab', 'new', '--label', 'other', self.url + '?s=other&n=%d#%s' % (int(time.time()), a))
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!!document.querySelector("#input").offsetParent)', timeout=40, what='the second tab')
        text = 'נדחית בלשונית השנייה'
        self.rule('refuse', text=text, reason='לא עכשיו')
        self.write(text)
        self.browser.wait('(()=>{const row=' + test_adv_send_page.ROW % json.dumps(text) + ';return JSON.stringify(!!row&&row.classList.contains("failed"));})()',
                          what='the reply failed in the second tab')
        self.browser.run('tab', first_tab)
        time.sleep(2)
        got = self.browser.eval(mark_of(a))
        self.assertEqual(got['mark'], 'לא נשלח', 'the first tab does not say that a reply of his in A failed: %s' % got)
        self.assertTrue(got['tab'].startswith('⚠️'), got['tab'])

    # ══ held ═════════════════════════════════════════════════════════════════

    def test_held_on_the_phone_a_full_row_keeps_room_for_its_title(self):
        """Pinned: on the phone (360 px) a row with a long title, "דחוף", the mute, a draft, the red count and
        "לא נשלח" keeps its time and every mark inside it, and its title some room."""
        a, b = 'stk-full-a', 'stk-full-b'
        title = 'כותרת ארוכה מאוד של נושא שאין לה סוף, עם עוד מילים ועוד מילים'
        self.topic_of(a, title, state='on-owner')
        self.topic_of(b, 'נושא אחר בטלפון')
        self.fail_one(a, title, SIZES[0])
        self.browser.eval('(()=>{const t=thread(%s);t.urgent=1;t.mute=true;keepDraft(%s,"טיוטה");render();return "ok";})()' % (json.dumps(a), json.dumps(a)))
        self.browser.eval('(()=>{history.back();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#channels .ch[data-id=%s] .stuck-mark")?.offsetParent)' % a, timeout=15, what='the phone\'s list')
        got = self.browser.eval('(()=>{const row=document.querySelector("#channels .ch[data-id=%s]"),r=row.getBoundingClientRect(),in_=x=>{const q=x.getBoundingClientRect();return q.left>=r.left-1&&q.right<=r.right+1;};'
                                'const marks=[...row.querySelectorAll(".ch-marks > *,.ch-time,.urgent-mark")];return JSON.stringify({all:marks.length,inside:marks.every(in_),'
                                'title:row.querySelector(".ch-title").getBoundingClientRect().width});})()' % a)
        self.assertTrue(got['inside'], got)
        self.assertGreaterEqual(got['all'], 5, got)
        self.assertGreater(got['title'], 60, 'the title of the row has almost no room left: %s' % got)


for _name in dir(test_adv_send_page.AdvSend):
    if _name.startswith('test') and _name not in AdvStuckMark.__dict__:
        setattr(AdvStuckMark, _name, None)


if __name__ == '__main__':
    unittest.main()
