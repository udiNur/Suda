#!/usr/bin/env python3
"""Hostile review of spaces (task 114): server holes. Each test asserts the CORRECT outcome; FAIL = hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import unittest

import test_spaces


class Adv(test_spaces.Spaces):
    def write(self, spaces):
        data = self.data()
        data['spaces'] = spaces
        (self.board / 'state.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    # a hand-edited 'spaces' passes check() and then breaks commands with a non-ValueError
    def test_adv_damaged_color_is_refused_as_damage(self):
        self.write([{'id': 'support', 'name': 'x', 'color': ['#fff'], 'prefix': ['sup-']}])
        r = self.cli('list', ok=False)          # check() must name the damage, like any other
        self.assertIn('spaces', r.stderr)

    def test_adv_damaged_prefix_entry_is_refused_as_damage(self):
        self.write([{'id': 'support', 'name': 'x', 'prefix': [1]}])
        r = self.cli('list', ok=False)
        self.assertIn('spaces', r.stderr)

    def test_adv_duplicate_or_main_space_ids_are_refused(self):
        for bad in ([{'id': 'main', 'name': 'x'}], [{'id': 'a', 'name': 'x'}, {'id': 'a', 'name': 'y'}]):
            with self.subTest(bad=bad):
                self.write(bad)
                r = self.cli('list', ok=False)
                self.assertIn('spaces', r.stderr)

    def test_adv_space_new_with_damaged_color_answers_cleanly(self):
        self.write([{'id': 'support', 'name': 'x', 'color': ['#fff'], 'prefix': []}])
        got = self.ingest({'op': 'space-new', 'name': 'חדש'})
        self.assertFalse(got['ok'])
        self.assertNotIn('again', got, 'a damaged file is not something another try fixes: ' + json.dumps(got, ensure_ascii=False))

    # the square's letter: invisible characters
    def test_adv_page_space_letter_is_visible(self):
        got = self.ingest({'op': 'space-new', 'name': '‏תמיכה'})
        self.assertTrue(got['ok'], got)
        sp = next(s for s in self.data()['spaces'] if s['id'] == got['space'])
        self.assertEqual(sp['letter'], 'ת', 'the letter is the first VISIBLE character of the name')

    def test_adv_cli_invisible_letter_refused(self):
        self.cli('space', 'add', 'zz', 'שם', '--letter', '​', ok=False)

    def test_adv_name_with_bidi_override_refused_or_cleaned(self):
        got = self.ingest({'op': 'space-new', 'name': '‮תמיכה'})
        if got['ok']:
            sp = next(s for s in self.data()['spaces'] if s['id'] == got['space'])
            self.assertNotIn('‮', sp['name'])

    # a merged thread is finished: moving it is the same as writing in it
    def test_adv_move_of_merged_thread_refused(self):
        self.cli('space', 'add', 'support', 'תמיכה', '--prefix', 'sup-')
        self.cli('merge', 'sup-8', '--into', 'sup-9')
        self.assertFalse(self.ingest({'op': 'space-move', 'thread': 'sup-8', 'space': 'main'})['ok'])

    def test_adv_no_space_wears_the_main_spaces_colour(self):
        for n in range(8):
            self.cli('space', 'add', f'c{n}', f'מרחב {n}')
        self.assertNotIn('#6b3fa0', [s['color'] for s in self.data()['spaces']], 'a space looks like the main one (S on #6b3fa0)')


if __name__ == '__main__':
    unittest.main(defaultTest='Adv', argv=['x', '-k', 'test_adv'])
