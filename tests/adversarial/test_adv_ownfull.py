#!/usr/bin/env python3
"""Hostile review of "his own pictures at full size even on a slow link" (suda-fixes m195, commit 27dcea2):
ownFull, ownFullNow, setOwnFull, shrinkPlan(state, full), slowWords(state, full), the .own-full chips, the
'own-full:on' / 'own-full:off' command.

Each test asserts the SAFE outcome, so a failing test is a hole. Tests marked "pinned" pass on 27dcea2: they
record a safe behavior that was checked and should stay.

The pure part runs under node like test_slack.py. The end to end part uses the harness of test_e2e.py (headless
Chrome, the real board server on loopback, a temporary board): THREADS_BOARDLIB_DIR points at the board server.
The slow link mode is put on by his own choice ("always tap"), which turns on the same 1280 px plan the measured
mode does, so no network emulation is needed.
"""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json
import re
import shutil
import time
import unittest
from pathlib import Path

import test_e2e
import test_slack
from test_e2e import SIZES

NODE = shutil.which('node')
ROOT = _paths.APP


class OwnFullPure(unittest.TestCase):
    page, node, pure_js = test_slack.SlackPageTests.page, test_slack.SlackPageTests.node, test_slack.SlackPageTests.pure_js

    # ── holes ──────────────────────────────────────────────────────────────

    def test_skill_md_names_the_setting_as_he_sees_it(self):
        """SKILL.md tells agents to point him to "התמונות שלי בגודל מלא" in the settings. No such words are on the
        page: the settings say "תמונות שאתה שולח:" and a chip "בגודל מלא"; Cmd+K says "התמונות שלי: בגודל מלא גם
        בקליטה איטית". An agent that quotes SKILL.md sends him looking for a line that is not there. The words
        SKILL.md quotes for the setting appear on the page as he sees them."""
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        page = (ROOT / 'suda.html').read_text(encoding='utf-8')
        bullet = skill.split('**His pictures arrive smaller on a slow link**', 1)[1].split('\n   - ', 1)[0]
        quoted = [' '.join(q.split()) for q in re.findall(r'"([^"]+)"', bullet)]
        self.assertTrue(quoted)
        # the page speaks English through tr() (the English release): its words are the tr keys, and the Cmd+K line
        # is built from its parts, as an English installation shows it
        words = re.search(r"const OWN_FULL_WORDS='([^']+)'", page)[1]
        also = '{words}, also on a slow link'.format(words=words)
        self.assertIn("tr('{words}, also on a slow link',{words:tr(OWN_FULL_WORDS)})", page)
        shown = '\n'.join([*re.findall(r"'([^'\n]+)'", page), also, 'My pictures: {what}'.format(what=also)])     # (labels such as SLOW_CHOICES' go through tr where drawn)
        for q in quoted:
            self.assertTrue(q in shown, 'SKILL.md quotes %r; the page has no such words' % q)

    # ── pinned ─────────────────────────────────────────────────────────────

    def test_odd_stored_values_fall_back_to_the_default_and_nothing_throws(self):
        """Pinned (passes): anything stored under own-full but 'on' or 'off' (an old 'true', 'ON', '1', junk) is
        the default, which follows the media choice; an odd media value is "auto" (shrunk). shrinkPlan takes only
        a real true as full, and slowWords does not throw on odd states."""
        self.pure_js(r"""
        for(const kept of ['true','ON','1','',null,undefined,{},[],0,'on ']){
          assert.strictEqual(ownFull(kept,'load'),true,String(kept));
          assert.strictEqual(ownFull(kept,'auto'),false,String(kept));
          assert.strictEqual(ownFull(kept,'tap'),false,String(kept));
          assert.strictEqual(ownFull(kept,'LOAD'),false,String(kept));
          assert.strictEqual(ownFull(kept,{}),false,String(kept));
        }
        assert.strictEqual(ownFull('on','tap'),true);assert.strictEqual(ownFull('off','load'),false);
        assert.deepStrictEqual(shrinkPlan({on:true,up:true},'true'),{side:1024,quality:0.6});
        assert.deepStrictEqual(shrinkPlan({on:true,up:true},1),{side:1024,quality:0.6});
        for(const s of [null,undefined,'x',5,{on:true},{on:true,whys:[1,null]},{on:false,up:true}])
          for(const f of [true,false,undefined,'on'])assert.doesNotThrow(()=>slowWords(s,f));
        // full is never bigger than the good-link plan: the client's own gate (picturesFit) is the same as there
        assert.deepStrictEqual(shrinkPlan({on:true,up:true},true),shrinkPlan(null));
        """)

    def test_the_words_follow_the_plan_in_every_state(self):
        """Pinned (passes): the settings say his pictures are shrunk exactly when they are: with the mode off but
        his uploads slow ("always load" and own-full 'off'), and not when he chose full size."""
        self.pure_js(r"""
        const states=[null,{on:false},{on:false,up:true},{on:true,whys:['tap'],why:'tap'},{on:true,whys:['up'],why:'up',up:true}];
        for(const s of states)for(const f of [true,false]){
          const said=/מוקטנות/.test(slowWords(s,f)),shrunk=shrinkPlan(s,f).side<PICTURE_SIDE;
          assert.strictEqual(said,shrunk,JSON.stringify([s,f,slowWords(s,f)]));
        }
        """)


@unittest.skipUnless(NODE, 'node is not installed')
class OwnFull(test_e2e.Suda):
    """Only the scenarios of this file: the ones of test_e2e.Suda run there."""

    KEY = staticmethod(lambda k: json.dumps(test_e2e.SLUG + ':' + k))
    TRAY = 'JSON.stringify((pictures.get(view.ch)||[]).map(p=>Math.max(p.w,p.h)))'
    CHIPS = 'JSON.stringify([...document.querySelectorAll("#notify-body .own-full button")].map(b=>[b.textContent,b.getAttribute("aria-pressed")]))'
    TOASTS = 'JSON.stringify([...document.querySelectorAll(".toasts .toast")].map(t=>t.textContent))'

    def start(self, tid, title, media='tap', own=None):
        self.ok('new', tid, title, '--state', 'working', '--note', 'בודקים', '--by', 'e2e')
        self.open_thread(SIZES[2], tid, title)
        own_js = 'localStorage.removeItem(%s)' % self.KEY('own-full') if own is None else 'localStorage.setItem(%s,%s)' % (self.KEY('own-full'), json.dumps(own))
        self.browser.eval('(()=>{%s;setSlowChoice(%s);pictures.delete(view.ch);renderTray();return "ok";})()' % (own_js, json.dumps(media)))

    def tray_is(self, n):
        self.browser.wait('JSON.stringify(%s.length===%d)' % (self.TRAY.replace('JSON.stringify(', '(', 1), n), timeout=20, what='%d in the tray' % n)
        return self.browser.eval(self.TRAY)

    def picture(self, name, w, h):
        path = Path(self.tmp.name) / name
        path.write_bytes(test_e2e.png(w, h, shade=40))
        return path

    def tearDown(self):
        if self.browser:
            self.browser.eval('(()=>{try{pictures.delete(view.ch);renderTray();localStorage.removeItem(%s);setSlowChoice("auto");closeNotify&&closeNotify();}catch{}return "ok";})()'
                              % self.KEY('own-full'))

    # ── holes ──────────────────────────────────────────────────────────────

    def test_choosing_full_size_does_not_leave_the_tray_shrunk_in_silence(self):
        """He attaches a screenshot on a slow link (always tap): the tray holds it at 1280 px. It looks soft, so
        he opens the settings and chooses "בגודל מלא"; the toast says "התמונות שלך יישלחו בגודל מלא". He sends,
        and the picture goes at 1280 px all the same: shrink() ran when he attached it, the tray keeps only the
        shrunk bytes, and nothing tells him. The same for the tray restored from the device after a reload. Safe:
        what is in the tray is made again at the size he chose, or he is told that the ones already attached stay
        as they are (attach them again)."""
        self.start('e2e-own-tray', 'תמונה במגש', media='tap')
        self.browser.upload('#pic-file', self.picture('tray.png', 1500, 1000))
        self.assertEqual(self.tray_is(1), [1280])
        self.browser.eval('(()=>{openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .own-full"))', timeout=10, what='the setting')
        self.browser.eval('(()=>{[...document.querySelectorAll("#notify-body .own-full button")].find(b=>b.textContent==="כמו בקליטה טובה").click();return "ok";})()')
        time.sleep(3)
        tray, toasts = self.browser.eval(self.TRAY), self.browser.eval(self.TOASTS)
        told = any(('שכבר' in t or 'מחדש' in t or 'שוב' in t) for t in toasts)
        self.assertTrue(tray == [1500] or told, 'the tray still %s and he was told only %s' % (tray, toasts))

    def test_full_size_is_not_promised_when_the_picture_is_still_cut_to_1600(self):
        """"בגודל מלא" is the good-link plan: the longest side cut to 1600 px and a JPEG at 0.82. A photo from his
        phone (4032 x 3024), or here 2400 x 1600, goes at 1600 px while the chip, the toast ("התמונות שלך יישלחו
        בגודל מלא") and Cmd+K say full size. Safe: either the picture keeps its size, or the words he reads do not
        promise "בגודל מלא" without saying it is as on a good link."""
        self.start('e2e-own-cap', 'תמונה גדולה', media='tap', own='on')
        self.browser.upload('#pic-file', self.picture('big.png', 2400, 1600))
        tray = self.tray_is(1)
        self.browser.eval('(()=>{openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .own-full"))', timeout=10, what='the setting')
        words = [label for label, _ in self.browser.eval(self.CHIPS)]
        self.browser.eval('(()=>{setOwnFull(true);return "ok";})()')
        words += self.browser.eval(self.TOASTS)
        words += self.browser.eval('JSON.stringify(actions().filter(a=>/^own-full:/.test(a.id)).map(a=>a.label))')
        promised = [w for w in words if 'בגודל מלא' in w and '1600' not in w and 'קליטה טובה' not in w]
        self.assertTrue(tray == [2400] or not promised, 'sent at %s px while he reads %s' % (tray, promised))

    def test_another_tab_choosing_keeps_the_open_settings_true(self):
        """Two tabs of Suda (the phone's app and a browser tab, or two windows). In one he chooses "בגודל מלא"; the
        other has its settings open and still shows "מוקטנות בקליטה איטית" pressed, while its next picture goes at
        full size (ownFullNow reads the store each time). The page listens to 'storage' for the list order and
        the theme and draws the open settings again; not for own-full. Safe: the open settings follow."""
        self.start('e2e-own-tabs', 'שתי לשוניות', media='tap')
        self.browser.eval('(()=>{openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .own-full"))', timeout=10, what='the setting')
        self.assertEqual(self.browser.eval(self.CHIPS), [['כמו בקליטה טובה', 'false'], ['מוקטנות בקליטה איטית', 'true']])
        # what the browser does in this tab when another tab writes the key
        self.browser.eval('(()=>{const k=%s;localStorage.setItem(k,"on");window.dispatchEvent(new StorageEvent("storage",{key:k,newValue:"on",oldValue:null,storageArea:localStorage}));return "ok";})()'
                          % self.KEY('own-full'))
        time.sleep(1)
        self.assertEqual(self.browser.eval('JSON.stringify(ownFullNow())'), True)
        self.assertEqual(self.browser.eval(self.CHIPS), [['כמו בקליטה טובה', 'true'], ['מוקטנות בקליטה איטית', 'false']])

    def test_the_chips_say_what_they_choose_to_a_screen_reader(self):
        """The section "תמונות וסרטונים" has two rows of pressed / not pressed buttons. The second row's
        "בגודל מלא" and "מוקטנות בקליטה איטית" are tied to "תמונות שאתה שולח:" only by sitting after it: moving
        by Tab (or the screen reader's list of buttons) he hears "בגודל מלא, pressed" and not of what. Safe: the
        row is a group whose accessible name says it is the pictures he sends, or each chip's name says so."""
        self.start('e2e-own-a11y', 'נגישות', media='tap')
        self.browser.eval('(()=>{openNotify();return "ok";})()')
        self.browser.wait('JSON.stringify(!!document.querySelector("#notify-body .own-full"))', timeout=10, what='the setting')
        named = self.browser.eval(r'''(()=>{
          const g=document.querySelector("#notify-body .own-full"),label=n=>(n.getAttribute("aria-label")||"")+" "+
            (n.getAttribute("aria-labelledby")||"").split(/\s+/).filter(Boolean).map(id=>(document.getElementById(id)||{}).textContent||"").join(" ");
          const group=g.getAttribute("role")==="group"&&/תמונות/.test(label(g));
          const each=[...g.querySelectorAll("button")].every(b=>/תמונות/.test(label(b)+" "+(b.title||"")));
          return JSON.stringify(group||each);})()''')
        self.assertTrue(named)

    # ── pinned ─────────────────────────────────────────────────────────────

    def test_every_way_in_uses_his_choice(self):
        """Pinned (passes): a paste into the box, a drop on the page and the gallery button all go through
        addPictures and shrink(), which reads the choice at that moment: with own-full 'on' under "always tap", a
        1500 px picture keeps its 1500 px by each of them; with it unset under "always tap", 1280."""
        self.start('e2e-own-ways', 'כל הדרכים', media='tap', own='on')
        make = ('(async()=>{const c=document.createElement("canvas");c.width=1500;c.height=1000;const x=c.getContext("2d");x.fillStyle="#357";x.fillRect(0,0,1500,1000);'
                'x.fillStyle="#fa0";x.fillRect(%d,10,200,200);const b=await new Promise(d=>c.toBlob(d,"image/png"));const f=new File([b],"s.png",{type:"image/png"});'
                'const dt=new DataTransfer();dt.items.add(f);%s;return "ok";})()')
        paste = 'input.focus();input.dispatchEvent(new ClipboardEvent("paste",{clipboardData:dt,bubbles:true,cancelable:true}))'
        drop = ('document.querySelector("#log").dispatchEvent(new DragEvent("dragenter",{dataTransfer:dt,bubbles:true,cancelable:true}));'
                'document.querySelector("#log").dispatchEvent(new DragEvent("drop",{dataTransfer:dt,bubbles:true,cancelable:true}))')
        self.browser.eval(make % (10, paste))
        self.assertEqual(self.tray_is(1), [1500])
        self.browser.eval(make % (400, drop))
        self.assertEqual(self.tray_is(2), [1500, 1500])
        self.browser.upload('#pic-file', self.picture('ways.png', 1500, 1000))
        self.assertEqual(self.tray_is(3), [1500, 1500, 1500])
        self.browser.eval('(()=>{pictures.delete(view.ch);renderTray();localStorage.removeItem(%s);return "ok";})()' % self.KEY('own-full'))
        self.browser.eval(make % (700, paste))
        self.assertEqual(self.tray_is(1), [1280])


# The scenarios of test_e2e.Suda belong to that file; here the class only lends its server, board and browser.
for _name in dir(test_e2e.Suda):
    if _name.startswith('test') and _name not in OwnFull.__dict__:
        setattr(OwnFull, _name, None)


if __name__ == '__main__':
    unittest.main()
