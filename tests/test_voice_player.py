#!/usr/bin/env python3
"""A voice message's length (suda-fixes 80, the owner's m414/m415): the player showed "0:00 / 0:00".

Two causes. A recording as MediaRecorder makes it (webm) carries no duration and no index at all, so a browser
knows its length only once it has read all of it; and the page's player loads nothing before he presses play (on a
slow link that is the point). So:

  - threads.py remuxes a new webm recording once, losslessly (ffmpeg -c copy), when it is stored: it then has its
    duration and can be sought in; with no ffmpeg, or when it fails, the file is kept as it came;
  - `threads voice-remux` does the same for the recordings already on the board: a list by default, and with
    --apply each changed file keeps its original beside it (<name>.orig); the board's state is not touched;
  - the page draws its own player: play, a bar, and "0:07 / 0:20" from the stored seconds, the audio read only when
    he presses play.

Run: THREADS_BOARDLIB_DIR=/path/to/boardlib python3 tests/test_voice_player.py
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_threads

APP = _paths.APP
PAGE = (APP / 'suda.html').read_text(encoding='utf-8')
PURE = PAGE.split('// <pure>')[1].split('// </pure>')[0]
NODE, FFMPEG, FFPROBE = shutil.which('node'), shutil.which('ffmpeg'), shutil.which('ffprobe')


def recording(seconds=3):
    """A webm as MediaRecorder writes it: opus, made into a pipe, so it has no duration and no cues."""
    r = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=%s' % seconds,
                        '-c:a', 'libopus', '-b:a', '32k', '-f', 'webm', 'pipe:1'], capture_output=True, check=True)
    return r.stdout


def duration(path):
    """The duration a browser can read from the file's header, or None ('N/A')."""
    r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)], capture_output=True, text=True)
    text = r.stdout.strip()
    return float(text) if text and text != 'N/A' else None


@unittest.skipUnless(FFMPEG and FFPROBE, 'ffmpeg and ffprobe are not installed')
class Stored(unittest.TestCase):
    setUp, run_cli, post = test_threads.ThreadsTests.setUp, test_threads.ThreadsTests.run_cli, test_threads.ThreadsTests.post

    def voice(self, cid, raw, seconds, env=None):
        return self.post({'op': 'reply', 'thread': 'topic', 'cid': cid, 'text': '',
                          'voice': {'type': 'audio/webm;codecs=opus', 'data': base64.b64encode(raw).decode(), 'seconds': seconds}}, env=env)

    def quiet(self, **more):
        # no transcription in these tests: the ear says nothing and ends at once
        ear = self.root / 'ear.py'
        ear.write_text('print("")\n')
        import shlex
        return dict(self.env, THREADS_SONIOX_CMD=shlex.join([sys.executable, str(ear)]), **more)

    def test_a_new_recording_is_stored_with_its_duration(self):
        raw = recording(3)
        probe = self.root / 'probe.webm'
        probe.write_bytes(raw)
        self.assertIsNone(duration(probe), 'the sample must be like a MediaRecorder file: no duration')
        env = self.quiet()
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.assertEqual(self.voice('v1', raw, 3.0, env=env)['ok'], True)
        stored = self.board / 'uploads/topic/m1.webm'
        got = duration(stored)
        self.assertIsNotNone(got, 'the stored recording still has no duration')
        self.assertAlmostEqual(got, 3.0, delta=0.2)
        # the same sound: only the container was rewritten (no re-encode); the size moves by a little
        self.assertLess(abs(stored.stat().st_size - len(raw)), len(raw) // 10)

    def test_without_ffmpeg_or_when_it_fails_the_recording_is_kept_as_it_came(self):
        raw = recording(2)
        env = self.quiet(THREADS_FFMPEG=str(self.root / 'no-such-ffmpeg'))
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.voice('v1', raw, 2.0, env=env)
        self.assertEqual((self.board / 'uploads/topic/m1.webm').read_bytes(), raw)
        # a file ffmpeg cannot read (only the webm magic and noise): kept, and the message is stored
        junk = b'\x1a\x45\xdf\xa3' + b'opus-audio' * 40
        self.assertEqual(self.voice('v2', junk, 2.0, env=self.quiet())['ok'], True)
        self.assertEqual((self.board / 'uploads/topic/m2.webm').read_bytes(), junk)

    def test_voice_remux_lists_then_mends_the_old_recordings_and_keeps_each_original(self):
        raw = recording(2)
        env = self.quiet(THREADS_FFMPEG=str(self.root / 'no-such-ffmpeg'))       # stored the old way: no duration
        self.run_cli('new', 'topic', 'כותרת', env=env)
        self.voice('v1', raw, 2.0, env=env)
        stored = self.board / 'uploads/topic/m1.webm'
        # the words of the recording are written in the background, a moment after it is stored: that is the
        # thread changing, not the remux, so "before" is taken once they are in
        give_up = time.time() + 30
        while json.loads(self.run_cli('show', 'topic', '--json').stdout)['messages'][-1]['voice'].get('state') == 'transcribing':
            self.assertLess(time.time(), give_up, 'the recording was never transcribed')
            time.sleep(0.2)
        state_before = self.run_cli('show', 'topic', '--json').stdout
        # a dry run by default: the list, nothing written
        listed = self.run_cli('voice-remux').stdout
        self.assertIn('uploads/topic/m1.webm', listed)
        self.assertEqual(stored.read_bytes(), raw)
        self.assertFalse((stored.parent / 'm1.webm.orig').exists())
        # --apply: the file gets its duration, the original stays beside it, the board's state is not touched
        self.run_cli('voice-remux', '--apply')
        self.assertIsNotNone(duration(stored))
        self.assertEqual((stored.parent / 'm1.webm.orig').read_bytes(), raw)
        self.assertEqual(self.run_cli('show', 'topic', '--json').stdout, state_before)
        # nothing left to do, and a second --apply never overwrites the kept original
        self.assertNotIn('uploads/topic/m1.webm', self.run_cli('voice-remux').stdout)
        self.run_cli('voice-remux', '--apply')
        self.assertEqual((stored.parent / 'm1.webm.orig').read_bytes(), raw)


@unittest.skipUnless(NODE, 'node is not installed')
class Player(unittest.TestCase):
    def test_the_time_reads_from_the_stored_seconds_until_the_file_knows_better(self):
        r = subprocess.run([NODE, '-e', "'use strict';\nconst assert=require('assert');\n" + PURE + r"""
        // before play (nothing loaded): the stored length
        assert.strictEqual(voiceTime(0,20,NaN),'0:00 / 0:20');
        assert.strictEqual(voiceTime(7.9,20,NaN),'0:07 / 0:20');
        // the file's own length once it is known (a remuxed file), else the stored one (Infinity: a webm with none)
        assert.strictEqual(voiceTime(3,20,21.4),'0:03 / 0:21');
        assert.strictEqual(voiceTime(3,20,Infinity),'0:03 / 0:20');
        assert.strictEqual(voiceTime(3,0,Infinity),'0:03');               // nothing known about the length
        assert.strictEqual(voiceTime(75,124,NaN),'1:15 / 2:04');
        for(const odd of [NaN,-5,undefined,null])assert.strictEqual(voiceTime(odd,20,NaN),'0:00 / 0:20');
        """], capture_output=True, text=True, env={**os.environ, 'TZ': 'UTC'})
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def test_the_player_loads_nothing_before_play(self):
        for part in ("function voicePlayer(src,seconds){", "audio.preload='none';",
                     "if(!audio.src)audio.src=src;", "const player=voicePlayer(voice.src,voice.seconds);"):
            self.assertIn(part, PAGE)
        self.assertNotIn("audio.controls=true;audio.preload='none';audio.src=voice.src;", PAGE)


if os.environ.get('VOICE_E2E', '1') == '1':
    import test_e2e
    from test_e2e import SIZES

    class Shown(test_e2e.Suda):
        """On the phone, in slow mode: the player says the length before anything is loaded."""
        TID = 'voice-len'

        def test_a_voice_message_shows_its_length_before_play_and_loads_nothing(self):
            if not FFMPEG:
                self.skipTest('ffmpeg is not installed')
            if self.TID not in self.state()['threads']:
                self.ok('new', self.TID, 'הקלטה', '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
            path = self.board / 'state/state.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'op': 'reply', 'thread': self.TID, 'cid': 'vp1', 'text': '',
                                        'voice': {'type': 'audio/webm;codecs=opus', 'data': base64.b64encode(recording(4)).decode(), 'seconds': 4.2}}))
            self.ok('ingest')
            self.browser.eval('(()=>{try{localStorage.setItem("suda-slow","load")}catch{}return 1})()')
            self.open_thread(SIZES[0], self.TID, 'הקלטה')
            self.browser.wait('JSON.stringify(!!document.querySelector("#log .vplayer"))', what='the voice player')
            got = self.browser.eval('JSON.stringify({time:document.querySelector("#log .vplayer .vp-time").textContent,'
                                    'src:document.querySelector("#log .vplayer audio").getAttribute("src"),'
                                    'asked:performance.getEntriesByType("resource").some(e=>/\\/uploads\\/.*\\.webm/.test(e.name))})')
            self.assertEqual(got, {'time': '0:00 / 0:04', 'src': None, 'asked': False})
            # play: the file is read, and the time moves on
            self.browser.eval('(()=>{document.querySelector("#log .vplayer .vp-play").click();return 1})()')
            self.browser.wait('JSON.stringify(!!document.querySelector("#log .vplayer audio").getAttribute("src"))', what='the file asked on play')

    for _name in dir(test_e2e.Suda):
        if _name.startswith('test') and _name not in Shown.__dict__:
            setattr(Shown, _name, None)


if __name__ == '__main__':
    unittest.main()
