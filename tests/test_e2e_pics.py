#!/usr/bin/env python3
"""End to end: a picture that did not load says so and comes by itself (the owner, thread suda m404).

"Just now, for example, the picture on the right did not load, I do not know why." A picture whose download
failed (the line dropped for a moment, the page was taken away and brought back) stayed an empty place in the
message for as long as the page lived: nothing asked for it again and nothing said what had happened. The same
harness as test_e2e.py (headless Chrome, the real board server on loopback, a temporary board), with a server
that fails the downloads of pictures on demand.

What is checked: a picture that failed shows a tile in its place, of the picture's own shape, that says it did
not load; the page asks for it again by itself and the picture then stands there; when it keeps failing the tile
stays and a press on it asks again; when the line comes back every picture that is missing is asked for at once;
and the other picture of the same message is not touched by any of it.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import time
import unittest
from pathlib import Path

import test_e2e
from test_e2e import SIZES, png

ALWAYS = 10 ** 6
SHOTS = ('(()=>JSON.stringify([...document.querySelectorAll("#log .shot")].map(f=>{const img=f.querySelector("img"),tile=f.querySelector(".shot-retry"),box=f.querySelector(".shot-open").getBoundingClientRect();'
         'return {failed:f.classList.contains("failed"),drawn:!!img&&img.complete&&img.naturalWidth>0&&!!img.offsetParent,tile:tile&&tile.offsetParent?tile.textContent:"",'
         'w:Math.round(box.width),h:Math.round(box.height)};})))()')


class Pics(test_e2e.Suda):
    """Only the scenarios of this file: the ones inherited from test_e2e run there."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.server.RequestHandlerClass

        class Flaky(base):
            fail = {}           # part of a picture's path → how many more of its downloads fail
            asked = []          # every download of a picture that came in

            def do_GET(self):
                if '/uploads/' in self.path:
                    path = self.path.split('?')[0]
                    Flaky.asked.append(self.path)
                    for part in list(Flaky.fail):
                        if part in path and Flaky.fail[part] > 0:
                            Flaky.fail[part] -= 1
                            return self.send_error(503)
                return super().do_GET()
        cls.flaky = Flaky
        cls.server.RequestHandlerClass = Flaky

    def setUp(self):
        self.flaky.fail.clear()
        del self.flaky.asked[:]
        self.addCleanup(self.flaky.fail.clear)

    def two_pictures(self, tid, title):
        self.needs('images')
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        first, second = Path(self.tmp.name) / (tid + '-1.png'), Path(self.tmp.name) / (tid + '-2.png')
        first.write_bytes(png(360, 840, shade=40))
        second.write_bytes(png(750, 835, shade=120))
        self.ok('say', tid, '--from', 'fork', '-', '--image', str(first), '--caption', 'הימנית', '--image', str(second), '--caption', 'השמאלית',
                '--by', 'e2e', '--state', 'working', '--note', 'תמונות', input='הודעה עם שתי תמונות')
        # what the conversation asks for: each picture's small copy where the server kept one (task 31)
        self.one, self.two = ((i.get('thumb') or i)['file'].rsplit('/', 1)[1] for i in self.thread(tid)['messages'][0]['images'])

    def open_at(self, tid, title):
        self.browser.open('about:blank')
        self.open_thread(SIZES[0], tid, title)
        self.browser.wait('JSON.stringify(typeof synced!=="undefined"&&synced&&!thread(%s).partial&&document.querySelectorAll("#log .shot").length===2)' % json.dumps(tid), timeout=30, what='the two pictures of the message')

    def shots(self):
        return self.browser.eval(SHOTS)

    def asked(self, part):
        return [path for path in self.flaky.asked if part in path]

    def test_a_picture_that_failed_says_so_and_comes_by_itself(self):
        tid = 'e2e-pics-once'
        self.two_pictures(tid, 'תמונה שנכשלה פעם אחת')
        self.flaky.fail[self.one] = 1
        self.open_at(tid, 'תמונה שנכשלה פעם אחת')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot")[1].querySelector("img").complete)', timeout=20, what='the other picture')
        # by itself, with no press: the page asks again and the picture stands in its place
        self.browser.wait('(()=>{const f=document.querySelectorAll("#log .shot")[0],img=f.querySelector("img");return JSON.stringify(!f.classList.contains("failed")&&img.complete&&img.naturalWidth>0);})()',
                          timeout=30, what='the picture that failed, asked for again by the page')
        first, second = self.shots()
        self.assertEqual((first['failed'], first['drawn'], first['tile']), (False, True, ''), first)
        self.assertEqual((second['failed'], second['drawn'], second['tile']), (False, True, ''), second)
        self.assertGreaterEqual(len(self.asked(self.one)), 2)
        self.assertEqual(len(self.asked(self.two)), 1, 'the picture that loaded was asked for again')

    def test_a_picture_that_keeps_failing_shows_a_tile_of_its_own_shape_and_a_press_asks_again(self):
        tid = 'e2e-pics-down'
        self.two_pictures(tid, 'תמונה שלא נטענת')
        self.flaky.fail[self.one] = ALWAYS
        self.open_at(tid, 'תמונה שלא נטענת')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot")[0].classList.contains("failed"))', timeout=20, what='the tile of the picture that failed')
        time.sleep(1)
        first, second = self.shots()
        self.assertTrue(first['failed'] and not first['drawn'], first)
        self.assertIn('התמונה לא נטענה', first['tile'])
        self.assertIn('נסה שוב', first['tile'])
        self.assertGreaterEqual(first['w'], 100, 'the tile is too small to see or to press: %s' % first)
        self.assertGreaterEqual(first['h'], 80, first)
        self.assertEqual((second['failed'], second['drawn']), (False, True), second)
        # the page asked a few times by itself and then left it to him: it does not ask without end
        time.sleep(9)
        tried = len(self.asked(self.one))
        self.assertTrue(2 <= tried <= 5, 'the page asked for the picture %d times by itself' % tried)
        time.sleep(4)
        self.assertEqual(len(self.asked(self.one)), tried, 'the page goes on asking without end')
        self.assertTrue(self.shots()[0]['failed'])
        # a press on the tile asks again (and does not open the picture viewer on an empty picture)
        self.flaky.fail[self.one] = 0
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot")[0].querySelector(".shot-open").click();return "ok";})()')
        self.browser.wait('(()=>{const f=document.querySelectorAll("#log .shot")[0],img=f.querySelector("img");return JSON.stringify(!f.classList.contains("failed")&&img.complete&&img.naturalWidth>0);})()',
                          timeout=20, what='the picture after his press')
        self.assertTrue(self.browser.eval('JSON.stringify(document.querySelector("#reader").hidden)'), 'the press on the tile opened the viewer')
        # now that it is there, a press opens it as any picture
        self.browser.eval('(()=>{document.querySelectorAll("#log .shot")[0].querySelector(".shot-open").click();return "ok";})()')
        self.browser.wait('JSON.stringify(!document.querySelector("#reader").hidden)', timeout=10, what='the viewer')

    def test_when_the_line_is_back_every_missing_picture_is_asked_for_at_once(self):
        tid = 'e2e-pics-line'
        self.two_pictures(tid, 'הקו חזר')
        self.flaky.fail[self.one] = ALWAYS
        self.flaky.fail[self.two] = ALWAYS
        self.open_at(tid, 'הקו חזר')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot.failed").length===2)', timeout=20, what='both tiles')
        time.sleep(11)                                              # the page's own tries are over
        self.assertEqual([s['failed'] for s in self.shots()], [True, True])
        self.flaky.fail.clear()
        self.browser.eval('(()=>{window.dispatchEvent(new Event("online"));return "ok";})()')
        self.browser.wait('JSON.stringify(document.querySelectorAll("#log .shot.failed").length===0&&[...document.querySelectorAll("#log .shot img")].every(i=>i.complete&&i.naturalWidth>0))',
                          timeout=20, what='both pictures once the line is back')


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in Pics.__dict__:
        setattr(Pics, _name, None)


if __name__ == '__main__':
    unittest.main()
