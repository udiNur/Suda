#!/usr/bin/env python3
"""End to end: the list of slash commands in the reply box (the approved mockup, suda m651, version 2, compact).

"/" at the start of the box opens the list: one 30px row a command (its Hebrew name, its English name, a short
line), six rows in sight and the rest scroll, the keys in the thin row at the top. It filters as he types, Hebrew or
English (and the keyboard left in the other language). Up and Down choose, Enter or Tab take the row, Esc closes the
list and keeps the text. After a command its short words are chips (Left and Right between them); the short words
beside /סנוז and /דחוף in the row run it whole in one press. Enter on a whole command does it instead of sending it.
The keys never leave the box. On a phone the list is one line of chips right above the box. The help sheet (?) and
Cmd+K list the commands. The same harness as test_e2e.py.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'e2e-slashui'
TITLE = 'רשימת הפקודות'
IN_BOX = 'JSON.stringify(document.activeElement===document.querySelector("#input"))'
OPEN = 'JSON.stringify(!document.querySelector("#slash").hidden)'
NAMES = 'JSON.stringify([...document.querySelectorAll("#slash .sl-row .sl-name")].map(x=>x.textContent))'
SELECTED = 'JSON.stringify((document.querySelector("#slash .on, #slash .first")||{}).textContent||"")'


class SlashList(test_e2e.Suda):
    def box(self):
        return self.browser.eval('JSON.stringify(document.querySelector("#input").value)')

    def start(self, size):
        if TID not in self.state()['threads']:
            self.ok('new', TID, TITLE, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        if 'urgent' in self.thread(TID):
            self.ok('urgent', TID, '--off')
        self.open_thread(size, TID, TITLE)
        self.browser.eval('(()=>{const b=document.querySelector("#input");b.focus();b.value="";b.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()')

    def type(self, text):
        """Real keystrokes into the box (it has the keys)."""
        self.browser.run('keyboard', 'type', text)

    def clear(self):
        self.browser.fill('#input', '')

    def test_the_list_opens_filters_and_takes_the_keys_on_a_desktop(self):
        self.needs('command')
        self.start(SIZES[2])
        self.type('/')
        self.browser.wait(OPEN, what='the list on "/"')
        got = self.browser.eval('''JSON.stringify((()=>{const s=document.querySelector("#slash"),rows=[...s.querySelectorAll(".sl-row")],list=s.querySelector(".sl-list"),
          box=s.getBoundingClientRect(),input=document.querySelector("#input").getBoundingClientRect();
          return {pop:s.classList.contains("pop"),rows:rows.length,height:Math.round(rows[0].getBoundingClientRect().height),seen:Math.round(list.clientHeight),
            first:[rows[0].querySelector(".sl-name").textContent,rows[0].querySelector(".sl-alias").textContent],keys:s.querySelector(".sl-head .sl-keys").textContent,
            above:box.bottom<=input.top+10,inside:box.left>=0&&box.right<=innerWidth,soon:s.querySelector(".sl-group").textContent};})())''')
        self.assertTrue(got['pop'])
        self.assertEqual((got['rows'], got['height'], got['first'], got['soon']), (17, 30, ['/מצב', '/status'], 'בקרוב'))
        self.assertLessEqual(got['seen'], 6 * 30 + 6)                      # six rows in sight, the rest scroll
        for key in ('↑', '↓', 'Enter', 'Tab', 'Esc'):
            self.assertIn(key, got['keys'])
        self.assertTrue(got['above'] and got['inside'], got)
        self.assertTrue(self.browser.eval(IN_BOX))
        # the short words in the row: /סנוז with 2h, מחר 09:00, 12h; /דחוף with on and off
        quick = self.browser.eval('JSON.stringify(Object.fromEntries([...document.querySelectorAll("#slash .sl-row")].filter(r=>r.querySelector(".sl-q"))'
                                  '.map(r=>[r.querySelector(".sl-name").textContent,[...r.querySelectorAll(".sl-q")].map(q=>q.textContent)])))')
        self.assertEqual(quick, {'/סנוז': ['2h', 'מחר 09:00', '12h'], '/דחוף': ['on', 'off'], '/השתק': ['on', 'off']})

        # filtering, in Hebrew
        self.type('ס')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["/סנוז","/סיים","/סקירה","/סגור"]))' % NAMES, what='the list filtered by "/ס"')
        # in English: the row shows the Hebrew name, the English one beside it
        self.clear()
        self.type('/sn')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["/סנוז"]))' % NAMES, what='the list filtered by "/sn"')
        self.assertIn('/snooze', self.browser.eval('JSON.stringify(document.querySelector("#slash .sl-alias").textContent)'))
        # the keyboard left in Hebrew: "/דאש" is "/sta"
        self.clear()
        self.type('/דאש')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["/מצב"]))' % NAMES, what='"/דאש" finds /status')
        self.assertIn('מקלדת בעברית', self.browser.eval('JSON.stringify(document.querySelector("#slash .sl-row").textContent)'))

        # the keys: Down and Up walk the rows, Tab completes without running, Esc closes and keeps the text
        self.clear()
        self.type('/')
        self.browser.wait(OPEN)
        self.browser.press('ArrowDown', 2)
        self.assertIn('/הרץ', self.browser.eval(SELECTED))
        self.browser.press('ArrowUp')
        self.assertIn('/הסבר', self.browser.eval(SELECTED))
        self.browser.press('Tab')
        self.assertEqual(self.box(), '/הסבר ')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.browser.wait(OPEN)                                          # what may follow it: a line that says what Enter does
        self.assertIn('Enter', self.browser.eval('JSON.stringify(document.querySelector("#slash .sl-free").textContent)'))
        self.browser.press('Escape')
        self.browser.wait('JSON.stringify(document.querySelector("#slash").hidden)', what='the list closed by Esc')
        self.assertEqual(self.box(), '/הסבר ')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.assertEqual(self.browser.eval('JSON.stringify(view.ch)'), TID)    # Esc closed the list, nothing else
        time.sleep(0.5)
        self.assertFalse(any(r['thread'] == TID for r in self.pending()))     # and nothing was sent

        # the chips after a command: Left and Right between them, Enter runs /סנוז 2h
        self.clear()
        self.type('/סנוז ')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#slash .sl-inline .sl-q").length===3)', what='the chips of /סנוז')
        self.assertEqual(self.browser.eval('JSON.stringify([...document.querySelectorAll("#slash .sl-inline .sl-q")].map(q=>q.textContent))'), ['2h', 'מחר 09:00', '12h'])
        self.assertEqual(self.browser.eval(SELECTED), '2h')
        self.browser.press('ArrowLeft')
        self.assertEqual(self.browser.eval(SELECTED), 'מחר 09:00')
        self.assertIn('עד מחר 09:00', self.browser.eval('JSON.stringify(document.querySelector("#slash .sl-crumb").textContent)'))
        self.browser.press('ArrowRight')
        self.assertEqual(self.browser.eval(SELECTED), '2h')
        before = time.time()
        self.browser.press('Enter')
        snooze = self.until(lambda: self.thread(TID).get('snooze'), what='/סנוז 2h on the server')
        self.assertAlmostEqual(snooze['until'], before + 7200, delta=90)
        self.browser.wait('JSON.stringify(document.querySelector("#input").value===""&&document.querySelector("#slash").hidden)', what='the box empty after the command')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(t=>t.innerText.includes("נודניק")))', what='the toast of the snooze')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.ok('unsnooze', TID)

        # Enter on /urgent on, typed whole; then one press on "off" in the row of /דחוף
        self.type('/urgent on')
        self.browser.press('Enter')
        self.until(lambda: self.thread(TID).get('urgent'), what='/urgent on, on the server')
        self.assertEqual(self.box(), '')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.type('/')
        self.browser.wait(OPEN)
        self.browser.wait('JSON.stringify((document.querySelector("#slash .sl-q.now")||{}).textContent==="on")', what='"on" marked as the one in force')
        self.browser.eval('(()=>{const r=[...document.querySelectorAll("#slash .sl-row")].find(r=>r.querySelector(".sl-name").textContent==="/דחוף");'
                          '[...r.querySelectorAll(".sl-q")].find(q=>q.textContent==="off").click();return "ok";})()')
        self.until(lambda: 'urgent' not in self.thread(TID), what='"off" in the row of /דחוף, on the server')
        self.assertTrue(self.browser.eval(IN_BOX))

        # nothing above went as a message
        self.assertEqual([m['text'] for m in self.thread(TID)['messages']], [])
        # a request to the agents, chosen from the list: /מצב goes as his reply with its name beside it
        self.type('/מצ')
        self.browser.wait('JSON.stringify(%s===JSON.stringify(["/מצב"]))' % NAMES)
        self.browser.press('Enter')                                     # the row: the box gets "/מצב "
        self.assertEqual(self.box(), '/מצב ')
        self.browser.press('Enter')                                     # nothing more to add: it goes
        row = self.until(lambda: next((r for r in self.pending() if r['thread'] == TID), None), what='/מצב in `threads pending`')
        self.assertEqual((row['text'], row['command']), ('/מצב', {'name': 'status', 'args': ''}))
        self.ok('ack', TID, row['msg_id'])

    def test_the_help_and_the_palette_list_the_commands(self):
        self.start(SIZES[2])
        self.browser.eval('(()=>{showHelp();return "ok";})()')
        rows = self.browser.eval('JSON.stringify([...document.querySelectorAll("#help-slash ~ .help-row")].map(r=>r.textContent))')
        self.assertEqual(len(rows), 12)
        self.assertTrue(any('/סנוז' in r and '/s' in r for r in rows), rows)
        self.browser.eval('(()=>{closeHelp();return "ok";})()')
        self.assertTrue(self.browser.eval(IN_BOX))
        # Cmd+K: a command of the box is found by its name, and goes into the box with its list open
        self.browser.eval('(()=>{openSwitcher();const q=document.querySelector("#sw-query");q.value="פקודה /סנוז";q.dispatchEvent(new Event("input",{bubbles:true}));return "ok";})()')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#sw-results .sw-row")].some(r=>r.textContent.includes("/סנוז")))', what='/סנוז in Cmd+K')
        self.browser.eval('(()=>{[...document.querySelectorAll("#sw-results .sw-row")].find(r=>r.textContent.includes("/סנוז")).click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="/סנוז "&&document.activeElement===document.querySelector("#input")&&document.querySelectorAll("#slash .sl-q").length===3)',
                          what='the box with /סנוז and its chips, after Cmd+K')
        self.clear()

    def test_run_rename_and_a_page_action_that_fails(self):
        """/הרץ end to end (the hostile review: the request was refused), /שם with its undo, and a page action that
        the server cannot do: the line stays in the box."""
        self.needs('command')
        tid = 'e2e-slashrun'
        self.ok('new', tid, 'הרצה מהתיבה', '--state', 'working', '--note', 'בונה', '--by', 'e2e')
        self.ok('say', tid, '--from', 'tower', 'לבדיקה:\n```\n! echo hi\n```')
        self.open_thread(SIZES[2], tid, 'הרצה מהתיבה')
        self.browser.fill('#input', '/הרץ')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(!document.querySelector("#run").hidden)', what='the run dialog')
        self.assertEqual(self.box(), '/הרץ')                              # the line waits for the dialog
        self.browser.click('#run-ok')
        row = self.until(lambda: next((r for r in self.pending() if r['thread'] == tid), None), what='the run request in `threads pending`')
        self.assertEqual((row['run']['command'], row['command']), ('! echo hi', {'name': 'run', 'args': ''}))
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="")', what='the box empty after the request')
        self.ok('ack', tid, row['msg_id'], '--as', 'tower')
        # the tower wrote after its block: /הרץ does not reach past it, and the line stays
        self.ok('say', tid, '--from', 'tower', 'אל תריץ את זה')
        self.browser.wait('JSON.stringify(thread(%r).messages.length===3)' % tid, what='the tower\'s newer word on the page')
        self.browser.fill('#input', '/הרץ')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(t=>t.innerText.includes("אין בנושא הזה פקודת ▶")))', what='no current block')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#run").hidden)'))
        self.assertEqual(self.box(), '/הרץ')
        # /שם: a new name, and its undo puts the old one back
        self.browser.fill('#input', '/שם שם חדש לבדיקה')
        self.browser.press('Enter')
        self.until(lambda: self.thread(tid)['title'] == 'שם חדש לבדיקה', what='/שם on the server')
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="")', what='the box empty after /שם')
        self.browser.eval('(()=>{const t=[...document.querySelectorAll(".toast")].find(t=>t.innerText.includes("השם החדש"));'
                          '[...t.querySelectorAll("button")].find(b=>b.textContent.includes("בטל")).click();return "ok";})()')
        self.until(lambda: self.thread(tid)['title'] == 'הרצה מהתיבה', what='the old name back')
        # a page action the server refuses: the toast says why and the line stays
        self.browser.fill('#input', '/משימה 9 בוצע')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(t=>t.innerText.includes("אין כאן משימה 9")))', what='the refusal')
        self.assertEqual(self.box(), '/משימה 9 בוצע')
        self.ok('task', 'add', tid, 'קיימת', '--owner', 'fork')
        self.browser.wait('JSON.stringify(thread(%r).tasks.length===1)' % tid, what='the task on the page')
        self.browser.eval('(()=>{window.__fetch=window.fetch;window.fetch=(u,o)=>o&&o.method==="POST"?Promise.reject(new TypeError("offline")):window.__fetch(u,o);return "ok";})()')
        self.browser.fill('#input', '/משימה 1 בוצע')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify([...document.querySelectorAll(".toast")].some(t=>t.innerText.includes("השורה נשארה בתיבה")))', what='the toast of no connection')
        self.assertEqual(self.box(), '/משימה 1 בוצע')
        self.browser.eval('(()=>{window.fetch=window.__fetch;return "ok";})()')
        self.browser.press('Enter')                                         # the connection back: the same line does it
        self.until(lambda: self.thread(tid)['tasks'][0]['status'] == 'done', what='the task done once the connection is back')
        self.browser.wait('JSON.stringify(document.querySelector("#input").value==="")', what='the box empty once it was done')
        self.assertTrue(self.browser.eval(IN_BOX))

    def test_on_a_phone_the_list_is_a_line_of_chips_above_the_box(self):
        self.needs('command')
        self.start(SIZES[0])
        self.browser.fill('#input', '/')
        self.browser.wait(OPEN, what='the chips on "/"')
        got = self.browser.eval('''JSON.stringify((()=>{const s=document.querySelector("#slash"),r=s.getBoundingClientRect(),box=document.querySelector("#composer .box").getBoundingClientRect(),
          chips=[...s.querySelectorAll(".sl-chips .sl-chip")];
          return {row:s.classList.contains("row"),chips:chips.length,first:chips[0].textContent,inside:r.left>=0&&r.right<=innerWidth+1,above:r.bottom<=box.top+1,
            tall:Math.round(r.height),close:!!s.querySelector(".sl-chip.x")};})())''')
        self.assertTrue(got['row'] and got['inside'] and got['above'] and got['close'], got)
        self.assertEqual(got['chips'], 17)
        self.assertTrue(got['first'].startswith('/מצב'), got)          # the first one says in two words what it does
        self.assertLess(got['tall'], 60)                                 # one line
        self.browser.fill('#input', '/סנוז ')
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#slash .sl-chip:not(.x)")].map(c=>c.textContent).join("|")==="2h|מחר 09:00|12h")', what='the chips of /סנוז on the phone')
        before = time.time()
        self.browser.eval('(()=>{[...document.querySelectorAll("#slash .sl-chip")].find(c=>c.textContent==="2h").click();return "ok";})()')
        snooze = self.until(lambda: self.thread(TID).get('snooze'), what='/סנוז 2h from a chip')
        self.assertAlmostEqual(snooze['until'], before + 7200, delta=90)
        self.assertEqual(self.box(), '')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.ok('unsnooze', TID)
        # the close chip closes the chips and keeps the text
        self.browser.fill('#input', '/ס')
        self.browser.wait(OPEN)
        self.browser.eval('(()=>{document.querySelector("#slash .sl-chip.x").click();return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelector("#slash").hidden)', what='the chips closed')
        self.assertEqual(self.box(), '/ס')
        self.assertTrue(self.browser.eval(IN_BOX))
        self.clear()
        # the inner screen of the foldable: the list is there and stays on the screen
        self.start(SIZES[1])
        self.browser.fill('#input', '/')
        self.browser.wait(OPEN)
        self.assertTrue(self.browser.eval('JSON.stringify((()=>{const r=document.querySelector("#slash").getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0;})())'))
        self.clear()


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in SlashList.__dict__:
        setattr(SlashList, _name, None)


if __name__ == '__main__':
    unittest.main()
