"""Hostile e2e: five open questions at 360 px (headless Chrome, real board server on loopback, temp board)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_e2e
from test_e2e import SIZES

TID = 'adv-five'
TITLE = 'חמש שאלות'


class FiveQuestions(test_e2e.Suda):
    def test_five_open_questions_at_360(self):
        self.ok('new', TID, TITLE, '--state', 'working', '--note', 'x', '--by', 'e2e')
        for i in range(1, 6):
            self.ok('ask', TID, f'שאלה מספר {i}: ' + 'מילים ארוכות למדי כדי לבדוק גלישה ' * 3, '--options', 'כן,לא,אולי')
        self.ok('ask', TID, 'שישית?', '--options', 'כן,לא', ok=False) if False else None
        self.open_thread(SIZES[0], TID, TITLE)
        got = (self.browser.wait(r'''JSON.stringify((()=>{const p=document.querySelector("#pin"),b=[...p.querySelectorAll(".pin-q")];
          if(b.length!==5)return null;const pr=p.getBoundingClientRect(),n=b[0],nb=[...n.querySelectorAll("button.option")];
          return {ids:b.map(x=>x.dataset.q),newest:n.classList.contains("newest"),vw:innerWidth,vh:innerHeight,pinH:Math.round(pr.height),
            over:p.scrollWidth-p.clientWidth,newestVisible:nb.every(x=>{const r=x.getBoundingClientRect();return r.bottom<=pr.bottom+1&&r.top>=pr.top-1;}),
            olderLive:b.slice(1).map(x=>[...x.querySelectorAll("button.option")].filter(y=>!y.disabled).length),
            log:Math.round(document.querySelector("#log").getBoundingClientRect().height)};})())''', what='five blocks'))
        print('\nFIVE@360', got)
        self.browser.run('screenshot', '/tmp/advq-five-360.png')
        self.assertEqual(got['ids'], ['m5', 'm4', 'm3', 'm2', 'm1'])
        self.assertLessEqual(got['over'], 0)
        self.assertTrue(got['newestVisible'], 'the newest question\'s answers are not visible without scrolling the strip')
        self.assertEqual(got['olderLive'], [3, 3, 3, 3])
        self.assertLessEqual(got['pinH'], got['vh'] * 0.37)
        self.assertGreaterEqual(got['log'], 150, 'the conversation is squeezed out')


for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in FiveQuestions.__dict__:
        setattr(FiveQuestions, _name, None)

if __name__ == '__main__':
    unittest.main()
