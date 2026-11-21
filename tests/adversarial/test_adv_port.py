#!/usr/bin/env python3
"""Hostile review of e59b00e (master merged into i18n145: slow link mode, slash commands, many threads at once).

What the port changed for a Hebrew installation, against master (where the same words were written inline), and
what an English installation lacks. Each test asserts the safe outcome and fails on e59b00e.

1. A Hebrew installation reads the panel of the chosen threads as master wrote it: one chosen thread has the
   button "סמן כנקרא" (master), not the card's title "סימון כנקרא"; closing one thread is "סגור" on the panel and
   on the confirm button (master), not "סגירה" (the old aria-label key "Close" was reused); the Cmd+K row that lets
   go of the choice is "ניקוי הבחירה" (master), not the panel's "נקה בחירה".
2. An English installation reads its own words for a time after /s, as the Hebrew one does ("2 שעות"): the code
   says '"2h" and "2 hours" (his units)', but the English build has no unit words at all.

Run: python3 test_adv_port.py (the e2e part: SUDA_E2E_SERVER=own, as test_e2e.py).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PAGE = ROOT / 'suda.html'


def pure_en(script):
    """The page's DOM-free logic as an English installation runs it (the table empty), under node, in UTC."""
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('node is not installed')
    pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
    r = subprocess.run([node, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                       capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
    return r


class EnglishSlashUnits(unittest.TestCase):
    def test_an_english_installation_reads_its_own_words_for_a_time(self):
        """/s 2 hours, /s 30 minutes, /s 1 day: an English user's words, as "2 שעות" is a Hebrew user's."""
        r = pure_en(r"""
        const now=Date.UTC(2026,10,20,10,0,0)/1000;
        for(const [line,secs] of [['/s 2 hours',7200],['/s 30 minutes',1800],['/s 1 day',86400],['/s 1 hour',3600]]){
          const p=parseSlash(line,{now});
          assert.ok(!p.error,line+': '+p.error);
          assert.strictEqual(p.args.until,now+secs,line);
        }
        """)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])


try:
    import test_e2e
    from test_e2e import SIZES
except Exception:        # (the e2e harness needs agent-browser; the node test above stands alone)
    test_e2e = None

if test_e2e is not None:
    DESK = SIZES[2]
    HOST = '.bulk-host:not([hidden])'

    class HebrewBulkWords(test_e2e.Suda):
        """The panel of the chosen threads in the owner's Hebrew installation, word for word as master shows it."""

        def mod_click(self, tid):
            self.browser.eval('(()=>{const b=document.querySelector(%s);if(!b)throw Error("no row");'
                              'b.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,button:0,metaKey:true}));return "ok";})()'
                              % json.dumps('#channels .ch[data-id=%s]' % json.dumps(tid)))

        def text_of(self, sel):
            return self.browser.eval('JSON.stringify(((document.querySelector(%s)||{}).textContent||"").trim())' % json.dumps(sel))

        def test_one_chosen_thread_reads_as_master_wrote_it(self):
            for tid in ('pt-a', 'pt-b'):
                if tid not in self.state()['threads']:
                    self.ok('new', tid, 'נושא ' + tid, '--state', 'working', '--note', 'בונה', '--by', 'e2e')
            self.open(DESK)
            self.browser.wait('JSON.stringify(synced&&!!document.querySelector("#channels .ch[data-id=\\"pt-a\\"]"))', what='the list')
            self.mod_click('pt-a')
            self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' [data-bulk=read]'), what='the panel')
            # master: bulkBtn(n===1?'סמן כנקרא':...) and bulkBtn(n===1?'סגור':...)
            with self.subTest('the read button (suda.html:9834)'):
                self.assertEqual(self.text_of(HOST + ' [data-bulk=read]'), 'סמן כנקרא')
            with self.subTest('the close button (suda.html:9840)'):
                self.assertEqual(self.text_of(HOST + ' [data-bulk=close]'), 'סגור')
            # master: add('ניקוי הבחירה'+of,'Esc',bulkClear,'bulk-clear')
            rows = self.browser.eval('(()=>{const out={};bulkActions((label,key,run,id)=>{out[id]=label;});return JSON.stringify(out);})()')
            with self.subTest('the Cmd+K row (suda.html:9920)'):
                self.assertEqual(rows.get('bulk-clear'), 'ניקוי הבחירה (1 נבחרו)')
            # master: okLabel=n===1?'סגור':'סגור '+n
            self.browser.click(HOST + ' [data-bulk=close]')
            self.browser.wait('JSON.stringify(!!document.querySelector(%s))' % json.dumps(HOST + ' [data-bulk=ok]'), what='the confirm')
            with self.subTest('the confirm button (suda.html:9779)'):
                self.assertEqual(self.text_of(HOST + ' [data-bulk=ok]'), 'סגור')
            self.browser.click(HOST + ' [data-bulk=cancel]')

    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in HebrewBulkWords.__dict__:
            setattr(HebrewBulkWords, _name, None)


if __name__ == '__main__':
    unittest.main()
