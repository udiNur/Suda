#!/usr/bin/env python3
"""End to end: ⌘K is the command center of the page (the owner, suda m507: "⌘K is missing lots of things like
settings, make it more usable"). Every setting and every action of a button or a key is a command of the palette,
found by its Hebrew or English words, with its key shown where it has one; the commands he used last come first
when nothing is typed. The same harness as test_e2e.py.

PALETTE_SHOTS=<dir> also takes a picture of the palette at 360 and 1280 wide.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import unittest

import test_e2e
from test_e2e import SIZES

ROWS = 'JSON.stringify([...document.querySelectorAll("#sw-results .sw-row")].map(r=>r.innerText.replace("›","").replace(/\\s+/g," ").trim()))'


class Palette(test_e2e.Suda):
    def palette(self, text=''):
        self.browser.eval('(()=>{if(!switcher.hidden)closeSwitcher();return "ok";})()')
        self.browser.wait('JSON.stringify(switcher.hidden)', what='the palette closed')
        self.browser.press('Control+k')
        self.browser.wait('JSON.stringify(!switcher.hidden)', what='the palette')
        self.browser.fill('#sw-query', text)
        return self.browser.eval(ROWS)

    def run_command(self, text, label):
        """Type `text`, and press the command whose label holds `label` (as his click does)."""
        self.palette(text)
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#sw-results .sw-act")].some(r=>r.innerText.includes(%s)))' % json.dumps(label),
                          what='"%s" found by "%s"' % (label, text))
        self.browser.eval('(()=>{[...document.querySelectorAll("#sw-results .sw-act")].find(r=>r.innerText.includes(%s)).click();return "ok";})()' % json.dumps(label))
        self.browser.wait('JSON.stringify(switcher.hidden)', what='the palette closed after "%s"' % label)

    def test_the_palette_is_the_command_center(self):
        if 'tower' not in self.state()['threads']:
            self.ok('new', 'tower', 'מגדל: תפעול', '--state', 'working', '--note', 'שקט', '--by', 'e2e')
        for tid, title, state in (('e2e-pal1', 'נושא לפקודות', 'working'), ('e2e-pal2', 'נושא שני', 'working'), ('e2e-pal3', 'מחכה לך', 'on-owner')):
            if tid not in self.state()['threads']:
                self.ok('new', tid, title, '--state', state, '--note', 'בונה', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-pal1', 'נושא לפקודות')
        self.browser.eval('(()=>{store.del("palette-recent");return "ok";})()')

        # "הגדרות" and "settings" find the settings: the dialog, and the settings themselves
        for word in ('הגדרות', 'settings', 'setings'):
            rows = self.palette(word)
            self.assertTrue(any(r.startswith('הגדרות:') for r in rows), (word, rows))
            self.assertTrue(any('מראה:' in r for r in rows), (word, rows))
            self.assertTrue(any('שעות שקט' in r or 'התראות' in r for r in rows), (word, rows))
        # English and Hebrew words, in any order
        self.assertTrue(any('מראה: כהה' in r for r in self.palette('theme')), self.browser.eval(ROWS))
        self.assertTrue(any('מראה: כהה' in r for r in self.palette('כהה מראה')), self.browser.eval(ROWS))
        self.assertTrue(any('דחוף' in r for r in self.palette('urgent')), self.browser.eval(ROWS))
        self.assertTrue(any('נודניק: בעוד שעה' in r for r in self.palette('snooze')), self.browser.eval(ROWS))
        # and a thread is still found by its name
        self.palette('שני')
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row")?.dataset.id==="e2e-pal2")', what='the thread found first')

        # a setting changed from the palette takes effect
        self.run_command('dark', 'מראה: כהה')
        self.browser.wait('JSON.stringify(document.documentElement.dataset.theme==="dark")', what='the dark theme')
        # three orders (suda-fixes m8): the palette offers the two that are not on now
        self.run_command('sort', 'סדר בתוך קטע: לפי מספר המקום')
        self.browser.wait('JSON.stringify(listOrder()==="slot")', what='the order by place numbers')
        self.run_command('sort', 'סדר בתוך קטע: מה שזז אחרון')
        self.browser.wait('JSON.stringify(listOrder()==="moved")', what='the order of what moved last')
        self.run_command('sort', 'סדר בתוך קטע: ההודעה האחרונה')
        self.browser.wait('JSON.stringify(listOrder()==="recent")', what='the order of the last message')
        self.run_command('fold all', 'קיפול כל הקטגוריות')
        self.browser.wait('JSON.stringify(folds.working&&folds["on-owner"]&&folds.done)', what='every section folded')
        self.run_command('expand all', 'פתיחת כל הקטגוריות')
        self.browser.wait('JSON.stringify(!folds.working&&!folds["on-owner"]&&!folds.done)', what='every section open')

        # thread actions run from the palette, on the open thread
        if 'urgent' in self.ops:
            self.run_command('דחוף', 'סמן כדחוף')
            self.until(lambda: self.thread('e2e-pal1').get('urgent'), what='urgent on the server')
        if 'snooze' in self.ops:
            self.run_command('snooze hour', 'נודניק: בעוד שעה')
            self.until(lambda: (self.thread('e2e-pal1').get('snooze') or {}).get('until'), what='the snooze on the server')
            self.browser.wait('JSON.stringify(asleep(thread("e2e-pal1")))', what='asleep on the page')
            self.run_command('unsnooze', 'נודניק: בטל')
            self.until(lambda: not self.thread('e2e-pal1').get('snooze'), what='the snooze taken away')
        if 'mute' in self.ops:
            self.run_command('mute', 'השתק')
            self.until(lambda: self.thread('e2e-pal1').get('mute'), what='muted on the server')
        self.run_command('details', 'פרטי הנושא')
        self.browser.wait('JSON.stringify(view.details)', what='the details open')
        self.run_command('next', 'הנושא הבא ברשימה')
        self.browser.wait('JSON.stringify(view.ch&&view.ch!=="e2e-pal1")', what='the next thread')
        self.browser.eval('(()=>{openChannel("e2e-pal1");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-pal1")', what='back in the thread')

        # nothing typed: the commands he used last come first, the newest on top
        self.palette('')
        rows = self.browser.eval(ROWS)
        self.assertIn('אחרונות', self.browser.eval('JSON.stringify(document.querySelector("#sw-results").firstElementChild.innerText)'))
        self.assertTrue(rows[0].startswith('הנושא הבא ברשימה'), rows[:5])
        self.assertTrue(rows[1].startswith('פרטי הנושא') or rows[1].startswith('סגירת פרטי הנושא'), rows[:5])
        # ...but the row Enter acts on is still the thread that waits for him first: ⌘K and Enter open it, as always
        ACTIVE = 'JSON.stringify((()=>{const rows=[...document.querySelectorAll("#sw-results .sw-row")],a=document.querySelector("#sw-results .sw-row.active");return {i:rows.indexOf(a),id:a&&a.dataset.id||"",text:a?a.innerText.replace("›","").replace(/\\s+/g," ").trim():""};})())'
        first_thread = self.browser.eval('JSON.stringify(document.querySelector("#sw-results .sw-row[data-id]").dataset.id)')
        self.assertEqual(first_thread, 'e2e-pal3', rows[:8])
        active = self.browser.eval(ACTIVE)
        self.assertEqual(active['id'], 'e2e-pal3', (active, rows[:8]))
        self.assertGreaterEqual(active['i'], 2, 'the recent commands stand above it')
        # the arrows reach the recent commands
        self.browser.press('ArrowUp')
        self.assertEqual(self.browser.eval(ACTIVE)['text'], rows[active['i'] - 1])
        self.browser.press('ArrowDown')
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(switcher.hidden&&view.ch==="e2e-pal3")', what='Enter on the empty palette opened the waiting thread')
        # and Enter on a recent command, reached by the arrows, runs it
        self.browser.eval('(()=>{openChannel("e2e-pal1");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-pal1")', what='back in the thread')
        self.palette('')
        self.browser.press('ArrowUp', self.browser.eval(ACTIVE)['i'])
        self.assertTrue(self.browser.eval(ACTIVE)['text'].startswith('הנושא הבא ברשימה'), self.browser.eval(ACTIVE))
        self.browser.press('Enter')
        self.browser.wait('JSON.stringify(switcher.hidden&&view.ch&&view.ch!=="e2e-pal1")', what='Enter ran "the next thread"')
        # a query typed: the first row again (no recent commands there)
        self.browser.eval('(()=>{openChannel("e2e-pal1");return "ok";})()')
        self.browser.wait('JSON.stringify(view.ch==="e2e-pal1")', what='back in the thread')
        self.palette('שני')
        self.browser.wait('JSON.stringify(document.querySelector("#sw-results .sw-row.active")?.dataset.id==="e2e-pal2")', what='the first row chosen')

        # every command with a key shows it, in the help's notation
        self.palette('')
        missing = self.browser.eval('''JSON.stringify((()=>{
          const shown=new Map([...document.querySelectorAll("#sw-results .sw-act")].map(r=>[r.querySelector(".sw-title").textContent,(r.querySelector(".sw-key")||{}).textContent||""]));
          return actions().filter(a=>a.key&&shown.get(a.label)!==a.key).map(a=>a.label+" "+a.key+" / "+shown.get(a.label));
        })())''')
        self.assertEqual(missing, [])
        keys = self.browser.eval('JSON.stringify(Object.fromEntries(actions().filter(a=>a.key).map(a=>[a.label,a.key])))')
        for label, key in (('סימון הנושא כנקרא', 'E'), ('כתיבת תשובה', 'R'), ('סגירת הנושא', 'C'), ('נושא חדש', 'N'), ('קיצורי מקלדת', '?')):
            self.assertEqual(keys.get(label), key, keys)
        shift = self.browser.eval('JSON.stringify(KEYS.shift)')
        self.assertEqual(keys.get('מעבר למגדל'), shift + ' T', keys)
        self.assertEqual(keys.get('סימון כל הנושאים כנקראו'), shift + ' E', keys)

        shots = os.environ.get('PALETTE_SHOTS')
        if shots:
            os.makedirs(shots, exist_ok=True)
            self.palette('')
            self.browser.run('screenshot', os.path.join(shots, 'palette-1280.png'))
            self.palette('הגדרות')
            self.browser.run('screenshot', os.path.join(shots, 'palette-1280-settings.png'))
            self.open_thread(SIZES[0], 'e2e-pal1', 'נושא לפקודות')
            self.browser.eval('(()=>{openSwitcher();return "ok";})()')
            self.browser.wait('JSON.stringify(!switcher.hidden)', what='the palette on the phone')
            self.browser.run('screenshot', os.path.join(shots, 'palette-360.png'))
            self.browser.fill('#sw-query', 'settings')
            self.browser.run('screenshot', os.path.join(shots, 'palette-360-settings.png'))
        self.browser.eval('(()=>{setTheme("system");return "ok";})()')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Palette.__dict__:
        setattr(Palette, _name, None)


if __name__ == '__main__':
    unittest.main()
