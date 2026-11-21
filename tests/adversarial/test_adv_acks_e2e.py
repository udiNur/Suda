#!/usr/bin/env python3
"""Hostile review of task 118, in the browser: the ack line never changes the height of his message at 360 px."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest

import test_e2e
from test_e2e import SIZES
from test_e2e_acks import Acks as Base, HEIGHT


class AdvAcksE2E(Base):
    def test_no_jump_at_the_cover_width(self):
        tid = 'adv-ak'
        self.ok('new', tid, 'קפיצה', '--state', 'working', '--note', 'x', '--by', 'e2e')
        self.ok('say', tid, '--from', 'owner', 'תעשה את זה')
        self.open_thread(SIZES[0], tid, 'קפיצה')
        self.wait_ack('m1', 'received')
        tall = {'received': self.browser.eval(HEIGHT % 'm1')}
        self.ok('ack', tid, 'm1')
        self.wait_ack('m1', 'taken')
        tall['taken'] = self.browser.eval(HEIGHT % 'm1')
        self.ok('react', tid, 'm1', '✅', '--by', 'a1')
        self.wait_ack('m1', 'done')
        tall['done'] = self.browser.eval(HEIGHT % 'm1')
        self.browser.run('screenshot', '/tmp/suda-adv-acks-360.png')
        self.assertEqual(len(set(tall.values())), 1, tall)


for _name in dir(Base):
    if _name.startswith('test') and _name not in AdvAcksE2E.__dict__:
        setattr(AdvAcksE2E, _name, None)

if __name__ == '__main__':
    unittest.main()
