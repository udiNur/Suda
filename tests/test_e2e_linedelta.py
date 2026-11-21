#!/usr/bin/env python3
"""End to end: an update comes in one step (suda-fixes 61, the owner's m270).

The board server sends the small change itself on the line (`event: delta`, before "changed"): the change file the
page would read and the summary's head. The page applies it and reads nothing for that update; on a weak link that
is one round trip less, about a second in the restaurant. A server from before this sends no delta: the page reads
as it always did, and the update still arrives. Run with THREADS_BOARDLIB_DIR at either server: the test asks the
server it runs which one it is.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest

import test_e2e
from test_e2e import SIZES

READS = ('JSON.stringify(performance.getEntriesByType("resource").filter(e=>e.startTime>=window.__mark&&'
         '(/\\/changes\\/\\d+\\.json/.test(e.name)||/\\/changes\\.json/.test(e.name)||/\\/summary\\.json/.test(e.name))&&'
         '!(/\\/summary\\.json/.test(e.name)&&(e.responseStatus===206||(e.decodedBodySize>0&&e.decodedBodySize<=64)))).map(e=>e.name.replace(location.origin,"")))')
# the summary's head alone (64 bytes): the measure of the link an update from the line asks for now and then (slow
# mode learns the latency from it); it is not a read of the update
HEADS = ('JSON.stringify(performance.getEntriesByType("resource").filter(e=>e.startTime>=window.__mark&&/\\/summary\\.json/.test(e.name)&&'
         '(e.responseStatus===206||(e.decodedBodySize>0&&e.decodedBodySize<=64))).length)')


class LineDelta(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    def test_an_agents_message_arrives_with_no_read_of_its_own(self):
        tid, title = 'delta-one', 'עדכון בצעד אחד'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&numbered)', timeout=20, what='the numbered line')
        inline = ('_inline_delta' in (test_e2e.SKILL / 'answer_server.py').read_text(encoding='utf-8')     # which server runs,
                  and self.browser.eval('JSON.stringify(typeof deltaOf==="function")'))                    # and a page that takes it
        for i in range(3):
            self.browser.eval('(()=>{window.__mark=performance.now();return "ok";})()')
            text = 'עדכון מספר %d מהסוכן' % i
            self.ok('say', tid, '--from', 'fork', text, '--by', 'e2e', '--state', 'working', '--note', 'עובד')
            self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes(%s))' % json.dumps(text), timeout=20, what='the update on the screen')
            time.sleep(0.5)
            reads = self.browser.eval(READS)
            if inline:
                self.assertEqual(reads, [], 'the server sent the change itself, yet the page read: %s' % reads)
                self.assertLessEqual(self.browser.eval(HEADS), 1, 'one measure of the link at most')
            else:
                self.assertTrue(reads, 'a server without deltas: the page reads, as before')
        # and the page is as up to date as a whole read would make it
        import re

        def same():
            held = self.browser.eval('JSON.stringify({seq:base&&base.seq,mark:base&&base.mark})')
            m = re.match(r'\{"seq":(\d+),"mark":"([0-9a-f]{8})"', (self.board / 'summary.json').read_text(encoding='utf-8')[:80])
            return (held['seq'], held['mark']) == (int(m.group(1)), m.group(2))
        self.until(same, timeout=15, what='the page holding the very summary the board has')

    def test_a_burst_of_fifty_comes_with_no_read_and_stays_at_the_end(self):
        """The owner, m273: 20 or 50 messages at once should come in one go and feel smooth. The server looks once a
        second, so the saves of that second come as one "changed", and the change itself rides on it (from
        changes.json when the page is more than a few numbers behind): no read, one drawing for each."""
        tid, title = 'delta-burst', 'פרץ של חמישים'
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&numbered)', timeout=20, what='the numbered line')
        inline = ('_inline_delta' in (test_e2e.SKILL / 'answer_server.py').read_text(encoding='utf-8')
                  and '_run_from_changes' in (test_e2e.SKILL / 'answer_server.py').read_text(encoding='utf-8')
                  and self.browser.eval('JSON.stringify(typeof deltaOf==="function")'))
        self.browser.eval('(()=>{window.__mark=performance.now();window.__reads=0;const plain=readChanges;readChanges=f=>{window.__reads++;return plain(f);};return "ok";})()')
        t0 = time.monotonic()
        for i in range(50):
            self.ok('say', tid, '--from', 'fork', 'הודעה %d בפרץ' % i, '--by', 'e2e', '--state', 'working', '--note', 'עובד')
        spent = time.monotonic() - t0
        self.browser.wait('JSON.stringify(document.querySelector("#log").innerText.includes("הודעה 49 בפרץ"))', timeout=30, what='the last of the burst on the screen')
        time.sleep(1)
        shown = self.browser.eval('JSON.stringify([...document.querySelectorAll("#log .msg")].filter(r=>/הודעה \\d+ בפרץ/.test(r.innerText)).length)')
        self.assertEqual(shown, 50)
        reads, readings = self.browser.eval(READS), self.browser.eval('JSON.stringify(window.__reads)')
        print('BURST %s: 50 saves in %.1f s, %d readings, reads %s' % ('inline' if inline else 'as before', spent, readings, len(reads)))
        if inline:
            self.assertEqual(reads, [], 'a burst with the change on the line, yet the page read: %s' % reads[:5])
            heads = self.browser.eval(HEADS)                     # the measure, at most one each MEASURE_GAP (2 s)
            self.assertLessEqual(heads, int(spent / 2) + 3, heads)
        self.assertTrue(self.browser.eval('JSON.stringify(nearBottom())'), 'the conversation did not stay at its end')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in LineDelta.__dict__:
        setattr(LineDelta, _name, None)


if __name__ == '__main__':
    unittest.main()
