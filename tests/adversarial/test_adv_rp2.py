#!/usr/bin/env python3
"""Hostile review of the release merges (i18n145 @ 9b68d87: master merged into the English release, then srvport170).
Each case asserts the SAFE outcome and failed on 9b68d87.

1. An old board's task history keeps the owner's old id. Master's boards (version 2) carry task `events`
   (task history, task 34): `by` is a person, and a `status` event's from/to are states ('on-<his old id>'), an
   `owner` event's from/to are owners. migrate_owner (version 3) rewrites every other field that holds his id, but
   not the events, so after the upgrade his own history says the old id and the old state, which the page and the
   CLI no longer know as his.
2. In an English (left to right) installation the "not sent" mark of a space ('!') sits exactly on the count of
   topics that wait for him: `.n` was made logical (inset-inline-end) for the release, the `.n.stuck` rule master
   added still says left:auto;right:-6px, which in Hebrew is the other corner and in English the same one.
3. The MD Viewer ignores config.json "locale_file": threads.py (and live_hook.py) take the installation's table from
   it, sync.localize reads only locales/<lang>.json, so Suda speaks the installation's language right to left while
   its viewer, in the same installation, is English and left to right.
4. Private names of the owner's own machine came in with master: the folder of his markdown reader in the shipped
   viewer's code, and the binary and config of his gateway in tests.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = _paths.APP
CLI = ROOT / 'threads.py'


class OldBoardEvents(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.threads-test-rp2-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'boards/threads'
        self.env = dict(os.environ, BOARDS_DIR=str(self.root / 'boards'), THREADS_NOTIFY_CMD='true')
        for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'TUIOS_PANE_ID'):
            self.env.pop(key, None)
        private = self.root / '.threads-config/threads'
        private.mkdir(parents=True)
        (private / 'config.json').write_text(json.dumps({'lang': 'he', 'owner_aliases': ['dana']}), encoding='utf-8')

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def test_an_old_boards_task_history_is_migrated_with_the_rest(self):
        """A version 2 board as master writes it: the owner's id 'dana', task events included. After the upgrade no
        event names him by the old id or says his old state; the words of a text event are left as they were."""
        events = [
            {'ts': 1.0, 'kind': 'created', 'by': 'dana'},
            {'ts': 2.0, 'kind': 'status', 'by': 'fork', 'from': 'todo', 'to': 'on-dana'},
            {'ts': 3.0, 'kind': 'owner', 'by': 'dana', 'from': 'fork', 'to': 'dana'},
            {'ts': 4.0, 'kind': 'status', 'by': 'dana', 'from': 'on-dana', 'to': 'working'},
            {'ts': 5.0, 'kind': 'text', 'by': 'dana', 'from': 'dana', 'to': 'on-dana'},       # words: never touched
        ]
        topic = {'id': 'topic', 'title': 'T', 'context': '', 'status': 'open', 'created': 1.0, 'updated': 5.0, 'next': 2,
                 'links': [], 'slot': 1, 'state': 'working', 'note': 'n', 'state_ts': 5.0, 'state_by': 'fork', 'auto': False,
                 'messages': [{'id': 'm1', 'from': 'fork', 'text': 'x', 'ts': 2.0}],
                 'tasks': [{'n': 1, 'text': 'on-dana', 'status': 'working', 'owner': 'dana', 'by': 'dana', 'note': '', 'from': None,
                            'ts': 1.0, 'updated': 5.0, 'events': events}]}
        self.board.mkdir(parents=True)
        (self.board / 'state.json').write_text(json.dumps({'version': 2, 'threads': {'topic': topic}}), encoding='utf-8')
        self.run_cli('list')
        state = json.loads((self.board / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['version'], 3)
        k = state['threads']['topic']['tasks'][0]
        self.assertEqual((k['owner'], k['by']), ('owner', 'owner'))          # (this part was migrated already)
        got = [(e['kind'], e.get('by'), e.get('from'), e.get('to')) for e in k['events']]
        self.assertEqual(got, [('created', 'owner', None, None),
                               ('status', 'fork', 'todo', 'on-owner'),
                               ('owner', 'owner', 'fork', 'owner'),
                               ('status', 'owner', 'on-owner', 'working'),
                               ('text', 'owner', 'dana', 'on-dana')])
        # what the page reads says the same: the thread's own file carries the events
        full = json.loads((self.board / 'full/topic.json').read_text(encoding='utf-8'))
        shown = [(e['kind'], e.get('by'), e.get('from'), e.get('to')) for e in full['tasks']['1']]        # (the thread's file: each task's events by its number)
        self.assertEqual(shown, got)


class StuckMarkLayout(unittest.TestCase):
    """The space square and the space rail carry two marks at once: the count of topics waiting for him (`.n`) and
    the "not sent" mark (`.n.stuck`). They stand in different corners in both directions."""

    SIDES = {'ltr': {'inset-inline-end': 'right', 'inset-inline-start': 'left'},
             'rtl': {'inset-inline-end': 'left', 'inset-inline-start': 'right'}}

    def rule(self, css, selector):
        m = re.search(r'(?:^|\})\s*' + re.escape(selector) + r'(?:,[^{]*)?\{([^}]*)\}', css, re.M)
        self.assertIsNotNone(m, selector)
        return dict(p.split(':', 1) for p in m.group(1).split(';') if ':' in p)

    def side(self, props, direction, base=None):
        """The horizontal edge a positioned mark is held to, after `base` (the rule it overrides)."""
        sides = dict(base or {})
        for prop, value in props.items():
            prop, value = prop.strip(), value.strip()
            physical = self.SIDES[direction].get(prop, prop)
            if physical in ('left', 'right'):
                sides[physical] = value
        held = [s for s, v in sides.items() if v != 'auto']
        return held, sides

    def test_the_not_sent_mark_never_covers_the_count(self):
        page = (ROOT / 'suda.html').read_text(encoding='utf-8')
        css = page.split('<style>', 1)[1].split('</style>', 1)[0]
        stuck = self.rule(css, '.space-sq .n.stuck')
        for base_sel in ('.space-sq .n', '.space-rail .n'):
            base = self.rule(css, base_sel)
            for direction in ('ltr', 'rtl'):
                with self.subTest(mark=base_sel, dir=direction):
                    count_side, sides = self.side(base, direction)
                    stuck_side, _ = self.side(stuck, direction, sides)
                    self.assertEqual(len(stuck_side), 1, stuck_side)
                    self.assertNotEqual(count_side, stuck_side, 'the "!" sits on the count in %s' % direction)


class ViewerLocaleFile(unittest.TestCase):
    def test_the_viewer_speaks_the_table_suda_speaks(self):
        """An installation whose table is its own file (config.json "locale_file"): the viewer `threads install`
        writes gets the same language, direction and words as the board page."""
        with tempfile.TemporaryDirectory(prefix='.threads-test-rp2-lf-', dir=ROOT) as tmp:
            root = Path(tmp)
            (root / 'my.json').write_text(json.dumps({'_dir': 'rtl', 'Close': 'CLOSE-X', 'Search this file': 'FIND-X'}), encoding='utf-8')
            private = root / '.threads-config/threads'
            private.mkdir(parents=True)
            (private / 'config.json').write_text(json.dumps({'lang': 'ar', 'locale_file': str(root / 'my.json')}), encoding='utf-8')
            env = dict(os.environ, BOARDS_DIR=str(root / 'boards'), THREADS_NOTIFY_CMD='true', HOME=str(root))
            for key in ('THREADS_NOTIFY', 'THREADS_SLUG', 'TUIOS_PANE_ID', 'THREADS_MDV_DIR'):
                env.pop(key, None)
            r = subprocess.run([sys.executable, str(CLI), 'install'], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            page = (root / 'boards/threads/suda.html').read_text(encoding='utf-8')
            self.assertIn('<html lang="ar" dir="rtl">', page)          # the board page took the file
            self.assertIn('CLOSE-X', page)
            l10n = json.loads((root / 'threads-mdv/l10n.json').read_text(encoding='utf-8'))
            self.assertEqual((l10n['lang'], l10n['dir']), ('ar', 'rtl'))
            self.assertEqual((l10n['table'].get('Close'), l10n['table'].get('Search this file')), ('CLOSE-X', 'FIND-X'))


class NoPrivateMachineNames(unittest.TestCase):
    def test_the_tree_names_none_of_the_owners_own_tools(self):
        names = re.compile('|'.join(n[::-1] for n in ('reweiv-sdm', 'yawetag-lacol', 'fc-yddac', 'adus-elifyddaC')))   # (spelled so this file does not hold them)
        files = subprocess.run(['git', 'ls-files'], cwd=_paths.REPO, capture_output=True, text=True, check=True).stdout.split()
        hits = []
        for name in files:
            if name.startswith(('suda/vendor/', 'docs/assets/', 'suda/icons/', 'suda/mdv/static/vendor/')) or name.endswith(('.png', '.gif', '.ico', '.mp4', '.webm')):
                continue
            for n, line in enumerate((_paths.REPO / name).read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if names.search(line) and Path(name).name != Path(__file__).name:
                    hits.append('%s:%d' % (name, n))
        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
