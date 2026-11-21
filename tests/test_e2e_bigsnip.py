#!/usr/bin/env python3
"""End to end: a text file over 2 MB (the owner, a big-file thread, m6: a 7 MB crash report). The board server
takes a request of up to 4 MB, so the page sends a big file in parts and the reply names them; on the Mac the
message holds the whole file. Then the reader shows it 300,000 characters at a time, with a button for more.
The same harness as test_e2e.py; the 6 MB text is made inside the browser (nothing big passes the test tool).
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import hashlib
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

MAKE = ('(()=>{const line="Thread 0 Crashed:: Dispatch queue: com.apple.main-thread שורה\\n";'
        'window.__big=line.repeat(95000)+"END-OF-REPORT";return String(window.__big.length);})()')


class BigSnippet(test_e2e.Suda):
    def test_a_file_over_four_mb_arrives_whole_and_reads_in_steps(self):
        self.ok('new', 'e2e-big', 'קובץ גדול', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], 'e2e-big', 'קובץ גדול')
        chars = int(self.browser.eval(MAKE))
        size = int(self.browser.eval('String(new TextEncoder().encode(window.__big).length)'))
        self.assertGreater(size, 6_000_000)
        self.browser.eval('(()=>{attachFile(new File([window.__big],"crash.ips",{type:"text/plain"}));return "ok";})()')
        self.browser.wait('JSON.stringify(!!attachedOf(view.ch))', what='the file attached', timeout=20)
        self.browser.fill('#input', 'דוח הקריסה')
        self.browser.click('#send')
        m = self.until(lambda: next((m for m in self.thread('e2e-big')['messages'] if m.get('snippet')), None), timeout=120,
                       what='the message with the big file in state.json')
        self.assertEqual((m['text'], m['snippet']['name'], m['snippet']['bytes'], m['snippet']['chars']), ('דוח הקריסה', 'crash.ips', size, chars))
        on_disk = (self.board / m['snippet']['file']).read_bytes()
        want = self.browser.eval('(async()=>{const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(window.__big));'
                                 'return [...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");})()')
        self.assertEqual(hashlib.sha256(on_disk).hexdigest(), want, 'the file on the Mac is not the file he sent')
        self.browser.eval('(()=>{delete window.__big;return "ok";})()')
        # the reader: the first 300,000 characters, then more at a press
        self.browser.wait('JSON.stringify([...document.querySelectorAll("#log .snip")].length>0)', what='the snippet card', timeout=30)
        self.browser.eval('(()=>{[...document.querySelectorAll("#log .snip .snip-body")].pop().click();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#reader-body .reader-more"))', what='the button for more', timeout=60)
        first = self.browser.eval('JSON.stringify(document.querySelector("#reader-body").textContent.length)')
        self.browser.eval('(()=>{document.querySelector("#reader-body .reader-more").click();return "ok";})()')
        time.sleep(0.5)
        second = self.browser.eval('JSON.stringify(document.querySelector("#reader-body").textContent.length)')
        self.assertGreater(second, first + 250_000, 'the button showed no more of the text')
        label = self.browser.eval('document.querySelector("#reader-body .reader-more").textContent')
        self.assertIn('600,000', label)


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in BigSnippet.__dict__:
        setattr(BigSnippet, _name, None)


if __name__ == '__main__':
    unittest.main()
