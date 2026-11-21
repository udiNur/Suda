"""The viewer end to end in a headless browser (agent-browser), served from a temp folder with a stand-in model.
Skips when agent-browser is missing. "os error 35" from agent-browser is a known flake: rerun."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import quote

os.environ['MDV_FAKE_MODEL'] = '1'
os.environ.setdefault('MDV_FAKE_DELAY', '0.01')
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, server  # noqa: E402
from mdv.testing import REPO, SAMPLES, prepare  # noqa: E402
prepare()
from mdv.testing import free_port  # noqa: E402

AB = shutil.which('agent-browser')

DOC = """# Plan for the viewer

A first paragraph with `inline code` and a [link to the other note](./other.md).

## A table

| Step | What |
|---|---|
| 1 | Mockup |
| 2 | Build |

```mermaid
flowchart LR
  A --> B
```

```python
x = 1  # שלום
```

Read also `~/root/other.md` please.
"""

# A note in Hebrew (invented): Hebrew and English in one document, several blocks, "Suda" more than once
HE_DOC = """# תוכנית: צופה בסגנון Suda

צופה Markdown שנראה כמו Suda: אותו פונט, אותם כרטיסים לקוד, לטבלאות ולדיאגרמות.

## מטרות

- קריאה נוחה בטלפון
- תרגום עברית ואנגלית, צד לצד

## שלבים

| שלב | מה |
|---|---|
| 1 | מוקאפ |
| 2 | מנוע משותף עם Suda |

```bash
# השרת מאזין רק על 127.0.0.1
uv run server.py --port 18000
```

> הרינדור משותף עם Suda, כך שתיקון אחד מתקן את שניהם.

## שאלות פתוחות

1. איזה מנוע תרגום?
2. האם הסיכום נשאר כפתור נפרד?
"""


class Browser:
    def __init__(self, name):
        self.name = name

    def run(self, *args, stdin=None, timeout=90):
        for attempt in range(3):
            r = subprocess.run([AB, '--session', self.name, *args], input=stdin, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 or 'os error 35' not in (r.stderr + r.stdout):
                break
            time.sleep(1)
        if r.returncode != 0:
            raise RuntimeError('agent-browser ' + ' '.join(args[:2]) + ': ' + (r.stderr or r.stdout).strip()[-600:])
        return r

    def eval(self, js):
        out = json.loads(self.run('eval', '--json', '--stdin', stdin=js).stdout)
        if not out.get('success'):
            raise RuntimeError(str(out.get('error'))[:600])
        value = out['data'].get('result')
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    def wait(self, js, timeout=20, what='the page'):
        """Poll `js` until it is truthy (a DOM node does not come back: test it with !!)."""
        end = time.monotonic() + timeout
        while True:
            value = self.eval(js)
            if value:
                return value
            if time.monotonic() > end:
                seen = ' '.join(str(self.eval('JSON.stringify(document.body.innerText)')).split())[:500]
                raise AssertionError('waited for %s: %s\nthe page says: %s' % (what, js[:160], seen))
            time.sleep(0.25)

    def click(self, sel):
        self.eval('(()=>{const e=document.querySelector(%s);if(!e)throw Error("no "+%s);e.click();return "ok"})()' % (json.dumps(sel), json.dumps(sel)))


@unittest.skipUnless(AB, 'agent-browser is not installed')
class Viewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(cls.tmp.name))
        cls.home = base
        cls.root = base / 'root'
        cls.root.mkdir()
        (cls.root / 'plan.md').write_text(DOC)
        (cls.root / 'other.md').write_text('# The other note\n\nShort.\n')
        (cls.root / 'he.md').write_text(HE_DOC)
        cfg = base / 'roots.json'
        cfg.write_text('{"roots": []}')
        cls.port = free_port()
        cls.srv = server.make_server(cls.port, server.Config(cfg, [cls.root], base, set()))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.b = Browser('mdv-e2e-%d' % os.getpid())
        try:
            cls.b.run('open', 'about:blank', timeout=120)
        except Exception as e:
            cls.srv.shutdown()
            raise unittest.SkipTest('agent-browser could not open a browser: ' + str(e)[:200])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.b.run('close', timeout=60)
        except Exception:
            pass
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def open(self, path, mode='', w=1280, h=800):
        self.b.run('set', 'viewport', str(w), str(h))
        url = 'http://127.0.0.1:%d/mdv/?path=%s%s' % (self.port, quote(str(path), safe=''), '&mode=' + mode if mode else '')
        self.b.run('open', url)
        self.b.wait('document.querySelectorAll("#doc .blk, #doc .oops, #doc .land").length>0', what='the document')

    def test_1_renders_in_suda_style(self):
        self.open(self.root / 'plan.md')
        got = self.b.wait('''(()=>{const svg=document.querySelector(".diagram-body svg");if(!svg)return 0;return JSON.stringify({
          title:document.getElementById("h-title").textContent,table:!!document.querySelector(".card.sheet table"),
          code:!!document.querySelector(".card.code .tk-com,.card.code pre"),path:document.getElementById("h-path").textContent,
          link:(document.querySelector("a.md-link")||{}).getAttribute&&document.querySelector("a.md-link").getAttribute("href"),
          codeLink:[...document.querySelectorAll("a.md-link")].map(a=>a.getAttribute("href"))})})()''', what='the diagram')
        self.assertEqual(got['title'], 'Plan for the viewer')
        self.assertTrue(got['table'] and got['code'])
        self.assertEqual(got['path'], '~/root/plan.md')
        self.assertEqual(got['codeLink'], ['/mdv/?path=~%2Froot%2Fother.md'] * 2)

    def test_2_translate_then_live_reload_then_update(self):
        for p in (core.sibling_path(self.root / 'plan.md', 'he'), core.state_path(self.root / 'plan.md', 'he')):
            p.unlink(missing_ok=True)
        self.open(self.root / 'plan.md', 'both')
        self.b.wait('!!document.querySelector(".xbar .btn.primary")', what='the translate button')
        self.b.click('.xbar .btn.primary')
        self.b.wait('!!document.querySelector(".chip.done")', what='the translation to finish')
        pairs = self.b.eval('JSON.stringify([...document.querySelectorAll(".pair")].map(p=>p.querySelector("[data-kind=tr]").innerText.slice(0,40)))')
        self.assertTrue(pairs[0].endswith('[HE]'), pairs)
        self.assertEqual(len(pairs), 7)
        self.assertTrue(core.sibling_path(self.root / 'plan.md', 'he').is_file())
        # an edit on disk: the page follows, flashes the block and marks only its translation old
        (self.root / 'plan.md').write_text(DOC.replace('A first paragraph', 'An edited paragraph'))
        self.b.wait('!!document.querySelector(".blk.flash")&&document.body.innerText.includes("An edited paragraph")', what='the reload')
        self.assertEqual(self.b.eval('document.querySelectorAll(".blk.stale").length'), 1)
        self.b.click('.xbar .btn')
        self.b.wait('!!document.querySelector(".chip.done")&&!document.querySelector(".blk.stale")', what='the update')
        st = core.load_state(core.state_path(self.root / 'plan.md', 'he'))
        edited = [b['t'] for b in st['blocks'] if b['s'].startswith('An edited')]
        self.assertEqual(len(edited), 1)
        self.assertTrue(edited[0].startswith('An edited paragraph') and edited[0].endswith('[HE]'), edited)

    def test_3_find(self):
        self.open(self.root / 'he.md')
        self.b.run('press', '/')
        self.b.eval('(()=>{const i=document.getElementById("find-q");i.value="Suda";i.dispatchEvent(new Event("input"));return 1})()')
        n = self.b.wait('document.querySelectorAll("mark.hl").length', what='matches')
        self.assertGreater(n, 1)
        self.assertEqual(self.b.eval('document.getElementById("find-count").textContent'), '1/%d' % n)

    def test_4_summary(self):
        core.summary_path(self.root / 'other.md').unlink(missing_ok=True)
        self.open(self.root / 'other.md')
        self.b.click('#b-sum')
        self.b.wait('!!document.querySelector(".sum .md")', what='the summary')
        self.assertTrue(core.summary_path(self.root / 'other.md').is_file())

    def test_5_phone_stacks_the_translation(self):
        self.open(self.root / 'he.md', 'both', 360, 840)
        self.b.wait('!!document.querySelector(".xbar .btn")')
        self.b.click('.xbar .btn')
        self.b.wait('!!document.querySelector(".chip.done")', what='the translation')
        got = self.b.eval('''JSON.stringify({under:document.querySelectorAll(".under").length,pairs:document.querySelectorAll(".pair").length,
          head:Math.round(document.querySelector(".head").getBoundingClientRect().height),
          wide:document.documentElement.scrollWidth<=window.innerWidth,
          seg:document.querySelector(".seg [data-mode=both]").textContent})''')
        self.assertGreater(got['under'], 5)
        self.assertEqual(got['pairs'], 0)
        self.assertGreater(got['head'], 40)
        self.assertTrue(got['wide'])
        self.assertEqual(got['seg'], 'One under the other')
        self.b.run('screenshot', '/tmp/mdv-e2e-phone.png')

    def test_6_a_link_opens_the_other_note(self):
        self.open(self.root / 'plan.md')
        self.b.click('a.md-link')
        self.b.wait('document.getElementById("h-title").textContent==="The other note"', what='the other note')

    def test_7_refused_and_landing(self):
        self.open('/etc/hosts.md')          # outside the roots: said the same whether or not it exists
        self.assertIn('outside the folders', self.b.eval('document.querySelector(".oops").textContent'))
        self.open(self.root / 'none.md')
        self.assertIn('not found', self.b.eval('document.querySelector(".oops").textContent'))
        self.open(self.home / 'roots.json')
        self.assertIn('.md', self.b.eval('document.querySelector(".oops").textContent'))
        self.b.run('open', 'http://127.0.0.1:%d/mdv/' % self.port)
        self.b.wait('!!document.querySelector(".land input")', what='the landing page')
        self.assertIn('~/root/', self.b.eval('document.querySelector(".land .recent").textContent'))

    def test_9_pictures_show(self):
        # suda-fixes task 45: a README's screenshots, by a path relative to the note, in both forms READMEs use
        import struct, zlib
        raw = b''.join(b'\x00' + bytes([30, 120, 200]) * 40 for _ in range(20))
        chunk = lambda k, d: struct.pack('>I', len(d)) + k + d + struct.pack('>I', zlib.crc32(k + d) & 0xffffffff)
        (self.root / 'docs').mkdir(exist_ok=True)
        (self.root / 'docs' / 'shot.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 40, 20, 8, 2, 0, 0, 0))
                                                     + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        (self.root / 'readme.md').write_text('# App\n\n![the screen](docs/shot.png)\n\n<p align="center"><img src="docs/shot.png" alt="Logo" width="120"></p>\n\n![gone](docs/none.png)\n')
        self.open(self.root / 'readme.md')
        got = self.b.wait('JSON.stringify((()=>{const imgs=[...document.querySelectorAll(".md-img img")];if(imgs.length<2||!imgs.every(i=>i.complete&&i.naturalWidth))return 0;'
                          'return {n:imgs.length,w:imgs.map(i=>i.naturalWidth),alt:imgs.map(i=>i.alt),missing:document.querySelectorAll(".md-img-missing").length}})())', what='the pictures')
        self.assertEqual(got['w'], [40, 40])
        self.assertEqual(got['alt'], ['the screen', 'Logo'])
        self.b.wait('document.querySelectorAll(".md-img-missing").length===1', what='the missing picture said by its name')

    def test_8_theme_and_no_console_errors(self):
        self.open(self.root / 'plan.md')
        self.b.click('#b-more')
        self.b.eval('(()=>{[...document.querySelectorAll("#menu button")].find(b=>b.textContent.includes("Theme")).click();return 1})()')
        self.assertIn(self.b.eval('document.documentElement.dataset.theme'), ('dark', 'light'))
        errors = self.b.run('errors').stdout.strip()
        self.assertNotIn('Content Security Policy', errors)

    def test_10_a_hebrew_installation_speaks_hebrew(self):
        """The installation's language (l10n.json, as threads install writes it): the page right to left, its words
        the Hebrew they were before the English release."""
        from mdv import sync
        viewer = self.home / 'installed'
        (viewer / 'static').mkdir(parents=True, exist_ok=True)
        sync.write(viewer / 'static', REPO / 'suda.html')
        for name in ('app.js', 'mdv-pure.js', 'index.html'):
            shutil.copyfile(REPO / 'mdv' / 'static' / name, viewer / 'static' / name)
        sync.localize(viewer, 'he', REPO / 'locales')
        os.environ['MDV_L10N'] = str(viewer / 'l10n.json')
        try:
            self.open(self.root / 'he.md', 'both', 360, 840)
            self.b.wait('!!document.querySelector(".seg [data-mode=both]")', what='the bar')
            got = self.b.eval('''JSON.stringify({dir:document.documentElement.dir,lang:document.documentElement.lang,
              seg:document.querySelector(".seg [data-mode=both]").textContent,find:document.getElementById("b-find").title,
              sum:document.getElementById("b-sum").title,q:document.getElementById("find-q").placeholder})''')
            self.assertEqual(got, {'dir': 'rtl', 'lang': 'he', 'seg': 'זה מתחת לזה', 'find': 'חיפוש בקובץ (/)',
                                   'sum': 'סיכום בעברית (S)', 'q': 'חיפוש בקובץ הזה'})
            self.open('/etc/hosts.md')
            self.assertIn('מחוץ לתיקיות', self.b.eval('document.querySelector(".oops").textContent'))
        finally:
            os.environ.pop('MDV_L10N', None)


if __name__ == '__main__':
    unittest.main()
