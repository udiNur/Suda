"""Hostile review, the two findings reported without a test:
- with a state sidecar, a hand edit in foo.he.md was not shown, and the next run wrote over it;
- on a disk that ignores case, OK.MD and ok.md are one file but got two jobs (two bills, two writers)."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ['MDV_FAKE_MODEL'] = '1'
sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core, model, server  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()


class Extra(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.note = self.root / 'n.md'
        self.note.write_text('# Title\n\nOne.\n\nTwo.\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_hand_edit_in_the_translation_is_shown_and_kept(self):
        text = self.note.read_text()
        blocks = core.blocks_of(text)
        out = core.translate_blocks(blocks, 'en', 'he', None, model.MODEL, model.stream)
        sib = core.save_translation(self.note, self.root, text, self.note.stat().st_mtime, 'en', 'he', out, model.MODEL)
        sib.write_text(sib.read_text().replace('One. [HE]', 'אחת, כמו שתיקנתי'))
        state = core.load_state(core.state_path(self.note, 'he'))
        view = core.translation_view(blocks, 0, sib.read_text(), state)
        self.assertEqual(view['blocks'][1]['t'], 'אחת, כמו שתיקנתי')
        # the source changes elsewhere; the run keeps his words for the block he fixed
        self.note.write_text(text.replace('Two.', 'Two, changed.'))
        state = core.with_hand_edits(state, sib.read_text())
        out = core.translate_blocks(core.blocks_of(self.note.read_text()), 'en', 'he', state, model.MODEL, model.stream)
        self.assertEqual(out['blocks'][1], 'אחת, כמו שתיקנתי')
        self.assertEqual(out['sent'], 1)

    def test_one_file_one_job_whatever_the_case_of_its_name(self):
        upper = self.root / 'N.MD'
        if not upper.exists():
            self.skipTest('this disk tells case apart')
        self.assertEqual(server.job_key(upper), server.job_key(self.note))

    def test_a_hand_written_translation_stops_the_run_before_the_model(self):
        (self.root / 'n.he.md').write_text('מה שכתבתי בעצמי\n')
        calls = []
        real = model.stream

        def spy(*a, **k):
            calls.append(1)
            yield from real(*a, **k)
        model.stream = spy
        try:
            job = server.Job()
            server.run_translation(job, self.note, self.root)
        finally:
            model.stream = real
        self.assertEqual(job.events[-1]['error'], 'not-ours')
        self.assertEqual(calls, [])
        self.assertEqual((self.root / 'n.he.md').read_text(), 'מה שכתבתי בעצמי\n')


if __name__ == '__main__':
    unittest.main()
