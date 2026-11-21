"""The port of polish158 into the English release, after a hostile review.

test_e2e_symmetry.py is the measure of polish158, and SKILL.md tells agents that "a new row, chip, dialog top or toast
gets its measure in that file". On the English page (SUDA_E2E_LANG=en) it fails ten times: its order checks are
written for right to left only ("right to left the place number leads the row", "the number leads the chip", "Back is
on the right of the title", "the action ends the notice, on the left"). Each failure stops its subtest, so the measures
after it (a row padded alike on its two sides, a chip with as much room by its number as by its x, the tools over
the list, the buttons of an action) are never taken on the English page: the English release is not measured at all.

The same for test_adv_symmetry.py: its CHOSEN is the Hebrew ", \u05e0\u05d1\u05d7\u05e8", so on the English page (where the row rightly
ends in ", chosen") it fails, and the English release has no guard on the "chosen" suffix after a live refresh.

The tests:
- each file run on the English page passes (the safe outcome: the measure holds for the language it ships in).
  The fix: test_e2e_symmetry.js() mirrors every rectangle on a left to right page, and CHOSEN follows the language.

Run: SUDA_E2E_SERVER=own python3 test_adv_polishport.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = _paths.REPO


def test_file(name):
    """tests/<name>, or tests/adversarial/<name> for a hostile one."""
    return next(p for p in (_paths.TESTS / name, _paths.TESTS / 'adversarial' / name) if p.is_file())


class EnglishRunOfTheSymmetryFiles(unittest.TestCase):
    def english_run(self, name):
        env = dict(os.environ, SUDA_E2E_LANG='en')
        r = subprocess.run([sys.executable, str(test_file(name))], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
        said = [line for line in r.stderr.splitlines() if line.startswith('AssertionError')]
        self.assertEqual(r.returncode, 0, name + ' fails on the English page:\n' + '\n'.join(said[:12]))

    def test_the_symmetry_file_passes_on_the_english_page(self):
        self.english_run('test_e2e_symmetry.py')

    def test_the_chosen_row_check_passes_on_the_english_page(self):
        """test_adv_symmetry.py holds CHOSEN = ', \u05e0\u05d1\u05d7\u05e8' (the Hebrew): on the English page the row
        rightly ends in ', chosen' and the check fails, so the English release has no guard on that suffix."""
        self.english_run('test_adv_symmetry.py')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(EnglishRunOfTheSymmetryFiles(name) for name in sorted(vars(EnglishRunOfTheSymmetryFiles)) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
