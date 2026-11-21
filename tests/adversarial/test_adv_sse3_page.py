#!/usr/bin/env python3
"""Hostile review of sse153, third pass: lineAction (the pure part of the 1 s line timer) under node, driven tick by
tick as the page drives it. Each test asserts the SAFE outcome: a failure is a real hole.

Run: python3 test_adv_sse3_page.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = _paths.APP
PURE = (ROOT / 'suda.html').read_text(encoding='utf-8').split('// <pure>')[1].split('// </pure>')[0]

# The page's timer, every second: lineAction on the line as it stands; 'reopen' closes it and opens a new one (its
# clock starts again). A link where a connection takes `connect` ms to open, or never (a server that is down).
DRIVE = r"""
function drive(connect,seconds){
  // (the page counts the attempts that did not open since the last line that did: `fails`)
  let line={state:0,numbered:false,wordAt:NaN,openedAt:NaN,startedAt:0,fails:0},attempts=1,opened=0;
  for(let t=0;t<=seconds*1000;t+=250){
    if(line.state===0&&connect!==null&&t-line.startedAt>=connect){line.state=1;line.openedAt=t;line.fails=0;opened++;}
    if(t%1000===0){
      const act=lineAction(line,t);
      if(act==='reopen'||act==='open'){line={state:0,numbered:false,wordAt:NaN,openedAt:NaN,startedAt:t,fails:line.state===0?line.fails+1:0};attempts++;}
    }
  }
  return {attempts,opened};
}
"""


class LineAction(unittest.TestCase):
    def js(self, script):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        r = subprocess.run([node, '-e', "'use strict';\n" + PURE + DRIVE + script], capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout)

    def test_a_link_that_needs_four_seconds_to_connect_gets_a_line(self):
        got = self.js('console.log(JSON.stringify(drive(4500,60)))')
        self.assertGreaterEqual(got['opened'], 1, 'a minute on a link that connects in 4.5 s, and no line ever opened: %s' % got)

    def test_a_server_that_is_down_is_not_asked_every_three_seconds_for_ever(self):
        """No backoff: a minute against a server that never answers is about 20 new connections (each a TCP and TLS
        handshake on a phone), and an hour is 1200."""
        got = self.js('console.log(JSON.stringify(drive(null,600)))')
        self.assertLessEqual(got['attempts'], 40, 'ten minutes against a server that is down: %d connection attempts' % got['attempts'])


if __name__ == '__main__':
    unittest.main()
