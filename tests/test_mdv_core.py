"""The viewer's logic without a server: python3 -m unittest discover -s tests"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(_paths.APP / 'mdv'))
from mdv import core  # noqa: E402
from mdv.testing import SAMPLES, prepare  # noqa: E402
prepare()

MDS = Path(os.environ.get('MDS_SERVER_PY', '/nonexistent'))       # (MDS's server.py, when this machine has it)


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.home = base / 'home'
        self.root = self.home / 'notes'
        (self.root / 'todo').mkdir(parents=True)
        (self.root / '.hidden').mkdir()
        (self.root / 'todo' / 'plan.md').write_text('# plan\n')
        (self.root / '.hidden' / 'x.md').write_text('x')
        (self.root / '.dot.md').write_text('x')
        (self.root / 'notes.txt').write_text('x')
        self.out = base / 'outside'
        self.out.mkdir()
        (self.out / 'secret.md').write_text('secret')
        (self.out / 'secret.txt').write_text('secret')
        cfg = base / 'roots.json'
        cfg.write_text(json.dumps({'roots': [{'alias': 'n', 'path': str(self.root)}, {'alias': 'gone', 'path': '/nope/x'}]}))
        self.roots = core.load_roots(cfg, [])

    def tearDown(self):
        self.tmp.cleanup()

    def ok(self, raw):
        return core.resolve(raw, self.roots, self.home)

    def no(self, raw, code):
        with self.assertRaises(core.Refused) as c:
            self.ok(raw)
        self.assertEqual(c.exception.code, code, raw)

    def test_roots(self):
        self.assertEqual(self.roots, [self.root])
        self.assertEqual(core.load_roots(Path('/nope/roots.json'), [self.out]), [self.out])

    def test_opens_a_note_by_absolute_and_home_path(self):
        self.assertEqual(self.ok(str(self.root / 'todo/plan.md'))[0], self.root / 'todo/plan.md')
        self.assertEqual(self.ok('~/notes/todo/plan.md')[0], self.root / 'todo/plan.md')

    def test_refuses(self):
        self.no('', 'no-path')
        self.no('notes/todo/plan.md', 'bad-path')
        self.no('~/notes/todo/plan.md\x00', 'bad-path')
        self.no(str(self.out / 'secret.md'), 'outside')
        self.no(str(self.root / 'todo/../../../outside/secret.md'), 'outside')
        self.no(str(self.root / 'notes.txt'), 'not-markdown')
        self.no(str(self.root / '.hidden/x.md'), 'hidden')
        self.no(str(self.root / '.dot.md'), 'hidden')
        self.no(str(self.root / 'todo/none.md'), 'missing')
        self.no(str(self.root / 'todo'), 'not-markdown')

    def test_symlinks_out_of_a_root_are_refused(self):
        (self.root / 'link.md').symlink_to(self.out / 'secret.md')
        self.no(str(self.root / 'link.md'), 'outside')
        (self.root / 'dir').symlink_to(self.out)
        self.no(str(self.root / 'dir/secret.md'), 'outside')
        # a .md name pointing at a file that is not markdown
        (self.root / 'txt.md').symlink_to(self.root / 'notes.txt')
        self.no(str(self.root / 'txt.md'), 'not-markdown')

    def test_a_fifo_is_not_a_file(self):
        os.mkfifo(self.root / 'pipe.md')
        self.no(str(self.root / 'pipe.md'), 'missing')

    def test_shown(self):
        self.assertEqual(core.shown(self.root / 'a.md', self.home), '~/notes/a.md')
        self.assertEqual(core.shown(Path('/etc/x.md'), self.home), '/etc/x.md')


class Blocks(unittest.TestCase):
    def test_split(self):
        text = '# t\n\npara one\nline two\n\n```py\na\n\nb\n```\n\n- x\n- y\n'
        self.assertEqual(core.blocks_of(text), ['# t', 'para one\nline two', '```py\na\n\nb\n```', '- x\n- y'])

    @unittest.skipUnless(MDS.is_file(), 'MDS is not on this machine')
    def test_split_is_mds_split(self):
        """The state sidecar is shared with MDS only while both cut a note the same way."""
        src = MDS.read_text()
        start = src.index('def _blocks_of(')
        code = src[start:src.index('\ndef ', start + 10)]
        ns = {}
        exec(code, ns)  # noqa: S102 - the function alone, from the MDS source on this machine
        for sample in SAMPLES.glob('*.md'):
            text = sample.read_text()
            self.assertEqual(core.blocks_of(text), ns['_blocks_of'](text), sample.name)

    def test_lang(self):
        self.assertEqual(core.detect_lang('שלום עולם hi'), 'he')
        self.assertEqual(core.detect_lang('hello שלום'), 'en')

    def test_verbatim(self):
        self.assertTrue(core.is_verbatim('```\nx = 1\n```'))
        self.assertTrue(core.is_verbatim('---'))
        self.assertTrue(core.is_verbatim('| 1 | 2 |'))
        self.assertFalse(core.is_verbatim('Hello'))


class View(unittest.TestCase):
    def test_no_translation(self):
        self.assertEqual(core.translation_view(['a'], 0, None, None), {'exists': False})

    def test_state_lines_up_and_marks_a_changed_block_stale(self):
        state = {'blocks': [{'s': 'A', 't': 'a'}, {'s': 'B', 't': 'b'}, {'s': 'C', 't': 'c'}]}
        v = core.translation_view(['A', 'B2', 'C', 'D'], 0, 'x', state)
        self.assertTrue(v['aligned'])
        self.assertEqual(v['blocks'], [{'t': 'a', 'stale': False}, {'t': 'b', 'stale': True},
                                       {'t': 'c', 'stale': False}, None])
        self.assertEqual(v['stale'], 2)

    def test_mds_opaque_pair_is_not_lined_up(self):
        state = {'blocks': [{'s': 'A\n\nB', 't': 'a\n\nb\n\nc'}]}
        v = core.translation_view(['A', 'B'], 0, '<!-- mds-translation source="x" source_mtime="5" -->\n\na\n\nb\n\nc', state)
        self.assertFalse(v['aligned'])
        self.assertEqual(v['full'], 'a\n\nb\n\nc')

    def test_sibling_without_state(self):
        sib = '<!-- mds-translation source="x" source_mtime="100" model="m" -->\n\na\n\nb\n'
        v = core.translation_view(['A', 'B'], 100, sib, None)
        self.assertEqual(v['blocks'], [{'t': 'a', 'stale': False}, {'t': 'b', 'stale': False}])
        v = core.translation_view(['A', 'B'], 200, sib, None)
        self.assertEqual(v['stale'], 2)

    def test_marker(self):
        info, body = core.split_marker('<!-- mds-translation source="a" source_mtime="12" model="m" -->\n\nhi')
        self.assertEqual(info, {'source_mtime': 12.0, 'model': 'm'})
        self.assertEqual(body, 'hi')
        self.assertEqual(core.split_marker('hi'), (None, 'hi'))


def fake_stream(skip=(), log=None):
    """A model: each block back as 'T:' + its text; numbers in `skip` are left out of the first answer."""
    import re

    def stream(system, messages):
        body = messages[-1]['content']
        if log is not None:
            log.append('\n'.join(m['content'] for m in messages))
        out = ''
        for m in re.finditer(r'<mdv-block n="(\d+)">\n(.*?)\n</mdv-block>', body, re.DOTALL):
            n = int(m.group(1))
            if n in skip and len(re.findall('<mdv-block', body)) > 1:
                continue
            out += '<mdv-block n="%d">\nT:%s\n</mdv-block>\n' % (n, m.group(2))
        for k in range(0, len(out), 7):
            yield out[k:k + 7]
    return stream


class Translate(unittest.TestCase):
    def test_parse_partial(self):
        part = '<mdv-block n="0">\nhello\n</mdv-block>\n<mdv-block n="1">\nwor'
        self.assertEqual(core.parse_blocks(part, {0, 1}), {0: 'hello'})
        self.assertEqual(core.parse_blocks('<mdv-block n="5">\nx\n</mdv-block>', {0}), {})

    def test_first_run_sends_prose_only_and_streams_each_block(self):
        log, seen = [], []
        src = ['# Title', 'Some text', '```\ncode\n```', '---']
        out = core.translate_blocks(src, 'en', 'he', None, 'm', fake_stream(log=log), lambda i, t, how: seen.append((i, how)))
        self.assertEqual(out['blocks'], ['T:# Title', 'T:Some text', '```\ncode\n```', '---'])
        self.assertEqual(out['sent'], 2)
        self.assertEqual(len(log), 1)
        self.assertNotIn('code', log[0])
        self.assertEqual(sorted(seen), [(0, 'model'), (1, 'model'), (2, 'copy'), (3, 'copy')])

    def test_second_run_sends_only_the_changed_block(self):
        src = ['# Title', 'one', 'two']
        first = core.translate_blocks(src, 'en', 'he', None, 'm', fake_stream())
        state = {'src_lang': 'en', 'tgt_lang': 'he', 'model': 'm', 'blocks': [{'s': s, 't': t} for s, t in first['pairs']]}
        log = []
        out = core.translate_blocks(['# Title', 'one changed', 'two'], 'en', 'he', state, 'm', fake_stream(log=log))
        self.assertEqual(out['sent'], 1)
        self.assertEqual(out['reused'], 2)
        self.assertIn('one changed', log[0])
        self.assertNotIn('<mdv-block n="2">', log[0])
        self.assertIn('T:# Title', log[0])   # the translated heading is given as context
        # another model: everything again
        log = []
        out = core.translate_blocks(src, 'en', 'he', state, 'other', fake_stream(log=log))
        self.assertEqual(out['sent'], 3)

    def test_a_block_left_out_is_asked_alone_then_reported(self):
        log = []
        out = core.translate_blocks(['a', 'b', 'c'], 'en', 'he', None, 'm', fake_stream(skip={1}, log=log))
        self.assertEqual(out['blocks'], ['T:a', 'T:b', 'T:c'])
        self.assertEqual(len(log), 2)
        self.assertEqual(out['failed'], [])

        def never(system, messages):
            yield 'nothing useful'
        out = core.translate_blocks(['a', 'b'], 'en', 'he', None, 'm', never)
        self.assertEqual(out['failed'], [0, 1])
        self.assertEqual(out['pairs'], [])

    def test_batches(self):
        items = [(i, 'x' * 3000) for i in range(5)]
        self.assertEqual([len(b) for b in core.batches(items)], [2, 2, 1])
        items = [(i, 'x') for i in range(130)]
        self.assertEqual([len(b) for b in core.batches(items)], [60, 60, 10])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.note = self.root / 'plan.md'
        self.note.write_text('# Title\n\nHello\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths(self):
        self.assertEqual(core.sibling_path(self.note, 'he').name, 'plan.he.md')
        self.assertEqual(core.state_path(self.note, 'he').name, '.plan.he.trans.json')
        self.assertEqual(core.summary_path(self.note).name, '.plan.summary.json')

    def test_save_is_mds_format_and_a_failed_block_stays_in_source(self):
        text = self.note.read_text()
        out = {'blocks': ['כותרת', None], 'pairs': [('# Title', 'כותרת')]}
        sib = core.save_translation(self.note, self.root, text, 100.0, 'en', 'he', out, 'm')
        body = sib.read_text()
        self.assertTrue(body.startswith('<!-- mds-translation source="plan.md" source_mtime="100" model="m" -->\n\n'))
        self.assertTrue(body.endswith('כותרת\n\nHello\n'))
        st = json.loads(core.state_path(self.note, 'he').read_text())
        self.assertEqual(st, {'v': 1, 'src_lang': 'en', 'tgt_lang': 'he', 'model': 'm', 'blocks': [{'s': '# Title', 't': 'כותרת'}]})
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith('.tmp')], [])

    def test_never_writes_through_a_symlink(self):
        target = self.root / 'elsewhere.txt'
        target.write_text('keep')
        core.sibling_path(self.note, 'he').symlink_to(target)
        with self.assertRaises(OSError):
            core.save_translation(self.note, self.root, 'x', 1, 'en', 'he', {'blocks': ['y'], 'pairs': [('x', 'y')]}, 'm')
        self.assertEqual(target.read_text(), 'keep')

    def test_original_of(self):
        sib = self.root / 'plan.he.md'
        sib.write_text('<!-- mds-translation source="plan.md" source_mtime="1" -->\n\nשלום')
        self.assertEqual(core.original_of(sib), self.note)
        plain = self.root / 'other.en.md'
        plain.write_text('no marker')
        self.assertIsNone(core.original_of(plain))

    def test_state_of_wrong_shape_is_ignored(self):
        p = core.state_path(self.note, 'he')
        p.write_text('{"blocks": [{"s": 1}]}')
        self.assertIsNone(core.load_state(p))
        p.write_text('not json')
        self.assertIsNone(core.load_state(p))


if __name__ == '__main__':
    unittest.main()
