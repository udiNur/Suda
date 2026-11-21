"""Hostile review 6 of the viewer's code direction (92efd2a): Find over a Hebrew comment.

Find in the viewer marks a match inside one text node. Before 92efd2a a comment was one text node (`<span class=tk-c>`),
so `# TODO` found `x = 1  # TODO תקן את זה`. codeNodes() now cuts a Hebrew comment after code into two nodes, its
marker (`# `, outside the island) and its words (in the <bdi>), so a search for the marker with the first word finds
nothing. The test asserts the search still finds it, and finds it in a comment alone on its line and after code alike.
Fails on 92efd2a. Skips when agent-browser is missing; "os error 35" or ERR_ABORTED are flakes: rerun."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

import test_mdv_e2e
from test_mdv_e2e import AB, Browser, server

DOC = '# a\n\n```python\nx = 1  # TODO תקן את זה\n# TODO לבד בשורה\n```\n\n```sql\nselect 1 -- הערה\n```\n'


@unittest.skipUnless(AB, 'agent-browser is not installed')
class FindInComments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.root = base / 'root'
        cls.root.mkdir()
        (cls.root / 'find.md').write_text(DOC)
        (base / 'roots.json').write_text('{"roots": []}')
        cls.port = test_mdv_e2e.free_port()
        cls.srv = server.make_server(cls.port, server.Config(base / 'roots.json', [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.b = Browser('mdv-adv-r6-find-%d' % os.getpid())
        try:
            cls.b.run('open', 'about:blank', timeout=120)
        except Exception as e:
            cls.srv.shutdown()
            raise unittest.SkipTest('agent-browser could not open a browser: ' + str(e)[:200])
        cls.b.run('set', 'viewport', '1280', '800')
        cls.b.run('open', 'http://127.0.0.1:%d/mdv/?path=%s' % (cls.port, quote(str(cls.root / 'find.md'), safe='')))
        cls.b.wait('document.querySelectorAll("#doc .md pre code").length===2', what='the code blocks')

    @classmethod
    def tearDownClass(cls):
        try:
            cls.b.run('close', timeout=60)
        except Exception:
            pass
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def find(self, q):
        # one find may be marked in pieces (a comment's marker and its island): its pieces share data-find
        return self.b.eval('(()=>{document.getElementById("find").hidden=false;const i=document.getElementById("find-q");'
                           'i.value=%s;i.dispatchEvent(new Event("input"));'
                           'const g={};for(const m of document.querySelectorAll("#doc mark.hl"))g[m.dataset.find]=(g[m.dataset.find]||"")+m.textContent;'
                           'return JSON.stringify(Object.keys(g).sort((a,b)=>a-b).map(k=>g[k]))})()'
                           % json.dumps(q))

    def test_a_the_marker_and_the_first_word_of_a_hebrew_comment_are_found(self):
        # one after code, one alone on its line: both comments hold "# TODO"
        self.assertEqual(self.find('# TODO'), ['# TODO', '# TODO'])

    def test_b_the_marker_and_hebrew_words_after_code_are_found(self):
        self.assertEqual(self.find('-- הערה'), ['-- הערה'])
        self.assertEqual(self.find('# תקן'), [], 'nothing matches what is not in the text')

    def test_c_find_leaves_the_code_text_as_it_was(self):
        self.find('# TODO')
        got = self.b.eval('JSON.stringify([...document.querySelectorAll("#doc .md pre code")].map(c=>c.textContent))')
        self.assertEqual(got, ['x = 1  # TODO תקן את זה\n# TODO לבד בשורה', 'select 1 -- הערה'])


if __name__ == '__main__':
    unittest.main()
