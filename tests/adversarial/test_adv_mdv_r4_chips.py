"""Hostile review, round 4 (suda-fixes m190): viewer links as file chips (suda.html, pure section).

- linkChip turns `.../mdv/?path=X` on ANY host into a file chip: `https://evil.example/mdv/?path=~/plan.md` in a
  message (from the tower, a Slack relay, a pasted text) is drawn as a trusted "file" chip named plan.md, with the
  file icon, and a press opens the foreign site (mdvTarget rightly refuses it, so it is a plain new tab).
- The chip's label is the percent-decoded file name: escapes that were inert in the address become live direction
  controls (U+202E) or invisible marks in the label, so the chip can name a file other than the one it opens.
- The label is taken by a regex on the raw address, the panel by URLSearchParams: `pa%74h=` and `+` make them name
  two different files.
Safe outcomes asserted below, under node."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = _paths.APP / 'suda.html'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'node is not installed')
class Chips(unittest.TestCase):
    def js(self, script):
        pure = PAGE.read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]
        r = subprocess.run([NODE, '-e', "'use strict';\nconst assert=require('assert');\n" + pure + '\n' + script],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_a_viewer_address_on_another_host_is_no_file_chip(self):
        self.js(r"""
for (const at of ['https://evil.example/mdv/?path=~/Documents/mds/plan.md',
                  'http://127.0.0.1.evil.example/mdv/?path=plan.md']) {
  const c=linkChip(at);
  assert.ok(!c||c.kind!=='file','a foreign address is drawn as a file chip: '+at+' '+JSON.stringify(c));
}
""")

    def test_the_label_holds_no_direction_controls(self):
        self.js(r"""
const c=linkChip('/mdv/?path=~/x/'+encodeURIComponent('‮dm.exe')),d=linkChip('/mdv/?path=~/x/a%E2%80%8Fb.md');
for (const x of [c,d]) assert.ok(x&&!/[‎‏‪-‮⁦-⁩]/.test(x.label),'a direction control in the label: '+JSON.stringify(x));
""")

    def test_the_label_names_the_file_the_panel_opens(self):
        self.js(r"""
const O='http://127.0.0.1:8767';
for (const at of ['/mdv/?pa%74h=~/secret.md&path=~/plan.md','/mdv/?path=~/a+b.md']) {
  const chip=linkChip(at),opens=mdvTarget(at,O);
  assert.strictEqual(chip&&chip.label,(opens||'').split('/').pop(),'chip says '+(chip&&chip.label)+', the panel opens '+opens);
}
""")


if __name__ == '__main__':
    unittest.main()
