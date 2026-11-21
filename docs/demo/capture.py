#!/usr/bin/env python3
"""The README's GIFs and stills, taken from the demo board only (docs/demo/demo.py; invented content).

    python3 docs/demo/demo.py --keep /tmp/suda-demo &        # prints the address
    python3 docs/demo/capture.py http://127.0.0.1:PORT/readme-demo/suda.html

Needs agent-browser (headless Chrome) and ffmpeg. Frames go to docs/demo/out/ (ignored by git); the GIFs to
docs/assets/. Each GIF is a few frames at the page's own size, one palette for the whole GIF, so it stays crisp
and small. The stills (docs/assets/show-*.png) are one thread each on a phone-sized window, 420 by 600.

    python3 docs/demo/capture.py URL            # everything
    python3 docs/demo/capture.py URL --stills   # only the show-*.png
    python3 docs/demo/capture.py URL --hero     # only the banner and the brand sheet, docs/assets/hero.png and brand.png
    python3 docs/demo/capture.py URL --scroll   # only the site's scroll story, docs/assets/scroll-1.png to 5
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/demo/out'
ASSETS = ROOT / 'docs/assets'
SESSION = 'suda-readme'
HOLD = 1.6                  # seconds a frame stays


def ab(*args, ok=True):
    r = subprocess.run(['agent-browser', '--session', SESSION, *args], capture_output=True, text=True, timeout=90)
    if ok and r.returncode != 0:
        sys.exit('agent-browser ' + ' '.join(args[:2]) + ': ' + (r.stderr or r.stdout).strip()[-300:])
    return r.stdout.strip()


def js(code):
    return ab('eval', code)


def gif(name, frames, holds=None):
    """frames: PNG paths; holds: how many HOLDs each frame stays (default 1)."""
    holds = holds or [1] * len(frames)
    listing = OUT / f'{name}.txt'
    listing.write_text(''.join(f"file '{f}'\nduration {HOLD * h}\n" for f, h in zip(frames, holds)) + f"file '{frames[-1]}'\n")
    target = ASSETS / f'{name}.gif'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-vf',
                    'split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];[b][p]paletteuse=dither=none',
                    '-loop', '0', str(target)], check=True)
    size = target.stat().st_size
    print(f'{target.relative_to(ROOT)}: {len(frames)} frames, {size / 1e6:.2f} MB')
    if size > 3_000_000:
        sys.exit(f'{target.name} is over 3 MB')


class Shots:
    def __init__(self, name):
        self.name, self.frames = name, []

    def __call__(self, wait=0.8):
        time.sleep(wait)
        path = OUT / f'{self.name}-{len(self.frames):02d}.png'
        ab('screenshot', str(path))
        self.frames.append(path)
        return path


def open_at(url, w, h, where=''):
    ab('set', 'viewport', str(w), str(h))
    ab('open', url + where)
    time.sleep(1.5)
    js('(()=>{try{localStorage.setItem("suda-theme","light")}catch(e){};return "ok"})()')      # one theme for every GIF
    ab('open', 'about:blank')
    ab('open', url + where)
    time.sleep(2.5)


def click_text(selector, text):
    js('(()=>{const b=[...document.querySelectorAll(%s)].find(x=>x.textContent.includes(%s)&&x.offsetParent);if(b)b.click();return String(!!b);})()'
       % (json.dumps(selector), json.dumps(text)))


def still(url, name, tid, prep=None, wait=1.2):
    """One thread on a phone-sized window, as the README shows it: docs/assets/show-<name>.png."""
    open_at(url, 420, 600, '#' + tid)
    if prep:
        js(prep)
    time.sleep(wait)
    target = ASSETS / f'show-{name}.png'
    ab('screenshot', str(target))
    print(f'{target.relative_to(ROOT)}: {target.stat().st_size / 1e3:.0f} KB')


# Bring a part of the open thread into sight (its top just under the head), or the end of the conversation.
SHOW = '(()=>{const e=document.querySelector(%s);if(e)e.scrollIntoView({block:"start"});return String(!!e)})()'
END = '(()=>{const l=document.querySelector("#log");if(l)l.scrollTop=l.scrollHeight;return "ok"})()'


def stills(url):
    still(url, 'diagram', 'demo-refund', SHOW % json.dumps('#log .msg:last-of-type'))
    still(url, 'diff', 'demo-review', SHOW % json.dumps('#log .msg:last-of-type'))
    still(url, 'chart', 'demo-costs')
    still(url, 'page', 'demo-pricing', wait=2.0)
    still(url, 'widget', 'demo-sim', SHOW % json.dumps('#log .msg:last-of-type'))
    still(url, 'status', 'demo-rollout', SHOW % json.dumps('#log .msg'))
    # the question's form, opened from its strip
    still(url, 'ticks', 'demo-rollout', '(()=>{const b=[...document.querySelectorAll("button")].find(x=>x.offsetParent&&/Pick from the list/.test(x.textContent));if(b)b.click();return String(!!b)})()')
    still(url, 'quote', 'demo-nightly', END)


def hero(url):
    """The banner: a desktop and a phone screenshot of the demo board, set in docs/demo/hero.html."""
    open_at(url, 1280, 800, '#demo-release')
    time.sleep(1.0)
    ab('screenshot', str(OUT / 'hero-desk.png'))
    open_at(url, 390, 844)
    time.sleep(1.0)
    ab('screenshot', str(OUT / 'hero-phone.png'))
    ab('set', 'viewport', '1280', '600')
    ab('open', (ROOT / 'docs/demo/hero.html').as_uri())
    time.sleep(1.5)
    target = ASSETS / 'hero.png'
    ab('screenshot', str(target))
    print(f'{target.relative_to(ROOT)}: {target.stat().st_size / 1e3:.0f} KB')
    # the brand sheet (docs/demo/brand.html): the mark, the palette, the type
    ab('set', 'viewport', '1280', '580')
    ab('open', (ROOT / 'docs/demo/brand.html').as_uri())
    time.sleep(1.0)
    target = ASSETS / 'brand.png'
    ab('screenshot', str(target))
    print(f'{target.relative_to(ROOT)}: {target.stat().st_size / 1e3:.0f} KB')


def scroll_screens(url):
    """The site's scroll story (docs/index.html): one phone screen per mode of Suda, docs/assets/scroll-1.png to 5."""
    def shot(n, where='', prep=None, wait=1.2):
        open_at(url, 390, 844, where)
        if prep:
            js(prep)
        time.sleep(wait)
        target = ASSETS / f'scroll-{n}.png'
        ab('screenshot', str(target))
        print(f'{target.relative_to(ROOT)}: {target.stat().st_size / 1e3:.0f} KB')
    shot(1)                                                     # the list, by whose turn it is
    shot(2, '#demo-release', '(()=>{scroller.scrollTop=0;return "ok"})()')    # a thread: its tasks, a table, a question
    # one tap, four seconds to undo: the same place in the thread as screen 2 (so one fades into the other), and the
    # tap is taken back after the picture, so the demo board keeps its question
    shot(3, '#demo-release', '(()=>{scroller.scrollTop=0;const b=[...document.querySelectorAll("button")].find(x=>x.offsetParent&&/Ship behind a flag/.test(x.textContent));if(b)b.click();setTimeout(()=>{scroller.scrollTop=0;},250);return String(!!b)})()', 0.8)
    js('(()=>{const u=[...document.querySelectorAll(".toast button, .toast a")].find(x=>/Undo/.test(x.textContent));if(u)u.click();return String(!!u)})()')
    shot(4, '#demo-migration', SHOW % json.dumps('#log .msg'))  # an agent at work: a live status card, nothing on you
    shot(5, '#demo-costs')                                      # done: the answer, as a chart


def main():
    if len(sys.argv) not in (2, 3) or '/readme-demo/' not in sys.argv[1] or sys.argv[2:] not in ([], ['--stills'], ['--hero'], ['--scroll']):
        sys.exit(__doc__)
    url = sys.argv[1].split('#')[0]
    for tool in ('agent-browser', 'ffmpeg'):
        if not shutil.which(tool):
            sys.exit(tool + ' is not installed')
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    if sys.argv[2:] in (['--stills'], ['--hero'], ['--scroll']):
        {'--stills': stills, '--hero': hero, '--scroll': scroll_screens}[sys.argv[2]](url)
        ab('close', ok=False)
        return

    # 1. the desktop: one thread after another (tasks, a question, a table; a run block; a diagram; a log; Hebrew)
    s = Shots('desktop')
    open_at(url, 1280, 800, '#demo-release'); s()
    for tid in ('demo-deploy', 'demo-architecture', 'demo-nightly', 'demo-ticket-1042'):
        js('(()=>{openChannel(%s);return "ok"})()' % json.dumps(tid)); s(1.5)
    gif('desktop', s.frames, [2, 1, 2, 1, 1])

    # 2. an answer button: one press, four seconds to take it back, then sent
    s = Shots('answer')
    open_at(url, 1280, 800, '#demo-release'); s()
    click_text('#pinned button, .pin button, .q-strip button, button', 'Ship behind a flag'); s(0.4)
    s(1.6)
    s(3.2)
    gif('answer', s.frames, [2, 1, 1, 2])

    # 3. a run block: the tower's command, approved with one press after reading it whole
    s = Shots('run')
    open_at(url, 1280, 800, '#demo-deploy'); s()
    js('(()=>{const b=document.querySelector("#log button.run");if(b)b.click();return String(!!b)})()'); s(1.0)
    gif('run', s.frames, [2, 3])

    # 4. Cmd+K: every thread and every command, one search
    s = Shots('palette')
    open_at(url, 1280, 800, '#demo-release'); s()
    ab('press', 'Meta+KeyK'); s(0.6)
    ab('type', '#sw-query', 'deploy'); s(0.8)
    ab('press', 'Enter'); s(1.5)
    gif('palette', s.frames, [1, 1, 2, 2])

    # 5. the phone's cover screen (narrow): the list, a thread, its tasks, back
    s = Shots('phone-cover')
    open_at(url, 360, 840); s()
    js('(()=>{openChannel("demo-release");return "ok"})()'); s(1.5)
    js('(()=>{const b=document.querySelector("#tasks-toggle");if(b)b.click();return String(!!b)})()'); s(1.0)
    js('(()=>{openChannel("demo-architecture");return "ok"})()'); s(2.0)
    gif('phone-cover', s.frames, [2, 2, 2, 2])

    # 6. the phone's inner screen (wide): the list beside the conversation
    s = Shots('phone-inner')
    open_at(url, 750, 835, '#demo-release'); s()
    js('(()=>{openChannel("demo-ticket-1042");return "ok"})()'); s(1.5)
    gif('phone-inner', s.frames, [2, 2])

    # 7. the stills: what an agent can show in a thread; 8. the banner
    stills(url)
    hero(url)
    ab('close', ok=False)


if __name__ == '__main__':
    main()
