#!/usr/bin/env python3
"""Persistent topic threads for the existing interview-board server."""
import argparse
import array
import base64
import bisect
import contextlib
import datetime
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import struct
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib

# Import the shared library without creating bytecode outside this repository.
sys.dont_write_bytecode = True
REPO = Path(os.path.realpath(__file__)).parent
sys.path.insert(0, os.environ.get('THREADS_BOARDLIB_DIR', str(Path.home() / '.claude/skills/html-interview-board')))
sys.path.insert(1, str(REPO))
try:
    import boardlib as bl           # the html-interview-board skill, when it is installed
except ImportError:
    import suda_boardlib as bl      # else Suda's own copy of the few helpers it needs (a fresh clone)
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('suda_store', REPO / 'store.py')
suda_store = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(suda_store)

VERSION = 3                       # 3: the human's id is 'owner' (was his name); see migrate_owner
ID = r'[a-z0-9][a-z0-9-]{0,47}'      # a thread id is also a folder name: nothing else may ever be one
SLUG = os.environ.get('THREADS_SLUG') or 'threads'
if not re.fullmatch(ID, SLUG):
    sys.exit('THREADS_SLUG is not valid')        # (before any config can be read: English only)
BOARD = bl.BOARDS_DIR / SLUG
STATE = BOARD / 'state.json'
DRAFTS = BOARD / 'drafts.json'    # what he typed and did not send: beside the state, never inside it
LINKS = BOARD / 'links.json'      # what is known of the pull requests that messages point at (their state, CI, review): for the chips
LIVE = BOARD / 'live.json'        # what every agent does right now (live_hook.py writes it; the page reads it): the live dot
PLACES = BOARD / 'places.json'    # where he was in each thread (the message at the top of his screen), for his other devices
# What a page opens with, written beside state.json at every save (see `lite`): the state without the conversations,
# and each thread's whole conversation in a file of its own. state.json itself stays whole, for everything else.
SUMMARY = BOARD / 'summary.json'
FULL = BOARD / 'full'
# Every save that changes what a page shows gets a new number (`seq`, kept in the state, the summary and the pulse):
# above every number before it and never below the clock in milliseconds, so a board put back from a backup never
# gives a number a page holds to other content. changes.json holds the last changes, each as what it did to the
# summary and the number it starts from (`from`), so a page that is a few changes behind reads them instead of the
# whole summary; changes/<from>.json holds each one alone, for a page one or two behind. summary.json starts with
# {"seq":N,"mark":"<mark of its content>"}: a page reads those first bytes to know that the summary under its number
# is still the one it holds (a writer that does not number, an older threads.py, keeps the number and leaves no mark).
CHANGES = BOARD / 'changes.json'
CHANGE_FILES = BOARD / 'changes'
CHANGES_MAX, CHANGES_BYTES = 200, 256 * 1024
CHANGES_FAN = 6                   # changes/<n>.json of the last 6 numbers holds every change from n to the board's number
PULSE = BOARD / '.pulse'
# The highest number this board ever gave, beside the board's folder (not in it): a folder put back from a backup
# forgets the numbers it gave since, and a clock that ran ahead and was set back may not be above them.
HIGH = bl.BOARDS_DIR / ('.' + SLUG.replace('/', '--') + '.seq')
TAIL = 4                          # how many of an open thread's last messages the summary carries whole
# The board's truth is SQLite since sqlite177 (suda-connectivity task 16): suda.db beside the files a page reads.
# THREADS_STORE=file keeps the old way (state.json, rewritten whole at every save). state.json is then only an
# import (a board from before, a test's fixture: a state.json newer than the last import is taken in) and an
# export (after every save on his real board until public182, and with THREADS_EXPORT_STATE=1; `threads export-state` once).
STORE_PATH = BOARD / 'suda.db'
STORE_KIND = os.environ.get('THREADS_STORE') or 'sqlite'
HOT_DAYS = float(os.environ.get('THREADS_HOT_DAYS') or 7)      # a closed thread stays in the summary this long
CHANGES_KEEP_DAYS = 30            # the store keeps every change this long: a page this far behind still catches up by them

# The human (the owner of this installation) has one id on the wire and in the state, whoever he is. An installation
# may accept its own names for him as input (config.json "owner_aliases", e.g. an id it used before): every input
# maps an alias to OWNER and 'on-<alias>' to ON_OWNER (see as_owner). 'human' and 'me' are aliases everywhere.
OWNER = 'owner'
ON_OWNER = 'on-' + OWNER
OWNER_ALIASES = ('human', 'me')
OWNER_NAME = 'the owner'            # how a message of the CLI names him when config.json has no "owner_name" (through tr)
STATES = (ON_OWNER, 'working', 'done')
AGENTS = ('tower', 'fork')
TOWER_THREAD = 'tower'            # the tower's own thread: it is never merged away, and always in the main space
SPACES_MAX = 8                    # spaces are few (thread suda m380: "without making a mess"); the main one is not counted
SPACE_NAME_MAX = 40
MAIN_COLOR = '#6b3fa0'            # the main space's square (the page draws it the same)
SPACE_COLORS = ('#c2681c', '#2f73c9', '#2f9467', '#b3184d', '#7d5a2b', '#8a5a09', '#0a6b8a', '#5c6470')
PAGE_OPS = ('reply', 'close', 'reopen', 'keep', 'done', 'sweep', 'rename', 'task', 'react', 'snooze', 'unsnooze', 'draft',
            'new', 'seen', 'mute', 'quiet', 'push-subscribe', 'push-unsubscribe', 'place', 'task-archive', 'link-meta', 'presence',
            'nudge', 'merge', 'space-move', 'space-new', 'urgent', 'snippet-part', 'task-add', 'task-text', 'save')
BOARD_OPS = ('sweep', 'new', 'quiet', 'push-subscribe', 'push-unsubscribe', 'presence', 'nudge', 'space-new')     # ops of the whole board: they name no thread
PAGE_FLAGS = ('images', 'run', 'quote', 'split', 'snippet-parts', 'command')   # listed with the ops: what a reply may carry ('voice' joins them when this machine can transcribe)
TASK_STATES = ('todo', 'working', 'building', 'done', 'blocked', ON_OWNER)
TASK_HISTORY_MAX = 20           # the old words of a task kept (each correction adds one)
TASK_EVENTS_MAX = 60            # the events a task keeps: its first one and the newest (suda-fixes task 34, m151/m153)
TASK_EVENT_TEXT_MAX = 200       # the words of a task as an event carries them (before and after a correction)
REACTIONS = ('👍', '✅', '❓')
# What he may ask the agents from the reply box (slash commands, suda m555, m637): a reply whose text is the command
# line carries `command: {name, args}`, so the tower acts on the name and not on his wording (he may type the
# command's Hebrew name). The kind says what may follow the name: free words, nothing, or a title.
# (The page's own actions, /done, /s, /task ..., are page ops of their own and never reach here.)
AGENT_COMMANDS = {'status': 'words', 'explain': 'words', 'review': 'words', 'draft': 'words', 'install': 'words',
                  'run': 'none', 'prs': 'none', 'split': 'title'}
COMMAND_ARGS_MAX = 300
# What install publishes beside the state, when the file exists here: the front ends and what they load.
PAGES = ('slack.html', 'suda.html', 'diagram.html', 'sw.js', 'manifest.json', 'favicon.ico')
# The old board page (board.html) is gone; suda.html is the page (suda m620). Old links point at
# .../board.html#<id>, so an installation that still has one gets this page in its place: it moves on to suda.html
# with the same address after the name (the thread's #id, any ?query). A new installation never gets a board.html.
OLD_BOARD_PAGE = 'board.html'
OLD_BOARD_REDIRECT = '''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Suda</title>
<script>location.replace('suda.html'+location.search+location.hash);</script>
</head>
<body>
<p><a id="go" href="suda.html">suda.html</a></p>
<script>document.getElementById('go').href='suda.html'+location.search+location.hash;</script>
</body>
</html>
'''
PAGE_DIRS = ('icons', 'vendor')
# Hours. Stored in state.json (`threads policy`), so the numbers are data.
POLICY = {'idle_hours': 12.0, 'grace_hours': 12.0, 'resolved_hours': 2.0, 'slot_cooldown_hours': 6.0,
          'task_archive_hours': 12.0}     # a task that has been done this long moves to the thread's archive of tasks (0: never by itself)
NOTE_MAX = 200
TEXT_MAX = 50_000      # an agent's message; details belong in a file with a link
LIMITS = {'title': 200, 'summary': 300, 'context': 20_000, 'by': 60, 'owner': 60, 'task': 300}
# Long text (a log, a transcript, an email) is a snippet: its own file beside the state, a short preview in the message.
INLINE_MAX = 4000           # what the owner writes beyond this is kept as a snippet
SNIPPET_MAX = 20_000_000    # UTF-8 bytes (a big-file thread, m6: a 7 MB crash report)
# The board server caps a request at 4 MB: a bigger text comes from the page in parts (op snippet-part), each of up
# to PART_MAX bytes, kept outside the served folder until the reply that names them joins them (or PARTS_KEEP passes).
PART_MAX, PARTS_MAX, PARTS_KEEP = 1_500_000, 100, 6 * 3600
PARTS_PLACES = 8            # big texts on their way at once (each up to SNIPPET_MAX): the disk is never filled by parts
SNIPPET_TYPES = ('.txt', '.md', '.log')
IMAGES_MAX, IMAGE_MAX, CAPTION_MAX = 4, 2_000_000, 500      # pictures of one message; bytes of one picture
VIDEOS_MAX, VIDEO_MAX = 2, 100_000_000      # videos of one message (mp4, webm); bytes of one video
HTML_MAX = 500_000          # an agent's page, shown in a sandboxed frame
VOICE_MAX, VOICE_SECONDS = 3_000_000, 900       # a voice message: bytes, and how long it may claim to be
VOICE_MODEL = os.environ.get('THREADS_SONIOX_MODEL') or 'stt-async-v6'
STALE_TASK = 2 * 3600       # an agent is reminded of a task it left "working" this long
OPEN_MAX = 60               # open threads a page may create up to
QUESTIONS_MAX = 5           # open questions in one thread (suda m508): more is a list, not a question
VOICING_MAX = 3             # recordings being transcribed at one time, on the whole board
RESERVED = ('constructor',)  # an id that a page's plain object already has a member for
# Notifications (`threads notify`), stored in state.json. The phone fallback is off until someone turns it on:
# a test board or a staging board must never reach his phone.
# His phone hears of a thing at once when no page has his eyes; while one has, it waits `fallback_minutes`.
# A page in front that nobody touched for `idle_minutes` is a window before an empty chair, not him.
NOTIFY = {'fallback_minutes': 15, 'idle_minutes': 2, 'snap': False, 'quiet': None, 'url': ''}
PRESENCE_STALE = 45         # seconds: a page that reported his focus and then said nothing for this long does not have it
PRESENCE_MAX = 20           # pages remembered at one time; the oldest goes
PAGE_ID = r'[A-Za-z0-9_-]{6,40}'    # the name a page gives itself when it loads (one per tab)
PANE_ID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{8,40}'     # a tuios pane
NUDGE_GAP = {'continue': 15, 'open': 4}     # seconds before the same press may reach the same agent again
RING_GAP = 60               # seconds between two phone alerts of one thread: two messages in a row are one ring, then another
PUSH_HOSTS = ('fcm.googleapis.com', '.push.services.mozilla.com', '.notify.windows.com', '.push.apple.com')
THREAD_DEFAULTS = (('slot', None), ('summary', ''), ('links', None), ('state', ON_OWNER), ('note', ''),
                   ('state_ts', None), ('state_by', ''), ('auto', True), ('question', None),
                   ('resolved', False), ('touched', None), ('soon_at', None), ('archive_at', None), ('tasks', None))
SAW_IT = object()     # the caller vouches that the owner answered the question that is open
UNKNOWN = object()    # an older page: it does not say which question was on his screen
migrated_from = None  # version of the file on disk when load() had to upgrade it
pending_import = False  # load() read state.json: the next save makes the store from it (sqlite177)
mended = False        # load() gave a slot to an open thread that had none of its own
out = []              # what the command prints: written after the lock is released and the state is saved
after_save = []       # what must happen only once the new state is on disk
waking = []           # mail to the tower that belongs to a change not saved yet: (text, tag, thread, kind)
mails = []            # mail to send once the command is over and the lock released
written = []          # files this command put beside the state before saving it: removed again when it fails
noting = {'push': False, 'phone': [], 'voice': [], 'at': None, 'links': []}     # who must be told and what must be transcribed, found while the state is in hand
telling = {'push': False, 'phone': [], 'voice': [], 'at': None, 'links': []}    # the same, once that state is on disk
errs = []             # lines for stderr that are advice, not failure
tidied = []           # threads in which the sweep moved finished tasks to the archive: a change to save, news to nobody


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A request to an outside service carries a credential meant for that host. An answer that points
    elsewhere is an answer (its status), never a second request."""
    def redirect_request(self, *args, **kwargs):
        return None


OUTSIDE = urllib.request.build_opener(NoRedirect)


class Refused(ValueError):
    """A refusal that tells the page something more than the reason."""
    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


def now():
    """Wall clock. THREADS_NOW pins it, for tests."""
    fixed = os.environ.get('THREADS_NOW')
    return float(fixed) if fixed else time.time()


def emit(value):
    out.append(json.dumps(value, ensure_ascii=False))


def one_line(text):
    return ' '.join(str(text).split())


def blank(text):
    """Nothing a person can see: empty, spaces, control or zero-width characters only."""
    return not any(unicodedata.category(ch)[0] not in 'CZ' for ch in text or '')


def short(text, field):
    """A header field as one line within its limit."""
    text = one_line(text)
    if len(text) > LIMITS[field]:
        raise ValueError(tr('--{field} is too long: up to {max} characters', field=field, max=LIMITS[field]))
    return text


def preview(text, limit):
    """A message as one plain line: markdown marks dropped, cut to `limit`."""
    flat = one_line(re.sub(r'```[^\n]*|\*\*|`', '', text))
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + '…'


# ── state file ──────────────────────────────────────────────────────────────

def load():
    """The board as the commands use it: {top-level keys..., 'threads': {id: thread}}. From the store (its hot
    threads; a cold one is read when a command names it), after taking in a state.json that is newer than it."""
    global pending_import
    pending_import = False
    if STORE_KIND == 'file':
        return load_file()
    # No store yet (a board from before it, a new board), or a state.json to take in: the board as state.json holds
    # it, and the store is made by the first save of this command, never by a command that saves nothing or fails
    if not STORE_PATH.exists() or needs_import(store()):
        pending_import = True
        return load_file()
    return load_store(store())


def load_file():
    try:
        data = json.loads(STATE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version': VERSION, 'policy': dict(POLICY), 'notify': dict(NOTIFY), 'threads': {}}
    return prepare(data)


def prepare(data):
    global migrated_from, mended
    check(data)
    version = data.get('version', 1)
    if version > VERSION:
        raise ValueError(tr('state.json was written by a newer version of threads'))
    data['policy'] = {**POLICY, **data.get('policy', {})}
    data['notify'] = {**NOTIFY, **data.get('notify', {})}
    if version < VERSION:
        migrated_from = version
        data['version'] = VERSION
    # Version 3 renames his id (with the backup of an upgrade). On a newer file the same walk mends what an older
    # client (a rollback) wrote under an alias since, or what an alias configured after the upgrade names.
    renamed = migrate_owner(data)
    # A record without a state was written by the older version (the upgrade itself, or its CLI on a
    # new file): its state is derived. Records that have one are never re-derived.
    old = [t for t in data['threads'].values() if 'state' not in t]
    for t in data['threads'].values():
        fill(t)
    for t in old:
        derive(t)
    mended = heal(data, now()) or bool(old) or (bool(renamed) and version >= 3)
    return data


def migrate_owner(data):
    """Version 3: the owner's id was his name. Every field that holds the id of a person (never the words of a
    message, a title, a note, a question or an option) and says one of his aliases now says OWNER, and a state
    'on-<alias>' says ON_OWNER. The aliases are this installation's (config.json "owner_aliases") and 'human'
    and 'me': without the config an old name stays as it was (read as some agent's), and nothing breaks.
    load() runs it on every file: a second run finds nothing. Returns how many values changed."""
    conf = config().get('owner_aliases')
    aliases = {*OWNER_ALIASES, *(x for x in conf if isinstance(x, str) and x)} if isinstance(conf, list) else set(OWNER_ALIASES)
    aliases -= {OWNER, 'system', 'auto', 'agent', *AGENTS}
    states = {'on-' + alias for alias in aliases}
    changed = 0

    def fix(record, *keys, state=False):
        nonlocal changed
        if not isinstance(record, dict):
            return
        for key in keys:
            value = record.get(key)
            if isinstance(value, str) and (value in aliases or (state and value in states)):
                record[key] = OWNER if value in aliases else ON_OWNER
                changed += 1

    for t in data['threads'].values():
        fix(t, 'state_by', 'opened_by', 'closed_by')
        fix(t, 'state', state=True)
        fix(t.get('split_from'), 'from')
        for q in [t.get('question')] + (t['questions'] if isinstance(t.get('questions'), list) else []):
            fix(q, 'from')
        for m in t['messages']:
            fix(m, 'from')
            fix(m.get('reply_to'), 'from')
            fix(m.get('merge'), 'by')
            for mark in (m['reactions'].values() if isinstance(m.get('reactions'), dict) else ()):
                fix(mark, 'by')
        for k in t.get('tasks') if isinstance(t.get('tasks'), list) else ():
            fix(k, 'owner', 'by')
            fix(k, 'status', state=True)
            for old in k['history'] if isinstance(k.get('history'), list) else ():
                fix(old, 'by')
            for e in k['events'] if isinstance(k.get('events'), list) else ():     # its history (a text event's words stay)
                fix(e, 'by')
                if isinstance(e, dict) and e.get('kind') == 'status':
                    fix(e, 'from', 'to', state=True)
                elif isinstance(e, dict) and e.get('kind') == 'owner':
                    fix(e, 'from', 'to')
    return changed


def number(value):
    return type(value) in (int, float)


def check(data):
    """Refuse a damaged file before anything is derived from it or written over it."""
    def damaged(what):
        return ValueError(tr('state.json is damaged ({what}); I did not touch it', what=what))
    if not isinstance(data, dict) or type(data.get('version', 1)) is not int or data.get('version', 1) < 1:
        raise damaged(tr('the structure or version'))
    threads, policy, freed = data.get('threads'), data.get('policy', {}), data.get('freed', {})
    if not isinstance(threads, dict) or not isinstance(data.get('retired', {}), dict):
        raise damaged('threads')
    if not isinstance(data.get('retired_tasks', {}), dict) or not all(type(v) is int for v in data.get('retired_tasks', {}).values()):
        raise damaged('retired_tasks')
    notify = data.get('notify', {})
    if not (isinstance(notify, dict) and number(notify.get('fallback_minutes', 1)) and isinstance(notify.get('url', ''), str)
            and number(notify.get('idle_minutes', 1)) and notify.get('idle_minutes', 1) > 0
            and (notify.get('quiet') is None or is_quiet(notify['quiet']))):
        raise damaged('notify')
    if not isinstance(freed, dict) or not all(number(v) for v in freed.values()):
        raise damaged('freed')
    spaces = data.get('spaces', [])
    if not (isinstance(spaces, list) and all(isinstance(sp, dict) and isinstance(sp.get('id'), str) and re.fullmatch(ID, sp['id']) and sp['id'] != 'main'
                                              and isinstance(sp.get('name'), str) and isinstance(sp.get('prefix', []), list)
                                              and all(isinstance(x, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}', x) for x in sp.get('prefix', []))
                                              and (sp.get('color') is None or isinstance(sp['color'], str) and re.fullmatch(r'#[0-9a-fA-F]{6}', sp['color']))
                                              and (sp.get('letter') is None or isinstance(sp['letter'], str))
                                              for sp in spaces)
            and len({sp['id'] for sp in spaces}) == len(spaces)):
        raise damaged('spaces')
    if not isinstance(policy, dict) or not all(number(v) and v >= 0 for v in policy.values()):
        raise damaged('policy')
    for tid, t in threads.items():
        check_thread(tid, t)



def check_thread(tid, t):
    """Refuse a damaged thread record (the same rules as the whole file's)."""
    def damaged(what):
        return ValueError(tr('state.json is damaged ({what}); I did not touch it', what=what))
    question = t.get('question') if isinstance(t, dict) else None
    # The id names folders (snippets/<id>, uploads/<id>): one that `threads new` would refuse is never trusted.
    if not (isinstance(tid, str) and re.fullmatch(ID, tid) and isinstance(t, dict) and t.get('id') == tid and isinstance(t.get('title'), str)
            and isinstance(t.get('context'), str) and isinstance(t.get('status'), str)
            and number(t.get('created')) and number(t.get('updated')) and type(t.get('next')) is int
            and isinstance(t.get('messages'), list) and isinstance(t.get('links', []), list)
            and isinstance(t.get('tasks', []), list) and all(isinstance(k, dict) and type(k.get('n')) is int for k in t.get('tasks', []))
            and (t.get('snooze') is None or isinstance(t['snooze'], dict) and number(t['snooze'].get('until')))
            and (t.get('alert') is None or isinstance(t['alert'], dict)) and (t.get('seen') is None or isinstance(t['seen'], dict))
            and all(isinstance(m, dict) and isinstance(m.get('id'), str) and isinstance(m.get('from'), str)
                    and isinstance(m.get('text'), str) and number(m.get('ts')) for m in t['messages'])
            and (t.get('merged_into') is None or isinstance(t['merged_into'], str) and re.fullmatch(ID, t['merged_into']))
            and (t.get('merged_from') is None or isinstance(t['merged_from'], list) and all(isinstance(x, str) for x in t['merged_from']))
            and (question is None or a_question(question))
            and (t.get('questions') is None or isinstance(t['questions'], list) and all(a_question(q) for q in t['questions']))):
        raise damaged(tr('thread {id}', id=tid))


def a_question(q):
    return isinstance(q, dict) and isinstance(q.get('id'), str) and isinstance(q.get('text'), str) and isinstance(q.get('options'), list)


def mark_of(value):
    """A short mark of a message (or of a thread's list of marks) as it stands: another content, another mark."""
    return '%08x' % zlib.crc32(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))


SAVED_PREVIEW = 160        # the start of a saved message's words, in its stamp: what the list of saved messages shows


def saved_rows(data, tower=False):
    """The messages he saved, in every thread (open, closed or merged), the last saved first. A ▶ request he saved
    while the tower has not picked it up is the tower's alone, as in `pending` (runrole161): anyone else does not see it."""
    rows = []
    for tid, t in all_threads(data).items():         # (a thread closed long ago is cold: it is read for this)
        for m in t['messages']:
            if number(m.get('saved')) and (tower or not run_request(m)):
                rows.append({'thread': tid, 'title': t['title'], 'status': t['status'], 'msg': m['id'], 'from': m['from'],
                             'ts': m['ts'], 'saved': m['saved'], 'text': m.get('text') or ''})
    return sorted(rows, key=lambda r: -r['saved'])


def saved_page(threads):
    """The list of saved messages the page shows ('Saved'), from these (id, thread) pairs: all of them (the page is
    his), each with the start of its words. In the summary's top, so a thread closed long ago (cold: no row there)
    keeps its saved messages in the list."""
    rows = []
    for tid, t in threads:
        for m in t['messages']:
            if number(m.get('saved')):
                rows.append({'thread': tid, 'title': t['title'], 'msg': m['id'], 'from': m['from'], 'ts': m['ts'],
                             'saved': m['saved'], 'text': preview(m.get('text') or '', SAVED_PREVIEW)})
    return rows


def lite(data):
    """The state in the two cuts a page opens with, so that it need not read every conversation to show the
    list and one thread. The summary is the state without the conversations: of every message only a stamp
    [id, sender, time, mark], and of an open thread its last few messages whole. Beside it, each thread's whole
    conversation. A whole message carries its mark as `v` in both, so a page can tell which of the messages it
    already holds still stand, and reads a conversation again only when one of them does not.
    Returns (the summary, {thread id: its whole conversation})."""
    summary, whole = {key: value for key, value in data.items() if key != 'threads'}, {}
    summary['lite'] = 1
    summary['saved'] = sorted(saved_page(data['threads'].items()), key=lambda r: -r['saved'])
    summary['threads'] = {}
    for tid, t in data['threads'].items():
        summary['threads'][tid], whole[tid] = lite_thread(t)
    return summary, whole


def lite_thread(t):
    """One thread's row in the summary, and its whole conversation record (full/<id>.json)."""
    tid = t['id']
    messages = [{**m, 'v': mark_of(m)} for m in t['messages']]
    stamps = [[m['id'], m['from'], m['ts'], m['v']] + ([m['saved'], preview(m.get('text') or '', SAVED_PREVIEW)] if number(m.get('saved')) else [])
              for m in messages]      # a saved message's stamp: when, and its first words (saved179)
    rev = mark_of(stamps)
    # a task's history (suda-fixes task 34): the summary carries only its last event, the thread's file all of them
    events = {str(k['n']): task_events(k) for k in t['tasks']}
    trev = mark_of(events)
    tasks = [{**{key: value for key, value in k.items() if key != 'events'}, 'last': (events[str(k['n'])] or [None])[-1]}
             for k in t['tasks']]
    row = {**{key: value for key, value in t.items() if key not in ('messages', 'tasks')}, 'tasks': tasks,
           'messages': messages[-TAIL:] if t['status'] == 'open' else [], 'stamps': stamps, 'rev': rev, 'trev': trev}
    return row, {'id': tid, 'rev': rev, 'messages': messages, 'trev': trev, 'tasks': events}


def a_seq(value):
    return value if type(value) is int and 0 <= value < 2 ** 53 else None


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def known_seq(data, old, changes):
    """The highest number the state and the files beside it know of. None on a board that never had one."""
    try:
        pulse = PULSE.read_text(encoding='ascii').strip()
    except (OSError, ValueError):
        pulse = ''
    try:
        high = HIGH.read_text(encoding='ascii').strip()
    except (OSError, ValueError):
        high = ''
    found = [a_seq(data.get('seq')), *(a_seq(int(x)) if re.fullmatch(r'\d{1,16}', x) else None for x in (pulse, high)),
             *(a_seq(x.get('seq')) for x in (old, changes) if isinstance(x, dict))]
    found = [n for n in found if n is not None]
    return max(found) if found else None


def canon(value):
    """A JSON value as one string, for equality as a page sees it: in Python True == 1 == 1.0, in JSON they differ."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_of(summary):
    return {key: value for key, value in summary.items() if key not in ('seq', 'mark')}


def vouched(summary):
    """A summary that a numbered save wrote: its mark is the mark of its content."""
    return isinstance(summary.get('mark'), str) and summary['mark'] == mark_of(content_of(summary))


def list_patch(before, after):
    """A list as what changed in it: {"n": its length, "from": [[i, j], ...], "at": [[i, item], ...]}. The list
    before it, cut or filled (with null) to n items; then item i is the item j of the list before it ("from": a
    message that moved up in the tail of a thread, a stamp after one that was removed), and then item i is the
    item given ("at"). Positions that keep their item are not named."""
    where, was = {}, [canon(item) for item in before]
    for j, item in enumerate(was):
        where.setdefault(item, j)
    moved, given = [], []
    for i, item in enumerate(after):
        now = canon(item)
        if i < len(was) and was[i] == now:
            continue
        j = where.get(now)
        if j is not None:
            moved.append([i, j])
        else:
            given.append([i, item])
    patch = {'n': len(after)}
    if moved:
        patch['from'] = moved
    if given:
        patch['at'] = given
    return patch


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def row_edit(before, after):
    """What changed in one thread's row of the summary, when that is smaller than the row: the keys set again, the
    keys gone, and long lists (its stamps) as the positions that changed."""
    edit = {'set': {}, 'drop': [key for key in before if key not in after], 'list': {}}
    for key, value in after.items():
        if key in before and canon(before[key]) == canon(value):
            continue
        if key in before and isinstance(value, list) and isinstance(before[key], list):
            patch = list_patch(before[key], value)
            if len(compact(patch)) < len(compact(value)):
                edit['list'][key] = patch
                continue
        edit['set'][key] = value
    edit = {key: part for key, part in edit.items() if part}
    return edit if len(compact(edit)) < len(compact(after)) else None


def change_entry(old, new, seq, start=None):
    """What one change did to the summary: {"from": the number it starts from, "seq", "threads": {id: its whole row,
    or null when it is gone}, "edit": {id: what changed in its row}, "top": {key: value}, "drop": [top keys gone]}."""
    rows, edits = {}, {}
    for tid, row in new['threads'].items():
        before = old['threads'].get(tid)
        if before is not None and canon(before) == canon(row):
            continue
        edit = row_edit(before, row) if isinstance(before, dict) else None
        if edit is None:
            rows[tid] = row
        else:
            edits[tid] = edit
    for tid in old['threads']:
        if tid not in new['threads']:
            rows[tid] = None
    entry = {'from': old.get('seq') if start is None else start, 'seq': seq, 'threads': rows,
             'top': {key: value for key, value in new.items() if key not in ('threads', 'seq') and (key not in old or canon(old[key]) != canon(value))}}
    drop = [key for key in old if key not in new and key not in ('threads', 'seq')]
    if edits:
        entry['edit'] = edits
    if drop:
        entry['drop'] = drop
    return entry


def write_changes(entries, seq, mark):
    """changes/<from>.json for each entry (named by the number it starts from), then changes.json: the last
    CHANGES_MAX entries that fit in CHANGES_BYTES, and the mark of the summary they lead to. Each file is
    {"seq", "entries"} like changes.json: for the last CHANGES_FAN numbers, every change from that number to the
    board's (a page a few changes behind reads all it lacks in one request, which on a slow link is what costs);
    an older file keeps what it held. The files of entries that fell out go."""
    texts, size, kept = [], 0, []
    for entry in reversed(entries[-CHANGES_MAX:]):
        text = compact(entry)
        if size + len(text.encode('utf-8')) + 64 > CHANGES_BYTES:
            break
        size += len(text.encode('utf-8')) + 1
        texts.append(text)
        kept.append(entry)
    kept.reverse()
    texts.reverse()
    CHANGE_FILES.mkdir(exist_ok=True)
    numbers = {entry['from'] for entry in kept}
    for i, entry in enumerate(kept):
        path = CHANGE_FILES / f"{entry['from']}.json"
        if i >= len(kept) - CHANGES_FAN:
            bl.atomic_write_text(path, '{"seq":%d,"entries":[%s]}\n' % (seq, ','.join(texts[i:])))
        elif not path.is_file():
            bl.atomic_write_text(path, '{"seq":%d,"entries":[%s]}\n' % (entry['seq'], texts[i]))
    bl.atomic_write_text(CHANGES, '{"seq":%d,"mark":%s,"entries":[%s]}\n' % (seq, json.dumps(mark), ','.join(texts)))
    for path in CHANGE_FILES.iterdir():
        if path.suffix == '.json' and re.fullmatch(r'\d{1,16}', path.stem) and int(path.stem) not in numbers:
            with contextlib.suppress(OSError):
                path.unlink()


def write_lite(data, summary, whole, old, changes):
    """Write the cuts beside the saved state: each conversation that changed, what changed (changes.json), then
    the summary, so that a page that reads a change finds the conversations it names. A conversation is written
    again only when it changed since `old` (the summary on disk, when the pages at its number hold it; else None and
    every conversation is written), and the file of a thread that is gone goes with it. These files are derived: a
    failure here does not fail the command (the state is saved already); the summary is then taken away, and a page
    that finds none reads state.json as it always did."""
    try:
        seq = summary['seq']
        # (a conversation's file holds its messages and its tasks' history: written again when either changed)
        before = {tid: (t.get('rev'), t.get('trev')) for tid, t in old['threads'].items() if isinstance(t, dict)} if old else {}
        FULL.mkdir(exist_ok=True)
        for tid, record in whole.items():
            path = FULL / f'{tid}.json'
            if before.get(tid) != (record['rev'], record.get('trev')) or not path.is_file():
                bl.atomic_write_text(path, compact(record) + '\n')
        for path in FULL.iterdir():
            if path.suffix == '.json' and re.fullmatch(ID, path.stem) and path.stem not in whole and path.is_file():
                path.unlink()
        if changes is not None:
            write_changes(changes, seq, summary['mark'])
        bl.atomic_write_text(SUMMARY, compact(summary) + '\n')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logged('lite', exc)
        with contextlib.suppress(OSError):
            SUMMARY.unlink()


def a_chain(entries, known):
    """The entries of changes.json, when each is an entry that starts where the one before it ended and the last
    ends at `known`; else None (a file another hand wrote, or cut)."""
    if not isinstance(entries, list):
        return None
    at = None
    for e in entries:
        if not (isinstance(e, dict) and a_seq(e.get('from')) is not None and a_seq(e.get('seq')) is not None and e['from'] < e['seq']
                and (at is None or e['from'] == at)):
            return None
        at = e['seq']
    return entries if at is None or at == known else None


def numbered(data):
    """The summary of the state as it is about to be saved, and the number of the save: a new one when the
    summary differs from the one on disk (or there is none to compare with, or the one on disk is not vouched for by
    its mark: another writer rewrote it under its number), the same one when nothing a page shows has changed.
    Returns (summary, whole conversations, the summary before, the entries for changes.json or None to leave it as
    it is)."""
    old = read_json(SUMMARY)
    if not (isinstance(old, dict) and isinstance(old.get('threads'), dict) and all(isinstance(t, dict) for t in old['threads'].values())):
        old = None
    changes = read_json(CHANGES)
    known = known_seq(data, old, changes)
    data.pop('seq', None)
    summary, whole = lite(data)
    summary = content_of(json.loads(compact(summary)))     # as a page will read it: equal only when equal in JSON
    mark = mark_of(summary)
    # The summary on disk is the one the pages at its number hold only when a numbered save wrote it (its mark).
    standing = old is not None and known is not None and old.get('seq') == known and vouched(old)
    if standing and old['mark'] == mark and canon(content_of(old)) == canon(summary):
        seq, entries = known, None
    else:
        # Above every number known, and never below the clock: a board put back from a backup has forgotten the
        # numbers it gave since, and a page may hold one of them.
        seq = max(known + 1 if known is not None else 0, int(time.time() * 1000))
        # The changes go on only from the summary they led to: one that another writer (an older threads.py, a
        # hand) rewrote under the same number is not what the pages at that number hold.
        kept = a_chain(changes.get('entries'), known) if isinstance(changes, dict) else None
        if standing and kept is not None and changes.get('seq') == known and changes.get('mark') == old['mark']:
            entries = [*kept, change_entry(old, {**summary, 'mark': mark}, seq, known)]
        else:
            entries = []                             # nothing to describe this change against: pages read the summary
    data['seq'] = seq
    summary = {'seq': seq, 'mark': mark, **summary}      # the head a page checks: its number, then the mark of its content
    return summary, whole, old if standing else None, entries


def tell_number(seq):
    """The number of the board as it now stands, in the pulse (the server tells the pages) and beside the folder.
    The state is saved already: a failure here fails nothing (a pulse that cannot be rewritten is touched)."""
    try:
        bl.atomic_write_text(HIGH, str(seq))
    except OSError as exc:
        logged('seq', exc)
    try:
        bl.atomic_write_text(PULSE, str(seq))
    except OSError as exc:
        logged('pulse', exc)
        with contextlib.suppress(OSError):
            PULSE.touch()


def write_state(data):
    # allow_nan=False: Infinity or NaN is not JSON; a page's fetch(...).json() throws on it and the board stops loading
    bl.atomic_write_text(STATE, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def renumber(data):
    """A board whose state needs no save gets the files beside it (a board from before them, or one whose summary
    is gone or not vouched for): a new number is written in the state too, then its pages hear of it."""
    summary, whole, old, entries = numbered(data)
    if entries is not None:
        write_state(data)
    write_lite(data, summary, whole, old, entries)
    if entries is not None:
        tell_number(data['seq'])


# ── the store (SQLite) ─────────────────────────────────────────────────────

_store = None
_store_id = None


def store():
    """The board's store, opened once per command (the board's lock is held by whoever writes)."""
    global _store, _store_id
    try:
        now_id = (STORE_PATH.stat().st_dev, STORE_PATH.stat().st_ino)
    except OSError:
        now_id = None
    if _store is not None and (now_id is None or now_id != _store_id):     # its file was taken away or replaced
        with contextlib.suppress(Exception):
            _store.close()
        _store = None
    if _store is None:
        _store = suda_store.Store(STORE_PATH)
        _store_id = (STORE_PATH.stat().st_dev, STORE_PATH.stat().st_ino)
    return _store


def peek_thread(tid):
    """A thread as it was last saved, read without the lock (only to find its files). None when there is none."""
    if STORE_KIND == 'file' or not STORE_PATH.exists():     # (no store yet: the board is still its state.json)
        if not STATE.exists():
            return None
        return json.loads(STATE.read_text(encoding='utf-8'))['threads'].get(tid)
    st = suda_store.Store(STORE_PATH, readonly=True)
    try:
        body = st.body(tid)
    finally:
        st.close()
    return json.loads(body) if body is not None else None


def is_hot(t, ts):
    """Does the summary carry this thread: open, or closed less than HOT_DAYS ago (or never told when)."""
    return t['status'] == 'open' or not number(t.get('closed_ts')) or ts - t['closed_ts'] < HOT_DAYS * 86400


class Threads(dict):
    """The board's threads as a command uses them: the hot ones are loaded; a cold one (closed long ago) is read
    from the store the moment a command names it (t = threads[id], .get(id), id in threads). Going over the threads
    (.values(), .items(), len) covers the ones loaded: what is cold is closed and asks nothing of anyone. A command
    that must see every thread calls load_all() first."""

    def __init__(self, st):
        super().__init__()
        self.st = st
        self.loaded = {}            # id -> the text it was loaded with (a thread whose text is another changed)
        self._looked = set()

    def put(self, tid, t, text):
        dict.__setitem__(self, tid, t)
        self.loaded[tid] = text

    def _cold(self, tid):
        if self.st is None or not isinstance(tid, str) or tid in self._looked or dict.__contains__(self, tid):
            return None
        self._looked.add(tid)
        text = self.st.body(tid)
        if text is None:
            return None
        t = json.loads(text)
        check_thread(tid, t)
        fill(t)
        if 'state' not in t:
            derive(t)
        self.put(tid, t, text)
        return t

    def __missing__(self, tid):
        t = self._cold(tid)
        if t is None:
            raise KeyError(tid)
        return t

    def get(self, tid, default=None):
        if dict.__contains__(self, tid):
            return dict.__getitem__(self, tid)
        t = self._cold(tid)
        return default if t is None else t

    def __contains__(self, tid):
        return dict.__contains__(self, tid) or self._cold(tid) is not None

    def __delitem__(self, tid):
        dict.__delitem__(self, tid)
        self._looked.add(tid)           # removed by this command: never read back from the store

    def load_all(self):
        if self.st is not None:
            for tid in self.st.ids():
                self.get(tid)
        return self


def all_threads(data):
    """Every thread of the board, the cold ones too (a listing, a rename of a space, an export)."""
    threads = data['threads']
    return threads.load_all() if isinstance(threads, Threads) else threads


def needs_import(st):
    """A state.json the store takes in by itself: into an empty store (a board from before the store), or, with
    THREADS_AUTO_IMPORT=1 (the tests, netlab: they write state.json as a fixture), one newer than the last import.
    On a board in use the store is the truth: a newer state.json (an old threads.py from another checkout wrote
    it) is NOT taken in by itself; it is noted, and `threads import-state` takes it in on purpose."""
    try:
        mtime = STATE.stat().st_mtime_ns
    except OSError:
        return False
    if st.empty():
        return True
    if mtime <= (st.get('store:imported') or 0):
        return False
    if os.environ.get('THREADS_AUTO_IMPORT') == '1':
        return True
    logged('store', 'state.json is newer than the store (another threads.py wrote it?): not taken in; `threads import-state` takes it in')
    return False


def stamp_of_state():
    try:
        return STATE.stat().st_mtime_ns
    except OSError:
        return 0


def load_store(st):
    meta = st.meta()
    if not meta:
        meta = {'version': VERSION, 'policy': dict(POLICY), 'notify': dict(NOTIFY)}
    threads = Threads(st)
    for tid, text in st.bodies(hot_only=True):
        threads.put(tid, json.loads(text), text)
    data = {**meta, 'threads': threads}
    seq = data.get('seq')
    data = prepare(data)
    if seq is not None:
        data['seq'] = seq
    return data


def import_state(st, data):
    """Take a whole state (from state.json) into the store, and write the files a page reads from it."""
    ts = now()
    rows = []
    for tid, t in data['threads'].items():
        row, whole = lite_thread(t)
        if not is_hot(t, ts):
            whole = {**whole, 'row': row}
        rows.append((tid, 1 if is_hot(t, ts) else 0, t.get('closed_ts') if t['status'] != 'open' and number(t.get('closed_ts')) else None,
                     compact(t), compact(row), compact(whole)))
    top = {key: value for key, value in data.items() if key != 'threads'}
    if not st.empty():                  # what the store held is kept beside it, never lost to an import
        stamp, n = time.strftime('%Y%m%d-%H%M%S'), 0
        while True:
            keep = STORE_PATH.with_name(f'{STORE_PATH.name}.bak-{stamp}' + (f'-{n}' if n else ''))
            if not keep.exists():
                break
            n += 1
        st.db.execute("VACUUM INTO ?", (str(keep),))
    st.replace_all(top, rows, store_keys={'store:imported': stamp_of_state()})
    # the files a page reads, from the store as it now stands (a new number: no page can catch up across an import)
    fresh = load_store(st)
    fresh['threads'].loaded.clear()
    return save_store(fresh, fresh_files=True)


def export_state(data, path=None):
    """The whole board as state.json held it (every thread, the cold ones too): a rollback, a test, a backup."""
    whole = {key: value for key, value in data.items() if key != 'threads'}
    whole['threads'] = dict(all_threads(data))
    target = path or STATE
    bl.atomic_write_text(target, json.dumps(whole, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    if target == STATE and STORE_KIND != 'file':
        st = store()
        st.db.execute('INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)', ('store:imported', json.dumps(stamp_of_state())))


def save_store(data, fresh_files=False):
    """Save into the store: only the threads whose text changed are written, with their new row and whole record;
    the summary is the hot threads' rows; a change entry when what a page shows changed. Then the files a page
    reads (as the file store wrote them): the conversations that changed, changes.json and changes/<n>.json, the
    summary. `fresh_files`: every conversation file anew (an import)."""
    st = data['threads'].st if isinstance(data['threads'], Threads) else store()
    threads = data['threads']
    loaded = threads.loaded if isinstance(threads, Threads) else {}
    ts = now()
    known = known_seq_store(st, data)
    # no summary on disk (a board whose files were taken away, or from before them): every file a page reads is
    # written again (the missing conversations too), under a new number
    repair = not fresh_files and not SUMMARY.exists()
    data.pop('seq', None)
    top = {key: value for key, value in data.items() if key != 'threads'}
    old_top = {key: value for key, value in st.meta().items() if key != 'seq'}
    # The saved messages the page lists (saved179): those of the threads this write holds, and, as the last write left
    # them, those of the cold threads it did not touch. Once, on a board from before the list, from every thread.
    prev = old_top.get('saved')
    if isinstance(prev, list) and isinstance(threads, Threads):      # (a plain dict holds every thread: nothing to keep)
        held = set(loaded) | set(dict.keys(threads))
        kept = [r for r in prev if isinstance(r, dict) and r.get('thread') not in held]
        fresh = saved_page(dict.items(threads))
    elif isinstance(threads, Threads):
        kept, fresh = [], saved_page(all_threads(data).items())
    else:
        kept, fresh = [], saved_page(threads.items())
    top['saved'] = sorted(kept + fresh, key=lambda r: -r['saved'] if number(r.get('saved')) else 0)
    old_rows = st.rows()                                        # id -> row text (the summary's threads as they stand)
    changed = {}
    for tid, t in dict.items(threads):
        text = compact(t)
        hot = is_hot(t, ts)
        if loaded.get(tid) != text or hot != (tid in old_rows):
            changed[tid] = (t, text, hot)
    gone = [tid for tid in loaded if not dict.__contains__(threads, tid)]
    new_rows, records, written = {}, {}, []
    for tid, (t, text, hot) in changed.items():
        row, whole = lite_thread(t)
        if not hot:
            whole = {**whole, 'row': row}       # closed long ago: the summary no longer carries it, its file does
        row_text, whole_text = compact(row), compact(whole)
        records[tid] = whole_text
        if hot:
            new_rows[tid] = row_text
        closed = t.get('closed_ts') if t['status'] != 'open' and number(t.get('closed_ts')) else None
        written.append((tid, 1 if hot else 0, closed, text, row_text, whole_text))
    rows_now = {tid: text for tid, text in old_rows.items() if tid not in changed and tid not in gone}
    rows_now.update(new_rows)
    # what a page shows changed: a thread's row (in, out, or another text), or a top-level key
    # how many threads the summary leaves out (closed long ago): a page reads closed.json when the number moves
    cold_before = set(st.ids(hot=False))
    cold_after = (cold_before - set(changed) - set(gone)) | {tid for tid, (_t, _x, hot) in changed.items() if not hot}
    top_page = {**top, 'lite': 1, 'cold': len(cold_after)}
    old_page = {**old_top, 'lite': 1, 'cold': len(cold_before)}
    top_diff = {key: value for key, value in top_page.items() if key not in old_page or canon(old_page[key]) != canon(value)}
    top_drop = [key for key in old_page if key not in top_page]
    rows, edits = {}, {}
    for tid in set(changed) | set(gone):
        before, after = old_rows.get(tid), rows_now.get(tid)
        if before == after:
            continue
        if after is None:
            rows[tid] = None
            continue
        row = json.loads(after)
        edit = row_edit(json.loads(before), row) if before is not None else None
        if edit is None:
            rows[tid] = row
        else:
            edits[tid] = edit
    # the mark of the summary: of its top level and of each row's text, in the order of the ids (a page compares
    # it, never computes it)
    order = [tid for tid in dict.keys(threads) if tid in rows_now]
    order += [tid for tid in rows_now if tid not in set(order)]          # (hot rows of threads not loaded: none, kept safe)
    crc = zlib.crc32(canon(top_page).encode('utf-8'))
    for tid in order:
        crc = zlib.crc32(rows_now[tid].encode('utf-8'), zlib.crc32(tid.encode('utf-8'), crc))
    mark = '%08x' % crc
    same = (not fresh_files and not repair and known is not None and st.get('store:mark') == mark
            and not rows and not edits and not top_diff and not top_drop)
    entry = None
    if same:
        seq = known
    else:
        seq = max(known + 1 if known is not None else 0, int(time.time() * 1000))
        if known is not None and not fresh_files and st.get('store:mark') is not None:
            e = {'from': known, 'seq': seq, 'threads': rows, 'top': {**top_diff, 'mark': mark}}
            if edits:
                e['edit'] = edits
            if top_drop:
                e['drop'] = top_drop
            entry = (seq, known, compact(e))
    data['seq'] = seq
    top_saved = {**top, 'seq': seq}
    keep = seq - CHANGES_KEEP_DAYS * 86400 * 1000     # (numbers are milliseconds of the real clock: counted back from this one)
    st.write(top_saved, written, gone, entry, keep_entries_after=keep if entry else None,
             store_keys={'store:mark': mark, **({'store:imported': stamp_of_state()} if fresh_files else {})})
    if isinstance(threads, Threads):
        for tid, (t, text, hot) in changed.items():
            threads.loaded[tid] = text
        for tid in gone:
            threads.loaded.pop(tid, None)
    # the files a page reads (derived: a failure here fails nothing, the store is saved)
    try:
        FULL.mkdir(exist_ok=True)
        if fresh_files:
            for path in FULL.iterdir():
                if path.suffix == '.json' and re.fullmatch(ID, path.stem):
                    path.unlink()
            for tid in st.ids():
                bl.atomic_write_text(FULL / f'{tid}.json', st.whole(tid) + '\n')
        else:
            for tid, text in records.items():
                bl.atomic_write_text(FULL / f'{tid}.json', text + '\n')
            for tid in gone:
                with contextlib.suppress(OSError):
                    (FULL / f'{tid}.json').unlink()
            if repair:
                for tid in st.ids():
                    if not (FULL / f'{tid}.json').exists():
                        bl.atomic_write_text(FULL / f'{tid}.json', st.whole(tid) + '\n')
        if entry is not None or fresh_files or not CHANGES.exists():
            write_changes(st.last_entries(CHANGES_MAX) if not fresh_files else [], seq, mark)
        if not same or fresh_files or not SUMMARY.exists():
            head = compact({'seq': seq, 'mark': mark, **top_page})[:-1]
            body = ','.join('%s:%s' % (json.dumps(tid), rows_now[tid]) for tid in order)
            bl.atomic_write_text(SUMMARY, head + ',"threads":{' + body + '}}\n')
        if not same or fresh_files:
            write_closed_index(st)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logged('lite', exc)
        with contextlib.suppress(OSError):
            SUMMARY.unlink()
    if export_wanted():
        export_state(data)
    return seq


def export_wanted():
    """state.json after every save: THREADS_EXPORT_STATE=1 (the tests), and on his real board until Suda's own server
    answers it from the store (public182, suda-connectivity m51): the board view (board.html, and every thread link
    the tower sends opens it) still reads state.json, and froze at the switch to the store (21.11). THREADS_EXPORT_STATE=0
    turns it off."""
    v = os.environ.get('THREADS_EXPORT_STATE')
    return v == '1' if v not in (None, '') else real_board()


CLOSED_INDEX = BOARD / 'closed.json'
CLOSED_KEYS = ('id', 'title', 'status', 'state', 'note', 'created', 'updated', 'closed_ts', 'closed_by', 'space',
               'merged_into', 'slot', 'rev', 'trev')


def write_closed_index(st):
    """closed.json: the threads the summary no longer carries (closed long ago), a short row each, the newest
    closed first: the page's archive reads it when he opens the archive or searches."""
    rows = []
    for tid, closed, row in st.cold_index():
        try:
            r = json.loads(row)
        except (TypeError, ValueError):
            continue
        rows.append({key: r[key] for key in CLOSED_KEYS if key in r})
    bl.atomic_write_text(CLOSED_INDEX, compact({'threads': rows}) + '\n')


def known_seq_store(st, data):
    """The highest number the store and the files beside it know of (as known_seq, with the store's own)."""
    found = [a_seq(st.get('seq')), a_seq(data.get('seq'))]
    for path in (PULSE, HIGH):
        try:
            x = path.read_text(encoding='ascii').strip()
        except (OSError, ValueError):
            x = ''
        found.append(a_seq(int(x)) if re.fullmatch(r'\d{1,16}', x) else None)
    found = [n for n in found if n is not None]
    return max(found) if found else None


def save(data):
    global migrated_from, mended
    for t in data['threads'].values():
        schedule(t, data['policy'])
    if 'freed' in data:     # slots of removed threads: remembered only while they rest
        limit = now() - data['policy']['slot_cooldown_hours'] * 3600
        data['freed'] = {slot: when for slot, when in data['freed'].items() if when > limit}
    if migrated_from is not None and STATE.exists():
        backup(migrated_from)
    alerts(data, now())
    # what a page may post: it can hide a control this server does not have yet
    data['ops'] = list(PAGE_OPS + PAGE_FLAGS) + (['voice'] if voice_ready() else [])
    global pending_import
    if STORE_KIND == 'file':
        summary, whole, old, entries = numbered(data)
        write_state(data)
        write_lite(data, summary, whole, old, entries)  # before the pulse: a page that hears it reads these
    elif pending_import:
        data['seq'] = import_state(store(), data)
        pending_import = False
    else:
        save_store(data)
    migrated_from, mended = None, False
    written.clear()                                 # the files of this command now belong to a saved message
    tell_number(data['seq'])                        # the number of the board as it now stands: the server tells the pages
    # A wake that the same command already settled (removed, closed, asleep again, answered) is no news.
    for message, tag, tid, kind in waking:
        t = data['threads'].get(tid)
        if t is not None and (kind != 'wake' or (t['status'] == 'open' and 'reminder' in t)):
            mails.append((message, tag))
    waking.clear()
    telling['push'] = telling['push'] or noting['push']
    telling['phone'] += noting['phone']
    telling['voice'] += noting['voice']
    telling['at'] = noting['at'] if noting['at'] is not None else telling['at']
    telling['links'] += noting['links']
    noting.update(push=False, phone=[], voice=[], at=None, links=[])


def backup(version):
    """Keep the file as the older version left it, in the private folder (backups/state.json.v<old>-<time>):
    never beside the state, which the board server serves. A name that is already taken is trusted only
    when it holds exactly these bytes."""
    raw, stamp, n = STATE.read_bytes(), time.strftime('%Y%m%d-%H%M%S'), 0
    folder = private_dir() / 'backups'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(folder / STATE.name)        # the folder is for him alone
    while True:
        target = folder / (f"{STATE.name}.v{version}-{stamp}" + (f'-{n}' if n else ''))
        if not target.exists():
            break
        if target.read_bytes() == raw:
            return
        n += 1
    tmp = target.with_name(f'.{target.name}.tmp')
    shutil.copy2(STATE, tmp)
    os.chmod(tmp, 0o600)
    if tmp.read_bytes() != raw:
        raise OSError(tr('The backup of state.json was not written in full'))
    os.replace(tmp, target)


def fill(t):
    for key, value in THREAD_DEFAULTS:
        if key not in t:
            t[key] = [] if key in ('links', 'tasks') else value
    if t['state_ts'] is None:
        t['state_ts'] = t.get('updated') or t.get('created') or now()
    mend_questions(t)


def mend_questions(t):
    """`questions` holds every open question, oldest first, and `question` is always its last (the newest), so a
    page or a CLI that knows only `question` reads the thread as before. A record from before `questions` has
    [question] or []. A CLI that knows only `question` (a rollback) knew only the newest: when it changed it
    (answered it, replaced it, ended it), that newest one is over, and the older ones it never saw stay open
    unless they were answered or the topic is done."""
    kept = t.get('questions') if isinstance(t.get('questions'), list) else []
    question = t.get('question')
    if question and question['id'] in [q['id'] for q in kept]:
        kept = [q for q in kept if q['id'] != question['id']] + [question]
    elif kept:
        answered = {m['re'].get('q') for m in t['messages'] if isinstance(m.get('re'), dict)}
        older = [] if t.get('state') == 'done' else [q for q in kept[:-1] if q['id'] not in answered]
        kept = older + ([question] if question else [])
    else:
        kept = [question] if question else []
    set_questions(t, kept)


def questions_of(t):
    """The open questions of a thread, oldest first."""
    return list(t['questions'])


def set_questions(t, questions):
    t['questions'] = questions
    t['question'] = questions[-1] if questions else None


def derive(t):
    """The turn of a record that carries none, read from its messages. (Its slot comes
    from mend_slots: creation order.) Nothing is closed or dropped."""
    own = [m for m in t['messages'] if m['from'] == OWNER]
    last = t['messages'][-1] if t['messages'] else None
    ts = last['ts'] if last else t['state_ts']
    if t['status'] != 'open':
        t.update(state='done', note='', state_ts=ts)
    elif last is None:
        t.update(state=ON_OWNER, note=tr('New topic: read it'), state_ts=ts)
    elif last['from'] == OWNER or has_pending(t):
        # A derived state is never "done": the upgrade must not start any archive clock.
        waiting = next((m for m in reversed(own) if m.get('status') == 'pending'), own[-1])
        acked = waiting.get('status') == 'acked'
        t.update(state='working', note=waiting_note(waiting), state_ts=waiting.get('acked_ts', waiting['ts']),
                 state_by='fork' if acked else 'tower')
    else:
        t.update(state=ON_OWNER, note=tr('Read: {text}', text=preview(last['text'], 110) or tr('New message')), state_ts=ts, state_by=last['from'])


def thread(data, tid):
    if tid not in data['threads']:
        raise ValueError(tr('Thread not found'))
    return data['threads'][tid]


def open_thread(data, tid):
    t = thread(data, tid)
    if t['status'] != 'open':
        raise ValueError(tr('The thread is closed'))
    return t


# ── turn, slots, archive ────────────────────────────────────────────────────

def has_pending(t):
    return any(m['from'] == OWNER and m.get('status') in ('pending', 'transcribing') for m in t['messages'])


def schedule(t, policy):
    """When the thread fades and archives. None while it waits on anyone."""
    t['soon_at'] = t['archive_at'] = None
    if (t['status'] != 'open' or t['state'] != 'done' or has_pending(t) or t.get('snooze')
            or any(k.get('status') != 'done' for k in t['tasks'])):
        return
    base = max([t['state_ts'], t.get('touched') or 0] + [m['ts'] for m in t['messages']])
    if t['resolved']:
        t['soon_at'], t['archive_at'] = base, base + policy['resolved_hours'] * 3600
    else:
        t['soon_at'] = base + policy['idle_hours'] * 3600
        t['archive_at'] = t['soon_at'] + policy['grace_hours'] * 3600


def sweep(data, ts, skip=None):
    """Archive what passed its deadline. `skip`: the thread (or threads) this command touches."""
    archived, skip = [], {skip} if isinstance(skip, str) else set(skip or ())
    drop_old_parts(ts)
    for t in data['threads'].values():
        if t.get('snooze') and t['snooze']['until'] <= ts:
            wake(t, ts)
        for mid in dict.fromkeys(t['voicing']) if isinstance(t.get('voicing'), list) else ():
            retry_voice(t, mid, ts)
        keep = data['policy']['task_archive_hours'] * 3600
        if keep and archive_tasks(t, ts, lambda k: number(k.get('updated')) and ts - k['updated'] >= keep, 'auto'):
            tidied.append(t['id'])
        schedule(t, data['policy'])
        if t['id'] not in skip and t['archive_at'] is not None and t['archive_at'] <= ts:
            close_thread(t, 'auto', ts)
            archived.append(t['id'])
    return archived


def is_slot(value):
    """The one definition of a usable slot number (free_slot never hands out more than open threads + 1)."""
    return type(value) is int and 0 < value < 100_000


def free_slot(data, ts, back=None):
    """A thread's fixed place. A freed slot rests for the cooldown before a DIFFERENT
    topic gets it. `back`: a thread that returns takes its own old slot, unless the
    slot is used or rests for someone else by now."""
    rows = data['threads'].values()
    used = {t['slot'] for t in rows if t['status'] == 'open' and is_slot(t['slot'])}
    limit = ts - data['policy']['slot_cooldown_hours'] * 3600
    resting = {t['slot'] for t in rows if t['status'] == 'closed' and is_slot(t['slot']) and t is not back
               and number(t.get('closed_ts')) and t['closed_ts'] > limit}
    resting |= {int(slot) for slot, when in data.get('freed', {}).items() if slot.isdigit() and when > limit}
    if back and is_slot(back['slot']) and back['slot'] not in used and back['slot'] not in resting:
        return back['slot']
    slot = 1
    while slot in used or slot in resting:
        slot += 1
    return slot


def heal(data, ts):
    """Mend what an older CLI or a hand edit can leave on a version 2 file.
    True when something changed."""
    back = [t for t in data['threads'].values() if t['status'] == 'open' and 'closed_ts' in t]
    for t in back:      # reopened by a client that knows nothing of slots or the archive clock
        del t['closed_ts']
        t.pop('closed_by', None)
        t.update(touched=ts, resolved=False)
    changed = mend_slots(data, ts, {t['id'] for t in back}) or bool(back)
    for t in data['threads'].values():
        if t['status'] == 'open' and 'merged_into' in t:      # opened by a client that knows nothing of merging
            del t['merged_into']
            t['unmerged_ts'] = ts
            changed = True
    for t in data['threads'].values():
        if t['status'] == 'open' and t['state'] != 'working' and not t['question']:
            waiting = [m for m in t['messages'] if m['from'] == OWNER and m.get('status') == 'pending' and m['ts'] > t['state_ts']]
            if waiting:     # his reply was stored without a state change: the turn is with the agents
                set_state(t, 'working', waiting_note(waiting[-1]), 'tower', waiting[-1]['ts'], auto=True)
                changed = True
    return changed


def mend_slots(data, ts, late=()):
    """Every open thread owns exactly one slot. A record without one (or with a
    duplicate) gets the next free slot; whoever sits in a slot keeps it, and a
    thread in `late` (it just came back) chooses last."""
    used, loose = set(), []
    for t in sorted((t for t in data['threads'].values() if t['status'] == 'open'),
                    key=lambda t: (t['id'] in late, t.get('created', 0), t['id'])):
        slot = t['slot']
        if is_slot(slot) and slot not in used:
            used.add(slot)
        else:
            t['slot'] = None
            loose.append(t)
    for t in loose:
        t['slot'] = free_slot(data, ts)
    return bool(loose)


def wake(t, ts):
    """The snooze is over: the thread is on him again, marked as a reminder, and the tower is told."""
    until = t.pop('snooze')['until']
    t['updated'] = ts
    if t['status'] == 'open' and t['state'] != ON_OWNER:
        # His own reminder, not an agent's ask: once he has read it he may put the thread away again
        # (unless a question still waits for his answer: that is a real ask).
        set_state(t, ON_OWNER, preview(tr('Reminder: {what}', what=t['note'] or t['title']), NOTE_MAX), OWNER, ts, auto=not t['question'])
    t['reminder'] = {'ts': ts, 'until': until}
    t['state_ts'] = ts              # on him since now, and a new thing to tell him of, even if he had the last message on screen
    t.pop('seen', None)
    waking.append((f"[threads] snooze woke {t['id']}: run: threads show {t['id']}", f"{t['id']} snooze", t['id'], 'wake'))


def snooze_thread(t, until, ts):
    if t['status'] != 'open':
        raise ValueError(tr('Only an open thread can wait for a reminder'))
    if not number(until) or not ts < until <= ts + 366 * 86400:
        raise ValueError(tr('The reminder time must be in the future, within a year from today'))
    t['snooze'] = {'until': until, 'set': ts}
    t.pop('reminder', None)
    t['updated'] = ts


def parse_when(text, ts):
    """'+2h', 'tomorrow 09:00' (or the Hebrew words for today and tomorrow), '2026-11-16 09:00', '16.11 09:00': by this machine's clock."""
    text, day = one_line(text), datetime.date.fromtimestamp(ts)
    bad = ValueError(tr('--until: I did not understand the time. Examples: "+2h", "tomorrow 09:00", "2026-11-16 09:00", "16.11 09:00"'))

    def local(year, month, mday, hour, minute, second=0):
        """A wall-clock time that exists (31.02 and 25:99 do not), as seconds."""
        try:
            return time.mktime(datetime.datetime(year, month, mday, hour, minute, second).timetuple()[:8] + (-1,))
        except (ValueError, OverflowError, OSError):
            raise bad from None

    m = re.fullmatch(r'\+(\d+(?:\.\d+)?)\s*([mhd])', text)
    if m:
        return ts + float(m[1]) * {'m': 60, 'h': 3600, 'd': 86400}[m[2]]
    m = re.fullmatch(r'(today|tomorrow|היום|מחר)\s+(\d{1,2}):(\d{2})', text)
    if m:
        day += datetime.timedelta(days=m[1] in ('tomorrow', 'מחר'))
        return local(day.year, day.month, day.day, int(m[2]), int(m[3]))
    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?', text)
    if m:
        return local(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0))
    m = re.fullmatch(r'(\d{1,2})[./](\d{1,2})\s+(\d{1,2}):(\d{2})', text)
    if m:
        when = local(day.year, int(m[2]), int(m[1]), int(m[3]), int(m[4]))
        return when if when > ts else local(day.year + 1, int(m[2]), int(m[1]), int(m[3]), int(m[4]))
    raise bad


def archive_tasks(t, ts, which, by='agent'):
    """Move finished tasks to the thread's archive: they stay in the record with their numbers, and the
    bar of the thread shows only what is still current. Returns the numbers that moved."""
    moved = [ensure_events(k) for k in t['tasks'] if k.get('status') == 'done' and not k.get('archived') and which(k)]
    for k in moved:
        k['archived'] = ts
        task_event(k, 'archived', ts, by)
    return [k.get('n') for k in moved]


def derived_events(k):
    """What a task from before events tells of itself, each event marked derived. Only what has its own time:
    when it was made, each correction of its words (the old words are kept with when and who), done (its last
    change, when it is done now) and the archive. Nothing else is made up (when a working task started is not
    known, so nothing is said of it)."""
    out = []
    if number(k.get('ts')):
        out.append({'ts': k['ts'], 'kind': 'created', 'derived': True})
    history = sorted((h for h in k.get('history') or [] if isinstance(h, dict) and number(h.get('ts'))) if isinstance(k.get('history'), list) else [],
                     key=lambda h: h['ts'])
    for i, h in enumerate(history):
        after = history[i + 1].get('text') if i + 1 < len(history) else k.get('text')
        e = {'ts': h['ts'], 'kind': 'text', 'from': event_text(h.get('text')), 'to': event_text(after), 'derived': True}
        if isinstance(h.get('by'), str) and h['by']:
            e['by'] = h['by']
        out.append(e)
    if k.get('status') == 'done' and number(k.get('updated')):
        out.append({'ts': k['updated'], 'kind': 'status', 'to': 'done', 'derived': True})
    if number(k.get('archived')) and k['archived']:
        out.append({'ts': k['archived'], 'kind': 'archived', 'derived': True})
    return sorted(out, key=lambda e: e['ts'])


def agent_name(owner):
    """Who a CLI write is credited to when it names nobody: the task's agent owner, else just "agent" (a CLI write
    is never his, and the sweep's name is its own)."""
    return owner if isinstance(owner, str) and owner and not reads_as_his(owner) else 'agent'


def ensure_events(k):
    """Fix a task's story before anything about it changes: an old task's derived events are read from what it held
    until now (read after a change, they would take the new state for the old one and make up times)."""
    if not isinstance(k.get('events'), list):
        k['events'] = derived_events(k)
    return k


def unmove(task, ts, by):
    """Opened again, a task that went to another thread in a merge is no longer that one: say so in its history."""
    went = task.pop('moved_to', None)
    if went:
        task_event(task, 'moved', ts, by, after=None)
        task['events'][-1]['back'] = went


def event_text(value):
    return preview(value, TASK_EVENT_TEXT_MAX) if isinstance(value, str) else value


EVENT_TS_MAX = 10 ** 11           # a time no date can be later than (year 5138): a damaged event is dropped, never shown


def task_events(k):
    """A task's events, oldest first: the ones it keeps, or for a task from before events what can be derived."""
    events = k.get('events')
    if isinstance(events, list):
        return [dict(e) for e in events if isinstance(e, dict) and number(e.get('ts')) and 0 < e['ts'] < EVENT_TS_MAX]
    return derived_events(k)


def task_event(k, kind, ts, by, before=None, after=None):
    """Record one thing that happened to a task (every writer of a task's status, words, owner, archive or move
    calls this). Bounded: the first event (how it began) and the newest stay."""
    events = [] if kind == 'created' and not isinstance(k.get('events'), list) else task_events(k)      # a new task begins its own story
    e = {'ts': ts, 'kind': kind, 'by': by or 'agent'}
    if before is not None:
        e['from'] = event_text(before)
    if after is not None:
        e['to'] = event_text(after)
    events.append(e)
    if len(events) > TASK_EVENTS_MAX:
        events = events[:1] + events[-(TASK_EVENTS_MAX - 1):]
    k['events'] = events


def find_task(t, n):
    task = next((k for k in t['tasks'] if k.get('n') == n), None)
    if task is None:
        raise ValueError(tr('Task not found'))
    return ensure_events(task)          # its story fixed before a writer changes it


def find_message(t, mid):
    msg = next((m for m in t['messages'] if m['id'] == mid), None) if isinstance(mid, str) and mid else None
    if msg is None:
        raise ValueError(tr('Message not found'))
    return msg


def close_thread(t, by, ts):
    # Everything else stays on the record: the slot (the page shows who left that
    # place) and the state, line and question (reopening is an undo).
    t.update(status='closed', closed_ts=ts, closed_by=by, updated=ts, soon_at=None, archive_at=None)
    t.pop('snooze', None)
    t.pop('reminder', None)
    t.pop('urgent', None)


def reopen_thread(data, t, ts):
    """Back as it was, in its old slot when that is still free, with a fresh archive clock."""
    t.update(status='open', slot=free_slot(data, ts, t), updated=ts, touched=ts, resolved=False)
    t.pop('closed_ts', None)
    t.pop('closed_by', None)
    if t.pop('merged_into', None):      # back on its own: the thread it went into keeps the story of that merge
        t['unmerged_ts'] = ts


def plain_name(name):
    """A name as it is compared: compatibility forms, invisible characters and letter case taken away."""
    return ''.join(c for c in unicodedata.normalize('NFKC', str(name)) if unicodedata.category(c) not in ('Cf', 'Mn', 'Zs', 'Cc')).casefold()


def owner_aliases():
    """The other names that mean the owner, as compared (plain_name): 'human', 'me', and this installation's own
    (config.json "owner_aliases", a list of strings). A name of the system or of an agent is never one of them."""
    conf = config().get('owner_aliases')
    names = [x for x in conf if isinstance(x, str)] if isinstance(conf, list) else []
    taken = {OWNER, 'system', 'auto', 'agent', *AGENTS}
    return tuple(dict.fromkeys(key for key in map(plain_name, (*OWNER_ALIASES, *names)) if key and key not in taken))


def human_ids():
    """Every name that reads as the owner: OWNER and its aliases (plain_name)."""
    return (OWNER,) + owner_aliases()


def as_owner(value, ids=None):
    """An id as it is stored: a name of the owner is OWNER, and 'on-<a name of his>' is ON_OWNER. Anything else
    (an agent, another state, not a string) is returned as it is. For every input: the CLI and the page."""
    if not isinstance(value, str):
        return value
    ids = human_ids() if ids is None else ids
    key = plain_name(value)
    if key in ids:
        return OWNER
    if key.startswith('on-') and key[3:] in ids:
        return ON_OWNER
    return value


def configured_name():
    """How this installation names the owner (config.json "owner_name", one line, up to 40 characters), or None."""
    name = config().get('owner_name')
    return one_line(name)[:40] if isinstance(name, str) and not blank(name) else None


def owner_name():
    """How a message of the CLI names the owner."""
    return configured_name() or tr(OWNER_NAME)


def reads_as_his(name):
    """Does this --by name read as the owner (or the archive)? Look-alikes count: compatibility forms, invisible
    characters and letter case are taken away first."""
    plain, ids = plain_name(name), human_ids()
    confusable = plain.translate(str.maketrans('аеорсухіј', 'aeopcyxij'))       # Cyrillic letters that look Latin
    return confusable in ids or plain in ids or confusable == 'auto'


def spaces_of(data):
    """The spaces besides the main one, as stored: [{id, name, letter, color, prefix: [...]}]."""
    return data['spaces'] if isinstance(data.get('spaces'), list) else []


def space_of(data, t):
    """The space a thread is in: its own choice, else the first space whose prefix its id starts with, else 'main'.
    The tower's thread is always in the main space."""
    if t['id'] == TOWER_THREAD:
        return 'main'
    known = {sp['id'] for sp in spaces_of(data)}
    if isinstance(t.get('space'), str) and (t['space'] == 'main' or t['space'] in known):
        return t['space']
    for sp in spaces_of(data):
        if any(t['id'].startswith(pre) for pre in sp.get('prefix') or []):
            return sp['id']
    return 'main'


def clean_space(sp_id, name, prefixes, letter, color, data, new):
    """Validate one space; raises ValueError in Hebrew."""
    if not (isinstance(sp_id, str) and re.fullmatch(ID, sp_id)) or sp_id == 'main':
        raise ValueError(tr('Invalid space id (main is kept for the main space)'))
    ids = [sp['id'] for sp in spaces_of(data)]
    if new and sp_id in ids:
        raise ValueError(tr('The space already exists'))
    if not new and sp_id not in ids:
        raise ValueError(tr('Space not found'))
    if new and len(ids) >= SPACES_MAX:
        raise ValueError(tr('Up to {max} spaces: spaces are few', max=SPACES_MAX))
    if name is not None and (not isinstance(name, str) or blank(visible(name)) or len(one_line(name)) > SPACE_NAME_MAX):
        raise ValueError(tr('Space name: 1 to {max} characters', max=SPACE_NAME_MAX))
    if prefixes is not None and not all(isinstance(x, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,30}', x) for x in prefixes):
        raise ValueError(tr('Prefix: lowercase English letters, digits and hyphens (e.g. sup-)'))
    if letter is not None and not (isinstance(letter, str) and 1 <= len(visible(letter).strip()) <= 2 and not blank(visible(letter))):
        raise ValueError(tr("The space's letter: one or two characters"))
    if color is not None and not (isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color)):
        raise ValueError(tr('Color: #rrggbb'))


def visible(text):
    """The text without invisible and direction characters (a name, a letter he must see)."""
    return ''.join(c for c in str(text) if unicodedata.category(c)[0] not in ('C',) and c not in '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')


def first_letter(name):
    return next((c for c in name if unicodedata.category(c)[0] not in ('C', 'Z', 'M', 'P', 'S')), '?')


def add_space(data, sp_id, name, prefixes=(), letter=None, color=None):
    clean_space(sp_id, name, list(prefixes), letter, color, data, True)
    storable(name)
    name = one_line(visible(name))
    taken = {sp.get('color') for sp in spaces_of(data) if isinstance(sp.get('color'), str)} | {MAIN_COLOR}
    sp = {'id': sp_id, 'name': name, 'letter': visible(letter).strip() if letter else first_letter(name),
          'color': (color or next((c for c in SPACE_COLORS if c not in taken), SPACE_COLORS[len(taken) % len(SPACE_COLORS)])).lower(),
          'prefix': list(dict.fromkeys(prefixes))}
    data['spaces'] = spaces_of(data) + [sp]
    return sp


def move_to_space(data, t, space):
    """His (or an agent's) choice of where a thread lives. Nobody's turn moves and nobody is told."""
    if t['id'] == TOWER_THREAD:
        raise ValueError(tr("The tower's thread is always in the main space"))
    if t.get('merged_into'):
        raise ValueError(tr('The thread was merged into {into}: it is there', into=t['merged_into']))
    if not (isinstance(space, str) and (space == 'main' or space in {sp['id'] for sp in spaces_of(data)})):
        raise ValueError(tr('Space not found'))
    if t.get('space') == space:
        return False
    t['space'] = space
    t['updated'] = now()
    return True


def merge_threads(data, src_id, dst_id, by, ts):
    """Merge thread `src_id` into `dst_id` (the owner, thread suda m377). The source is closed under "merged" and
    remembers where it went; the target remembers where its new parts came from and gets one message that tells
    of it; the open tasks of the source move to the target, numbered there anew, and each old one says where it
    went. Nothing is deleted. Returns False when this very merge was already done."""
    if not (isinstance(dst_id, str) and re.fullmatch(ID, dst_id)):
        raise ValueError(tr('The thread to merge into: invalid id'))
    if src_id == dst_id:
        raise ValueError(tr('A thread cannot be merged into itself'))
    if src_id not in data['threads'] or dst_id not in data['threads']:
        raise ValueError(tr('Thread {id} not found', id=src_id if src_id not in data['threads'] else dst_id))
    src, dst = data['threads'][src_id], data['threads'][dst_id]
    if src.get('merged_into') == dst_id:
        return False
    if src.get('merged_into'):
        raise ValueError(tr('Thread {id} was already merged into {into}', id=src_id, into=src['merged_into']))
    if TOWER_THREAD in (src_id, dst_id):
        raise ValueError(tr("The tower's thread is not merged, and nothing is merged into it"))
    if dst['status'] != 'open':
        raise ValueError(tr('Thread {id} is closed: reopen it first (threads reopen {id})', id=dst_id))
    n = max([k['n'] for k in dst['tasks']] + [data.get('retired_tasks', {}).get(dst_id, 0)])
    moved, finished = [], 0
    for k in src['tasks']:
        if k.get('moved_to'):       # it went once already: it lives where it went (one opened again lost the mark and goes again)
            continue
        # every task goes, the done ones too (suda-fixes task 34): the target holds the whole list, each with its story
        n += 1
        ensure_events(k)
        done = k.get('status') == 'done'
        copy = {'n': n, 'text': k.get('text', ''), 'status': k.get('status', 'todo'), 'owner': k.get('owner'),
                'note': k.get('note', ''), 'from': None, 'moved_from': {'thread': src_id, 'n': k['n']},
                'ts': k.get('ts', ts), 'updated': ts,
                **({'history': k['history']} if isinstance(k.get('history'), list) and k['history'] else {}),
                **({'archived': k['archived']} if done and number(k.get('archived')) and k['archived'] else {}),
                'events': task_events(k)}
        task_event(copy, 'moved', ts, by or 'agent', before={'thread': src_id, 'n': k['n']})
        dst['tasks'].append(copy)
        if done:
            finished += 1
        else:                       # an open one is done here: it goes on there
            task_event(k, 'status', ts, by or 'agent', k.get('status'), 'done')
            k.update(status='done', note=preview(tr('Moved to {thread} (task {n})', thread=dst_id, n=n), NOTE_MAX))
            k.pop('archived', None)
        k.update(moved_to={'thread': dst_id, 'n': n}, updated=ts)
        task_event(k, 'moved', ts, by or 'agent', after={'thread': dst_id, 'n': n})
        moved.append([k['n'], n])
    count = len(src['messages'])
    first = src['messages'][0]['ts'] if src['messages'] else src.get('created')
    last = src['messages'][-1]['ts'] if src['messages'] else src.get('updated')
    text = (tr('**Merged here: «{title}»** ({id}): {count} messages', title=src['title'], id=src_id, count=count)
            + (tr(', {n} tasks moved ({pairs})', n=len(moved), pairs=', '.join(f'{a}→{b}' for a, b in moved))
               + (tr(', {n} of them done', n=finished) if finished else '') if moved else '')
            # its open questions end with it: said here, so whoever waited for an answer to one learns it (suda m508)
            + (tr(', open questions closed without an answer: {list}', list=', '.join(f"{q['id']} «{preview(q['text'], 60)}»" for q in src['questions']))
               if src['questions'] else '')
            + tr('.\nThe full history stays in thread {id}: /threads/suda.html#{id}', id=src_id))
    # a line of the system (as a split is): never news, never a push or a ring, also for his own press
    append(dst, 'system', text, ts, merge={'thread': src_id, 'title': src['title'], 'messages': count, 'first': first,
                                          'last': last, 'tasks': moved, 'by': by or 'agent'})
    if not isinstance(dst.get('merged_from'), list):
        dst['merged_from'] = []
    if src_id not in dst['merged_from']:
        dst['merged_from'].append(src_id)
    dst['touched'] = ts
    for k in dst['tasks'][len(dst['tasks']) - len(moved):]:
        undone(dst, k, k.get('owner'), ts)      # open tasks arrived: a target that said done is not done
    set_questions(src, [])
    if src['status'] == 'open':
        close_thread(src, by or 'agent', ts)
    set_state(src, 'done', preview(tr('Merged into «{title}» ({id})', title=dst['title'], id=dst_id), NOTE_MAX), by or 'agent', ts, auto=False)
    src.update(merged_into=dst_id, merged_ts=ts, updated=ts)
    src.pop('unmerged_ts', None)
    return True


def clean_note(note, state):
    note = one_line(note or '')
    if len(note) > NOTE_MAX:
        raise ValueError(tr('The line is too long: up to {max} characters', max=NOTE_MAX))
    if blank(note):
        note = ''
    if state == ON_OWNER and not note:
        raise ValueError(tr('--note is required: what {owner} needs to decide or do, in one line', owner=owner_name()))
    return note


def revive(data, t, ts):
    """Nobody decided to close a thread that archived itself: whoever writes into it
    brings it back. A thread someone closed stays closed until it is reopened."""
    if t['status'] != 'open' and t.get('closed_by') == 'auto':
        reopen_thread(data, t, ts)
    return t['status'] == 'open'


def set_state(t, state, note, by, ts, auto=False, resolved=False):
    t.update(state=state, note=note, state_by=by, state_ts=ts, auto=auto, resolved=resolved, touched=ts, updated=ts)
    if state == 'done':
        set_questions(t, [])        # an open question ends with his answer, when it is replaced, or with the topic: never because an agent wrote again
    t.pop('reminder', None)         # whatever the reminder was about, the thread has moved on
    if state == ON_OWNER and by != OWNER:
        t.pop('seen', None)         # a new ask, even with no new message: he has not seen THIS


def unsnooze(t, ts):
    """Cancel the sleep or dismiss the reminder. True when there was one. Looking at the thread again
    is activity: it must not archive itself the moment it is back."""
    had = t.pop('snooze', None) is not None
    had = t.pop('reminder', None) is not None or had
    if had:
        t.update(touched=ts, updated=ts)
    return had


def waiting_note(msg):
    tail = tr('an agent is working on it') if msg.get('status') == 'acked' else tr('waiting to be picked up')
    return tr('You answered «{text}»: {tail}', text=preview(msg['text'], 60), tail=tail)


def append(t, sender, text, ts, cid=None, **extra):
    msg = {'id': f"m{t['next']}", 'from': sender, 'text': text, 'ts': ts}
    if sender == OWNER:
        msg['status'] = 'pending'
    if cid is not None:
        msg['cid'] = cid
    msg.update(extra)
    noting['links'] += pr_links(text)       # the chips of its pull requests are looked up once it is stored
    t['next'] += 1
    t['updated'] = msg['ts']
    t['messages'].append(msg)
    return msg


def owner_spoke(t, msg, under=SAW_IT, answers=None, answering=True):
    """His reply settles the question he answered, and only that one: while another question is open the thread
    stays on him for it; with none left the turn goes to the agents. Which question he answered: the one whose
    answer he pressed or ticked (`answers`, its id); else the question whose message he replied to; else `under`,
    the newest question that was on his screen when he wrote (an id; None: there was none; SAW_IT: the caller
    vouches it is the newest open one; UNKNOWN: an older page that does not say, so it answers none).
    A reply is never filed under a question he did not see. A command he typed for the agents (`answering`
    False) answers none, also when it quotes the question."""
    t.pop('snooze', None)
    t.pop('reminder', None)
    open_now = questions_of(t)
    newest = open_now[-1] if open_now else None
    opened = lambda qid: next((q for q in open_now if q['id'] == qid), None)
    asking = lambda qid: next((m for m in t['messages'] if m['id'] == qid and m.get('q')), None)
    replied = msg['reply_to'].get('id') if isinstance(msg.get('reply_to'), dict) else None
    if not answering:
        asked = answer = None
    elif answers is not None:
        asked = answer = opened(answers)
    elif replied and asking(replied):           # a reply to the question's own message (also a late one, to a question that is over)
        asked, answer = asking(replied), opened(replied)
    elif under is SAW_IT:
        asked = answer = newest
    elif under is UNKNOWN:
        # A client that does not say what was on his screen (only a very old page; suda.html says it).
        # Which question these words answer cannot be known, so none is closed and none is named (suda m508): a "yes"
        # must never be filed as the answer to a question he did not see. The words reach the agents in `pending`
        # all the same, the questions keep their buttons, and the thread stays on him.
        asked = answer = None
    elif under is None:
        asked = answer = None
    else:
        asked, answer = asking(under), opened(under)
    if asked:
        msg['re'] = {'q': asked['id'], 'text': asked['text']}
    if answer is None and open_now:
        return      # it answers no open question (written before they appeared, or to one that is over): they stay open, on him
    rest = [q for q in open_now if q is not answer]
    set_questions(t, rest)
    if not rest:
        set_state(t, 'working', waiting_note(msg), 'tower', msg['ts'], auto=True)
        return
    # Another question still waits for him: the thread stays on him for the newest of them (a real ask). Its
    # moment stays as it was, and when he had the newest one in front of him his own answer is no news to him.
    if t['state'] == ON_OWNER:
        t.update(note=preview(rest[-1]['text'], NOTE_MAX) or one_line(rest[-1]['text'])[:NOTE_MAX], state_by=rest[-1].get('from') or t['state_by'],
                 auto=False, resolved=False, touched=msg['ts'], updated=msg['ts'])
    if answer is newest or under == newest['id']:
        t['seen'] = {'msg': msg['id'], 'ts': msg['ts']}


def unseen(t, raw):
    """The page says which message was last on his screen. A newer one must not be
    dismissed or archived before he saw it."""
    if 'last' in raw and raw['last'] != (t['messages'][-1]['id'] if t['messages'] else ''):
        raise ValueError(tr('A new message came in this thread. Read it first'))


def agent_spoke(t, msg, state=None, note='', by=''):
    """An agent that says nothing about the turn hands it to the owner: a wrong
    "read this" costs him one glance, a wrong "working" stalls the topic."""
    if state:
        set_state(t, state, note, by or msg['from'], msg['ts'])
    elif t['question']:
        # He has not answered yet: whatever was said since, the thread is on him for that question (a real ask,
        # so "read it" does not put it away).
        if t['state'] != ON_OWNER or t['auto']:
            asked = t['question']
            set_state(t, ON_OWNER, preview(asked['text'], NOTE_MAX) or one_line(asked['text'])[:NOTE_MAX], asked.get('from') or msg['from'], msg['ts'])
    elif t['state'] != ON_OWNER or t['auto']:
        set_state(t, ON_OWNER, tr('Read: {text}', text=preview(msg['text'], 110) or tr('New message')), msg['from'], msg['ts'], auto=True)


def within(file, limit, refusal):
    """A file named on the command line, read ONCE and never past its limit (a pipe or a device has no size to ask)."""
    with open(file, 'rb') as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(refusal)
    return raw


ORDERS = ('אבגדהוזחטיכלמנסעפצקרשת', 'abcdefghijklmnopqrstuvwxyz')


def in_label_order(options):
    """Options that carry marks of one kind (Hebrew letters, A/B/C, 1/2/3) must come in the order of the marks: he reads
    them as a list, and the recommended one is marked, not moved. True when they have no such marks or are in order."""
    marks = [re.match(r'\(?([א-ת]|[A-Za-z]|\d{1,2})(?:[.):]|\s+[-\u2013])?\s', option + ' ') for option in options]
    if len(options) < 2 or not all(marks):
        return True
    marks = [m[1].lower() for m in marks]
    for order in ORDERS:
        if all(mark in order for mark in marks):
            places = [order.index(mark) for mark in marks]
            return places == sorted(set(places))
    if all(mark.isdigit() for mark in marks):
        places = [int(mark) for mark in marks]
        return places == sorted(set(places))
    return True         # marks of mixed kinds are not a list


def parse_options(raw):
    options = []
    for part in (raw or '').split(','):
        part = one_line(part)
        if part and part not in options:
            options.append(part)
    if raw is not None and not 2 <= len(options) <= 6:
        raise ValueError(tr('--options: between 2 and 6 options, separated by commas'))
    if any(len(option) > 40 for option in options):
        raise ValueError(tr('--options: up to 40 characters per option'))
    return options


def clean_groups(raw):
    """The groups of a multi-select question, as written: [{title, items:[text | {text, recommended}]}]."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise ValueError(tr('Groups: a list of 1 to 12 groups'))
    groups, total = [], 0
    for group in raw:
        if not isinstance(group, dict) or not isinstance(group.get('items'), list) or not group['items']:
            raise ValueError(tr('Groups: each group is {title, items:[…]} with at least one item'))
        title, items = one_line(group.get('title') or ''), []
        for item in group['items']:
            text = one_line(item.get('text', '') if isinstance(item, dict) else item if isinstance(item, str) else '')
            if blank(text) or len(text) > 80 or text in [i['text'] for i in items]:
                raise ValueError(tr('Groups: each item is a text of up to 80 characters, with no repeats in a group'))
            items.append({'text': text, 'recommended': bool(isinstance(item, dict) and item.get('recommended'))})
        if len(title) > 60 or title in [g['title'] for g in groups]:
            raise ValueError(tr('Groups: a unique title of up to 60 characters'))
        groups.append({'title': title, 'items': items})
        total += len(items)
    if total > 40:
        raise ValueError(tr('Groups: up to 40 items in all'))
    return groups


def picked(question, answer, note):
    """His ticks, checked against the question and put in its written order; plus the message he would have typed."""
    groups = question.get('groups') if question else None
    if not groups or not isinstance(answer, dict):
        raise ValueError(tr('This is not a multiple-choice question, or the answer is not valid'))
    chosen = {}
    for title, items in answer.items():
        group = next((g for g in groups if g['title'] == title), None)
        if group is None or not isinstance(items, list) or not all(i in [x['text'] for x in group['items']] for i in items):
            raise ValueError(tr('The answer has a group or an item that was not asked'))
        chosen[title] = [x['text'] for x in group['items'] if x['text'] in items]
    note = one_line(note or '')
    if not any(chosen.values()) and not note:
        raise ValueError(tr('Nothing was chosen and there is no note'))
    lines = [(f"**{g['title']}:** " if g['title'] else '') + ', '.join(chosen[g['title']]) for g in groups if chosen.get(g['title'])]
    lines = (lines or [tr('Nothing was chosen')]) + ([tr('Note: {note}', note=note)] if note else [])
    return {g['title']: chosen[g['title']] for g in groups if chosen.get(g['title'])}, note, '\n'.join(lines)


def clean_link(label, target):
    label, target = one_line(label), (target or '').strip()
    if not label or len(label) > 40:
        raise ValueError(tr('Link label: 1 to 40 characters'))
    # A browser drops control characters and reads "\\" as "/": neither may hide a scheme or another host.
    if not target or len(target) > 500 or re.search(r'[\x00-\x1f\x7f]', target) or (target[0] in '/\\' and '\\' in target):
        raise ValueError(tr('Invalid link target'))
    # http(s), a path on the board server, or a file path shown as text. No other scheme reaches the page.
    if not re.match(r'https?://', target, re.I) and (target.startswith('//') or re.match(r'[a-z][a-z0-9+.-]*:', target, re.I)):
        raise ValueError(tr('Link: only http(s), a path on the server (/…) or a file path'))
    return {'label': label, 'url': target}


def snippet_name(text, name=None):
    """Check a snippet before anything is written; returns its cleaned base name (or None)."""
    if not isinstance(text, str) or blank(text):
        raise ValueError(tr('Empty snippet'))
    if name is not None and not isinstance(name, str):
        raise ValueError(tr('Invalid snippet name'))
    try:
        size = len(text.encode('utf-8'))
    except UnicodeEncodeError:
        raise ValueError(tr('The snippet is not valid text')) from None
    if size > SNIPPET_MAX:
        raise ValueError(tr('The snippet is too big: up to {mb}MB', mb=SNIPPET_MAX // 1_000_000))
    # A name, never a path: the file's place is decided here, not by whoever sends it.
    base = re.split(r'[\\/]', name or '')[-1]
    return one_line(''.join(ch for ch in base if ch.isspace() or unicodedata.category(ch)[0] != 'C'))[:120] or None


def parts_dir(tid, cid):
    """Where the parts of one big text wait: outside the served folder, one folder per (thread, message)."""
    return private_dir() / 'parts' / hashlib.sha256(f'{tid}\n{cid}'.encode('utf-8')).hexdigest()[:40]


def take_part(raw, ts):
    """One part of a big text from the page (op snippet-part): checked, then kept until its reply comes."""
    tid, cid, i, n, text = (raw.get(k) for k in ('thread', 'cid', 'i', 'n', 'text'))
    if not isinstance(cid, str) or not cid.strip() or len(cid) > 80:
        raise ValueError(tr('Invalid message id'))
    if type(n) is not int or type(i) is not int or not 1 <= n <= PARTS_MAX or not 0 <= i < n:
        raise ValueError(tr('Invalid part of a snippet'))
    if not isinstance(text, str) or not text:
        raise ValueError(tr('Empty part of a snippet'))
    storable(text)
    raw_part = text.encode('utf-8')
    if len(raw_part) > PART_MAX:
        raise ValueError(tr('Too big a part of a snippet'))
    with locked():
        t = thread(load(), tid)
        # its message is already here (the answer to the reply was lost on the way): nothing to keep, and the page
        # goes on to the reply, which is answered as it was the first time, whatever happened to the thread since
        if any(m.get('cid') == cid for m in t['messages']):
            return {'ok': True, 'op': 'snippet-part', 'thread': tid, 'i': i, 'n': n, 'dup': True}
        if t['status'] != 'open' or t.get('merged_into'):
            raise ValueError(tr('The thread is closed'))
    where = parts_dir(tid, cid)
    meta = where / 'meta.json'
    try:
        kept = json.loads(meta.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        kept = None
    if not isinstance(kept, dict) or kept.get('n') != n:        # a new try, cut otherwise: start over
        shutil.rmtree(where, ignore_errors=True)
        try:
            others = [p for p in (private_dir() / 'parts').iterdir() if p.is_dir()]
        except OSError:
            others = []
        if len(others) >= PARTS_PLACES:
            raise Refused(tr('Too many big snippets on the way right now. Try again in a moment'), again=True)
    else:       # the parts of one text never hold more than a whole snippet may
        held = sum(p.stat().st_size for p in where.glob('*.part') if p.name != f'{i}.part')
        if held + len(raw_part) > SNIPPET_MAX:
            raise ValueError(tr('The snippet is too big: up to {mb}MB', mb=SNIPPET_MAX // 1_000_000))
    where.mkdir(parents=True, exist_ok=True)
    bl.atomic_write_text(meta, json.dumps({'n': n, 'ts': ts}))
    fd, tmp = tempfile.mkstemp(dir=str(where), prefix='.in-')
    with os.fdopen(fd, 'wb') as f:
        f.write(raw_part)
    os.replace(tmp, where / f'{i}.part')
    return {'ok': True, 'op': 'snippet-part', 'thread': tid, 'i': i, 'n': n}


def joined_parts(tid, cid, n):
    """The whole text of a big snippet, from its parts; None when they are not all here (gone, or never came)."""
    where = parts_dir(tid, cid)
    try:
        if json.loads((where / 'meta.json').read_text(encoding='utf-8')).get('n') != n:
            return None
        size = sum((where / f'{i}.part').stat().st_size for i in range(n))
        if size > SNIPPET_MAX:
            raise ValueError(tr('The snippet is too big: up to {mb}MB', mb=SNIPPET_MAX // 1_000_000))
        return b''.join((where / f'{i}.part').read_bytes() for i in range(n)).decode('utf-8')
    except (OSError, AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def drop_old_parts(ts):
    """Parts whose reply never came: gone after PARTS_KEEP."""
    try:
        places = list((private_dir() / 'parts').iterdir())
    except OSError:
        return
    for where in places:
        try:
            when = json.loads((where / 'meta.json').read_text(encoding='utf-8')).get('ts')
        except (OSError, ValueError, AttributeError):
            when = None
        if not isinstance(when, (int, float)):      # no meta yet (being written now) or a broken one: by its age on disk
            try:
                when = ts - (time.time() - where.stat().st_mtime)
            except OSError:
                continue
        if ts - when >= PARTS_KEEP:
            shutil.rmtree(where, ignore_errors=True)


def folder(kind, tid):
    """A thread's own folder of files (snippets/<id>, uploads/<id>). Never through a link: the board
    is served over HTTP, and what is written or read here must really be inside it."""
    try:
        inside = BOARD.resolve() / kind / tid
        through_a_link = (BOARD / kind / tid).resolve() != inside
    except (RuntimeError, OSError):         # a link that points at itself
        through_a_link = True
    if through_a_link:
        raise ValueError(tr("The thread's file folder is a link; I did not touch it"))
    return inside


def put_file(path, raw):
    """Write one file of a message. It is remembered until the state is saved: a message that was
    never stored leaves nothing behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())            # on the disk before the state that names it
        written.append(path)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def discard():
    """Take back the files of a command that failed: its message was never stored. An emptied folder goes too."""
    for path in written:
        try:
            path.unlink()
        except OSError:
            pass
        try:
            path.parent.rmdir()
        except OSError:
            pass
    written.clear()


@contextlib.contextmanager
def locked():
    """The lock of the state. A command that fails inside it takes its files back BEFORE the lock is released:
    the next command may be given the same message id, and so the same file names."""
    with bl.file_lock(STATE):
        try:
            yield
        except BaseException:
            discard()
            raise


def attach(t, msg, text, name, only):
    """Store the long text in its own file beside the state. The message keeps a
    pointer, the sizes and the first lines; `only` says the message has no text of
    its own (its `text` is then a one-line preview)."""
    ext = Path(name or '').suffix.lower()
    name_on_disk = f"{msg['id']}{ext if ext in SNIPPET_TYPES else '.txt'}"
    put_file(folder('snippets', t['id']) / name_on_disk, text.encode('utf-8'))      # bytes: every line end as he sent it
    lines = text.splitlines()
    head = '\n'.join(lines[:12])
    if len(head) > 599 or len(lines) > 12:
        head = head[:599].rstrip() + '…'
    msg['snippet'] = {'file': f"snippets/{t['id']}/{name_on_disk}", 'name': name, 'bytes': len(text.encode('utf-8')), 'chars': len(text),
                      'lines': len(lines), 'head': head, 'only': only}


def file_path(t, kind, file):
    """Where a file of a message is. Only ever inside this thread's own folder."""
    if not isinstance(file, str):
        raise ValueError(tr('This message has no such file'))
    base, path = folder(kind, t['id']), (BOARD / file).resolve()
    if base not in path.parents:
        raise ValueError(tr("The file path goes outside the thread's folder"))
    return path


def snippet_path(t, msg):
    record = msg.get('snippet')
    if not isinstance(record, dict) or not isinstance(record.get('file'), str):
        raise ValueError(tr('This message has no snippet'))
    return file_path(t, 'snippets', record['file'])


def read_exact(path):
    """A text file with its line ends untouched (CRLF stays CRLF)."""
    with open(path, encoding='utf-8', newline='') as f:
        return f.read()


def spoken(t, sender, text, body, name, ts, cid=None, pictures=(), page=None, voice=None, videos=()):
    """Append one message, with what comes beside it: a snippet, pictures, videos, an agent's page."""
    only = body is not None and blank(text)
    bare = blank(text) and body is None and bool(pictures or videos)      # pictures or videos and not a word: the text is a stand-in
    shown_pictures = (tr('Picture') if len(pictures) == 1 else tr('{n} pictures', n=len(pictures))) if pictures else ''
    shown_videos = (tr('Video') if len(videos) == 1 else tr('{n} videos', n=len(videos))) if videos else ''
    stand_in = tr('{pictures} and {videos}', pictures=shown_pictures, videos=shown_videos) if pictures and videos else shown_pictures or shown_videos
    msg = append(t, sender, (preview(body[:2000], 160) or tr('Snippet')) if only else stand_in if bare else text, ts, cid)
    if bare:
        msg['placeholder'] = True
    if body is not None:
        attach(t, msg, body, name, only)
    if pictures:
        msg['images'] = []
        for n, pic in enumerate(pictures, 1):
            file = f"uploads/{t['id']}/{msg['id']}-{n}.{pic['ext']}"
            put_file(folder('uploads', t['id']) / f"{msg['id']}-{n}.{pic['ext']}", pic['raw'])
            record = {'file': file, 'name': pic['name'], 'bytes': len(pic['raw']), 'w': pic['w'], 'h': pic['h']}
            if pic.get('shrunk'):
                record['shrunk'] = pic['shrunk']
            small = put_thumb(t, f"{msg['id']}-{n}", pic)
            if small:       # shown until he taps the picture; the agents always get the picture itself
                record['thumb'] = small
            if pic['caption']:
                record['caption'] = pic['caption']
            msg['images'].append(record)
    if videos:
        msg['videos'] = []
        for n, clip in enumerate(videos, 1):
            base = f"{msg['id']}-v{n}"
            put_file(folder('uploads', t['id']) / f"{base}.{clip['ext']}", clip['raw'])
            record = {'file': f"uploads/{t['id']}/{base}.{clip['ext']}", 'name': clip['name'], 'bytes': len(clip['raw']), 'type': clip['ext'],
                      'w': clip['w'], 'h': clip['h'], 'seconds': clip['seconds']}
            if clip['poster']:      # its first frame, shown before it plays (a jpg made by ffmpeg, checked as any picture)
                put_file(folder('uploads', t['id']) / f"{base}.jpg", clip['poster']['raw'])
                record['poster'] = f"uploads/{t['id']}/{base}.jpg"
            if clip['caption']:
                record['caption'] = clip['caption']
            msg['videos'].append(record)
    if voice:
        # Not a reply for the agents yet: it becomes one when its words are in (see transcribe).
        voice = {**voice, 'raw': seekable_voice(voice['raw'], voice['ext'])}      # its length and an index (suda-fixes 80)
        put_file(folder('uploads', t['id']) / f"{msg['id']}.{voice['ext']}", voice['raw'])
        msg.update(text=tr('Voice recording'), placeholder=True, status='transcribing',
                   voice={'file': f"uploads/{t['id']}/{msg['id']}.{voice['ext']}", 'bytes': len(voice['raw']), 'seconds': voice['seconds'],
                          'state': 'transcribing', 'started': ts, 'tries': 1})
        t['voicing'] = [*(t['voicing'] if isinstance(t.get('voicing'), list) else []), msg['id']]
        noting['voice'].append([t['id'], msg['id']])
    if page:
        # Kept as .txt on purpose: the board's origin never serves an agent's HTML as a page of its own.
        put_file(folder('uploads', t['id']) / f"{msg['id']}.html.txt", page['raw'])
        msg['html'] = {'file': f"uploads/{t['id']}/{msg['id']}.html.txt", 'name': page['name'], 'bytes': len(page['raw'])}
    return msg


# ── a voice message ─────────────────────────────────────────────────────────

def seekable_voice(raw, ext):
    """A recording as MediaRecorder makes it (webm) has no duration and no index: a browser knows its length only
    once it has read all of it, and cannot seek in it (the player showed 0:00 / 0:00, suda-fixes 80). It is
    remuxed once, losslessly (ffmpeg -c copy: the same sound, a new container that says its duration). With no
    ffmpeg, or when it fails or gives something odd, the recording is kept as it came."""
    if ext != 'webm':
        return raw
    ffmpeg = os.environ.get('THREADS_FFMPEG', shutil.which('ffmpeg') or '')
    if not ffmpeg:
        return raw
    try:
        work = private_dir()
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(work), prefix='voice-') as tmp:
            src, out = Path(tmp) / 'in.webm', Path(tmp) / 'out.webm'
            src.write_bytes(raw)
            r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', 'file:' + str(src), '-map', '0:a', '-c', 'copy',
                                '-map_metadata', '-1', '-f', 'webm', 'file:' + str(out)], capture_output=True, timeout=60)
            done = out.read_bytes() if r.returncode == 0 and out.is_file() else b''
    except (OSError, subprocess.SubprocessError):
        return raw
    if done[:4] != b'\x1a\x45\xdf\xa3' or not len(raw) // 2 <= len(done) <= len(raw) * 2:
        return raw
    return done


def voice_remux(apply=False):
    """The recordings already on the board, made seekable as new ones are (seekable_voice). A list by default; with
    `apply`, each changed file keeps its original beside it (<name>.orig, never overwritten). The board's state is
    not touched: the files keep their names, and only their container changes."""
    ffprobe = os.environ.get('THREADS_FFPROBE', shutil.which('ffprobe') or '')

    def has_duration(path):
        if not ffprobe:
            return False
        r = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', 'file:' + str(path)],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and r.stdout.strip() not in ('', 'N/A')

    lines, todo = [], []
    with locked():
        data = load()
        for tid, t in all_threads(data).items():
            for m in t.get('messages', []):
                v = m.get('voice') if isinstance(m, dict) else None
                file = v.get('file') if isinstance(v, dict) else None
                if not (isinstance(file, str) and re.fullmatch(r'uploads/[a-z0-9][a-z0-9-]{0,47}/m\d+\.webm', file)):
                    continue
                path = BOARD / file
                if path.is_file() and not has_duration(path):
                    todo.append(path)
    for path in todo:
        rel = path.relative_to(BOARD).as_posix()
        if not apply:
            lines.append(f'would remux: {rel} ({path.stat().st_size} bytes)')
            continue
        raw = path.read_bytes()
        done = seekable_voice(raw, 'webm')
        if done is raw:
            lines.append(f'unchanged (ffmpeg missing or failed): {rel}')
            continue
        keep = path.with_name(path.name + '.orig')
        if not keep.exists():
            shutil.copy2(path, keep)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
        try:
            os.fchmod(fd, 0o644)
            with os.fdopen(fd, 'wb') as f:
                f.write(done)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        lines.append(f'remuxed: {rel} ({len(raw)} -> {len(done)} bytes; the original in {keep.name})')
    lines.append(f'{len(todo)} recording(s) without a duration' + ('' if apply else '; run with --apply to mend them'))
    return lines


def voice_ready():
    """Can this board turn a recording into words? Only the real board reads the real key: a test board
    or another BOARDS_DIR transcribes through the stand-in command, or not at all."""
    return bool(os.environ.get('THREADS_SONIOX_CMD')) or (real_board() and (Path.home() / '.soniox').is_file())


def voice_of(raw):
    """The recording of a reply from the page: {type?, data (base64), seconds}. Its kind is read from the bytes."""
    if not isinstance(raw, dict) or not isinstance(raw.get('data'), str) or not number(raw.get('seconds')) or not 0.1 <= raw['seconds'] <= VOICE_SECONDS:
        raise ValueError(tr('Invalid recording'))
    try:
        data = base64.b64decode(raw['data'], validate=True)
    except ValueError:
        raise ValueError(tr('Invalid recording')) from None
    ext = 'webm' if data[:4] == b'\x1a\x45\xdf\xa3' else 'm4a' if data[4:8] == b'ftyp' else 'ogg' if data[:4] == b'OggS' else None
    if ext is None or len(data) > VOICE_MAX:
        raise ValueError(tr('A recording of type webm, m4a or ogg, up to {mb}MB', mb=VOICE_MAX // 1_000_000))
    if not voice_ready():
        raise ValueError(tr('This server does not transcribe recordings'))
    return {'raw': data, 'ext': ext, 'seconds': round(float(raw['seconds']), 1)}


line = {'soniox': None}      # one kept connection to the transcription service: a new one costs half a second each time
leftovers = []                # what this process left at the service, to delete once the words are stored


def soniox(method, path, key, body=None, headers=None):
    """One call on the kept connection. Nothing follows a redirect; an error is its status and nothing more,
    so nothing of the key or of the request reaches a log."""
    for attempt in (1, 2):
        try:
            if line['soniox'] is None:
                line['soniox'] = http.client.HTTPSConnection('api.soniox.com', timeout=60)
            line['soniox'].request(method, '/v1' + path, body=body, headers={'Authorization': 'Bearer ' + key, **(headers or {})})
            answer = line['soniox'].getresponse()
            raw = answer.read()
            break
        except (http.client.HTTPException, OSError) as exc:
            if line['soniox'] is not None:
                line['soniox'].close()
            line['soniox'] = None
            # A kept connection the other side has closed: once more on a new one, but never a second upload or job.
            if attempt == 2 or method == 'POST':
                raise OSError(f'Soniox: no connection ({type(exc).__name__})') from None
    if answer.status >= 300:
        raise OSError(f'Soniox answered {answer.status}')
    return json.loads(raw) if raw else {}


def heard(path):
    """The words of a recording, by Soniox's ASYNC API (more accurate than the live one). The key is read
    here and only here, from ~/.soniox: it is never an argument of a command, never printed, never stored.
    The upload is named plainly. What is left at the service is deleted by tidy_voice(), after the words
    are stored: he does not wait for the cleaning."""
    stand_in = os.environ.get('THREADS_SONIOX_CMD')
    if stand_in:                                # tests: a command stands in for the service and prints the words
        return subprocess.run(shlex.split(stand_in) + [str(path)], capture_output=True, text=True, timeout=120, check=True).stdout.strip()
    if not real_board():                        # checked HERE, beside the key: no caller can forget it
        raise OSError('Soniox: this board does not transcribe')
    key = (Path.home() / '.soniox').read_text(encoding='utf-8').strip().split('=')[-1].strip().strip('"\'')
    if not key or len(key.split()) != 1:
        raise OSError('the Soniox key file is not one key')
    boundary = 'threads' + os.urandom(12).hex()
    kind = {'.webm': 'audio/webm', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg'}[path.suffix]
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice{path.suffix}"\r\nContent-Type: {kind}\r\n\r\n'.encode()
            + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
    upload = soniox('POST', '/files', key, body, {'Content-Type': f'multipart/form-data; boundary={boundary}'})['id']
    leftovers.append((f'/files/{upload}', key))
    job = soniox('POST', '/transcriptions', key, json.dumps({'model': VOICE_MODEL, 'file_id': upload, 'language_hints': ['he', 'en']}).encode(),
                 {'Content-Type': 'application/json'})['id']
    leftovers.insert(0, (f'/transcriptions/{job}', key))
    began, pause = time.time(), 0.35
    while True:                                 # the job takes about three seconds: ask often at first, then less and less
        time.sleep(pause)
        status = soniox('GET', f'/transcriptions/{job}', key)
        if status.get('status') == 'completed':
            break
        if status.get('status') == 'error' or time.time() - began > 600:
            raise OSError('Soniox: ' + one_line(str(status.get('error_message') or status.get('error_type') or 'no answer in ten minutes'))[:120])
        if time.time() - began > 8:
            pause = min(pause * 1.5, 2.0)
    return str(soniox('GET', f'/transcriptions/{job}/transcript', key).get('text') or '').strip()


def tidy_voice():
    """Delete from the service what this process uploaded and asked for. After the words are stored (or the failure is)."""
    while leftovers:
        path, key = leftovers.pop(0)
        try:
            soniox('DELETE', path, key)
        except (OSError, ValueError):
            pass
    if line['soniox'] is not None:
        line['soniox'].close()
        line['soniox'] = None


def settle_voice(t, msg, text, problem, ts):
    """The recording has its words (or will never have them): now it is a reply like any other."""
    voice = msg['voice']
    voice.update(state='failed' if problem else 'done')
    voice.pop('started', None)
    voice.pop('tries', None)
    if problem:
        voice['error'] = problem
        msg['text'] = tr('(voice recording: the transcription failed. The file is kept, and its path is attached)')
    else:
        msg['text'] = text or tr('(voice recording: no words were recognized in it)')
        msg.pop('placeholder', None)
    msg['status'] = 'pending'
    t['voicing'] = [mid for mid in t.get('voicing', []) if mid != msg['id']]
    if not t['voicing']:
        del t['voicing']
    t['updated'] = ts
    if t['status'] == 'open' and t['state'] == 'working' and t['auto'] and t['state_by'] == 'tower':
        t['note'] = waiting_note(msg)


def retry_voice(t, mid, ts):
    """A worker that died leaves its message in the air: the timer starts another, and after three the
    message is handed over without words rather than lost."""
    msg = next((m for m in t['messages'] if m['id'] == mid), None)
    voice = msg.get('voice') if msg else None
    if not isinstance(voice, dict) or voice.get('state') != 'transcribing':
        t['voicing'] = [x for x in t.get('voicing', []) if x != mid]
        if not t['voicing']:
            del t['voicing']
        return
    if ts - (voice.get('started') if number(voice.get('started')) else 0) < 15 * 60:
        return
    tried_out = (voice.get('tries') if type(voice.get('tries')) is int else 1) >= 3
    if tried_out or not voice_ready():
        settle_voice(t, msg, None, 'no transcript after three tries' if tried_out else 'this board does not transcribe', ts)
        waking.append((f"[threads] reply in {t['id']} ({mid}): a voice message that could not be transcribed: run: threads pending", f"{t['id']} {mid}", t['id'], 'reply'))
    else:
        voice.update(started=ts, tries=(voice.get('tries') if type(voice.get('tries')) is int else 1) + 1)
        noting['voice'].append([t['id'], mid])


def transcribe(tid, mid):
    """The slow half of a voice message, in a process of its own (the page already has its receipt)."""
    try:
        t = peek_thread(tid) or {}     # a look without the lock: only to find the file
        msg = find_message(t, mid)
        if not re.fullmatch(ID, tid) or t.get('id') != tid or not isinstance(msg.get('voice'), dict) or msg['voice'].get('state') != 'transcribing':
            return
        path = file_path(t, 'uploads', msg['voice']['file'])
        if path.name not in (f'{mid}.webm', f'{mid}.m4a', f'{mid}.ogg'):       # only ever this message's own recording
            return
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return
    try:
        text, problem = heard(path), None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        text, problem = None, one_line(str(exc)[8:] if isinstance(exc, OSError) and str(exc).startswith('Soniox: ') else
                                       str(exc) if isinstance(exc, OSError) and str(exc).startswith('Soniox') else type(exc).__name__)[:160]
    ts = now()
    with locked():
        data = load()
        t = data['threads'].get(tid)
        msg = next((m for m in t['messages'] if m['id'] == mid), None) if t else None
        if not msg or not isinstance(msg.get('voice'), dict) or msg['voice'].get('state') != 'transcribing':
            return      # settled meanwhile (another worker, or the thread is gone)
        settle_voice(t, msg, text, problem, ts)
        save(data)
    notify(tid, msg)


# ── a command of the tower's that he asks to run ────────────────────────────

def command_of(msg, index):
    """The command in code block `index` of a message, when it is one he may ask to run: a block the TOWER
    wrote, 1 to 10 lines that each start with "! ", nothing but printable ASCII (what he approves on the
    screen is exactly what is stored), up to 2000 characters. Else None. The page applies the same rule."""
    blocks, current = [], None
    for line in msg['text'].split('\n'):
        if re.match(r'[ \t]*```', line):       # spaces and tabs only, here and below: the page and the server must read a block alike
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    if msg['from'] != 'tower' or type(index) is not int or not 0 <= index < len(blocks):
        return None
    lines = [line.strip(' \t\r') for line in blocks[index] if line.strip(' \t\r')]
    command = '\n'.join(lines)
    if not 1 <= len(lines) <= 10 or len(command) > 2000 or not all(re.match(r'! \S', line) for line in lines) or not re.fullmatch(r'[\x20-\x7e\n]+', command):
        return None
    return command


def run_asked(t, raw):
    """Check his request to run a command against the tower's own stored message. Nothing runs here, ever:
    the tower reads the request, takes the command from ITS message, and decides."""
    if not isinstance(raw, dict) or not isinstance(raw.get('msg_id'), str) or type(raw.get('block_index')) is not int or not isinstance(raw.get('sha256'), str):
        raise ValueError(tr('Invalid run request'))
    source = next((m for m in t['messages'] if m['id'] == raw['msg_id']), None)
    command = command_of(source, raw['block_index']) if source else None
    if command is None:
        raise ValueError(tr("This message has no command of the tower's that can be asked to run"))
    if hashlib.sha256(command.encode('utf-8')).hexdigest() != raw['sha256']:
        raise ValueError(tr('The command on the screen differs from the one the tower wrote. Reload the page and try again'))
    if any(m['from'] == OWNER and m.get('status') == 'pending' and isinstance(m.get('run'), dict)
           and (m['run'].get('msg_id'), m['run'].get('block_index')) == (raw['msg_id'], raw['block_index']) for m in t['messages']):
        raise ValueError(tr('You already asked to run this command, and the tower has not picked up the request yet'))
    return {'msg_id': raw['msg_id'], 'block_index': raw['block_index'], 'sha256': raw['sha256']}


def agent_command(raw):
    """The command of a reply he sent from the reply box ({name, args}), checked: a known agent command, its words
    as one line within their limit, on a plain typed reply whose text is the command line (no picture, recording,
    snippet or answer beside it). /run carries the ▶ request it is (`run`, checked by run_asked); no other does. Its
    text is the server's own ("▶ Run ...", written over whatever the page sent), so it need not start with "/"."""
    c = raw['command']
    if not (isinstance(c, dict) and set(c) == {'name', 'args'} and c['name'] in AGENT_COMMANDS and isinstance(c['args'], str)):
        raise ValueError(tr('Invalid command: one of {names}, with its words', names=', '.join('/' + n for n in AGENT_COMMANDS)))
    kind, words = AGENT_COMMANDS[c['name']], c['args']
    most = LIMITS['title'] if kind == 'title' else COMMAND_ARGS_MAX
    if '\n' in words or '\r' in words or len(one_line(words)) > most:
        raise ValueError(tr('/{name}: one line of up to {n} characters', name=c['name'], n=most))
    words = one_line(words)
    if kind == 'none' and words:
        raise ValueError(tr('/{name} takes no words after it', name=c['name']))
    if kind == 'title' and blank(words):
        raise ValueError(tr('/{name}: the title of the new topic', name=c['name']))
    if any(k in raw for k in ('images', 'voice', 'snippet', 'answer', 'q')) or not isinstance(raw.get('text'), str) \
            or (c['name'] != 'run' and not raw['text'].lstrip().startswith('/')):
        raise ValueError(tr('A command is sent alone, on a line of its own'))
    if (c['name'] == 'run') != ('run' in raw):
        raise ValueError(tr("/run asks for a tower's ▶ block") if c['name'] == 'run' else tr('A command is sent alone, on a line of its own'))
    storable(words)
    return {'name': c['name'], 'args': words}


def page_task_text(raw):
    """The words of a task he typed on the page (/task ...): as `threads task add` and `task set --text` take them."""
    text = raw.get('text')
    if not isinstance(text, str) or blank(text):
        raise ValueError(tr('Empty task'))
    text = one_line(text)
    if len(text) > LIMITS['task']:
        raise ValueError(tr('Task: up to {n} characters', n=LIMITS['task']))
    storable(text)
    return text


def next_task(data, t):
    """The number of a new task: numbers are never reused (tasks are never deleted, and a removed thread's are remembered)."""
    return max([k['n'] for k in t['tasks']] + [data.get('retired_tasks', {}).get(t['id'], 0)]) + 1


# ── pictures ────────────────────────────────────────────────────────────────

def shown(text):
    """A label as it may be shown and printed: no control characters, no hidden direction marks."""
    return one_line(''.join(ch for ch in text if ch.isspace() or unicodedata.category(ch)[0] != 'C'))


def picture(raw, name=None, caption=None):
    """One picture, checked and cleaned before anything is written. Its kind is read from the bytes (never
    from the name); there must really be a picture inside; and only what a decoder needs is kept, so what a
    camera or an editor adds beside the pixels (place, device, time, comments, private blocks) is gone."""
    if not isinstance(raw, bytes) or not raw or len(raw) > IMAGE_MAX:
        raise ValueError(tr('An empty or too big picture: up to {mb}MB per picture', mb=IMAGE_MAX // 1_000_000))
    if caption is not None and not isinstance(caption, str):
        raise ValueError(tr('Invalid caption'))
    caption = shown(caption or '')
    if len(caption) > CAPTION_MAX:
        raise ValueError(tr('The caption is too long: up to {max} characters', max=CAPTION_MAX))
    try:
        if raw[:3] == b'\xff\xd8\xff':
            ext, (raw, w, h) = 'jpg', clean_jpeg(raw)
        elif raw[:8] == b'\x89PNG\r\n\x1a\n':
            ext, (raw, w, h) = 'png', clean_png(raw)
        elif raw[:6] in (b'GIF87a', b'GIF89a'):
            ext, (raw, w, h) = 'gif', clean_gif(raw)
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            ext, (raw, w, h) = 'webp', clean_webp(raw)
        else:
            raise ValueError(tr('This is not a picture of type jpg, png, gif or webp'))
    except (struct.error, IndexError):
        raise DAMAGED() from None
    if not w or not h or w * h > PIXELS_MAX:
        raise ValueError(tr('The picture file is damaged, or the picture is bigger than {mp} megapixels', mp=PIXELS_MAX // 1_000_000))
    base = shown(re.split(r'[\\/]', name if isinstance(name, str) else '')[-1])[:120]
    return {'raw': raw, 'ext': ext, 'w': w, 'h': h, 'name': base or None, 'caption': caption}


def DAMAGED():
    """A picture that cannot be read as one (made when it is refused: its words are the installation's)."""
    return ValueError(tr('The picture file is damaged'))


PIXELS_MAX = 50_000_000
PNG_KEEP = frozenset((b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'iCCP', b'sBIT', b'pHYs', b'bKGD', b'cICP',
                      b'acTL', b'fcTL', b'fdAT'))
WEBP_KEEP = frozenset((b'VP8 ', b'VP8L', b'VP8X', b'ALPH', b'ANIM', b'ANMF', b'ICCP'))


def turned(turn):
    """A TIFF block with one tag, the orientation: all that is kept of a picture's EXIF when it is stored turned."""
    return b'MM\0*' + struct.pack('>IH', 8, 1) + struct.pack('>HHIHH', 0x0112, 3, 1, turn, 0) + struct.pack('>I', 0)


def clean_jpeg(raw):
    """Keep the segments a decoder needs: the tables, the frame, the scans, JFIF, a colour profile, Adobe's
    colour marker. Every other application segment, every comment and whatever follows the end of the
    picture is dropped. A picture stored turned keeps a tiny EXIF that says only how to turn it."""
    out_, i, turn, size, scanned = [raw[:2]], 2, 1, (0, 0), False
    stuffed = frozenset((0x00, *range(0xD0, 0xD8)))     # inside a scan: a stuffed zero, or a restart marker
    while i + 2 <= len(raw):
        if raw[i] != 0xFF:
            raise DAMAGED()
        marker = raw[i + 1]
        if marker == 0xFF:                      # fill byte
            i += 1
            continue
        if marker == 0xD9:                      # the end: nothing after it is part of the picture
            out_.append(b'\xff\xd9')
            break
        if marker in (0x01, *range(0xD0, 0xD8)):
            out_.append(raw[i:i + 2])
            i += 2
            continue
        length = struct.unpack('>H', raw[i + 2:i + 4])[0]
        segment = raw[i:i + 2 + length]
        if length < 2 or len(segment) != 2 + length:
            raise DAMAGED()
        i += 2 + length
        if marker == 0xE1 and segment[4:10] == b'Exif\0\0':
            turn = orientation(segment[10:]) or turn
        if marker in (*range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC), *range(0xCD, 0xD0)):
            size = struct.unpack('>HH', segment[5:9])[::-1]
        if marker == 0xDA:                      # a scan: its data runs to the next real marker
            j = i
            while True:
                j = raw.find(b'\xff', j)
                if j < 0 or j + 1 >= len(raw):
                    raise DAMAGED()
                if raw[j + 1] in stuffed:
                    j += 2
                elif raw[j + 1] == 0xFF:
                    j += 1
                else:
                    break
            out_.append(segment + raw[i:j])
            i, scanned = j, True
        elif 0xE0 <= marker <= 0xEF:            # an application segment is kept only for what it is known to hold
            if ((marker == 0xE0 and segment[4:9] in (b'JFIF\0', b'JFXX\0')) or (marker == 0xE2 and segment[4:16] == b'ICC_PROFILE\0')
                    or (marker == 0xEE and segment[4:9] == b'Adobe')):
                out_.append(segment)
        elif marker != 0xFE and not 0xF0 <= marker <= 0xFD:
            out_.append(segment)
    else:
        raise DAMAGED()
    if not scanned:
        raise DAMAGED()
    if 2 <= turn <= 8:
        tiff = turned(turn)
        out_.insert(1, b'\xff\xe1' + struct.pack('>H', 8 + len(tiff)) + b'Exif\0\0' + tiff)
    w, h = size
    return b''.join(out_), *((h, w) if turn >= 5 else (w, h))


def orientation(tiff):
    """The EXIF orientation (1 to 8) of a TIFF block, or None."""
    try:
        order = {b'II': '<', b'MM': '>'}[tiff[:2]]
        offset = struct.unpack(order + 'I', tiff[4:8])[0]
        for k in range(struct.unpack(order + 'H', tiff[offset:offset + 2])[0]):
            tag, kind, _, value = struct.unpack(order + 'HHIH', tiff[offset + 2 + 12 * k:offset + 12 + 12 * k])
            if tag == 0x0112 and kind == 3:
                return value if 1 <= value <= 8 else None
    except (KeyError, struct.error):
        pass
    return None


def clean_png(raw):
    """Keep the chunks a decoder needs (header, palette, pixels, colour, animation); drop every other one."""
    out_, i, size, pixels = [raw[:8]], 8, None, False
    while i + 12 <= len(raw):
        length, kind = struct.unpack('>I4s', raw[i:i + 8])
        chunk = raw[i:i + 12 + length]
        if len(chunk) != 12 + length or (size is None) != (kind == b'IHDR'):      # the header comes first, and once
            raise DAMAGED()
        if kind == b'IHDR':
            size = struct.unpack('>II', chunk[8:16])
        pixels = pixels or kind == b'IDAT'
        if kind in PNG_KEEP:
            out_.append(chunk)
        i += 12 + length
        if kind == b'IEND':
            if not pixels:
                raise DAMAGED()
            return b''.join(out_), *size
    raise DAMAGED()


def clean_gif(raw):
    """Walk the blocks: keep the pictures, their timing and the loop count; drop comments, text and every
    other application block (XMP lives in one), and stop at the end marker."""
    w, h = struct.unpack('<HH', raw[6:10])
    i = 13 + ((3 << ((raw[10] & 7) + 1)) if raw[10] & 0x80 else 0)
    out_, frames = [raw[:i]], 0

    def after(j):           # the index after a run of data sub-blocks
        while True:
            n = raw[j]
            j += 1 + n
            if n == 0:
                return j
    while True:
        kind = raw[i]
        if kind == 0x3B:
            out_.append(b';')
            break
        if kind == 0x2C:        # a picture: its descriptor, its own palette, the code size, the data
            j = after(i + 10 + ((3 << ((raw[i + 9] & 7) + 1)) if raw[i + 9] & 0x80 else 0) + 1)
            keep, frames = True, frames + 1
        elif kind == 0x21:
            j = after(i + 2)
            keep = raw[i + 1] == 0xF9 or (raw[i + 1] == 0xFF and raw[i + 2] == 11 and raw[i + 3:i + 14] in (b'NETSCAPE2.0', b'ANIMEXTS1.0'))
        else:
            raise DAMAGED()
        if j > len(raw):
            raise DAMAGED()
        if keep:
            out_.append(raw[i:j])
        i = j
    if not frames:
        raise DAMAGED()
    return b''.join(out_), w, h


def clean_webp(raw):
    """Keep the picture chunks, the colour profile and the animation; drop every other chunk and whatever
    lies past the end the file declares. A picture stored turned keeps only the tag that says how to turn it."""
    end = min(len(raw), 8 + struct.unpack('<I', raw[4:8])[0])
    chunks, i, size, turn, extended, pixels = [], 12, (0, 0), None, False, False
    while i + 8 <= end:
        kind, length = struct.unpack('<4sI', raw[i:i + 8])
        data = raw[i + 8:i + 8 + length]
        if len(data) != length or i + 8 + length > end:
            raise DAMAGED()
        if kind == b'VP8X':
            if len(data) < 10:
                raise DAMAGED()
            extended = True
            data = bytes([data[0] & ~0x0C]) + data[1:]          # no EXIF, no XMP: say so in the header too
            size = (int.from_bytes(data[4:7], 'little') + 1, int.from_bytes(data[7:10], 'little') + 1)
        elif kind == b'VP8 ' and not any(size):
            size = tuple(v & 0x3FFF for v in struct.unpack('<HH', data[6:10]))
        elif kind == b'VP8L' and not any(size):
            bits = int.from_bytes(data[1:5], 'little')
            size = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        elif kind == b'EXIF':
            turn = orientation(data[6:] if data[:6] == b'Exif\0\0' else data)
        pixels = pixels or kind in (b'VP8 ', b'VP8L', b'ANMF')
        if kind in WEBP_KEEP:
            chunks.append(struct.pack('<4sI', kind, length) + data + (b'\0' if length % 2 else b''))
        i += 8 + length + length % 2
    if not pixels:
        raise DAMAGED()
    if extended and turn and 2 <= turn <= 8:
        chunks = [c[:8] + bytes([c[8] | 0x08]) + c[9:] if c[:4] == b'VP8X' else c for c in chunks]
        chunks.append(struct.pack('<4sI', b'EXIF', 26) + turned(turn))
        size = size[::-1] if turn >= 5 else size
    body = b'WEBP' + b''.join(chunks)
    return b'RIFF' + struct.pack('<I', len(body)) + body, *size


def pictures_of(raw):
    """The pictures of a reply from the page: [{name?, type?, data (base64), caption?}]."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= IMAGES_MAX:
        raise ValueError(tr('Pictures: between 1 and {max} in a message', max=IMAGES_MAX))
    found = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('data'), str):
            raise ValueError(tr('Invalid picture'))
        try:
            data = base64.b64decode(item['data'], validate=True)
        except ValueError:
            raise ValueError(tr('Invalid picture')) from None
        pic = picture(data, item.get('name'), item.get('caption'))
        # his page sent it smaller than he took it (a slow link): the sides of the original, so the page can say the
        # full quality never reached the server (m198). Kept when sane, dropped otherwise, never a refusal.
        orig = item.get('shrunk')
        if isinstance(orig, dict) and all(type(orig.get(k)) is int and 1 <= orig[k] <= 20000 for k in ('w', 'h')) \
                and orig['w'] * orig['h'] > pic['w'] * pic['h']:
            pic['shrunk'] = {'w': orig['w'], 'h': orig['h']}
        found.append(pic)
    return found


def image_rows(t, m):
    """The pictures of a message as an agent needs them: where each file is, and what he wrote under it."""
    rows = []
    for record in m.get('images') if isinstance(m.get('images'), list) else []:
        try:
            rows.append({'path': str(file_path(t, 'uploads', record['file'])), **{k: record.get(k) for k in ('caption', 'name', 'bytes', 'w', 'h')},
                         **({'shrunk': record['shrunk']} if isinstance(record.get('shrunk'), dict) else {})})       # his page sent it smaller than the original
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    return rows


# ── videos ──────────────────────────────────────────────────────────────────
# A video is attached by an agent (`say --video FILE`): an mp4 or a webm, read from its bytes. The page plays it
# from the board (a <video> with its own controls), so it must be one a browser plays and must start without the
# whole file: an mp4 is stored with its index (moov) before the frames. What a camera or an editor writes beside
# the frames (the place, the device, a title, a date) is not stored: in an mp4 the udta, meta and uuid boxes, in a
# webm its Tags, Attachments and the Title and date of its Info. Where the file cannot be moved (a fragmented mp4,
# offsets outside the frames) they are blanked in place, so every offset still holds.


class Untranslated(ValueError):
    """A refusal made once, when the file loads: its English text is put in the installation's language when shown."""
    def __str__(self):
        return tr(self.args[0])


NOT_A_VIDEO = Untranslated('--video: not an mp4 or webm video')
DAMAGED_VIDEO = Untranslated('--video: the video file is damaged')
NO_PICTURE = Untranslated('--video: it holds no picture (only sound?)')
MP4_BRANDS = frozenset((b'isom', b'iso2', b'iso3', b'iso4', b'iso5', b'iso6', b'iso7', b'iso8', b'iso9', b'mp41', b'mp42', b'avc1',
                        b'av01', b'dash', b'M4V ', b'M4VH', b'M4VP', b'MSNV', b'mmp4'))
MP4_INSIDE = (b'moov', b'trak', b'mdia', b'minf', b'stbl')     # the boxes walked down to the chunk offsets
MP4_PRIVATE = (b'udta', b'meta', b'uuid')                       # what a camera or an editor adds (XMP is a uuid): dropped
MP4_DROPPED = (b'free', b'skip', b'wide', *MP4_PRIVATE)         # top-level boxes that hold no frames
# The tracks a video may carry. Another kind (a GoPro's gpmd, camm: where the camera was, second by second) is refused.
MP4_TRACKS = frozenset((b'vide', b'soun', b'tmcd', b'text', b'sbtl', b'subt'))
SECONDS_MAX = 10_000_000


def clip_seconds(value):
    """A length as it may be stored: a number JSON can hold, of a video that could be (else 0, unknown)."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return round(value, 1) if math.isfinite(value) and 0 < value <= SECONDS_MAX else 0


def mp4_boxes(raw, start, end):
    """The boxes between `start` and `end`: [(kind, start, body, end)]. One that runs past its parent: damaged."""
    found, at = [], start
    while at < end:
        if end - at < 8 or len(found) > 200_000:
            raise DAMAGED_VIDEO
        size, kind = struct.unpack_from('>I4s', raw, at)
        body = at + 8
        if size == 1:
            size, body = struct.unpack_from('>Q', raw, at + 8)[0], at + 16
        elif size == 0:
            size = end - at
        if size < body - at or at + size > end:
            raise DAMAGED_VIDEO
        found.append((kind, at, body, at + size))
        at += size
    return found


def mp4_blanked(raw, top):
    """The file with every private box (at the top and down the road to the offsets) made free space of the same
    size: nothing moves, so every offset still holds."""
    out, todo = None, [(box, 0) for box in top]
    while todo:
        (kind, start, body, end), depth = todo.pop()
        if kind in MP4_PRIVATE:
            out = out if out is not None else bytearray(raw)
            out[start + 4:start + 8] = b'free'
            out[body:end] = bytes(end - body)
        elif depth < len(MP4_INSIDE) and kind == MP4_INSIDE[depth]:
            todo += [(kid, depth + 1) for kid in mp4_boxes(raw, body, end)]
    return raw if out is None else out


def clean_mp4(raw):
    """An mp4 as the page needs it: (bytes, w, h, seconds). Its index (moov) first, so playing starts before the
    rest has arrived (the board server does not answer a request for a part of a file), and nothing private. The
    chunk offsets inside the index are moved with the frames, in arrays of machine numbers (never one Python
    number each). A fragmented mp4, or one whose offsets point outside its frames, is blanked in place instead."""
    top = mp4_boxes(raw, 0, len(raw))
    if top[0][0] != b'ftyp':
        raise NOT_A_VIDEO
    brand = raw[top[0][2]:top[0][2] + 4]
    if brand == b'qt  ':
        raise ValueError(tr('--video: this is a QuickTime video (mov), and a browser does not always play it. Convert it to mp4: ffmpeg -i IN.mov -c copy OUT.mp4'))
    if brand not in MP4_BRANDS:
        raise NOT_A_VIDEO
    moovs = [box for box in top if box[0] == b'moov']
    if len(moovs) != 1 or not any(box[0] in (b'mdat', b'moof') for box in top):
        raise DAMAGED_VIDEO
    moov = moovs[0]
    kids = mp4_boxes(raw, moov[2], moov[3])
    seconds = 0
    for kind, _, body, end in kids:
        if kind == b'mvhd' and end - body >= 32:
            scale, length = struct.unpack_from('>IQ', raw, body + 20) if raw[body] == 1 else struct.unpack_from('>II', raw, body + 12)
            if scale and length not in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                seconds = clip_seconds(length / scale)
    size = None
    for kind, _, body, end in kids:
        if kind != b'trak':
            continue
        parts = mp4_boxes(raw, body, end)
        heads = [p for p in parts if p[0] == b'tkhd']
        for mdia in (p for p in parts if p[0] == b'mdia'):
            for hdlr in (p for p in mp4_boxes(raw, mdia[2], mdia[3]) if p[0] == b'hdlr'):
                handler = raw[hdlr[2] + 8:hdlr[2] + 12]
                if handler not in MP4_TRACKS:
                    raise ValueError(tr("--video: it has a data track ({kind}), for example where a camera was from moment to moment. "
                                        'Keep only the picture and the sound: ffmpeg -i IN -map 0:v -map 0:a? -c copy -map_metadata -1 OUT.mp4',
                                        kind=handler.decode('latin-1').strip()))
                if handler == b'vide' and heads and size is None and heads[0][3] - heads[0][2] >= 84:
                    w, h = struct.unpack_from('>II', raw, heads[0][3] - 8)
                    size = (w >> 16, h >> 16)
    if size is None:
        raise NO_PICTURE
    if any(box[0] == b'moof' for box in top) or any(kid[0] == b'mvex' for kid in kids):
        return mp4_blanked(raw, top), *size, seconds
    kept = [box for box in top if box[0] not in (b'ftyp', b'moov', *MP4_DROPPED)]
    view = memoryview(raw)

    def written(box, depth=0):
        kind, start, body, end = box
        if depth < len(MP4_INSIDE) and kind == MP4_INSIDE[depth]:      # down the one road to the offsets, never deeper
            return 8 + sum(written(kid, depth + 1) for kid in mp4_boxes(raw, body, end) if kid[0] not in MP4_PRIVATE)
        return end - start                                              # (the offsets take as many bytes after as before)
    head = top[0]
    at, moved = head[3] - head[1] + written(moov), []
    for box in kept:
        moved.append((box[1], box[3], at))
        at += box[3] - box[1]
    starts = [start for start, _, _ in moved]

    def offsets(numbers):
        """Every offset where its frames now are: one shift for the box they all lie in, else each its own."""
        if not numbers:
            return
        low, high = min(numbers), max(numbers)
        i = bisect.bisect_right(starts, low) - 1
        if i >= 0 and high < moved[i][1]:
            shift = moved[i][2] - moved[i][0]
            if shift:
                for k in range(len(numbers)):
                    numbers[k] += shift
            return
        for k in range(len(numbers)):
            i = bisect.bisect_right(starts, numbers[k]) - 1
            if i < 0 or numbers[k] >= moved[i][1]:
                raise LookupError(numbers[k])
            numbers[k] += moved[i][2] - moved[i][0]

    def write(box, out, depth=0):
        kind, start, body, end = box
        if depth < len(MP4_INSIDE) and kind == MP4_INSIDE[depth]:
            place = len(out)
            out += b'\0\0\0\0' + kind
            for kid in mp4_boxes(raw, body, end):
                if kid[0] not in MP4_PRIVATE:
                    write(kid, out, depth + 1)
            struct.pack_into('>I', out, place, len(out) - place)
        elif kind in (b'stco', b'co64'):
            width = 8 if kind == b'co64' else 4
            count = struct.unpack_from('>I', raw, body + 4)[0]
            if body + 8 + count * width > end:
                raise DAMAGED_VIDEO
            numbers = array.array('Q' if width == 8 else 'I')         # (8 and 4 bytes on every platform Python runs on here)
            numbers.frombytes(view[body + 8:body + 8 + count * width])
            if sys.byteorder == 'little':
                numbers.byteswap()
            offsets(numbers)
            if sys.byteorder == 'little':
                numbers.byteswap()
            out += view[start:body + 8]
            out += numbers
            out += view[body + 8 + count * width:end]
        else:
            out += view[start:end]
    out = bytearray(view[head[1]:head[3]])
    try:
        write(moov, out)
    except (LookupError, OverflowError):        # frames outside the boxes that hold them: blanked in place, it may still play
        return mp4_blanked(raw, top), *size, seconds
    for box in kept:
        out += view[box[1]:box[3]]
    return out, *size, seconds


# A webm: its elements, what describes the frames, and what is private.
WEBM_HEAD, WEBM_SEGMENT, WEBM_CLUSTER, WEBM_INFO, WEBM_TRACKS = 0x1A45DFA3, 0x18538067, 0x1F43B675, 0x1549A966, 0x1654AE6B
WEBM_PRIVATE = (0x1254C367, 0x1941A469)         # Tags (a place, a title, an author), Attachments (a cover picture)
WEBM_INFO_PRIVATE = (0x7BA9, 0x4461)            # the Title and the date (DateUTC) of the Info
# The elements of the segment itself: where the frames of a cluster of no size end.
WEBM_TOP = frozenset((WEBM_CLUSTER, WEBM_INFO, WEBM_TRACKS, *WEBM_PRIVATE, 0x1C53BB6B, 0x114D9B74, 0x1043A770))


def ebml(raw, at, end, left):
    """The elements of a webm between `at` and `end`: (id, start, body, stop, unknown size). `left` is how many
    elements the whole walk may still read (one list for all of it)."""
    while at < end:
        left[0] -= 1
        if left[0] < 0:
            raise DAMAGED_VIDEO
        start, first = at, raw[at]
        n = next((i + 1 for i in range(4) if first & (0x80 >> i)), 0)
        if not n:
            raise DAMAGED_VIDEO
        ident, at = int.from_bytes(raw[at:at + n], 'big'), at + n
        first = raw[at]
        n = next((i + 1 for i in range(8) if first & (0x80 >> i)), 0)
        if not n or at + n > end:
            raise DAMAGED_VIDEO
        size, at = int.from_bytes(raw[at:at + n], 'big') & ((1 << 7 * n) - 1), at + n
        unknown = size == (1 << 7 * n) - 1
        stop = end if unknown else at + size
        if stop > end:
            raise DAMAGED_VIDEO
        yield ident, start, at, stop, unknown
        at = stop


def ebml_void(length):
    """An EBML Void element of exactly `length` bytes (at least 2): what stands where a private element was."""
    n = min(8, length - 1)
    return bytes([0xEC]) + ((length - 1 - n) | (1 << 7 * n)).to_bytes(n, 'big') + bytes(length - 1 - n)


def clean_webm(raw):
    """A webm as it is stored: (bytes, w, h, seconds). Its private elements become Void of the same length (nothing
    moves); its size and length are read from its Info and its Tracks. The clusters are stepped over by their size;
    the frames of a cluster of no size (a live recording) are read up to the next element of the segment."""
    left = [2_000_000]
    top = ebml(raw, 0, len(raw), left)
    ident, _, body, stop, _ = next(top)
    if ident != WEBM_HEAD or next((raw[b:s] for i, _, b, s, _ in ebml(raw, body, stop, left) if i == 0x4282), b'').rstrip(b'\0') != b'webm':
        raise NOT_A_VIDEO
    segment = next((e for e in top if e[0] == WEBM_SEGMENT), None)
    if segment is None:
        raise DAMAGED_VIDEO
    uint = lambda b, s: int.from_bytes(raw[b:s], 'big') if s - b <= 8 else 0      # a number of more than 8 bytes is none
    scale, length, size, voids = 1_000_000, None, None, []
    at, end = segment[2], segment[3]
    while at is not None:
        walk, at = ebml(raw, at, end, left), None
        for ident, start, body, stop, unknown in walk:
            if ident == WEBM_CLUSTER and unknown:
                at = next((kid[1] for kid in ebml(raw, body, end, left) if kid[0] in WEBM_TOP), None)
                break
            if unknown:                     # nothing after an element of no size can be found
                break
            if ident in WEBM_PRIVATE:
                voids.append((start, stop))
            elif ident == WEBM_INFO:
                for i, st, b, s, _ in ebml(raw, body, stop, left):
                    if i == 0x2AD7B1:
                        scale = uint(b, s) or scale
                    elif i == 0x4489 and s - b in (4, 8):
                        length = struct.unpack('>f' if s - b == 4 else '>d', raw[b:s])[0]
                    elif i in WEBM_INFO_PRIVATE:
                        voids.append((st, s))
            elif ident == WEBM_TRACKS:
                for entry in (e for e in ebml(raw, body, stop, left) if e[0] == 0xAE):
                    fields = {i: (b, s) for i, _, b, s, _ in ebml(raw, entry[2], entry[3], left)}
                    if 0x83 in fields and uint(*fields[0x83]) == 1 and size is None:
                        pixels = {i: uint(b, s) for i, _, b, s, _ in ebml(raw, *fields[0xE0], left)} if 0xE0 in fields else {}
                        size = tuple(v if 0 < v <= 65535 else 0 for v in (pixels.get(0xB0, 0), pixels.get(0xBA, 0)))
    if size is None:
        raise NO_PICTURE
    seconds = clip_seconds(length * scale / 1e9) if isinstance(length, float) and math.isfinite(length) else 0
    if voids:
        raw = bytearray(raw)
        for start, stop in voids:
            raw[start:stop] = ebml_void(stop - start)
    return raw, *size, seconds


THUMB_EDGE = 720           # the long side of the small copy of a picture, in px (the page shows a picture up to 360 px wide)
THUMB_FROM = 96_000        # bytes: a picture this small, and no longer than THUMB_EDGE, is shown as it is
THUMB_WORTH = 0.6          # the small copy is kept only when it is at most this part of the picture
THUMB_BUDGET = 20          # seconds, all the small copies of one run together: the board server stops its hook at 60
THUMB_EACH = 10            # seconds for one copy
_thumb_until = None        # when this run stops making copies (set by the first one)


def moving(raw, ext):
    """Whether a picture moves (an animated gif, png or webp): a still copy would show it frozen, so it gets none."""
    if ext == 'gif':
        return b'NETSCAPE2.0' in raw or b'ANIMEXTS1.0' in raw or raw.count(b'\x21\xf9\x04') > 1
    if ext == 'png':
        end = raw.find(b'IDAT')
        return b'acTL' in raw[:end if end > 0 else len(raw)]
    if ext == 'webp':
        return raw[12:16] == b'VP8X' and bool(raw[20] & 0x02)
    return False


def see_through(raw, ext):
    """Whether a picture may have pixels one sees through: its small copy is then a png, which keeps them."""
    if ext == 'png':
        end = raw.find(b'IDAT')
        return raw[25] in (4, 6) or b'tRNS' in raw[:end if end > 0 else len(raw)]
    if ext == 'webp':
        return raw[12:16] == b'VP8L' or (raw[12:16] == b'VP8X' and bool(raw[20] & 0x10))
    return ext == 'gif'


def thumb_of(pic):
    """A small copy of a big picture, which the page shows in the conversation until he taps it (the picture itself
    opens then): its long side THUMB_EDGE, a jpg, or a png when it can be seen through. Made by ffmpeg when it is on
    this machine (THREADS_FFMPEG names it; empty: none), checked as any picture. Never a reason to refuse the
    picture: None when there is no ffmpeg, it fails, or the copy would not save enough to be worth it."""
    global _thumb_until
    if (max(pic['w'], pic['h']) <= THUMB_EDGE and len(pic['raw']) <= THUMB_FROM) or moving(pic['raw'], pic['ext']):
        return None
    ffmpeg = os.environ.get('THREADS_FFMPEG', shutil.which('ffmpeg') or '')
    if not ffmpeg:
        return None
    if _thumb_until is None:
        _thumb_until = time.monotonic() + THUMB_BUDGET
    left = min(THUMB_EACH, _thumb_until - time.monotonic())
    if left < 1:            # a slow or stuck ffmpeg never keeps his message past the hook's limit
        return None
    out = ['-c:v', 'png'] if see_through(pic['raw'], pic['ext']) else ['-c:v', 'mjpeg', '-q:v', '5', '-pix_fmt', 'yuvj420p']
    try:
        r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', 'pipe:0', '-frames:v', '1',
                            '-vf', f"scale=w='min({THUMB_EDGE},iw)':h='min({THUMB_EDGE},ih)':force_original_aspect_ratio=decrease",
                            *out, '-f', 'image2pipe', '-'], input=pic['raw'], capture_output=True, timeout=left)
        small = picture(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not small or len(small['raw']) > len(pic['raw']) * THUMB_WORTH:
        return None
    # the shape of the picture it stands for (the page stretches it into the picture's place), within a pixel
    w, h, sw, sh = pic['w'], pic['h'], small['w'], small['h']
    if max(sw, sh) > THUMB_EDGE or (sw >= sh) != (w >= h) or abs(sh - sw * h / w) > 1.5 or abs(sw - sh * w / h) > 1.5:
        return None
    return small


def put_thumb(t, base, pic):
    """Store the small copy of a picture beside it (uploads/<thread>/<base>.thumb.<ext>): what its record carries."""
    small = thumb_of(pic)
    if not small:
        return None
    try:
        put_file(folder('uploads', t['id']) / f"{base}.thumb.{small['ext']}", small['raw'])
    except OSError:         # the copy is never a reason to refuse the picture
        return None
    return {'file': f"uploads/{t['id']}/{base}.thumb.{small['ext']}", 'w': small['w'], 'h': small['h'], 'bytes': len(small['raw'])}


def poster_of(path):
    """The first frame of a video as a small jpg, when ffmpeg is on this machine (THREADS_FFMPEG names it; empty:
    none). Never a reason to refuse the video: without it the browser shows the first frame by itself."""
    ffmpeg = os.environ.get('THREADS_FFMPEG', shutil.which('ffmpeg') or '')
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', 'file:' + str(Path(path).resolve()), '-frames:v', '1',
                            '-vf', "scale='min(720,iw)':-2", '-f', 'image2pipe', '-c:v', 'mjpeg', '-q:v', '5', '-'],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        return picture(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def video(path, caption=None):
    """One video named on the command line, checked before anything is written. Its kind is read from the bytes."""
    refusal = tr('--video: up to {mb}MB per video. Make it smaller, for example: ffmpeg -i IN -vf scale=-2:720 -crf 30 OUT.mp4', mb=VIDEO_MAX // 1_000_000)
    try:
        if os.path.getsize(path) > VIDEO_MAX:       # (a pipe has no size: it is read up to the limit)
            raise ValueError(refusal)
        raw = within(path, VIDEO_MAX, refusal)
    except OSError as exc:
        raise ValueError(tr('--video: cannot read {path} ({error})', path=path, error=exc.strerror or exc)) from None
    caption = shown(caption or '')
    if len(caption) > CAPTION_MAX:
        raise ValueError(tr('The caption is too long: up to {max} characters', max=CAPTION_MAX))
    try:
        if raw[4:8] == b'ftyp':
            ext, (raw, w, h, seconds) = 'mp4', clean_mp4(raw)
        elif raw[:4] == b'\x1a\x45\xdf\xa3':
            ext, (raw, w, h, seconds) = 'webm', clean_webm(raw)
        else:
            raise NOT_A_VIDEO
    except (struct.error, IndexError, StopIteration, OverflowError):
        raise DAMAGED_VIDEO from None
    base = shown(Path(path).name)[:120]
    return {'raw': raw, 'ext': ext, 'w': w, 'h': h, 'seconds': seconds, 'name': base or None, 'caption': caption, 'poster': poster_of(path)}


def video_rows(t, m):
    """The videos of a message as an agent needs them: where each file is, and what is written under it."""
    rows = []
    for record in m.get('videos') if isinstance(m.get('videos'), list) else []:
        try:
            rows.append({'path': str(file_path(t, 'uploads', record['file'])), **{k: record.get(k) for k in ('caption', 'name', 'bytes', 'type', 'w', 'h', 'seconds')}})
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    return rows


# A local path of a video in the words of a message: the page never opens one (the board serves its own folder only).
VIDEO_PATH = re.compile(r'~?/[^\s`\'"<>()\[\]]*\.(?:mp4|webm|mov|m4v|mkv)', re.I)
VIDEO_KINDS = ('.mp4', '.webm', '.mov', '.m4v', '.mkv')


def video_paths(text):
    """The local video files a text names, each once: every word on its own (one pass over the text), stripped of
    the marks around it, taken only when the whole of it is such a path."""
    if not any(kind in text.lower() for kind in VIDEO_KINDS):
        return []
    found = (word.strip('`\'"()[]<>,;:!?') for word in text.split())
    return list(dict.fromkeys(word for word in found if VIDEO_PATH.fullmatch(word)))


class InOrder(argparse._AppendAction):
    """--image, --video and --caption: each kept as given, and also in the order they came (a caption right after
    a video is the video's)."""

    def __call__(self, parser, namespace, values, option_string=None):
        super().__call__(parser, namespace, values, option_string)
        namespace.order = [*getattr(namespace, 'order', ()), (self.dest, values)]


def put_link(t, link):
    for i, old in enumerate(t['links']):
        if old['label'] == link['label']:
            t['links'][i] = link
            return
    if len(t['links']) >= 8:
        raise ValueError(tr('Up to 8 links per thread'))
    t['links'].append(link)


# ── notifications and the page ──────────────────────────────────────────────

def notify(tid, msg):
    # His words stay out of the mail: the tower reads them with `threads pending`, where they are marked as his.
    # A line that ends with the tool's own instruction must hold nothing that anyone on the network can write.
    how = 'THREADS_ROLE=tower threads pending (or threads pending --as tower)' if 'run' in msg else 'threads pending'
    send(f"[threads] reply in {tid} ({msg['id']}): run: {how}", f"{tid} {msg['id']}")


def outside_env():
    """The environment of a command this tool runs: no pane identity, and the usual places on PATH (the
    board server and the timer run with a short one)."""
    env = os.environ.copy()
    env.pop('TUIOS_PANE_ID', None)
    paths = env.get('PATH', '').split(os.pathsep)
    for extra in ('/opt/homebrew/bin', str(Path.home() / '.local/bin')):
        if extra not in paths:
            paths.append(extra)
    env['PATH'] = os.pathsep.join(paths)
    return env


def logged(tag, problem):
    try:
        with (BOARD / 'notify.log').open('a', encoding='utf-8') as log:
            log.write(f"{time.time():.3f} {tag}: {' '.join(str(problem).split())}\n")
    except OSError:
        pass  # A committed reply remains successful even if logging fails.


def real_board():
    """Is this the board he really uses? A test's board, or any other BOARDS_DIR, is not."""
    return bl.BOARDS_DIR.resolve() == (Path.home() / 'Documents/mds/boards').resolve()


def outside(variable, usual=None):
    """The command that reaches a person or a service outside this tool, or None when this board may not.
    The variable names it; else, on the real board only, this installation's config.json ("commands") or the
    usual command. Any other board (a test, a copy) reaches nobody's phone, mailbox or paid service unless a
    stand-in is named for it: forgetting the variable must be harmless."""
    named = os.environ.get(variable)
    if named:
        return shlex.split(named)
    if not real_board():
        return None
    commands = config().get('commands')
    mine = commands.get(variable) if isinstance(commands, dict) else None
    return shlex.split(mine) if isinstance(mine, str) and mine.strip() else shlex.split(usual) if usual else None


def send(message, tag):
    """Mail the tower. Never inside the lock; a failure is logged and nothing else."""
    cmd = outside('THREADS_NOTIFY_CMD')        # who the tower is on this installation: config.json
    if os.environ.get('THREADS_NOTIFY') == '0' or cmd is None:
        return
    try:
        subprocess.run(cmd + [shown(message)], env=outside_env(), capture_output=True, text=True, timeout=5, check=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logged(tag, exc)


# What reaches HIM (not the tower): a push to the browsers he subscribed, then his phone when he has not looked.

def is_quiet(value):
    return (isinstance(value, dict) and all(isinstance(value.get(k), str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value[k]) for k in ('from', 'to')))


def quiet_now(data, ts):
    quiet = data['notify'].get('quiet')
    if not quiet:
        return False
    start, end = (int(quiet[k][:2]) * 60 + int(quiet[k][3:]) for k in ('from', 'to'))
    clock = time.localtime(ts)
    minute = clock.tm_hour * 60 + clock.tm_min
    return start <= minute < end if start < end else (minute >= start or minute < end) if start > end else False


def thing(t):
    """What is on him in this thread and he has not seen: its key, else None. (The service worker applies
    the same rule to decide what a push shows.) An agent that puts a new ask on him, and a reminder that
    wakes, drop `seen`: what he saw before is not what is on him now."""
    if t['state'] != ON_OWNER:
        return None
    # A line of the system (a split) is never the news, nor is his own message: when he answers one of several open
    # questions the thread stays on him, and what is news is still what an agent wrote (suda m508).
    said = [m for m in t['messages'] if m.get('from') not in ('system', OWNER)]
    last = said[-1] if said else None
    seen = t['seen'].get('msg') if isinstance(t.get('seen'), dict) else None
    ids = [m['id'] for m in t['messages']]
    if seen == (last['id'] if last else '') or (last and seen in ids and ids.index(seen) > ids.index(last['id'])):
        return None
    return f"{last['id'] if last else ''}|{t['state_ts']}"


def hidden(t):
    """Out of his sight for now (closed, muted, asleep): nothing is told, but what was told is remembered,
    so coming back into sight is not news."""
    return t['status'] != 'open' or bool(t.get('mute')) or bool(t.get('snooze'))


def due(t):
    return None if hidden(t) else thing(t)


def sound(alert):
    return (isinstance(alert, dict) and isinstance(alert.get('key'), str)
            and all(k in alert and (alert[k] is None or number(alert[k])) for k in ('pushed', 'told', 'snapped')))


def alerts(data, ts):
    """Decide who must be told now, and write it down in the state so it is told once: a push for every
    new thing on him, and his phone at the first moment no page has his eyes (at once when the thing
    lands and he is not on Suda; within a minute of his leaving it). While a page has them the phone
    waits, and gets the thing anyway once it is `fallback_minutes` old and he still has not looked.
    A board whose pages never reported his focus waits those minutes every time.
    Nothing during quiet hours: it waits for their end. A command run with notifications off decides
    nothing, so it uses up nothing he is owed. True when the state changed."""
    if os.environ.get('THREADS_NOTIFY') == '0':
        return False
    quiet, wait, changed = quiet_now(data, ts), data['notify']['fallback_minutes'] * 60, False
    here = UNKNOWN  # is he on Suda? Asked once, and only when the answer decides something
    for t in data['threads'].values():
        key, alert = thing(t), t.get('alert') if sound(t.get('alert')) else None
        if key is None:
            if 'alert' in t:        # the thing is over: seen, answered, or the turn moved
                del t['alert']
                changed = True
            continue
        if alert is None or alert['key'] != key:
            fresh = alert is None or alert['snapped'] is not None       # after a phone alert, a new thing starts a new count
            alert = t['alert'] = {'key': key, 'pushed': None, 'told': None if fresh else alert['told'], 'snapped': None}
            changed = True
        if quiet or hidden(t):
            continue
        after = lambda channel: ts >= (alert[channel] if number(alert.get(channel)) else 0)
        if alert['pushed'] is None and after('retry_push'):
            alert['pushed'] = ts
            alert['told'] = alert['told'] or ts
            noting.update(push=True, at=ts)
            changed = True
        # The phone does not wait for a push that keeps failing: its clock runs from the first attempt.
        # Two things in a row (two messages, a turn that goes and comes back): one ring, and the next not within a minute.
        just_rang = number(t.get('rang')) and 0 <= ts - t['rang'] < RING_GAP
        if data['notify']['snap'] and alert['snapped'] is None and alert['told'] is not None and after('retry_phone') and not just_rang:
            late = ts - alert['told'] >= wait       # old enough to ring whoever is looking
            if not late and here is UNKNOWN:
                here = on_suda(ts, data['notify']['idle_minutes'] * 60)
            if late or here is False:           # None: the pages of this board do not say, so it waits as it always did
                alert['snapped'] = t['rang'] = ts
                noting['phone'].append({'id': t['id'], 'title': one_line(t['title']), 'note': one_line(t['note']), 'url': data['notify'].get('url') or '',
                                        'again': type(alert.get('failed')) is int and alert['failed'] > 0})
                noting['at'] = ts
                changed = True
    return changed


def owed(at, push_failed, phones):
    """A delivery failed after the state said it was made: write it back as owed, to be tried again, each
    time a little later (half a minute, a minute, two … up to half an hour)."""
    with locked():
        data = load()
        for t in data['threads'].values():
            alert = t.get('alert')
            if not sound(alert):
                continue
            again = (push_failed and alert['pushed'] == at, t['id'] in phones and alert['snapped'] == at)
            if any(again):
                alert['failed'] = (alert['failed'] if type(alert.get('failed')) is int else 0) + 1
                later = now() + min(30 * 2 ** min(alert['failed'] - 1, 10), 1800)
            if again[0]:
                alert.update(pushed=None, retry_push=later)
            if again[1]:
                alert.update(snapped=None, retry_phone=later)
        save(data)


def private_dir():
    """Keys and push subscriptions: never inside a folder the board server serves. A board that is not the
    real one (a test, another BOARDS_DIR) keeps its own beside its boards, so it can never reach his devices."""
    if os.environ.get('THREADS_CONFIG_DIR'):
        return Path(os.environ['THREADS_CONFIG_DIR']) / SLUG
    if real_board():
        return Path.home() / '.config/threads' / SLUG
    return bl.BOARDS_DIR.resolve().parent / '.threads-config' / SLUG


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def openssl(*args, data=None):
    return subprocess.run(['/usr/bin/openssl', *args], input=data, capture_output=True, timeout=10, check=True).stdout


def private(path):
    """A private file and its folder are for him alone, also when someone left them wider."""
    for target, mode in ((path.parent, 0o700), (path, 0o600)):
        try:
            if target.exists() and target.stat().st_mode & 0o777 != mode:
                os.chmod(target, mode)
        except OSError:
            pass
    return path


def write_private(path, raw):
    """A whole private file or none: readers never meet a half-written key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')      # mkstemp makes it 0600
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    private(path)


def vapid_key(create=False):
    """(path of the private key, public key as the browser wants it), or (None, None) when there is none.
    Made once; the public half is published as push.json beside the state, the private half never leaves
    the private folder. A key file that cannot be read is no key (and is made again when asked to)."""
    pem = private(private_dir() / 'vapid.pem')
    try:
        public = b64url(openssl('ec', '-in', str(pem), '-pubout', '-outform', 'DER')[-65:]) if pem.exists() else None
    except (OSError, subprocess.SubprocessError):
        public = None
    if public is None or len(public) != 87:
        if not create:
            return None, None
        write_private(pem, openssl('ecparam', '-name', 'prime256v1', '-genkey', '-noout'))
        public = b64url(openssl('ec', '-in', str(pem), '-pubout', '-outform', 'DER')[-65:])
    target = BOARD / 'push.json'
    try:
        same = json.loads(target.read_text(encoding='utf-8')).get('publicKey') == public
    except (OSError, ValueError, AttributeError):
        same = False
    if not same:
        bl.atomic_write_text(target, json.dumps({'publicKey': public}) + '\n')
    return pem, public


def subscriptions(change=None):
    """The browsers that asked for pushes: {endpoint: when}. `change(subs)` edits them under their own lock."""
    path = private(private_dir() / 'push-subs.json')
    if change is None and not path.exists():
        return {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with bl.file_lock(path):
        try:
            subs = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            subs = {}
        subs = {k: v for k, v in subs.items() if isinstance(k, str)} if isinstance(subs, dict) else {}
        if change is not None:
            before = dict(subs)
            change(subs)
            if subs != before:
                write_private(path, (json.dumps(subs, indent=1) + '\n').encode())
        return subs


def push_endpoint(value):
    """A subscription's address, only when it is one of the browsers' push services: this machine
    will POST there, so nobody may point it at an address of their choice."""
    # Plain visible ASCII and nothing else: no spaces or control characters (the sender would choke on them),
    # no "[…]" (an address literal can name any machine), no "%" in the host.
    if not isinstance(value, str) or len(value) > 1000 or not re.fullmatch(r'https://[a-z0-9.-]+(:443)?/[!-~]*', value, re.I):
        raise ValueError(tr('Invalid notification subscription'))
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError(tr('Invalid notification subscription')) from None
    host = (url.hostname or '').lower()
    if url.scheme != 'https' or url.username or url.password or port not in (None, 443) or not any(host == h or (h[0] == '.' and host.endswith(h)) for h in PUSH_HOSTS):
        raise ValueError(tr('Invalid notification subscription: not a known push service'))
    return value


def push(endpoint, pem, public):
    """One push with NO payload: nothing of his travels through the push service; the service worker
    wakes, reads state.json itself and shows what is on him. Returns the HTTP status."""
    recorder = os.environ.get('THREADS_PUSH_CMD')
    if recorder:        # tests: a command stands in for the push service and prints the status
        done = subprocess.run(shlex.split(recorder) + [endpoint], env=outside_env(), capture_output=True, text=True, timeout=10)
        return int(done.stdout.strip() or 201)
    origin = '{0.scheme}://{0.netloc}'.format(urllib.parse.urlsplit(endpoint))
    claims = {'aud': origin, 'exp': int(time.time()) + 12 * 3600}
    try:
        contact = private(private_dir() / 'contact').read_text(encoding='utf-8').strip()
    except OSError:
        contact = ''
    if contact:
        claims['sub'] = contact
    signed = '.'.join(b64url(json.dumps(part, separators=(',', ':')).encode()) for part in ({'typ': 'JWT', 'alg': 'ES256'}, claims))
    der = openssl('dgst', '-sha256', '-sign', str(pem), data=signed.encode())
    # DER (30 len 02 len r 02 len s) to the fixed 64 bytes a JWT wants
    at = 4 if der[1] < 0x80 else 5
    r_len = der[at - 1]
    r, s_len = der[at:at + r_len], der[at + r_len + 1]
    s_ = der[at + r_len + 2:at + r_len + 2 + s_len]
    token = signed + '.' + b64url(r[-32:].rjust(32, b'\0') + s_[-32:].rjust(32, b'\0'))
    request = urllib.request.Request(endpoint, data=b'', method='POST', headers={
        'TTL': '86400', 'Urgency': 'high', 'Topic': 'threads', 'Content-Length': '0',
        'Authorization': f'vapid t={token}, k={public}'})
    try:
        with OUTSIDE.open(request, timeout=8) as answer:
            return answer.status
    except urllib.error.HTTPError as exc:
        return exc.code


def push_all():
    """Push every subscribed browser; forget the ones the push service says are gone, and any stored address
    that is not one. [(endpoint, status)]; status 0 is "no answer". One address that cannot be pushed, or a
    key that cannot be read, never costs the others or the phone alert."""
    subs, results = subscriptions(), []
    if not subs or not (os.environ.get('THREADS_PUSH_CMD') or real_board()):
        return results
    try:
        pem, public = vapid_key()
    except Exception as exc:        # noqa: BLE001 - whatever is wrong with the key, the rest of the delivery goes on
        pem, public = None, None
        logged('push', type(exc).__name__)
    if pem is None:
        logged('push', 'no usable push key')
        return [('', 0)]
    gone = []
    for endpoint in subs:
        try:
            push_endpoint(endpoint)
        except ValueError:
            gone.append(endpoint)
            continue
        try:
            status = push(endpoint, pem, public)
        except Exception as exc:    # noqa: BLE001 - see above
            status = 0
            logged('push', type(exc).__name__)
        results.append((endpoint, status))
        if status in (404, 410):
            gone.append(endpoint)
        elif status not in (0, 200, 201, 202):
            logged('push', f'{urllib.parse.urlsplit(endpoint).hostname} answered {status}')
    if gone:
        subscriptions(lambda subs: [subs.pop(endpoint, None) for endpoint in gone])
    return results


PHONE_WAIT, PHONE_WAIT_AGAIN = 20, 38
patient = False     # this process may wait long for his phone: the sweep's timer, or the detached half of a page action


def phone(row):
    """His phone, through Snap: something is on him and no page has his eyes (or he is on Suda and has
    not opened it for too long). True when the phone command took it. `snap notify` often answers late (3 of 5
    alerts timed out at 20 s, and a try right after went through): a first failure is written back as owed
    and not logged, and the next sweep tries again, after reading the state anew (the thing may be over by
    then). That second try waits longer, where nobody waits for it, and only its failure is logged."""
    cmd = outside('THREADS_SNAP_CMD')          # the phone app's alert command, if there is one: config.json
    if cmd is None:
        return True
    body = re.sub(r'^-+', lambda dashes: '\u2013' * len(dashes[0]), shown(row['note'])[:240]) or tr('Waiting for you in the threads')     # never read as an option of the command
    if row['url']:
        cmd += ['--open', f"url:{row['url']}#{row['id']}"]
    try:
        subprocess.run(cmd + [tr('Your turn: {title}', title=shown(row['title'])[:80]), body], env=outside_env(), capture_output=True, text=True,
                       timeout=PHONE_WAIT_AGAIN if row.get('again') is True and patient else PHONE_WAIT, check=True)
        return True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if row.get('again') is True:
            logged(f"{row['id']} phone", exc)
        return False


def tell():
    """Deliver what the saved state says he must be told. Outside every lock. What could not be delivered
    is written back as owed."""
    if os.environ.get('THREADS_NOTIFY') == '0':
        return
    push_failed, phones = False, []
    try:
        if telling['push']:
            results = push_all()
            push_failed = bool(results) and not any(200 <= status < 300 for _, status in results)
    finally:
        phones = [row['id'] for row in telling['phone'] if not phone(row)]
    if (push_failed or phones) and telling['at'] is not None:
        owed(telling['at'], push_failed, phones)


def presence_path():
    return private(private_dir() / 'presence.json')


def with_him(page, ts, idle_limit):
    """Does this remembered page have his eyes at `ts`? It said so within the last 45 seconds, and somebody
    touched it not longer ago than the limit (what it reported, plus the time since)."""
    return (isinstance(page, dict) and number(page.get('ts')) and 0 <= ts - page['ts'] <= PRESENCE_STALE
            and (page['idle'] if number(page.get('idle')) else 0) + ts - page['ts'] <= idle_limit)


def on_suda(ts, idle_limit):
    """Is a page of his in front of him now? None when no page of this board ever reported: its pages are
    older than the report (or it has none), nobody can tell, and the phone keeps to its waiting time.
    Read without the lock (the file is replaced whole). A file that cannot be read means nobody is there:
    an error must cost a needless ring, never a missed one."""
    try:
        pages = json.loads(presence_path().read_text(encoding='utf-8'))['pages']
        return any(with_him(page, ts, idle_limit) for page in pages.values())
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError):     # also a number too large to count with
        return False


def save_presence(page, focused, tid, idle, ts):
    """A page reports whether it has his focus. Kept outside the served folder (nobody but this tool reads
    it), under its own lock: a heartbeat never rewrites the state or wakes a page. Only the pages that have
    his focus are kept; one that lost it, or said nothing for 45 seconds, is forgotten."""
    path = presence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with bl.file_lock(path):
        try:
            before = json.loads(path.read_text(encoding='utf-8'))['pages']
        except (OSError, ValueError, KeyError, TypeError):
            before = None
        before = before if isinstance(before, dict) else {}
        pages = {k: v for k, v in before.items() if isinstance(k, str) and isinstance(v, dict) and number(v.get('ts')) and 0 <= ts - v['ts'] <= PRESENCE_STALE and k != page}
        if focused:
            while len(pages) >= PRESENCE_MAX:       # junk can crowd his own page out only until its next heartbeat
                del pages[min(pages, key=lambda k: pages[k]['ts'])]
            pages[page] = {'ts': ts, 'thread': tid, 'idle': idle}
        if pages != before or not path.exists():        # the first report is kept even when it says "not here": now the pages do report
            write_private(path, (json.dumps({'version': 1, 'pages': pages}, indent=1) + '\n').encode())


def live_agent(pane):
    """The agent in this pane as live.json tells it now, or None. Read without a lock (the file is replaced whole)."""
    try:
        agents = json.loads(LIVE.read_text(encoding='utf-8'))['agents']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return next((a for a in agents if isinstance(a, dict) and a.get('pane') == pane), None) if isinstance(agents, list) else None


def nudge(raw, ts):
    """He pressed a button of the live card: open the agent's window, or tell an agent that stopped to go on.
    Only an agent live.json lists now, only these two things, and the words are this tool's own: nothing he
    sends reaches tuios but a pane id and the id of a thread. "Continue" goes as mail to the agent's own pane
    (never typed into it), not to an agent that is working, and not twice within a few seconds."""
    pane, action, tid = raw.get('pane'), raw.get('action'), raw.get('thread') or ''
    if action not in ('open', 'continue') or not (isinstance(pane, str) and re.fullmatch(PANE_ID, pane)):
        raise ValueError(tr('nudge: pane is a tuios window, and action is open or continue'))
    if not (isinstance(tid, str) and (tid == '' or re.fullmatch(ID, tid))):
        raise ValueError(tr('Invalid thread'))
    agent = live_agent(pane)
    if agent is None:
        raise ValueError(tr('This agent is not in the live list (was the window closed?)'))
    session = agent.get('session') if isinstance(agent.get('session'), str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,59}', agent.get('session') or '') else ''
    if not session:
        raise ValueError(tr('Unknown which session the agent is in'))
    # "continue" only to one that stopped by itself: at rest, at its limit, near the end of its context, after an API
    # error. One that waits for an approval gets it in its window; one whose context is FULL ('Prompt is too long')
    # needs /compact there (a mail would not fit either).
    if action == 'continue' and not (agent.get('state') == 'idle' or (agent.get('state') == 'stuck' and agent.get('why') in ('limit', 'error', 'near'))):
        raise ValueError(tr('The agent is working, waiting for an approval, or its context is full: that is done in its own window'))
    key = action + ':' + pane
    path = private(private_dir() / 'nudges.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with bl.file_lock(path):
        try:
            sent = json.loads(path.read_text(encoding='utf-8'))
            sent = {k: v for k, v in sent.items() if isinstance(k, str) and number(v) and 0 <= ts - v < 3600} if isinstance(sent, dict) else {}
        except (OSError, ValueError):
            sent = {}
        if ts - sent.get(key, -3600) < NUDGE_GAP[action]:
            raise ValueError(tr('"Continue" was already sent to this agent a moment ago') if action == 'continue' else tr('The window was opened a moment ago'))
        while len(sent) >= 200:
            del sent[min(sent, key=sent.get)]
        sent[key] = ts
        write_private(path, (json.dumps(sent) + '\n').encode())
    # The thread is named in the words only when it is a thread of the board and the very one the agent is on:
    # nothing the request chose reaches the agent's reading.
    try:
        known = peek_thread(tid) is not None
    except (OSError, ValueError, KeyError, TypeError):
        known = False
    tid = tid if known and tid == agent.get('thread') else ''
    cmd = outside('THREADS_TUIOS_CMD', 'tuios')
    if cmd is None or os.environ.get('THREADS_NOTIFY') == '0':
        return {'ok': True, 'op': 'nudge', 'action': action, 'sent': False}
    try:
        if action == 'open':        # his client goes to the agent's session (when one is attached), then to its pane
            subprocess.run(cmd + ['switch-session', session], env=outside_env(), capture_output=True, text=True, timeout=3)
            subprocess.run(cmd + ['focus-window', '-s', session, pane], env=outside_env(), capture_output=True, text=True, timeout=3, check=True)
        else:
            words = '[threads] the owner pressed "continue" for you on Suda' + (f' (thread {tid})' if tid else '') + ': continue your work.'
            subprocess.run(cmd + ['send-agent-message', '-s', session, '-w', pane, words], env=outside_env(), capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        logged('nudge', exc)
        raise ValueError(tr('tuios did not answer')) from None
    return {'ok': True, 'op': 'nudge', 'action': action, 'sent': True}


def further(t, last):
    """Has he now seen further than the state knows? `last` is a message of this thread ('' in an empty one).
    What he has seen never moves back: an older tab or device changes nothing."""
    order = [m['id'] for m in t['messages']]
    if last not in order and (last or order):
        raise ValueError(tr('Message not found'))
    known = t['seen'].get('msg') if isinstance(t.get('seen'), dict) else None
    return not ((known in order and last in order and order.index(last) <= order.index(known)) or known == last == '')


PR_URL = re.compile(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})/pull/(\d{1,7})(?!\d)')


def looks_up():
    """May this board ask GitHub? Only the real one (or a test that names a stand-in), and not with notifications off."""
    return os.environ.get('THREADS_NOTIFY') != '0' and outside('THREADS_GH_CMD', 'gh pr view') is not None


def pr_links(text):
    """The pull requests a text points at, each as …/pull/<n> (whatever follows the number is dropped)."""
    return list(dict.fromkeys(m[0] for m in PR_URL.finditer(text if isinstance(text, str) else '')))


def side_write(path, text):
    """A file beside the board (links, places, drafts): pages ask it "changed since?" by its whole-second time, so
    its time is set again once the new content is in place. The writer stamps it at its flush, and a slow fsync
    (a busy disk) may rename it in seconds later: a change would hide behind a 304."""
    bl.atomic_write_text(path, text)
    with contextlib.suppress(OSError):
        os.utime(path)


def links_file(change=None):
    """What is known of the pull requests: {'links': {address: facts}, 'wanted': [addresses to ask about]}.
    Its own file and lock, like drafts and places: it never rewrites the state. `change(data)` edits it."""
    if change is None and not LINKS.exists():
        return {'links': {}, 'wanted': []}
    with bl.file_lock(LINKS):
        try:
            data = json.loads(LINKS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        data = {'version': 1, 'links': data['links'] if isinstance(data, dict) and isinstance(data.get('links'), dict) else {},
                'wanted': [u for u in data.get('wanted', []) if isinstance(u, str)] if isinstance(data, dict) and isinstance(data.get('wanted'), list) else [],
                # being asked about right now, by a worker: not to be queued a second time meanwhile
                'asking': {u: at for u, at in data['asking'].items() if number(at)} if isinstance(data, dict) and isinstance(data.get('asking'), dict) else {}}
        if change is not None:
            before = json.dumps(data, sort_keys=True)
            change(data)
            if len(data['links']) > 500:        # the ones asked about longest ago go first
                for url in sorted(data['links'], key=lambda u: data['links'][u].get('checked') or 0)[:len(data['links']) - 500]:
                    del data['links'][url]
            if json.dumps(data, sort_keys=True) != before:
                side_write(LINKS, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
        return data


PR_FRESH, PR_FRESH_LOOKING = 180, 60      # seconds an open pull request's state is trusted: by default, and while he opens its thread


def stale(facts, ts, fresh=PR_FRESH):
    """Is it time to ask again? A merged pull request never changes; an open one may at any minute (suda m469:
    a merge shows on its chip within three minutes, and within one when he opens the thread)."""
    if not isinstance(facts, dict) or not number(facts.get('checked')):
        return True
    age = ts - facts['checked']
    if facts.get('error'):      # a failure is usually a passing one (a slow network, a busy machine): soon again, three times, then rarely
        return age > (300 if (facts.get('tries') if type(facts.get('tries')) is int else 1) < 3 else 6 * 3600)
    return age > (fresh if facts.get('state') in ('open', 'draft') else 86400 if facts.get('state') == 'closed' else float('inf'))


def want_links(urls, ts, limit=100, fresh=PR_FRESH):
    """Queue the pull requests that are unknown or due to be asked about again. Returns how many are now waiting
    that were not before. Only well-formed addresses of pull requests ever get in."""
    urls = [u for u in dict.fromkeys(urls) if isinstance(u, str) and PR_URL.fullmatch(u)]
    added = []

    def queue(data):
        data['asking'] = {u: at for u, at in data['asking'].items() if 0 <= ts - at < 180}      # a worker that died does not hold its addresses for ever
        for url in urls:
            if (len(added) < limit and len(data['wanted']) < 100 and url not in data['wanted'] and url not in data['asking']
                    and stale(data['links'].get(url), ts, fresh)):
                data['wanted'].append(url)
                added.append(url)
    if urls:
        links_file(queue)
    return len(added)


def pr_facts(url, raw, ts):
    """What `gh pr view --json …` said, as the pages want it."""
    owner, repo, number_ = PR_URL.fullmatch(url).groups()
    marks = [str(c.get('conclusion') or c.get('state') or c.get('status') or '').upper() for c in raw.get('statusCheckRollup') or [] if isinstance(c, dict)]
    failed = ('FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE')
    passed = ('SUCCESS', 'NEUTRAL', 'SKIPPED')
    try:
        updated = datetime.datetime.fromisoformat(str(raw.get('updatedAt')).replace('Z', '+00:00')).timestamp()
    except ValueError:
        updated = None
    state = str(raw.get('state') or '').lower()
    return {'kind': 'pr', 'repo': f'{owner}/{repo}', 'number': int(number_), 'title': shown(str(raw.get('title') or ''))[:200],
            'state': 'draft' if raw.get('isDraft') and state == 'open' else state if state in ('open', 'merged', 'closed') else '',
            'author': shown(str((raw.get('author') or {}).get('login') or ''))[:60] if isinstance(raw.get('author'), dict) else '',
            'base': shown(str(raw.get('baseRefName') or ''))[:120], 'head': shown(str(raw.get('headRefName') or ''))[:120],
            'ci': '' if not marks else 'fail' if any(m in failed for m in marks) else 'pass' if all(m in passed for m in marks) else 'pending',
            'review': {'APPROVED': 'approved', 'CHANGES_REQUESTED': 'changes', 'REVIEW_REQUIRED': 'pending'}.get(raw.get('reviewDecision'), ''),
            'updated': updated, 'checked': ts}


def fetch_links(limit=10):
    """Ask GitHub (the local gh, with his own login) about the pull requests that wait, a few at a time, and
    store what it said. Outside every lock and never inside a page action. A pull request it cannot read is
    remembered as such, so nobody asks again for hours. Pages are woken only when something they show changed."""
    if not looks_up():
        return 0
    cmd, taken, changed = outside('THREADS_GH_CMD', 'gh pr view'), [], []

    def take(data):
        taken.extend(data['wanted'][:limit])
        data['wanted'] = data['wanted'][limit:]
        data['asking'].update({url: now() for url in taken})
    links_file(take)
    for url in taken:
        ts = now()
        try:
            done = subprocess.run(cmd + [url, '--json', 'number,title,state,isDraft,author,baseRefName,headRefName,statusCheckRollup,reviewDecision,updatedAt'],
                                  env=outside_env(), capture_output=True, text=True, timeout=45, check=True)
            facts = pr_facts(url, json.loads(done.stdout), ts)
        except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
            facts = None

        def store(data, url=url, ts=ts, facts=facts):       # each answer is stored as it comes
            old = data['links'].get(url) if isinstance(data['links'].get(url), dict) else None
            data['asking'].pop(url, None)
            known = old is not None and not old.get('error')
            if facts is None:
                if not known:       # a failure never replaces what is known: that stays, and is asked about again when due
                    tries = (old.get('tries') if old and type(old.get('tries')) is int else 0) + 1
                    data['links'][url] = {'kind': 'pr', 'state': '', 'error': True, 'checked': ts, 'tries': tries}
            elif not (known and number(old.get('checked')) and old['checked'] > ts):       # nor does an older answer replace a newer one
                if not known or {k: v for k, v in old.items() if k != 'checked'} != {k: v for k, v in facts.items() if k != 'checked'}:
                    changed.append(url)
                data['links'][url] = facts
        links_file(store)
    if changed:
        (BOARD / '.pulse').touch()
    return len(changed)


def save_place(tid, place, ts):
    """Where he is in a thread, for his other devices. Its own file and its own lock, like a draft: a scroll
    never rewrites the state, wakes a page or mails anyone. The newest wins; the same place again writes
    nothing. `place` None forgets the thread. Returns the time of the stored place."""
    with bl.file_lock(PLACES):
        try:
            places = json.loads(PLACES.read_text(encoding='utf-8')).get('places')
        except (OSError, ValueError, AttributeError):
            places = None
        places = {k: v for k, v in places.items() if isinstance(v, dict)} if isinstance(places, dict) else {}
        old = places.get(tid)
        if place is None:
            if old is None:
                return None
            del places[tid]
        elif old and all(old.get(k) == place[k] for k in place) and number(old.get('ts')):
            return old['ts']
        else:
            places[tid] = {**place, 'ts': ts}
        side_write(PLACES, json.dumps({'version': 1, 'places': places}, ensure_ascii=False, indent=1) + '\n')
        return ts


def save_draft(tid, text, ts):
    """What he typed and did not send, kept for every device. Its own file and its own lock: saving a
    draft never rewrites the state, wakes a page or mails anyone. An empty text stays as a marker, so
    another device can tell "cleared" from "never saved"."""
    with bl.file_lock(DRAFTS):
        try:
            drafts = json.loads(DRAFTS.read_text(encoding='utf-8')).get('drafts')
        except (OSError, ValueError, AttributeError):
            drafts = None
        drafts = drafts if isinstance(drafts, dict) else {}
        drafts[tid] = {'text': text, 'ts': ts}
        month = ts - 30 * 86400
        drafts = {k: v for k, v in drafts.items() if isinstance(v, dict) and (v.get('text') or number(v.get('ts')) and v['ts'] > month)}
        side_write(DRAFTS, json.dumps({'version': 1, 'drafts': drafts}, ensure_ascii=False, indent=1) + '\n')


def storable(*texts):
    """Refuse text that cannot be written (a lone surrogate) before an id is promised or a file is made."""
    try:
        for text in texts:
            if isinstance(text, str):
                text.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError(tr('The text has a character that cannot be saved')) from None


LATIN = dict(zip('אבגדהוזחטיכךלמםנןסעפףצץקרשת', ('a', 'b', 'g', 'd', 'h', 'v', 'z', 'ch', 't', 'y', 'k', 'k', 'l', 'm', 'm', 'n', 'n',
                                                  's', 'a', 'p', 'p', 'ts', 'ts', 'k', 'r', 'sh', 't')))


def title_from(text):
    """A stand-in title: the first words of his message. The tower gives the thread a real one."""
    flat, title = one_line(re.sub(r'```[^\n]*|\*\*|`', '', text)), ''
    for word in flat.split()[:7]:
        if len(title) + len(word) + 1 > 59:
            break
        title = f'{title} {word}'.strip()
    title = title or flat[:59]
    return title + ('…' if len(title) < len(flat) else '')


def new_id(data, title):
    """An id for a thread he opened from the page: its title in Latin letters, or t-<n> when nothing is left of it."""
    flat, base = ''.join(LATIN.get(ch, ch) for ch in unicodedata.normalize('NFKD', title.lower())), ''
    for word in re.findall(r'[a-z0-9]+', flat)[:4]:
        if len(base) + len(word) + 1 > 28:
            break
        base = f'{base}-{word}'.strip('-')
    taken = lambda tid: tid in data['threads'] or tid in data.get('retired', {}) or tid in RESERVED
    tid, n = (base, 2) if len(base) >= 3 else ('t-1', 2)
    while taken(tid):
        tid, n = (f'{base}-{n}' if len(base) >= 3 else f't-{n}'), n + 1
    return tid


def opened(raw, ts):
    """A new topic, opened by him from the page. His message is its first, and the tower hears of it like
    of any reply. Without a title the first words stand in, and `title_pending` says a real one is owed.
    With `split` the topic is cut out of a message of another thread: it carries that message along, and
    the source thread gets a line that says where the matter went."""
    title, text, cid, context, links = (raw.get(k, d) for k, d in (('title', ''), ('text', ''), ('cid', None), ('context', ''), ('links', [])))
    if not all(isinstance(v, str) for v in (title, text, context)) or len(text) > 8000 or len(context) > LIMITS['context']:
        raise ValueError(tr('New topic: a title, and a message of up to 8000 characters'))
    if not isinstance(cid, str) or not cid.strip() or len(cid) > 80:
        raise ValueError(tr('Invalid message id'))
    if not isinstance(links, list) or len(links) > 8 or not all(isinstance(link, dict) for link in links):
        raise ValueError(tr('Links: up to 8, each {label, url}'))
    if any(key in raw for key in ('images', 'snippet', 'voice')):
        raise ValueError(tr('A new topic opens with text only: the rest is sent in the next message'))
    split = raw.get('split')
    if split is not None and not (isinstance(split, dict) and isinstance(split.get('thread'), str) and isinstance(split.get('msg'), str)):
        raise ValueError(tr('Split: a thread and a message are needed'))
    links = [clean_link(link.get('label') or '', link.get('url') if isinstance(link.get('url'), str) else '') for link in links]
    title = one_line(title)
    storable(title, text, cid, context, *(value for link in links for value in link.values()))
    with locked():
        data = load()
        sweep(data, ts)
        rows = data['threads'].values()
        again = next((t for t in rows if t.get('opened_by') == OWNER and t['messages'] and t['messages'][0].get('cid') == cid), None)
        if again:       # the page sent it twice: the same thread, not a second one
            return {'ok': True, 'op': 'new', 'thread': again['id'], 'msg': again['messages'][0]['id'], 'msg_id': again['messages'][0]['id'], 'dup': True}
        source = data['threads'].get(split['thread']) if split else None
        cut = next((m for m in source['messages'] if m['id'] == split['msg'] and m['from'] != 'system'), None) if source else None
        if split and cut is None:
            raise ValueError(tr('The message to split from was not found'))
        owed = blank(title) or raw.get('title_pending') is True
        if blank(title):        # his first words stand in; with a split and not a word of his, the first words of that message
            if blank(text) and cut is None:
                raise ValueError(tr('A new topic needs a title or a message'))
            title = title_from(text if not blank(text) else cut['text'])
        if blank(shown(title)):
            raise ValueError(tr('A new topic needs a readable title'))
        if len(title) > 120:
            raise ValueError(tr('The title is too long: up to 120 characters'))
        text, body, name = (title if blank(text) else text), None, None
        if len(text) > INLINE_MAX:
            body, text, name = text, '', snippet_name(text)
        same = next((t for t in rows if t['status'] == 'open' and one_line(t['title']).casefold() == title.casefold()), None)
        if same and not owed:
            raise Refused(tr('There is already an open topic with this name'), thread=same['id'])
        if sum(t['status'] == 'open' for t in rows) >= OPEN_MAX:
            raise ValueError(tr('There are already {max} open topics: close some before opening a new one', max=OPEN_MAX))
        tid = new_id(data, title)
        t = {'id': tid, 'title': title, 'context': context, 'status': 'open', 'created': ts, 'updated': ts, 'next': 1,
             'messages': [], 'slot': free_slot(data, ts), 'summary': '', 'links': links, 'opened_by': OWNER}
        fill(t)
        if owed:
            t['title_pending'] = True
        if cut:
            t['split_from'] = {'thread': source['id'], 'msg': cut['id'], 'from': cut['from'], 'ts': cut['ts'], 'text': cut['text']}
            try:
                put_link(t, clean_link(tr('Source: {title}', title=one_line(source['title']))[:40], f"/{SLUG}/suda.html#{source['id']}/{cut['id']}"))
            except ValueError:
                pass        # eight links of his own already: the source is in split_from all the same
            # The source says where the matter went. Not a message of the tower's or of an agent's (a page action never
            # writes one): a line of the system, which changes nobody's turn and is news to nobody.
            last = source['messages'][-1]['id']
            line = append(source, 'system', tr('Split off into a new topic'), ts, split_to={'thread': tid, 'title': title})
            cut['split_to'] = tid
            if isinstance(source.get('seen'), dict) and source['seen'].get('msg') == last:
                source['seen']['msg'] = line['id']
        data['threads'][tid] = t
        if isinstance(raw.get('space'), str) and raw['space'] != 'main' and raw['space'] in {sp['id'] for sp in spaces_of(data)}:
            t['space'] = raw['space']           # opened while he was in that space (task 114): it stays there
        msg = spoken(t, OWNER, text, body, name, ts, cid)
        owner_spoke(t, msg, None)
        save(data)
    owes = tr(' (the title is a stand-in: threads rename {id} "<a short title>")', id=tid) if owed else ''
    send(f"[threads] NEW topic {tid} opened by owner ({msg['id']}): run: threads pending{owes}", f"{tid} {msg['id']}")
    forget_draft('_new', ts)
    return {'ok': True, 'op': 'new', 'thread': tid, 'msg': msg['id'], 'msg_id': msg['id'], 'dup': False}


def forget_draft(tid, ts):
    """Sent (or its thread is gone): the draft is over on every device. Never worth failing a saved change for."""
    try:
        save_draft(tid, '', ts)
    except (OSError, ValueError, bl.LockTimeout):
        pass


def ingest():
    """One action from the page: the server stored its body, then ran on-state.sh."""
    body = BOARD / 'state/state.json'
    raw = json.loads(body.read_text(encoding='utf-8'))
    # The request sits inside the served folder until the next one. What is private in it must not: a picture
    # as his phone made it, a recording, a long text, the address of his browser.
    if isinstance(raw, dict) and (str(raw.get('op', '')).startswith('push-') or raw.get('op') == 'snippet-part'
                                  or any(k in raw for k in ('images', 'voice', 'snippet'))):
        try:
            bl.atomic_write_text(body, '{}\n')
        except OSError:
            pass
    if not isinstance(raw, dict) or raw.get('op') not in PAGE_OPS:
        raise ValueError(tr('Invalid request'))
    op, tid, ts = raw['op'], raw.get('thread'), now()
    if op == 'sweep':
        with locked():
            data = load()
            archived = sweep(data, ts)
            if alerts(data, ts) or archived or waking or noting['voice'] or tidied or migrated_from is not None or mended:
                save(data)
        return {'ok': True, 'op': op, 'archived': archived}
    if op == 'new':
        return opened(raw, ts)
    if op == 'snippet-part':
        return take_part(raw, ts)
    if op == 'push-subscribe':      # this browser wants pushes: only its address is kept, outside the served folder
        endpoint = push_endpoint(raw['sub'].get('endpoint') if isinstance(raw.get('sub'), dict) else None)
        public = vapid_key(create=True)[1]

        def add(subs):
            while endpoint not in subs and len(subs) >= 20:     # the oldest goes: junk can never lock his own browser out
                del subs[min(subs, key=lambda k: subs[k] if number(subs[k]) else 0)]
            subs.setdefault(endpoint, ts)
        subscriptions(add)
        return {'ok': True, 'op': op, 'publicKey': public}
    if op == 'push-unsubscribe':
        if not isinstance(raw.get('endpoint'), str):
            raise ValueError(tr('Invalid notification subscription'))
        subscriptions(lambda subs: subs.pop(raw['endpoint'], None))
        return {'ok': True, 'op': op}
    if op == 'quiet':               # hours in which nothing is pushed and the phone is left alone
        quiet = None if raw.get('off') is True else {'from': raw.get('from'), 'to': raw.get('to')}
        if quiet is not None and not is_quiet(quiet):
            raise ValueError(tr('Quiet hours: from and to as HH:MM'))
        if quiet is not None:
            start, end = (int(quiet[k][:2]) * 60 + int(quiet[k][3:]) for k in ('from', 'to'))
            if (end - start) % 1440 > 16 * 60:      # nobody proves who sent a page action: one of them must not silence everything
                raise ValueError(tr('Quiet hours from the page: up to 16 hours a day (more than that: threads notify --quiet)'))
        with locked():
            data = load()
            swept = sweep(data, ts)
            if data['notify'].get('quiet') == quiet and not (alerts(data, ts) or swept or waking or noting['voice'] or tidied):
                return {'ok': True, 'op': op, 'quiet': quiet}
            data['notify']['quiet'] = quiet
            save(data)
        return {'ok': True, 'op': op, 'quiet': quiet}
    if op == 'presence':            # a page says whether it has his focus: his phone is left alone while one has
        page, focused, idle = raw.get('page'), raw.get('focused'), raw.get('idle', 0)
        # Nobody proves who posts a page action: a number no clock can hold (hundreds of digits) must not be
        # kept, or every later command would fall over it while it counts who is looking.
        if not (isinstance(page, str) and re.fullmatch(PAGE_ID, page) and isinstance(focused, bool) and number(idle) and 0 <= idle <= 1e9):
            raise ValueError(tr('Presence: page is the name of the page (6 to 40 characters), focused is true or false, and idle is a number of seconds'))
        save_presence(page, focused, tid if isinstance(tid, str) and re.fullmatch(ID, tid) else '', float(idle), ts)
        return {'ok': True, 'op': op, 'focused': focused, 'ts': ts}
    if op == 'nudge':               # a button of the live card: open an agent's window, or tell it to go on
        return nudge(raw, ts)
    if op == 'space-new':           # he adds a space from the square's menu (task 114): only a name; its id is made here
        name = raw.get('name')
        if not (isinstance(name, str) and not blank(name) and len(one_line(name)) <= SPACE_NAME_MAX):
            raise ValueError(tr('Space name: 1 to {max} characters', max=SPACE_NAME_MAX))
        with locked():
            data = load()
            sweep(data, ts)
            ids = {sp['id'] for sp in spaces_of(data)}
            sp_id = next(f's{n}' for n in range(1, 10_000) if f's{n}' not in ids)
            sp = add_space(data, sp_id, name)
            save(data)
        return {'ok': True, 'op': op, 'space': sp['id'], 'name': sp['name']}
    if op == 'space-move':          # he moves this thread to another space (task 114)
        space = raw.get('space')
        if not (isinstance(tid, str) and re.fullmatch(ID, tid) and isinstance(space, str)):
            raise ValueError(tr('Move to a space: thread and space are ids'))
        with locked():
            data = load()
            swept = sweep(data, ts, skip=tid)
            moved = move_to_space(data, thread(data, tid), space)
            if moved or swept:
                save(data)
        return {'ok': True, 'thread': tid, 'op': op, 'space': space, 'moved': moved}
    if op == 'merge':               # he merges this thread into another (thread suda m377)
        into = raw.get('into')
        if not (isinstance(tid, str) and re.fullmatch(ID, tid) and isinstance(into, str)):
            raise ValueError(tr('Merge: thread and into are thread ids'))
        with locked():
            data = load()
            archived = sweep(data, ts, skip=(tid, into))
            if tid in data['threads']:
                unseen(data['threads'][tid], raw)       # like close: not over a message he has not seen
            merged = merge_threads(data, tid, into, OWNER, ts)
            if merged or archived:
                save(data)
        return {'ok': True, 'thread': tid, 'op': op, 'into': into, 'merged': merged}
    if not isinstance(tid, str):
        raise ValueError(tr('Invalid thread'))
    if op == 'link-meta':   # he opened (or came back to) this thread: look up the pull requests its messages point at, if unknown or old
        try:
            texts = [m.get('text') for m in peek_thread(tid)['messages']]       # (None: no such thread, refused below)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ValueError(tr('Thread not found')) from None
        urls = [url for text in texts for url in pr_links(text)][-200:]
        if 'url' in raw:        # a minute after a press on one chip (he may have merged it there): that one alone
            urls = [raw['url']] if isinstance(raw['url'], str) and raw['url'] in urls else []
        queued = want_links(urls, ts, fresh=PR_FRESH_LOOKING) if looks_up() else 0
        telling['links'] += ['-'] if queued else []         # something waits: main() starts the worker
        return {'ok': True, 'thread': tid, 'op': op, 'queued': queued}
    if op == 'place':      # where he is in this thread: the last message he has seen, the one at the top of his screen, and whether he is at the end
        seen, at, bottom = raw.get('seen'), raw.get('at'), raw.get('bottom')
        if not isinstance(seen, str) or not isinstance(at, str) or not isinstance(bottom, bool):
            raise ValueError(tr('Place: seen and at are message ids, and bottom is true or false'))
        try:        # a look without the lock: most scrolls move nothing the state keeps
            t = peek_thread(tid)
            ids = [m['id'] for m in t['messages']]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError(tr('Thread not found')) from None
        if (at and at not in ids) or (seen not in ids and (seen or ids)):
            raise ValueError(tr('Message not found'))
        if further(t, seen):        # he has seen more than the state knows: that part IS the state's (the unread mark, the alert)
            with locked():
                data = load()
                sweep(data, ts, skip=tid)
                t = thread(data, tid)
                if further(t, seen):
                    t['seen'] = {'msg': seen, 'ts': ts}
                    save(data)
        return {'ok': True, 'thread': tid, 'op': op, 'ts': save_place(tid, {'seen': seen, 'at': at, 'bottom': bottom}, ts)}
    if op == 'draft':
        text = raw.get('text')
        if not isinstance(text, str) or len(text) > 20_000:
            raise ValueError(tr('Draft: a text of up to 20,000 characters'))
        storable(text)
        try:        # '_new' is the new-topic form; any other draft belongs to a thread that exists
            known = tid == '_new' or peek_thread(tid) is not None
        except (OSError, ValueError, KeyError, TypeError):
            known = tid == '_new'
        if not known:
            raise ValueError(tr('Thread not found'))
        save_draft(tid, text, ts)
        return {'ok': True, 'thread': tid, 'op': op, 'ts': ts}
    if op == 'rename':
        title = short(raw['title'], 'title') if isinstance(raw.get('title'), str) else ''
        if blank(title):
            raise ValueError(tr('Empty title'))
        storable(title)
    if op == 'task' and isinstance(raw.get('status'), str):
        raw['status'] = as_owner(raw['status'])       # an older page (or an alias of his): the status as it is stored
    if op == 'task' and (type(raw.get('n')) is not int or raw.get('status') not in TASK_STATES):
        raise ValueError(tr('Invalid task or status'))
    if op == 'task-archive' and not ((type(raw.get('n')) is int and isinstance(raw.get('on'), bool)) or (raw.get('n') == 'done' and raw.get('on') is True)):
        raise ValueError(tr('Task archive: n is a task number (with on) or "done" for everything that is done'))
    if op == 'react' and (raw.get('emoji') not in REACTIONS or not isinstance(raw.get('on'), bool)):
        raise ValueError(tr('Invalid reaction'))
    if op == 'save' and not isinstance(raw.get('on'), bool):
        raise ValueError(tr('Save: on is true or false'))
    if op == 'urgent' and not isinstance(raw.get('on'), bool):
        raise ValueError(tr('Invalid request'))
    if op == 'mute' and not isinstance(raw.get('on'), bool):
        raise ValueError(tr('Mute: on is true or false'))
    if 'command' in raw and op != 'reply':
        raise ValueError(tr('A command is sent alone, on a line of its own'))
    command = agent_command(raw) if op == 'reply' and 'command' in raw else None
    if op in ('task-add', 'task-text'):        # his /task from the reply box: new work, or new words for a task
        task_text = page_task_text(raw)
        if op == 'task-text' and type(raw.get('n')) is not int:
            raise ValueError(tr('Task not found'))
        # a page that got no answer sends the same /task again with the same cid: it is added once
        if 'cid' in raw and not (isinstance(raw['cid'], str) and raw['cid'].strip() and len(raw['cid']) <= 80):
            raise ValueError(tr('Invalid message id'))
    if 'reply_to' in raw and not (isinstance(raw['reply_to'], str) and raw['reply_to']):
        raise ValueError(tr('Message not found'))
    quote = None
    if op == 'reply' and 'quote' in raw:        # the words he marked in the message he answers, as he saw them (not checked against the markdown)
        lines = [shown(line) for line in raw['quote'].splitlines()] if isinstance(raw['quote'], str) else []
        quote = '\n'.join(line for line in lines if line)
        if 'reply_to' not in raw or not quote or len(quote) > 500 or quote.count('\n') >= 6:
            raise ValueError(tr('Quote: up to 500 characters and 6 lines, and only with the message it is taken from'))
        storable(quote)
    joined = None                       # a reply whose snippet came in parts: how many
    if op == 'reply':
        text, cid, q = (raw.get(k) for k in ('text', 'cid', 'q'))
        body = name = None
        if 'snippet' in raw:            # a long text or a text file, attached to the reply
            if not isinstance(raw['snippet'], dict):
                raise ValueError(tr('Invalid snippet'))
            parts = raw['snippet'].get('parts')
            if 'parts' in raw['snippet']:   # a big text that came in parts (see take_part): joined here, or missing
                if type(parts) is not int or not 1 <= parts <= PARTS_MAX or 'text' in raw['snippet'] or not isinstance(raw.get('cid'), str):
                    raise ValueError(tr('Invalid snippet'))
                joined, body = parts, joined_parts(tid, raw['cid'], parts)
                name = snippet_name(body, raw['snippet'].get('name')) if body is not None else None
            else:
                body = raw['snippet'].get('text')
                name = snippet_name(body, raw['snippet'].get('name'))
        pictures = pictures_of(raw['images']) if 'images' in raw else ()
        voice = voice_of(raw['voice']) if 'voice' in raw else None
        if voice and (body is not None or joined is not None or pictures or 'answer' in raw or 'run' in raw or not isinstance(text, str) or not blank(text)):
            raise ValueError(tr('A recording is sent alone'))
        if 'answer' in raw:             # ticks in a multi-select question: the server writes the message itself
            if not isinstance(raw['answer'], dict) or not isinstance(q, str) or not isinstance(raw.get('note', ''), str) or len(raw.get('note', '')) > 2000:
                raise ValueError(tr('Invalid choice answer'))
            text = ''
        if not isinstance(text, str) or len(text) > 8000 or (blank(text) and body is None and joined is None and not pictures and not voice and 'answer' not in raw):
            raise ValueError(tr('Write a message of up to 8000 characters'))
        if body is None and joined is None and len(text) > INLINE_MAX:     # a long paste into a plain box is kept as a snippet, not lost
            body, text, name = text, '', snippet_name(text)
        if not isinstance(cid, str) or not cid.strip() or len(cid) > 80:
            raise ValueError(tr('Invalid message id'))
        if any(key in raw and raw[key] is not None and not isinstance(raw[key], str) for key in ('q', 'under')):
            raise ValueError(tr('Invalid question'))
        storable(text, cid, name, raw.get('note'), *(v for pic in pictures for v in (pic['name'], pic['caption'])))
    if ('last' in raw and not isinstance(raw['last'], str)) or (op in ('done', 'seen') and 'last' not in raw):
        raise ValueError(tr('Invalid request'))
    if 'always' in raw and (op != 'done' or raw['always'] is not True):
        raise ValueError(tr('Invalid request'))
    mine = op == 'done' and raw.get('always') is True       # his own /done (suda-fixes m426), not the page's automatic "read it"
    msg = None
    with locked():
        data = load()
        swept = sweep(data, ts, skip=tid)      # his action wins over a deadline that just passed
        t = thread(data, tid)
        # A merged thread lives on in the one it went into: nothing new is written into it from the page (a message
        # that is already here, sent again by a page that got no answer, is still answered as it was).
        if op == 'task-add' and 'cid' in raw:      # the same /task again (its answer was lost): answered as the first time
            had = next((k for k in t['tasks'] if k.get('cid') == raw['cid']), None)
            if had:
                return {'ok': True, 'thread': tid, 'op': op, 'n': had['n'], 'dup': True}
        if t.get('merged_into') and op in ('reply', 'task', 'task-archive', 'task-add', 'task-text', 'keep', 'done', 'snooze', 'unsnooze') \
                and not (op == 'reply' and any(m.get('cid') == cid for m in t['messages'])) and not mine:
            into = data['threads'].get(t['merged_into'])
            raise ValueError(tr('The thread was merged into «{into}»: write there, or reopen it', into=into['title'] if into else t['merged_into']))
        result = {'ok': True, 'thread': tid, 'op': op}
        # Nothing to change and nothing else to write: a second tap or a second device rewrites no state and wakes
        # no page (an old file is upgraded by the first command that changes something, not by a tap that does not).
        idle = lambda: not (alerts(data, ts) or swept or waking or noting['voice'] or tidied)
        if op == 'reply':
            # The page sends a message again when it got no answer (its renderer was taken away, the line broke):
            # one that is already here is answered as it was the first time, whatever happened to the thread since.
            old = next((m for m in t['messages'] if m.get('cid') == cid), None)
            if old:
                if joined is not None:
                    shutil.rmtree(parts_dir(tid, cid), ignore_errors=True)
                return {'ok': True, 'thread': tid, 'msg_id': old['id'], 'dup': True}
            if t['status'] != 'open':
                raise ValueError(tr('The thread is closed'))
            if joined is not None and body is None:
                raise ValueError(tr('The big snippet did not arrive whole. Send it again'))
            # A stale tab must not answer a question that is no longer open (answered, replaced, or the topic ended).
            question = next((x for x in questions_of(t) if x['id'] == q), None) if q is not None else None
            if q is not None and question is None:
                raise ValueError(tr('This question is no longer open'))
            quoted = find_message(t, raw['reply_to']) if 'reply_to' in raw else None
            ticks = picked(question, raw['answer'], raw.get('note')) if 'answer' in raw else None
            asked = run_asked(t, raw['run']) if 'run' in raw else None
            if asked:       # like "done" and "close": not over a message he has not seen (the tower may have taken the command back)
                unseen(t, raw)
                text = tr('▶ Run the command from message {id}', id=asked['msg_id']) + (tr(', block {n}', n=asked['block_index'] + 1) if asked['block_index'] else '')
            if voice and sum(len(x['voicing']) for x in data['threads'].values() if isinstance(x.get('voicing'), list)) >= VOICING_MAX:
                raise Refused(tr('{n} recordings are still being transcribed. Try again in a moment', n=VOICING_MAX), again=True)        # the page does try again in a moment, by itself
            msg = spoken(t, OWNER, ticks[2] if ticks else text, body, name, ts, cid, pictures, voice=voice)
            if asked:       # he asks the tower to run a command the tower itself wrote; nothing runs here
                msg['run'] = asked
            if command:     # a command for the agents, typed in the reply box: its name and words, for the tower
                msg['command'] = command
            if quoted:      # he answers this message: a page draws the quote from here, the fork gets the whole text
                msg['reply_to'] = {'id': quoted['id'], 'from': quoted['from'], 'text': preview(quoted['text'], 140)}
                if quote:   # exactly which words of it he answers
                    msg['reply_to']['quote'] = quote
            owner_spoke(t, msg, raw['under'] if 'under' in raw else UNKNOWN, answers=q, answering=not command)
            if ticks:       # what he ticked, by group: the fork reads this, not the rendering
                msg['re'].update(answer=ticks[0], note=ticks[1])
            if voice and t['auto'] and t['state'] == 'working':
                t['note'] = tr('You answered with a voice recording: transcribing it')
            result = {'ok': True, 'thread': tid, 'msg_id': msg['id'], 'dup': False}
        elif op == 'close':
            if t['status'] == 'open':
                unseen(t, raw)
                close_thread(t, OWNER, ts)
            elif idle():
                return result                   # second tap, or a second device
        elif op == 'reopen':
            if t['status'] != 'open':
                reopen_thread(data, t, ts)
            elif idle():
                return result
        elif op == 'keep':
            if t['status'] != 'open':
                raise ValueError(tr('The thread is closed'))
            t.update(touched=ts, resolved=False, updated=ts)
        elif mine:
            # His /done always works: finishing is his right (suda-fixes m426). Whatever is open ends his turn: an
            # open ask is closed unanswered (its message stays, and says so), a note on him is cleared, his words
            # still waiting stay with the agents, open tasks stay as they are and the page shows them. A message he
            # has not seen yet is not put away in silence: it comes back in the answer and the page shows it.
            if t['status'] != 'open':
                if idle():
                    return result               # already over (closed, or merged into another thread)
            else:
                ids = [m['id'] for m in t['messages']]
                after = ids.index(raw['last']) + 1 if raw['last'] in ids else (0 if raw['last'] == '' else len(ids) - 1)
                fresh = [{'id': m['id'], 'from': m['from'], 'text': preview(m.get('text') or '', 110)}
                         for m in t['messages'][after:] if m['from'] != OWNER][-5:]      # the newest few: the page shows the last
                asks = questions_of(t)
                left = [k['n'] for k in t['tasks'] if k.get('status') != 'done' and not k.get('archived')]
                result.update(asks=[q['id'] for q in asks], tasks=left, unseen=fresh)
                if t['state'] == 'done' and not asks and idle():
                    return result               # a second tap, or a second device
                for q in asks:
                    said = next((m for m in t['messages'] if m['id'] == q['id']), None)
                    if said is not None:
                        said['q_closed'] = {'ts': ts, 'by': OWNER}
                set_state(t, 'done', tr('You finished it'), OWNER, ts)
        elif op == 'done':
            # "Read it, nothing to do" answers an agent that only reported; a real ask needs a real answer.
            if t['status'] != 'open' or t['state'] != ON_OWNER or not t['auto'] or t['question']:
                raise ValueError(tr('There is an open request here: answer it, or close the thread'))
            unseen(t, raw)
            set_state(t, 'done', tr('Read; nothing open follows'), OWNER, ts, auto=True)
        elif op == 'rename':
            t.update(title=title, updated=ts)
            t.pop('title_pending', None)
            result['title'] = title
        elif op == 'task':          # his one tap on a task. It is activity: the thread does not archive under his finger
            task = find_task(t, raw['n'])
            was = task.get('status')
            task.update(status=raw['status'], updated=ts, by=OWNER)
            if was != raw['status']:
                task_event(task, 'status', ts, OWNER, was, raw['status'])
            if raw['status'] != 'done':
                if task.pop('archived', None):                      # open again: back among the current ones
                    task_event(task, 'unarchived', ts, OWNER)
                unmove(task, ts, OWNER)                          # and no longer the one that went to another thread
            t.update(updated=ts, touched=ts)
            undone(t, find_task(t, raw['n']), OWNER, ts)
            result.update(n=raw['n'], status=raw['status'])
        elif op == 'task-add':      # /task <text>: new work in this thread, written by him (who does it is not said yet)
            revive(data, t, ts)
            if t['status'] != 'open':
                raise ValueError(tr('The thread is closed'))
            task = {'n': next_task(data, t), 'text': task_text, 'status': 'todo', 'owner': '', 'note': '', 'from': None,
                    'ts': ts, 'updated': ts, 'by': OWNER}
            if 'cid' in raw:
                task['cid'] = raw['cid']
            task_event(task, 'created', ts, OWNER)
            t['tasks'].append(task)
            t.update(updated=ts, touched=ts)
            undone(t, task, OWNER, ts)
            result['n'] = task['n']
        elif op == 'task-text':     # /task <n> = <text>: a task described wrong, corrected in place (it keeps its number)
            if t['status'] != 'open':
                raise ValueError(tr('The thread is closed'))
            task = find_task(t, raw['n'])
            result['n'] = raw['n']
            if task.get('text') == task_text:
                if idle():
                    return result
            else:
                history = task['history'] if isinstance(task.get('history'), list) else []
                history.append({'text': task.get('text'), 'ts': ts, 'by': OWNER})
                task_event(task, 'text', ts, OWNER, task.get('text'), task_text)
                task.update(text=task_text, history=history[-TASK_HISTORY_MAX:], updated=ts)
                t.update(updated=ts, touched=ts)
        elif op == 'task-archive':  # finished tasks move out of sight (or one comes back); nobody's turn changes
            if raw['n'] == 'done':
                moved = archive_tasks(t, ts, lambda k: True, OWNER)
            else:
                task = find_task(t, raw['n'])
                if raw['on'] and task.get('status') != 'done':
                    raise ValueError(tr('Only a task that is done goes into the archive'))
                moved = bool(task.get('archived')) != raw['on']
                if moved and raw['on']:
                    task['archived'] = ts
                    task_event(task, 'archived', ts, OWNER)
                elif moved:
                    del task['archived']
                    task_event(task, 'unarchived', ts, OWNER)
            result['archived'] = sorted(k['n'] for k in t['tasks'] if k.get('archived') and type(k.get('n')) is int)
            if not moved and idle():
                return result
        elif op == 'react':         # quick feedback on a message; nobody's turn changes
            target = find_message(t, raw.get('msg'))
            marks = dict(target['reactions']) if isinstance(target.get('reactions'), dict) else {}
            result.update(msg=target['id'], emoji=raw['emoji'], on=raw['on'])
            had = marks.get(raw['emoji'])
            his = had is True or (isinstance(had, dict) and had.get('by') == OWNER)
            # His press is about HIS mark: an agent's mark of the same kind is replaced by his (on), or taken away (off).
            if raw['on'] == his and (raw['on'] or had is None):
                if idle():
                    return result
            elif raw['on']:
                marks[raw['emoji']] = {'by': OWNER, 'ts': ts}
                # ❓ asks the tower to explain: once per message in ten minutes, however often it is switched.
                if raw['emoji'] == '❓' and not (number(target.get('asked')) and 0 <= ts - target['asked'] < 600):
                    target['asked'] = ts
                    waking.append((f"[threads] owner marked ❓ on {tid} ({target['id']}): run: threads show {tid}",
                                   f"{tid} {target['id']} ?", tid, 'ask'))
                t['updated'] = ts
            else:
                del marks[raw['emoji']]
                t['updated'] = ts
            if marks:
                target['reactions'] = marks
            else:
                target.pop('reactions', None)
        elif op == 'save':          # he keeps a message to find it later (suda m787): in any thread, open, closed or merged
            target = find_message(t, raw.get('msg'))
            result.update(msg=target['id'], on=raw['on'])
            if raw['on'] == bool(target.get('saved')):
                if idle():
                    return result
            elif raw['on']:
                target['saved'] = ts
            else:
                del target['saved']
        elif op == 'snooze':
            snooze_thread(t, raw.get('until'), ts)
        elif op == 'unsnooze':      # cancel the sleep, or dismiss the reminder
            if not unsnooze(t, ts) and idle():
                return result
        elif op == 'seen':          # he has this thread on his screen, up to this message
            if further(t, raw['last']):
                t['seen'] = {'msg': raw['last'], 'ts': ts}
            elif idle():
                return result
        elif op == 'urgent':        # first in its section on the page (suda m501); nobody's turn moves, nobody is told
            if raw['on'] and t['status'] != 'open':
                raise ValueError(tr('A closed topic is not marked urgent'))
            if number(t.get('urgent')) == raw['on']:
                if idle():
                    return result
            elif raw['on']:
                t['urgent'] = ts
            else:
                t.pop('urgent', None)
            result['on'] = raw['on']
        elif op == 'mute':          # no push and no phone alert for this thread; the page still shows it
            if bool(t.get('mute')) == raw['on']:
                if idle():
                    return result
            elif raw['on']:
                t['mute'] = True
            else:
                del t['mute']
            result['on'] = raw['on']
        save(data)
    if msg and joined is not None:
        shutil.rmtree(parts_dir(tid, cid), ignore_errors=True)     # stored in the snippet's own file now
    if msg:
        if msg.get('status') == 'pending':      # a voice message is told to the tower when its words are in
            notify(tid, msg)
        forget_draft(tid, ts)       # sent: the draft of this thread is over, on every device
    return result


# ── CLI ─────────────────────────────────────────────────────────────────────

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)

    def turn(cmd):
        cmd.add_argument('--note', default='', help='one line: what the owner must do / what the agent does / the outcome')
        cmd.add_argument('--by', default='', help='who is working (agent name)')

    new = sub.add_parser('new')
    new.add_argument('id')
    new.add_argument('title')
    new.add_argument('--context', default='')
    new.add_argument('--summary', default='', help='one line: what this topic is')
    new.add_argument('--state', type=as_owner, choices=STATES)
    new.add_argument('--link', action='append', default=[], metavar='LABEL=URL')
    turn(new)
    ls = sub.add_parser('list')
    ls.add_argument('--open', action='store_true')
    ls.add_argument('--json', action='store_true')
    ls.add_argument('--as', dest='role', choices=['tower', 'agent'], default=None, help='tower: ▶ requests too (default: THREADS_ROLE)')
    show = sub.add_parser('show')
    show.add_argument('id')
    show.add_argument('--json', action='store_true')
    show.add_argument('--as', dest='role', choices=['tower', 'agent'], default=None, help='tower: ▶ requests too (default: THREADS_ROLE)')
    say = sub.add_parser('say')
    say.add_argument('id')
    say.add_argument('--from', dest='sender', type=as_owner, choices=[*AGENTS, OWNER], required=True,
                     help=f'{OWNER} (or one of his aliases) writes as the owner')
    say.add_argument('text')
    say.add_argument('--state', type=as_owner, choices=STATES)
    say.add_argument('--force', action='store_true', help='with --state done: although tasks of the thread are still open')
    say.add_argument('--on-his-word', metavar='mN', help="with --state done, over open tasks: the owner's own message mN in this thread asked to finish (it is recorded)")
    say.add_argument('--snippet', metavar='FILE', help='attach a text file (up to 20 MB) as a collapsed snippet')
    say.add_argument('--snippet-name', help='the name to show instead of the file name')
    say.add_argument('--image', action=InOrder, default=[], metavar='FILE', help='a picture (jpg, png, gif, webp; up to 4, 2 MB each)')
    say.add_argument('--video', action=InOrder, default=[], metavar='FILE', help='a video (mp4 or webm; up to 2, 100 MB each), played in the message')
    say.add_argument('--caption', action=InOrder, default=[], metavar='TEXT',
                     help='the line under a picture, in the order of --image; right after a --video, the line under that video')
    say.add_argument('--live', action='store_true', help='a message you will update in place (a status card): see `threads update`')
    say.add_argument('--html', metavar='FILE', help='a self-contained page (up to 500 KB), shown in a sandboxed frame: no outside scripts or pictures')
    turn(say)
    update = sub.add_parser('update', help='replace the text of a LIVE message of yours in place (no new message, nobody is alerted)')
    update.add_argument('id')
    update.add_argument('msg_id')
    update.add_argument('--from', dest='sender', choices=AGENTS, required=True)
    update.add_argument('text')
    update.add_argument('--state', type=as_owner, choices=STATES)
    update.add_argument('--force', action='store_true', help='with --state done: although tasks of the thread are still open')
    update.add_argument('--on-his-word', metavar='mN', help="with --state done, over open tasks: the owner's own message mN in this thread asked to finish (it is recorded)")
    turn(update)
    rename = sub.add_parser('rename', help='change the title; the id and the slot stay')
    rename.add_argument('id')
    rename.add_argument('title')
    snooze = sub.add_parser('snooze', help='hide the thread until a time; it then returns to "on you" as a reminder')
    snooze.add_argument('id')
    snooze.add_argument('--until', required=True, help='"+2h", "tomorrow 09:00", "2026-11-16 09:00", "16.11 09:00"')
    sub.add_parser('unsnooze').add_argument('id')
    urgent = sub.add_parser('urgent', help='first in its section on the page, until taken away or closed (his turn does not move)')
    urgent.add_argument('id')
    urgent.add_argument('--off', action='store_true')
    mute = sub.add_parser('mute', help='no push and no phone alert for this thread')
    mute.add_argument('id')
    mute.add_argument('--off', action='store_true')
    alert = sub.add_parser('notify', help='how he is told: a push, and his phone at once unless a page has his focus')
    alert.add_argument('--snap', choices=['on', 'off'], help='his phone, through `snap notify`')
    alert.add_argument('--fallback-minutes', type=float, help='while he is on Suda and does not open the thread: how long until the phone gets it anyway')
    alert.add_argument('--idle-minutes', type=float, help='a page in front that nobody touched for this long does not count as him being there')
    alert.add_argument('--quiet', metavar='HH:MM-HH:MM|off', help='hours with no push and no phone alert')
    alert.add_argument('--url', metavar='URL|off', help='the page a phone alert opens (the thread id is added after #)')
    alert.add_argument('--contact', metavar='mailto:…|https://…|off', help='the contact the push service may see; none by default')
    alert.add_argument('--test', action='store_true', help='push every subscribed browser now and print what the push service answered')
    task = sub.add_parser('task', help='the requests of a thread, tracked one by one').add_subparsers(dest='task_cmd', required=True)
    add = task.add_parser('add')
    add.add_argument('id')
    add.add_argument('text')
    add.add_argument('--from-msg', help='the message the request came from')
    add.add_argument('--owner', default='', help=f'who does it; "{OWNER}" for a task that is his')
    add.add_argument('--by', help='who adds it (for its history); by default the owner when an agent, else "agent"')
    put = task.add_parser('set')
    put.add_argument('id')
    put.add_argument('n', type=int)
    put.add_argument('status', type=as_owner, choices=TASK_STATES, nargs='?', help='left out: the status stays')
    put.add_argument('--text', help='new words for the task (it keeps its number; the old words go to its history)')
    put.add_argument('--note')
    put.add_argument('--owner')
    put.add_argument('--by', help='who corrects the words (for the history); by default the owner before the change')
    shelve = task.add_parser('archive', help='move finished tasks out of the bar of the thread (they are kept)')
    shelve.add_argument('id')
    shelve.add_argument('n', type=int, nargs='?')
    shelve.add_argument('--done-older-than', type=float, metavar='HOURS', help='every task that has been done at least this long (0: every done task)')
    back = task.add_parser('unarchive')
    back.add_argument('id')
    back.add_argument('n', type=int)
    tasks = sub.add_parser('tasks')
    tasks.add_argument('id')
    tasks.add_argument('--json', action='store_true')
    tasks.add_argument('--all', action='store_true', help='also the finished tasks that moved to the archive')
    url = sub.add_parser('url', help="print the page's address on this installation (the secure one when there is one)")
    url.add_argument('id', nargs='?')
    snippet = sub.add_parser('snippet', help='print the full text of a message snippet')
    snippet.add_argument('id')
    snippet.add_argument('msg_id')
    state = sub.add_parser('state')
    state.add_argument('id')
    state.add_argument('state', type=as_owner, choices=STATES)
    state.add_argument('--force', action='store_true', help='done although tasks of the thread are still open')
    state.add_argument('--on-his-word', metavar='mN', help="done over open tasks: the owner's own message mN in this thread asked to finish (it is recorded)")
    turn(state)
    ask = sub.add_parser('ask', description=f'Ask him a question. Up to {QUESTIONS_MAX} questions stay open side by side in a thread: '
                                             'a new ask is added beside the open ones (the same question asked again by the same agent replaces it), '
                                             'and his answer to one closes only that one.')
    ask.add_argument('id')
    ask.add_argument('question')
    taking = ask.add_mutually_exclusive_group()
    taking.add_argument('--replace', metavar='mN', help='take back the open question asked in message mN, and ask this one instead')
    taking.add_argument('--replace-all', action='store_true', help='take back every open question of the thread: this one is the only one')
    ask.add_argument('--options', help='comma separated choices, 2 to 6 (with --multi: up to 40)')
    ask.add_argument('--multi', action='store_true', help='checkboxes: he may tick any of the options')
    ask.add_argument('--groups-file', metavar='JSON', help='grouped checkboxes: [{"title":…, "items":[text | {"text":…, "recommended":true, "image":"FILE"}]}]')
    ask.add_argument('--option-image', action='append', default=[], metavar='LABEL=FILE', help='a picture for an option: it is shown as a tile (jpg, png, gif, webp; up to 12)')
    ask.add_argument('--recommended', metavar='LABEL', help='the option you recommend: it is marked, never moved (options keep their order)')
    ask.add_argument('--from', dest='sender', choices=AGENTS, default='fork')
    resolve = sub.add_parser('resolve')
    resolve.add_argument('id')
    resolve.add_argument('--force', action='store_true', help='although tasks of the thread are still open')
    resolve.add_argument('--on-his-word', metavar='mN', help="over open tasks: the owner's own message mN in this thread asked to finish (it is recorded)")
    turn(resolve)
    edit = sub.add_parser('set')
    edit.add_argument('id')
    for field in ('title', 'summary', 'context'):
        edit.add_argument('--' + field)
    link = sub.add_parser('link')
    link.add_argument('id')
    link.add_argument('label')
    link.add_argument('target', nargs='?')
    link.add_argument('--rm', action='store_true')
    policy = sub.add_parser('policy')
    for key in POLICY:
        policy.add_argument('--' + key.replace('_', '-'), type=float, dest=key)
    saved = sub.add_parser('saved', help='the messages he saved (a bookmark on the page), in every thread, the last saved first')
    saved.add_argument('--json', action='store_true')
    saved.add_argument('--as', dest='role', choices=['tower', 'agent'], default=None, help='tower: a ▶ request he saved too (default: THREADS_ROLE)')
    react = sub.add_parser('react', help="an agent's mark on a message, above all ✅ on his message once what it asked is done")
    react.add_argument('id')
    react.add_argument('msg_id')
    react.add_argument('emoji', choices=list(REACTIONS))
    react.add_argument('--by', default='agent')
    react.add_argument('--off', action='store_true', help="take the agent's mark away (his own stays)")
    space = sub.add_parser('space', help='spaces of threads (a square at the top-left of the page switches them)').add_subparsers(dest='space_cmd', required=True)
    sp_add = space.add_parser('add')
    sp_add.add_argument('id')
    sp_add.add_argument('name')
    sp_set = space.add_parser('set')
    sp_set.add_argument('id')
    sp_set.add_argument('--name')
    for one in (sp_add, sp_set):
        one.add_argument('--prefix', action='append', help='threads whose id starts with this are in the space (e.g. sup-); again for more')
        one.add_argument('--letter', help='what its square shows (default: the first letter of the name)')
        one.add_argument('--color', help='#rrggbb')
    space.add_parser('rm').add_argument('id')
    space.add_parser('list').add_argument('--json', action='store_true')
    move = sub.add_parser('move', help='move a thread to a space (main = the main one)')
    move.add_argument('id')
    move.add_argument('--space', required=True)
    runst = sub.add_parser('run-status', help="what became of a command he asked to run: the tower says it (task 123)")
    runst.add_argument('id')
    runst.add_argument('msg_id', help="the tower's message with the block")
    runst.add_argument('block', type=int, help='run.block_index of the pending row (0 = the first block)')
    runst.add_argument('state', choices=['running', 'ok', 'fail'])
    runst.add_argument('--note', help='one line: what came out, or why it failed')
    merge = sub.add_parser('merge', help='merge a thread into another: it closes under "merged", its open tasks move')
    merge.add_argument('id')
    merge.add_argument('--into', required=True)
    merge.add_argument('--by', default='tower')
    for name in ('close', 'reopen', 'rm', 'ack'):
        cmd = sub.add_parser(name)
        cmd.add_argument('id')
        if name == 'close':
            cmd.add_argument('--by', default='tower')
            cmd.add_argument('--force', action='store_true', help='although tasks of the thread are still open')
        cmd.add_argument('--on-his-word', metavar='mN', help="over open tasks: the owner's own message mN in this thread asked to finish (it is recorded)")
        if name == 'ack':
            cmd.add_argument('--as', dest='role', choices=['tower', 'agent'], default=None, help='a ▶ request is acked only by the tower (default: THREADS_ROLE)')
        if name == 'rm':
            cmd.add_argument('--yes', action='store_true', required=True)
        if name == 'ack':
            cmd.add_argument('msg_id')
    sub.add_parser('help', help="`threads help visual`: everything a thread can show him, with when to use each; `threads help lang`: "
                               "the installation's language, the one to write to him in").add_argument('topic', nargs='?', choices=['visual', 'lang'])
    sub.add_parser('tell').add_argument('what')       # internal: see main()
    exp = sub.add_parser('export-state', help='the whole board (every thread, the closed ones too) as state.json: a backup, or the way back to the file store')
    exp.add_argument('--to', default=None, help='another file than the board\'s state.json')
    sub.add_parser('import-state', help='take the board\'s state.json into the store (it replaces what the store holds)')
    remux = sub.add_parser('voice-remux', help='the recordings already on the board get their duration (a list by default; --apply keeps each original as <name>.orig)')
    remux.add_argument('--apply', action='store_true')
    sub.add_parser('links')                           # internal: ask GitHub about the pull requests that wait
    worker = sub.add_parser('transcribe')             # internal: the slow half of a voice message
    worker.add_argument('id')
    worker.add_argument('msg_id')
    for name in ('pending', 'sweep', 'ingest', 'install'):
        cmd = sub.add_parser(name)
        if name == 'sweep':
            cmd.add_argument('--quiet', action='store_true', help='for the timer: one dated line, and only when something happened')
        if name == 'pending':
            cmd.add_argument('--as', dest='role', choices=['tower', 'agent'], default=None,
                             help='tower: also the ▶ run requests, which no other agent sees (default: THREADS_ROLE, else agent)')
    return p


def config():
    """This installation's own settings: config.json in the private folder (never in the repo, never served).
    {"secure_home": "https://…", "commands": {"THREADS_NOTIFY_CMD": "…", …}, "live_alias": {"tower": "<pane>"},
     "owner_name": "<how the pages and messages name the owner>", "owner_aliases": ["<another id of his>", …]}"""
    try:
        value = json.loads((private_dir() / 'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


LOCALES = REPO / 'locales'
_LOCALE = {}


def language():
    """This installation's language: "lang" in config.json (default "en", the language the code is written in)."""
    value = config().get('lang')
    return value if isinstance(value, str) and re.fullmatch(r'[a-z]{2}(-[A-Z]{2})?', value) else 'en'


def locale(pages=False):
    """The translation table of this installation's language, {English text: its translation}, plus "_dir"
    ("rtl" or "ltr"). From config.json "locale_file", else locales/<lang>.json; English needs none.
    pages: the table the served pages carry, without locales/<lang>.cli.json (the messages of this file, which
    reach a page already translated)."""
    lang = language()
    if (lang, pages) not in _LOCALE:
        table = {}
        if lang != 'en':
            named = config().get('locale_file')
            # locales/<lang>.json, and any locales/<lang>.<part>.json beside it (merged in name order)
            places = [Path(os.path.expanduser(named))] if isinstance(named, str) and named else \
                [LOCALES / f'{lang}.json', *sorted(p for p in LOCALES.glob(f'{lang}.*.json') if not (pages and p.name == f'{lang}.cli.json'))]
            for where in places:
                try:
                    raw = json.loads(where.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if isinstance(raw, dict):
                    table.update({k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)})
        _LOCALE[lang, pages] = table
    return _LOCALE[lang, pages]


def tr(text, /, **values):
    """`text` (English, as the code says it) in this installation's language, with {name} filled from `values`."""
    out = locale().get(text, text)
    return out.format(**values) if values else out


def text_dir():
    return 'rtl' if locale().get('_dir') == 'rtl' else 'ltr'


def localized_page(text):
    """A page as this installation shows it: its language, direction and translations, its secure address, the
    owner's name and the tower's live alias, all written into the copy that is served (the repo's stays as is)."""
    esc = lambda value, ascii=True: json.dumps(value, ensure_ascii=ascii).replace('<', '\\u003c')
    home, named = secure_home(), configured_name()
    alias = config().get('live_alias')
    alias = {k: v for k, v in alias.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(alias, dict) else {}
    if home:
        text = text.replace("const SECURE_HOME='';", 'const SECURE_HOME=' + json.dumps(home) + ';', 1)
    if alias:
        text = text.replace('const LIVE_ALIAS={};', 'const LIVE_ALIAS=' + esc(alias) + ';', 1)
    if named:       # how the pages name him (default: "Me", in the installation's language)
        text = text.replace("const OWNER_NAME='Me';", 'const OWNER_NAME=' + esc(named) + ';', 1)
    elif language() != 'en':
        word = tr('Me')
        plain = re.fullmatch(r"[^'\\<\n\r\u2028\u2029]*", word)
        text = text.replace("const OWNER_NAME='Me';", 'const OWNER_NAME=' + (f"'{word}'" if plain else esc(word)) + ';', 1)
    if language() != 'en':
        table = {k: v for k, v in locale(pages=True).items() if not k.startswith('_')}
        text = text.replace("var LANG='en',L10N={};", 'var LANG=' + json.dumps(language()) + ',L10N=' + esc(table, False) + ';', 1)
    # (in English too: the page says which language it is in, whatever its source said)
    return re.sub(r'<html lang="[^"]*" dir="[^"]*">', f'<html lang="{language()}" dir="{text_dir()}">', text, count=1)


def localized_worker(text):
    """sw.js as this installation shows it: its language and direction, and the translations of the few texts it
    shows (only those: the worker carries no page's table)."""
    if language() == 'en':
        return text
    wanted = set(re.findall(r"\btr\('([^'\\]*)'", text))
    table = {k: v for k, v in locale().items() if k in wanted}
    return text.replace("var LANG='en',DIR='ltr',L10N={};", 'var LANG=' + json.dumps(language()) + ',DIR=' + json.dumps(text_dir())
                        + ',L10N=' + json.dumps(table, ensure_ascii=False, sort_keys=True) + ';', 1)


def localized_manifest(text):
    """manifest.json as this installation shows it: its description, language and direction."""
    if language() == 'en':
        return text
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    if isinstance(data.get('description'), str):
        data['description'] = tr(data['description'])
    data.update(lang=language(), dir=text_dir())
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


def secure_home():
    """The https address where a gateway serves this board's /threads/ (notifications, the microphone and the
    clipboard need a secure page): THREADS_SECURE_HOME, else "secure_home" in config.json of the private folder.
    None: the page offers no secure address."""
    value = os.environ.get('THREADS_SECURE_HOME')
    if value is None:
        value = config().get('secure_home')
    if not isinstance(value, str) or not value:
        return None
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+(:\d{1,5})?', value):
        raise ValueError(tr('secure_home: only https://host[:port], without a path'))
    return value
def mdv_dir() -> Path:
    """Where `threads install` puts the MD Viewer, and the board server imports it from (suda-fixes m149):
    THREADS_MDV_DIR, else ~/.local/share/threads/mdv. A board somewhere else (BOARDS_DIR set: the tests, a second
    board) gets its viewer beside its boards folder, never in the live one."""
    if os.environ.get('THREADS_MDV_DIR'):
        return Path(os.environ['THREADS_MDV_DIR'])
    if os.environ.get('BOARDS_DIR'):
        return Path(os.environ['BOARDS_DIR']).parent / 'threads-mdv'
    return Path.home() / '.local' / 'share' / 'threads' / 'mdv'


def install_mdv():
    """The viewer's code and page, copied whole (a new copy, then a rename), with Suda's own style sheet, icons and
    pure code written from suda.html into it. Folders 0755, files 0644. The board server reads the page's files on
    each request; its Python modules are read when it starts."""
    src = REPO / 'mdv'
    if not (src / 'mdv_web.py').is_file():
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location('mdv_sync', src / 'mdv' / 'sync.py')
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    dest = mdv_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tag = '.%d' % os.getpid()
    new, old = dest.with_name(dest.name + '.new' + tag), dest.with_name(dest.name + '.old' + tag)
    shutil.rmtree(new, ignore_errors=True)
    skip = shutil.ignore_patterns('__pycache__', '*.pyc', 'samples', *sync.NAMES)

    def ignore(folder, names):      # a symlink is never followed into the copy (it could lead to a private file)
        return set(skip(folder, names)) | {n for n in names if os.path.islink(os.path.join(folder, n))}
    try:
        shutil.copytree(src, new, ignore=ignore)
        sync.write(new / 'static', REPO / 'suda.html')
        named = config().get('locale_file')
        sync.localize(new, language(), LOCALES, Path(os.path.expanduser(named)) if isinstance(named, str) and named else None)   # the viewer in the installation's language (locales/mdv/), with its own table when it has one
        for path in [new, *new.rglob('*')]:
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)     # a failed install leaves the working copy as it was, and no half one
        raise
    if dest.exists():
        os.rename(dest, old)
    os.rename(new, dest)
    shutil.rmtree(old, ignore_errors=True)


def install():
    BOARD.mkdir(parents=True, exist_ok=True)
    with locked():
        data = load()       # first: a state file this version must not touch stops the install before anything is replaced
        secure_home()               # (a bad address stops the install before anything is replaced)
        for page in PAGES:
            if (REPO / page).exists():
                shutil.copyfile(REPO / page, BOARD / page)
                localize = {'suda.html': localized_page, 'sw.js': localized_worker, 'manifest.json': localized_manifest}.get(page)
                if localize:            # this installation's own language and settings
                    bl.atomic_write_text(BOARD / page, localize((BOARD / page).read_text(encoding='utf-8')))
        if (BOARD / OLD_BOARD_PAGE).is_file():        # only over an old installation: its links still lead somewhere
            bl.atomic_write_text(BOARD / OLD_BOARD_PAGE, OLD_BOARD_REDIRECT)
        for name in PAGE_DIRS:
            if (REPO / name).is_dir():
                shutil.copytree(REPO / name, BOARD / name, dirs_exist_ok=True)
        install_mdv()
        try:        # the key pages subscribe with; without openssl there are simply no pushes
            vapid_key(create=True)
        except (OSError, subprocess.SubprocessError):
            pass
        hook = BOARD / 'on-state.sh'
        slug = '' if SLUG == 'threads' else f'export THREADS_SLUG={shlex.quote(SLUG)}\n'
        bl.atomic_write_text(hook, '#!/bin/sh\n' + slug + 'exec python3 ' + shlex.quote(str(REPO / 'threads.py')) + ' ingest\n')
        hook.chmod(0o755)
        if STORE_KIND != 'file' or not STATE.exists() or migrated_from is not None or mended:
            save(data)              # (the store: a save that changes nothing keeps the number, and writes the files a page reads)
        else:
            renumber(data)          # a board from before these files gets them now (and its pages hear of a new number)
    out.append(str(BOARD))


def tower_role(a=None):
    """Is the caller the tower? `--as` when given, else THREADS_ROLE (2026-11-20: the ▶ requests are the tower's alone)."""
    role = getattr(a, 'role', None) if a is not None else None
    return str(role or os.environ.get('THREADS_ROLE', '')).strip().lower() == 'tower'


def run_request(m):
    """His ▶ request the tower has not picked up yet (any `run` field, whatever its shape)."""
    return isinstance(m, dict) and m.get('from') == OWNER and m.get('status') == 'pending' and 'run' in m


def for_agent(t, tower):
    """A copy of the thread as an agent may read it: a pending ▶ request is the tower's alone."""
    return t if tower else {**t, 'messages': [m for m in t['messages'] if not run_request(m)]}


def listing(data, a):
    rows = sorted(all_threads(data).values(), key=lambda t: (
        (0, t['slot'] or 10**6, t['created']) if t['status'] == 'open' else (1, -(t.get('closed_ts') or t['updated']), 0)))
    rows = [t for t in rows if not a.open or t['status'] == 'open']
    if a.json:
        emit([for_agent(t, tower_role(a)) for t in rows])
        return
    # The first five columns are the v1 table, unchanged; the new ones follow.
    out.append('ID\tSTATUS\tMESSAGES\tPENDING\tTITLE\tSLOT\tSTATE\tNOTE')
    for t in rows:
        n = sum(m.get('status') == 'pending' for m in t['messages'])
        slot = t['slot'] if t['status'] == 'open' and t['slot'] else '-'
        out.append(f"{t['id']}\t{t['status']}\t{len(t['messages'])}\t{n}\t{one_line(t['title'])}\t{slot}\t{t['state']}\t{one_line(t['note'])}")


def event_words(e):
    """One event of a task as a line for an agent: what happened, then who (derived: told from what the task kept)."""
    def where(x):
        return f"{x.get('thread')} #{x.get('n')}" if isinstance(x, dict) else str(x)
    kind, before, after = e.get('kind'), e.get('from'), e.get('to')
    what = (f"status {before or '?'} → {after}" if kind == 'status' and before else f"status → {after}" if kind == 'status'
            else f"text «{preview(str(before or ''), 60)}» → «{preview(str(after or ''), 60)}»" if kind == 'text'
            else f"owner {before or '-'} → {after or '-'}" if kind == 'owner'
            else f"moved from {where(before)}" if kind == 'moved' and before is not None
            else f"moved to {where(after)}" if kind == 'moved' and after is not None
            else f"opened again, no longer the one moved to {where(e.get('back'))}" if kind == 'moved' and e.get('back') else str(kind))
    return what + (f" · {e['by']}" if e.get('by') else '') + (' (derived)' if e.get('derived') else '')


def with_events(rows):
    """Copies of tasks, each with its events (for a task from before events: what can be derived)."""
    return [{**k, 'events': task_events(k)} for k in rows]


def showing(t, a):
    t = for_agent(t, tower_role(a))
    if a.json:
        t = json.loads(json.dumps(t))       # a copy: the path is for the reader, it is not stored
        t['tasks'] = with_events(t['tasks'])
        for m in t['messages']:
            try:
                m['snippet']['path'] = str(snippet_path(t, m))
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            for record, row in zip(m.get('images') if isinstance(m.get('images'), list) else [], image_rows(t, m)):
                record['path'] = row['path']
            for record, row in zip(m.get('videos') if isinstance(m.get('videos'), list) else [], video_rows(t, m)):
                record['path'] = row['path']
        emit(t)
        return
    slot = f"[{t['slot']}] " if t['status'] == 'open' and t['slot'] else ''
    out.append(f"{slot}{t['id']}: {t['title']} ({t['status']} · {t['state']})")
    stamp = lambda when: time.strftime('%d/%m %H:%M', time.localtime(when))
    for label, value in ((tr('State'), t['note']), (tr('About'), t['summary']),
                         (tr('Title'), t.get('title_pending') and tr('temporary, from its first words. To give it a title: threads rename {id} "…"', id=t["id"])),
                         (tr('Split from'), isinstance(t.get('split_from'), dict) and f"{t['split_from'].get('thread')} {t['split_from'].get('msg')}: {preview(str(t['split_from'].get('text', '')), 120)}"),
                         (tr('Snoozed'), t.get('snooze') and tr('asleep until {when}', when=stamp(t['snooze']['until']))),
                         (tr('Reminder'), t.get('reminder') and tr('woke from a snooze at {when}', when=stamp(t['reminder']['ts']))),
                         (tr('Notifications'), t.get('mute') and tr('muted')),
                         *((tr('Open question {id}', id=q['id']) if len(t['questions']) > 1 else tr('Question'), q['text'] + ''.join(f' [{o}]' for o in q['options']))
                           for q in t['questions']),
                         (tr('Links'), ' · '.join(f"{link['label']} → {link['url']}" for link in t['links']))):
        if value:
            out.append(f'{label}: {value}')
    out.append(t['context'])
    if t['tasks']:      # each task with its history (suda-fixes task 34)
        out.append(tr('Tasks:'))
        for k in t['tasks']:
            out.append(f"  {k['n']}. [{k.get('status', '')}] {k.get('text', '')}" + (tr(' (archived)') if k.get('archived') else ''))
            out.extend(f"      {stamp(e['ts'])} {event_words(e)}" for e in task_events(k) if number(e.get('ts')))
    for m in t['messages']:
        out.append(f"\n{m['id']} · {m['from']} · {time.strftime('%d/%m %H:%M', time.localtime(m['ts']))} {m.get('status', '')}\n{m['text']}")
        try:
            where = snippet_path(t, m)
            out.append(tr('[snippet: {name} · {chars} characters · {where}]', name=m['snippet'].get('name') or tr('text'),
                          chars=m['snippet'].get('chars'), where=where))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        for row in image_rows(t, m):
            out.append(tr('[picture: {path}]', path=row['path'] + (f" · {row['caption']}" if row['caption'] else '')
                          + (tr(' · sent smaller, the original {w}x{h}', w=row['shrunk']['w'], h=row['shrunk']['h']) if row.get('shrunk') else '')))
        for row in video_rows(t, m):
            out.append(tr('[video: {path} · {w}x{h} · {seconds} seconds{caption}]', path=row['path'], w=row['w'], h=row['h'],
                          seconds=row['seconds'], caption=f" · {row['caption']}" if row['caption'] else ''))
        try:
            out.append(tr('[HTML page: {path}]', path=file_path(t, 'uploads', m['html']['file'])))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        if m.get('live') is True:
            out.append(tr('[live message · updated {n} times]', n=m['edits']) if type(m.get('edits')) is int else tr('[live message]'))
        if isinstance(m.get('split_to'), (str, dict)):
            out.append(tr('[split into topic: {id}]', id=m['split_to'] if isinstance(m['split_to'], str) else m['split_to'].get('thread')))
        if isinstance(m.get('reply_to'), dict):
            marked = m['reply_to'].get('quote')
            out.append(tr('[in reply to {id}{quote}]', id=m['reply_to'].get('id'), quote=f": «{one_line(marked)}»" if isinstance(marked, str) else ''))
        try:
            words = {'transcribing': tr('transcribing'), 'failed': tr('transcription failed')}.get(m['voice'].get('state'), tr('transcribed'))
            out.append(tr('[voice recording: {path} · {seconds} seconds · {state}]', path=file_path(t, 'uploads', m['voice']['file']), seconds=m['voice'].get('seconds'), state=words))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        if isinstance(m.get('run'), dict):
            out.append(tr('[run request: block {block} in message {id}]', block=m['run'].get('block_index'), id=m['run'].get('msg_id')))
        if m.get('from') == OWNER and isinstance(m.get('command'), dict) and m['command'].get('name') in AGENT_COMMANDS:
            words = m['command'].get('args')
            out.append(tr('[command: /{name}{args}]', name=m['command']['name'], args=' ' + one_line(words) if isinstance(words, str) and words.strip() else ''))
        if isinstance(m.get('reactions'), dict) and m['reactions']:
            his = [e for e, v in m['reactions'].items() if v is True or (isinstance(v, dict) and v.get('by') == OWNER)]
            theirs = [e for e in m['reactions'] if e not in his]
            if his:
                out.append(tr('[marked by {owner}: {marks}]', owner=owner_name(), marks=' '.join(his)))
            if theirs:
                out.append(tr('[marked by an agent: {marks}]', marks=' '.join(theirs)))


def pending_rows(data, tower=False):
    """His replies no agent has picked up. A ▶ request (a row with `run`) is the tower's alone: anyone else does not
    see it at all (2026-11-20: an agent that read `pending` ran the tower's command before the tower did)."""
    rows = []
    for t in data['threads'].values():
        for i, m in enumerate(t['messages']):
            if m['from'] == OWNER and m.get('status') == 'pending' and (tower or not run_request(m)):
                row = {'thread': t['id'], 'title': t['title'], 'context': t['context'],
                       'msg_id': m['id'], 'text': m['text'], 'ts': m['ts'],
                       'history': [{k: prev[k] for k in ('id', 'from', 'text', 'ts')} for prev in t['messages'][:i] if tower or not run_request(prev)],
                       'slot': t['slot'], 'state': t['state'], 'note': t['note'], 'summary': t['summary'], 'links': t['links']}
                if 're' in m:
                    row['re'] = m['re']             # the question this reply answers
                quoted = next((x for x in t['messages'] if x['id'] == m.get('reply_to', {}).get('id')), None) if isinstance(m.get('reply_to'), dict) else None
                if quoted:                          # the message he answers, in full, and the words of it he marked (if he marked any)
                    row['reply_to'] = {'id': quoted['id'], 'from': quoted['from'], 'text': quoted['text']}
                    if isinstance(m['reply_to'].get('quote'), str):
                        row['reply_to']['quote'] = m['reply_to']['quote']
                try:                                # the whole text is in this file
                    where = snippet_path(t, m)
                    row['snippet'] = {'path': str(where), **{k: m['snippet'].get(k) for k in ('name', 'bytes', 'chars', 'lines')}}
                    # A long message he typed into the box (no file of his): whoever reads `text` still gets all of it.
                    if m['snippet'].get('only') and not m['snippet'].get('name') and (m['snippet'].get('chars') or 0) <= 8000:
                        row['text'] = read_exact(where)
                except (ValueError, KeyError, TypeError, AttributeError, OSError):
                    pass
                if image_rows(t, m):                # each picture: where the file is, and what he wrote under it
                    row['images'] = image_rows(t, m)
                if video_rows(t, m):
                    row['videos'] = video_rows(t, m)
                try:                                # he spoke it: `text` is the transcript, this is the recording
                    row['voice'] = {'path': str(file_path(t, 'uploads', m['voice']['file'])), **{k: m['voice'].get(k) for k in ('seconds', 'state', 'error') if m['voice'].get(k) is not None}}
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
                if isinstance(m.get('run'), dict):  # he asks to run a command of the tower's: taken from the tower's own message, never from his reply
                    source = next((x for x in t['messages'] if x['id'] == m['run'].get('msg_id')), None)
                    command = command_of(source, m['run'].get('block_index')) if source else None
                    row['run'] = {k: m['run'].get(k) for k in ('msg_id', 'block_index', 'sha256')}      # these three and nothing a hand could have added
                    if t['status'] != 'open':
                        row['run']['error'] = 'he closed the thread after asking'
                    elif command is not None and hashlib.sha256(command.encode('utf-8')).hexdigest() == m['run'].get('sha256'):
                        row['run']['command'] = command
                    else:
                        row['run']['error'] = 'the stored block no longer matches what he approved'
                if isinstance(m.get('command'), dict) and m['command'].get('name') in AGENT_COMMANDS:     # a command he typed for the agents
                    row['command'] = {'name': m['command']['name'], 'args': m['command'].get('args') if isinstance(m['command'].get('args'), str) else ''}
                if t.get('title_pending'):          # he opened the topic without a title: give it one (threads rename)
                    row['title_pending'] = True
                if isinstance(t.get('split_from'), dict):   # the topic was cut out of this message of another thread
                    row['split_from'] = t['split_from']
                if t.get('merged_into'):        # the thread went into another: answer him there
                    row['merged_into'] = t['merged_into']
                rows.append(row)
    return sorted(rows, key=lambda m: m['ts'])


def tasks_first(t, a, ts):
    """The tasks of a thread are what he reads: an agent may not call the thread done over tasks that are
    still open (unless it says --force), and is reminded of a task it left "working" hours ago."""
    left = [k for k in t['tasks'] if k.get('status') != 'done']
    ends = a.cmd == 'resolve' or (a.cmd == 'close' and a.by != 'tower') or getattr(a, 'state', None) == 'done'     # the tower closes on his word
    word = getattr(a, 'on_his_word', None)
    if word is not None:
        # He asked in words to finish (suda-fixes m428): the agent acting on it names that message of his, and it is
        # kept on the thread, so an end over open tasks is never a blind one.
        said = next((m for m in t['messages'] if m['id'] == word), None)
        if said is None or said['from'] != OWNER:
            raise ValueError(tr('--on-his-word: {word} is not a message of the owner in this thread', word=word))
        if a.cmd in ('resolve', 'close') or getattr(a, 'state', None) == 'done':      # (the tower's close too)
            t['his_word'] = {'msg': word, 'cmd': a.cmd, 'by': a.by or getattr(a, 'sender', None) or 'agent', 'ts': ts}
    if left and ends and not a.force and word is None:
        rows = '; '.join(f"{k['n']} ({k.get('status', '?')}) {preview(str(k.get('text', '')), 40)}" for k in left[:6]) + (' …' if len(left) > 6 else '')
        raise ValueError(tr('The thread has open tasks: {rows}. Update them (threads task set {id} N done); when the owner asked to finish: --on-his-word mN (his message); else --force', rows=rows, id=t['id']))
    for k in left:
        owner = one_line(str(k.get('owner') or '')).casefold()
        # His own tasks are his to update. An agent that names itself is reminded of its tasks and of those nobody owns.
        mine = owner != OWNER and (not a.by or not owner or owner == a.by.casefold())
        if mine and k.get('status') in ('working', 'building') and number(k.get('updated')) and ts - k['updated'] > STALE_TASK:
            since = time.strftime('%d/%m %H:%M' if ts - k['updated'] > 86400 else '%H:%M', time.localtime(k['updated']))
            errs.append(f"threads: task {k['n']} «{preview(str(k.get('text', '')), 50)}» still {k['status']} since {since} (threads task set {t['id']} {k['n']} <status> --note …)")


def undone(t, task, by, ts):
    """A task was opened (or opened again) in a thread that says done: the thread is not done."""
    if t['status'] == 'open' and t['state'] == 'done' and task.get('status') != 'done':
        set_state(t, 'working', preview(tr('Open task: {text}', text=str(task.get('text', ''))), NOTE_MAX), by or 'agent', ts, auto=True)


def change(data, a, ts):
    """Apply one mutating command. Everything is validated before anything is written."""
    if a.cmd == 'new':
        if not re.fullmatch(ID, a.id) or a.id in RESERVED:
            raise ValueError(tr('Invalid thread id'))
        if a.id in data['threads']:
            raise ValueError(tr('The thread already exists'))
        state = a.state or ON_OWNER
        note = clean_note(a.note, state if a.state or a.note else None)
        links = [clean_link(*(raw.split('=', 1) + [''])[:2]) for raw in a.link]
        t = {'id': a.id, 'title': a.title, 'context': a.context, 'status': 'open', 'created': ts, 'updated': ts,
             'next': data.get('retired', {}).get(a.id, 1), 'messages': [], 'slot': free_slot(data, ts),
             'summary': one_line(a.summary), 'links': []}
        fill(t)
        for link in links:
            put_link(t, link)
        explicit = bool(a.state or note)
        set_state(t, state, note or ('' if explicit else tr('New topic: read it')), a.by, ts, auto=not explicit)
        data['threads'][a.id] = t
        return
    if a.cmd == 'space':
        if a.space_cmd == 'add':
            add_space(data, a.id, a.name, a.prefix or (), a.letter, a.color)
        elif a.space_cmd == 'set':
            clean_space(a.id, a.name, a.prefix, a.letter, a.color, data, False)
            sp = next(x for x in spaces_of(data) if x['id'] == a.id)
            if a.name is not None:
                storable(a.name)
                sp['name'] = one_line(visible(a.name))
            if a.prefix is not None:
                sp['prefix'] = list(dict.fromkeys(a.prefix))
            if a.letter is not None:
                sp['letter'] = visible(a.letter).strip()
            if a.color is not None:
                sp['color'] = a.color.lower()
        elif a.space_cmd == 'rm':
            if a.id == 'main' or a.id not in {x['id'] for x in spaces_of(data)}:
                raise ValueError(tr('Space not found (the main space cannot be removed)'))
            data['spaces'] = [x for x in spaces_of(data) if x['id'] != a.id]
            for other in all_threads(data).values():      # what chose it goes back to the main space
                if other.get('space') == a.id:
                    del other['space']
        return
    t = thread(data, a.id)
    if a.cmd == 'move':
        if not move_to_space(data, t, a.space):
            out.append(tr('Thread {id} is already in space {space}', id=a.id, space=a.space))
            return False
        return
    if t.get('merged_into') and a.cmd in ('say', 'state', 'ask', 'update', 'resolve', 'task', 'react'):
        raise ValueError(tr('Thread {id} was merged into {into}: write there (threads {cmd} {into} …), or threads reopen {id}', id=a.id, into=t['merged_into'], cmd=a.cmd))
    if a.cmd == 'run-status':
        # What became of a command he asked to run (task 123, thread suda m430): kept on the tower's message, per
        # block; the page's ▶ button shows it. Nobody's turn moves and nobody is told.
        target = find_message(t, a.msg_id)
        command = command_of(target, a.block) if a.block >= 0 else None
        if command is None:
            raise ValueError(tr('This tower message has no run block with this number (block = run.block_index from pending)'))
        sha = hashlib.sha256(command.encode('utf-8')).hexdigest()
        # only a block he asked to run, as it stands now: a ✓ never shows on a button he did not press
        if not any(m.get('from') == OWNER and isinstance(m.get('run'), dict) and m['run'].get('msg_id') == a.msg_id
                   and m['run'].get('block_index') == a.block and m['run'].get('sha256') == sha for m in t['messages']):
            raise ValueError(tr('This block (as it is written now) was not asked to run by {owner}', owner=owner_name()))
        runs = dict(target['runs']) if isinstance(target.get('runs'), dict) else {}
        mark = {'state': a.state, 'ts': ts, 'sha': sha}
        if a.note:
            mark['note'] = a.note
        runs[str(a.block)] = mark
        target['runs'] = runs
        t['updated'] = ts
        return
    if a.cmd == 'react':
        # An agent's mark (task 118, thread suda m404): ✅ on his message says what it asked is done. His own marks
        # are his: an agent never takes one over or away. Nobody's turn moves and nobody is told.
        target = find_message(t, a.msg_id)
        marks = dict(target['reactions']) if isinstance(target.get('reactions'), dict) else {}
        had = marks.get(a.emoji)
        his = had is True or (isinstance(had, dict) and had.get('by') == OWNER)
        if his or (a.off and had is None) or (not a.off and isinstance(had, dict) and had.get('by') == a.by):
            return False
        if a.off:
            del marks[a.emoji]
        else:
            marks[a.emoji] = {'by': a.by, 'ts': ts}
            if a.emoji == '✅' and target['from'] == OWNER and target.get('status') == 'pending' and (tower_role(a) or not run_request(target)):
                target.update(status='acked', acked_ts=ts)     # done is also picked up: it leaves `pending`
        if marks:
            target['reactions'] = marks
        else:
            target.pop('reactions', None)
        t['updated'] = ts
        return
    if a.cmd == 'merge':
        if not merge_threads(data, a.id, a.into, a.by, ts):
            out.append(tr('Thread {id} was already merged into {into}', id=a.id, into=a.into))
            return False
        return
    if a.cmd in ('say', 'state', 'resolve', 'update') or (a.cmd == 'close' and t['status'] == 'open'):
        tasks_first(t, a, ts)
    if a.cmd == 'say':
        if not revive(data, t, ts):
            print(tr('Warning: the thread is closed, and {owner} will not see the message. To bring it back: threads reopen {id}', owner=owner_name(), id=a.id), file=sys.stderr)
        msg = spoken(t, a.sender, a.text, a.body, a.sname, ts, pictures=a.pictures, page=a.page, videos=a.videos)
        if a.live:      # a status card: the same message is updated as the thing it shows moves on
            msg['live'] = True
        if a.sender == OWNER:
            owner_spoke(t, msg)
        else:
            agent_spoke(t, msg, a.state, a.note, a.by)
        out.append(msg['id'])
    elif a.cmd == 'update':
        # Only a message that was made to change. What he read, answered or approved as an ordinary message stays as it was.
        msg = find_message(open_thread(data, a.id), a.msg_id)
        if msg.get('live') is not True or msg['from'] != a.sender or msg.get('q'):
            raise ValueError(tr('Only a live message (threads say --live) of the same sender can be updated'))
        if msg['text'] == a.text and not a.state:
            return False
        if msg['text'] != a.text:
            msg.update(text=a.text, edited=ts, edits=(msg['edits'] if type(msg.get('edits')) is int else 0) + 1)
            if isinstance(msg.get('runs'), dict):       # what was said of a command that is no longer there goes with it
                keep = {}
                for key, mark in msg['runs'].items():
                    cmd = command_of(msg, int(key)) if key.isdigit() else None
                    if cmd is not None and isinstance(mark, dict) and mark.get('sha') == hashlib.sha256(cmd.encode('utf-8')).hexdigest():
                        keep[key] = mark
                if keep:
                    msg['runs'] = keep
                else:
                    msg.pop('runs', None)
            noting['links'] += pr_links(a.text)
            t['updated'] = ts
        if a.state:
            set_state(t, a.state, a.note, a.by or a.sender, ts)
    elif a.cmd == 'state':
        revive(data, t, ts)
        set_state(open_thread(data, a.id), a.state, a.note, a.by, ts)
    elif a.cmd == 'ask':
        revive(data, t, ts)
        open_thread(data, a.id)
        # Questions stay open side by side (suda m508): a new one is added, unless it takes one back. Checked before
        # anything is written, so a refused ask leaves no message behind.
        staying = questions_of(t)
        if a.replace_all:
            staying = []
        elif a.replace:
            if a.replace not in [q['id'] for q in staying]:
                raise ValueError(tr('--replace: question {id} is not open in this thread. The open questions: {open}',
                                    id=a.replace, open=', '.join(q['id'] for q in staying) or tr('none')))
            staying = [q for q in staying if q['id'] != a.replace]
        # The same question asked again by the same agent (same words, same options) replaces it. The same words from
        # another agent may be about another thing: both stay open.
        staying = [q for q in staying if not (q['text'].strip() == a.question and q.get('from') == a.sender and q['options'] == a.options)]
        if len(staying) >= QUESTIONS_MAX:
            raise ValueError(tr('There are already {max} open questions in this thread. Wait for an answer, or replace one: '
                                '--replace mN (one of: {ids}), or --replace-all', max=QUESTIONS_MAX, ids=', '.join(q['id'] for q in staying)))
        more = {'multi': True, 'groups': a.groups} if a.groups else {}
        msg = append(t, a.sender, a.question, ts, q=True, options=a.options)
        if a.option_images:         # an option he must SEE: its picture, stored like a picture of a message
            stored = {}
            for k, label in enumerate(a.options, 1):
                pic = a.option_images.get(label)
                if pic:
                    put_file(folder('uploads', t['id']) / f"{msg['id']}-o{k}.{pic['ext']}", pic['raw'])
                    stored[label] = {'file': f"uploads/{t['id']}/{msg['id']}-o{k}.{pic['ext']}", 'w': pic['w'], 'h': pic['h']}
                    small = put_thumb(t, f"{msg['id']}-o{k}", pic)
                    if small:
                        stored[label]['thumb'] = small
            more['option_images'] = stored
            for group in a.groups or []:
                for item in group['items']:
                    if item['text'] in stored:
                        item['image'] = stored[item['text']]
        if a.recommended:           # marked, never moved: the options keep the order they were written in
            more['recommended'] = a.recommended
            for group in a.groups or []:
                for item in group['items']:
                    item['recommended'] = item['recommended'] or item['text'] == a.recommended
        msg.update(more)
        set_state(t, ON_OWNER, a.ask_note, a.sender, ts)
        taken = [q for q in questions_of(t) if q not in staying]
        set_questions(t, staying + [{'id': msg['id'], 'text': a.question, 'options': a.options, 'from': a.sender, 'ts': ts, **more}])
        if taken:       # never silent: whoever waits for an answer to one of these learns it is over
            errs.append(f"threads: {msg['id']} took back the open question(s) " + ', '.join(f"{q['id']} (from {q.get('from') or '?'})" for q in taken)
                        + ': their buttons are gone, and no answer to them will come')
        out.append(msg['id'])
    elif a.cmd == 'resolve':
        open_thread(data, a.id)
        set_state(t, 'done', a.note or (t['note'] if t['state'] == 'done' else tr('Resolved')), a.by, ts, resolved=True)
    elif a.cmd == 'close':
        if t['status'] == 'open':
            close_thread(t, a.by, ts)
    elif a.cmd == 'reopen':
        if t['status'] != 'open':
            reopen_thread(data, t, ts)
            t.pop('alert', None)        # an agent brought it back: if it is on him, he is told (his own reopen from the page is not news)
            t.pop('seen', None)
    elif a.cmd == 'rm':
        # A later thread of the same name continues the numbering: an answer kept by a page for the old one cannot land on it.
        data.setdefault('retired', {})[a.id] = t['next']
        last_task = max([k['n'] for k in t['tasks']] + [data.get('retired_tasks', {}).get(a.id, 0)])
        if last_task:               # task numbers continue too: a tap kept by a page cannot land on another topic's task
            data.setdefault('retired_tasks', {})[a.id] = last_task
        if is_slot(t['slot']):      # its slot rests like any freed slot, though the record is gone
            freed = ts if t['status'] == 'open' else t.get('closed_ts') if number(t.get('closed_ts')) else 0
            data.setdefault('freed', {})[str(t['slot'])] = max(freed, data.get('freed', {}).get(str(t['slot']), 0))
        del data['threads'][a.id]
        for other in all_threads(data).values():      # no merge points at a thread that is gone (a new one of its name is another topic)
            if other.get('merged_into') == a.id:
                del other['merged_into']
            if isinstance(other.get('merged_from'), list) and a.id in other['merged_from']:
                other['merged_from'] = [x for x in other['merged_from'] if x != a.id]

        def its_files():            # its files and its unsent draft go with it
            for kind in ('snippets', 'uploads'):
                try:                        # only its own folder inside the board: never through a link, at any level
                    shutil.rmtree(folder(kind, a.id), ignore_errors=True)
                except ValueError:
                    pass
            forget_draft(a.id, ts)
            try:
                save_place(a.id, None, ts)
            except (OSError, ValueError, bl.LockTimeout):
                pass
        after_save.append(its_files)
    elif a.cmd == 'rename':
        t.update(title=a.title, updated=ts)
        t.pop('title_pending', None)
    elif a.cmd == 'snooze':
        snooze_thread(t, parse_when(a.until, ts), ts)
    elif a.cmd == 'unsnooze':
        return unsnooze(t, ts)
    elif a.cmd == 'urgent':
        if t['status'] != 'open' and not a.off:
            raise ValueError(tr('A closed topic is not marked urgent'))
        if number(t.get('urgent')) != a.off:       # (a mark that is not a time, left by a hand edit, is no mark)
            return False
        if a.off:
            t.pop('urgent', None)
        else:
            t['urgent'] = ts
    elif a.cmd == 'mute':
        if bool(t.get('mute')) != a.off:
            return False
        if a.off:
            del t['mute']
        else:
            t['mute'] = True
    elif a.cmd == 'task' and a.task_cmd == 'archive':
        if a.n is not None:
            if find_task(t, a.n).get('status') != 'done':
                raise ValueError(tr('Only a task that is done goes into the archive'))
            moved = archive_tasks(t, ts, lambda k: k.get('n') == a.n)
        else:
            moved = archive_tasks(t, ts, lambda k: number(k.get('updated')) and ts - k['updated'] >= a.done_older_than * 3600)
        out.append(' '.join(str(n) for n in moved))
        return bool(moved)
    elif a.cmd == 'task' and a.task_cmd == 'unarchive':
        if find_task(t, a.n).pop('archived', None) is None:
            return False
        task_event(find_task(t, a.n), 'unarchived', ts, 'agent')
    elif a.cmd == 'task' and a.task_cmd == 'add':
        revive(data, t, ts)
        if a.from_msg:
            find_message(t, a.from_msg)
        n = next_task(data, t)
        t['tasks'].append({'n': n, 'text': a.text, 'status': 'todo', 'owner': a.owner, 'note': '', 'from': a.from_msg or None,
                           'ts': ts, 'updated': ts})
        task_event(t['tasks'][-1], 'created', ts, a.by or agent_name(a.owner))
        t.update(updated=ts, touched=ts)
        undone(t, t['tasks'][-1], a.owner, ts)
        out.append(str(n))
    elif a.cmd == 'task':
        task = find_task(t, a.n)
        by = a.owner or task.get('owner') or 'agent'
        # who did it, for the task's history: the name given, else the owner before the change when that is an agent;
        # never him (a CLI write is an agent's) and never the new owner (a hand-over is not made by whom it goes to)
        actor = a.by or agent_name(task.get('owner'))
        reworded = a.text is not None and a.text != task.get('text')
        if not reworded and a.status is None and a.note is None and a.owner is None:
            return False                        # the same words and nothing else: nothing to record
        if reworded:
            # corrected in place (the owner, a tasks thread, m132): the number stays, the old words are kept, with who
            # corrected them (not the owner it is given now: an agent handing it to him did not word it as him)
            was = task.get('owner')
            history = task['history'] if isinstance(task.get('history'), list) else []
            history.append({'text': task.get('text'), 'ts': ts, 'by': a.by or (was if was and was != OWNER else 'agent')})
            task_event(task, 'text', ts, a.by or actor, task.get('text'), a.text)
            task.update(text=a.text, history=history[-TASK_HISTORY_MAX:])
        task['updated'] = ts
        if a.status is not None:
            if a.status != task.get('status'):
                task_event(task, 'status', ts, actor, task.get('status'), a.status)
            task.update(status=a.status, by=by)
            if a.status != 'done':
                if task.pop('archived', None):  # open again: back among the current ones
                    task_event(task, 'unarchived', ts, actor)
                unmove(task, ts, actor)         # and no longer the one that went to another thread
        if a.note is not None:
            task['note'] = a.note
        if a.owner is not None:
            if a.owner != task.get('owner'):
                task_event(task, 'owner', ts, actor, task.get('owner') or '', a.owner)
            task['owner'] = a.owner
        t.update(updated=ts, touched=ts)        # activity: finishing the last task starts the archive clock from now
        if a.status is not None:                # (new words or a note do not open anything: a done thread stays done)
            undone(t, task, task.get('owner'), ts)
    elif a.cmd == 'ack':
        msg = next((m for m in t['messages'] if m['id'] == a.msg_id), None)
        if msg is None or msg['from'] != OWNER:
            raise ValueError(tr('No message of {owner} was found', owner=owner_name()))
        if msg.get('status') == 'acked':
            return False
        if run_request(msg) and not tower_role(a):
            raise ValueError(tr("A ▶ request is the tower's alone: only the tower marks it (THREADS_ROLE=tower)"))
        if msg.get('status') == 'transcribing':
            raise ValueError(tr('This recording is still being transcribed; it will show in pending when its words arrive'))
        msg.update(status='acked', acked_ts=ts)
        t['updated'] = ts
        # Picked up: an agent works on his reply since now. That is activity: a thread someone had
        # marked done over his unread reply must not archive itself under the agent's hands.
        if t['status'] == 'open' and (t['state'] == 'done' or (t['state'] == 'working' and t['auto'])):
            set_state(t, 'working', waiting_note(msg), 'fork', ts, auto=True)
    elif a.cmd == 'set':
        fields = {k: getattr(a, k) for k in ('title', 'summary', 'context') if getattr(a, k) is not None}
        if not fields:
            raise ValueError(tr('Nothing to update: --title, --summary or --context'))
        t.update(fields, updated=ts)
        if 'title' in fields:
            t.pop('title_pending', None)
    elif a.cmd == 'link':
        if a.rm:
            keep = [link for link in t['links'] if link['label'] != one_line(a.label)]
            if len(keep) == len(t['links']):
                raise ValueError(tr('Link not found'))
            t['links'] = keep
        else:
            put_link(t, clean_link(a.label, a.target))
        t['updated'] = ts


def run(a):
    if a.cmd == 'ingest':
        out.append(json.dumps(ingest()))        # ASCII: the hook may run without a UTF-8 locale
        return
    if a.cmd == 'install':
        install()
        return
    if a.cmd == 'url':          # where he reads: the secure address, else the board server on this machine
        if a.id is not None and not re.fullmatch(ID, a.id):
            raise ValueError(tr('Invalid thread id'))
        base = secure_home() or os.environ.get('THREADS_BASE_URL') or 'http://127.0.0.1:8767'
        out.append(f'{base}/{SLUG}/suda.html' + (f'#{a.id}' if a.id else ''))
        return
    if a.cmd == 'voice-remux':
        out.extend(voice_remux(a.apply))
        return
    if a.cmd in ('export-state', 'import-state'):
        if STORE_KIND == 'file':
            raise ValueError('THREADS_STORE=file: state.json is already the board')
        with locked():
            if a.cmd == 'export-state':
                target = Path(a.to).expanduser() if a.to else None
                export_state(load(), target)
                out.append(str(target or STATE))
            else:
                if not STATE.exists():
                    raise ValueError(tr('There is no state.json to import'))
                import_state(store(), load_file())
                out.append(str(STORE_PATH))
        return
    if a.cmd == 'help':         # the chapter of the skill, for an agent that did not load it
        if a.topic is None:
            out.append(parser().format_help().rstrip())
        elif a.topic == 'lang':
            out.append(f"{language()} ({text_dir()}): the language of this installation. Write to the owner in it: messages, notes, "
                       "tasks, titles and questions")
        else:
            chapter = re.search(r'<!-- visual:start -->\n(.*?)<!-- visual:end -->', (REPO / 'SKILL.md').read_text(encoding='utf-8'), re.S)
            if chapter is None:
                raise ValueError(tr('The chapter was not found in SKILL.md'))
            out.append(chapter[1].rstrip())
        return
    ts = now()
    # Everything that can be refused is checked before the lock and before any write.
    if a.cmd == 'say':
        # Read stdin before taking the lock: a slow pipe must not block the page.
        a.text = sys.stdin.read() if a.text == '-' else a.text
        if blank(a.text) and not a.image and not a.video:
            raise ValueError(tr('Empty message'))
        storable(a.text, *a.caption)    # refuse text that cannot be stored before an id is promised
        a.body = a.sname = a.page = None
        inline = INLINE_MAX if a.sender == OWNER else TEXT_MAX
        # A --caption right after a --video is that video's; every other one goes to the pictures, in their order.
        captions, under, last, n = [], [None] * len(a.video), None, -1
        for kind, value in getattr(a, 'order', ()):
            if kind == 'video':
                n, last = n + 1, n + 1
            elif kind == 'caption' and last is not None:
                under[last], last = value, None
            else:
                last = None
                if kind == 'caption':
                    captions.append(value)
        if a.video and len(captions) > len(a.image):
            raise ValueError(tr('--caption: at most one per video (right after its --video), and the rest go to the pictures in their order'))
        if len(a.image) > IMAGES_MAX or len(captions) > len(a.image):
            raise ValueError(tr('--image: up to {max} pictures in a message, and at most one --caption per picture', max=IMAGES_MAX))
        if len(a.video) > VIDEOS_MAX:
            raise ValueError(tr('--video: up to {max} videos in a message, and at most one --caption per video (right after it)', max=VIDEOS_MAX))
        a.pictures = [picture(within(f, IMAGE_MAX, tr('--image: up to {mb}MB per picture', mb=IMAGE_MAX // 1_000_000)), Path(f).name, captions[i] if i < len(captions) else None)
                      for i, f in enumerate(a.image)]
        a.videos = [video(f, under[i]) for i, f in enumerate(a.video)]
        attached = {os.path.realpath(f) for f in a.video}
        for named in video_paths(a.text):      # a local video named in the words: he cannot open it
            if os.path.isfile(os.path.expanduser(named)) and os.path.realpath(os.path.expanduser(named)) not in attached:
                print(tr('Warning: the message names a local video, and a page cannot open a local path. For {owner} to see it, attach it: --video {path}', owner=owner_name(), path=named), file=sys.stderr)
        if a.html:                  # an agent's page: shown inside a sandboxed frame, so it must carry everything it needs
            if a.sender == OWNER:
                raise ValueError(tr("--html: an agent's page only"))
            raw = within(a.html, HTML_MAX, tr("--html: an agent's page, up to {kb}KB", kb=HTML_MAX // 1000))
            try:
                a.page = {'raw': raw, 'name': snippet_name(raw.decode('utf-8'), Path(a.html).name)}
            except UnicodeDecodeError:
                raise ValueError(tr('--html: the file is not UTF-8 text')) from None
        if a.snippet:               # a text file attached to the message
            try:                    # decoded from the bytes as they are: every line end stays as it was
                a.body = within(a.snippet, SNIPPET_MAX, tr('The snippet is too big: up to {mb}MB', mb=SNIPPET_MAX // 1_000_000)).decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError(tr('--snippet: the file is not UTF-8 text')) from None
            a.sname = snippet_name(a.body, a.snippet_name or Path(a.snippet).name)
            if len(a.text) > inline:
                raise ValueError(tr('The message is too long beside a snippet: up to {max} characters', max=inline))
        elif len(a.text) > inline:  # too long to read inline: the whole text is kept as a snippet
            a.body, a.text, a.sname = a.text, '', snippet_name(a.text)
        if a.sender == OWNER and (a.state or a.note or a.by or a.live):
            raise ValueError(tr("--state, --note, --by and --live belong to an agent's message"))
        if not a.state and (a.note or a.by):
            raise ValueError(tr('--note and --by come with --state'))
    if a.cmd == 'update':
        a.text = sys.stdin.read() if a.text == '-' else a.text
        if blank(a.text) or len(a.text) > TEXT_MAX:
            raise ValueError(tr('The message is empty or too long: up to {max} characters', max=TEXT_MAX))
        storable(a.text)
        if not a.state and (a.note or a.by):
            raise ValueError(tr('--note and --by come with --state'))
    if a.cmd in ('state', 'resolve') or (a.cmd in ('say', 'update') and a.state):
        a.note = clean_note(a.note, 'done' if a.cmd == 'resolve' else a.state)
    if a.cmd == 'ask':
        a.question = a.question.strip()
        if blank(a.question) or len(a.question) > 2000:
            raise ValueError(tr('The question is empty or too long'))
        a.groups, pictured = None, list(a.option_image)
        if a.groups_file:
            written_groups = json.loads(Path(a.groups_file).read_text(encoding='utf-8'))
            a.groups = clean_groups(written_groups)
            for group in written_groups:        # an item may name its picture in the file itself (a path beside the file, or a whole one)
                for item in group['items']:
                    if isinstance(item, dict) and isinstance(item.get('image'), str):
                        pictured.append(f"{one_line(item.get('text', ''))}={Path(a.groups_file).parent / item['image']}")
        elif a.multi:
            a.groups = clean_groups([{'title': '', 'items': [part for part in (a.options or '').split(',') if part.strip()]}])
        a.options = [item['text'] for group in a.groups for item in group['items']] if a.groups else parse_options(a.options)
        if not in_label_order(a.options):
            raise ValueError(tr('--options: the options are marked (A/B/C, 1/2/3) and are not in order. Keep the order, and mark the recommended one with --recommended instead of moving it'))
        a.recommended = one_line(a.recommended) if a.recommended else None
        if a.recommended and a.recommended not in a.options:
            raise ValueError(tr('--recommended: the label must be one of the options, as it is written'))
        a.option_images = {}
        for raw in pictured:
            label, _, file = raw.partition('=')
            label = one_line(label)
            if label not in a.options or not file or label in a.option_images:
                raise ValueError(tr("--option-image: 'label=file', where the label is one of the options, once per option"))
            a.option_images[label] = picture(within(file, IMAGE_MAX, tr('--option-image: up to {mb}MB per picture', mb=IMAGE_MAX // 1_000_000)), Path(file).name)
        if len(a.option_images) > 12:
            raise ValueError(tr('--option-image: up to 12 pictures per question'))
        # The one line he reads: the question as plain text (or as written, when it is nothing but marks).
        a.ask_note = clean_note(preview(a.question, NOTE_MAX) or one_line(a.question)[:NOTE_MAX], ON_OWNER)
    if a.cmd == 'run-status' and a.note is not None:
        if len(a.note) > NOTE_MAX:
            raise ValueError(tr('--note: up to {max} characters', max=NOTE_MAX))
        a.note = one_line(a.note)
    if hasattr(a, 'by') and not (a.cmd == 'task' and a.by is None):     # (task set: no --by, the owner before the change)
        a.by = short(a.by, 'by')
        if a.cmd in ('close', 'merge', 'react') and reads_as_his(a.by):      # the owner's name, any of them, or 'auto'
            raise ValueError(tr('--by: this name is kept for the page and the automatic close'))
        if a.cmd in ('new', 'say', 'update', 'state', 'resolve'):
            a.by = as_owner(a.by)       # an agent that says the turn is his writes it as the page would
    if a.cmd == 'task' and a.task_cmd in ('archive', 'unarchive'):
        if a.task_cmd == 'archive' and (a.n is None) == (a.done_older_than is None):
            raise ValueError(tr('threads task archive <id> <n>, or --done-older-than <hours>'))
        if a.task_cmd == 'archive' and a.done_older_than is not None and not 0 <= a.done_older_than <= 100000:
            raise ValueError(tr('Invalid number of hours'))
    elif a.cmd == 'task':
        if a.task_cmd == 'add':
            a.text, a.owner = short(a.text, 'task'), short(a.owner, 'owner')
            if blank(a.text):
                raise ValueError(tr('Empty task'))
            if a.by is not None and reads_as_his(a.by):     # a task's history says who made it: never him, never the sweep
                raise ValueError(tr('--by: this name is kept for the page and the automatic close'))
        else:
            a.note = clean_note(a.note, None) if a.note is not None else None
            a.owner = short(a.owner, 'owner') if a.owner is not None else None
            if a.by is not None and reads_as_his(a.by):          # (look-alikes and the sweep's own name too: the history shows who)
                raise ValueError(tr('--by: this name is kept for the page'))
            if a.text is not None:
                a.text = short(a.text, 'task')
                if blank(a.text):
                    raise ValueError(tr('Empty task'))
            if a.status is None and a.text is None and a.note is None and a.owner is None:
                raise ValueError(tr('Nothing to update: a status, --text, --note or --owner'))
        if a.owner is not None:
            a.owner = as_owner(a.owner)     # one spelling for "this one is his"
    if a.cmd in ('new', 'set', 'rename'):
        for field in ('title', 'summary', 'context'):
            value = getattr(a, field, None)
            if value is None:
                continue
            if field == 'context':
                if len(value) > LIMITS['context']:
                    raise ValueError(tr('--{field} is too long: up to {max} characters', field='context', max=LIMITS['context']))
            else:
                setattr(a, field, short(value, field))
        if getattr(a, 'title', None) is not None and blank(a.title):
            raise ValueError(tr('Empty title'))
    wanted = {k: getattr(a, k) for k in POLICY if getattr(a, k, None) is not None} if a.cmd == 'policy' else {}
    if any(not 0 <= v <= 100000 for v in wanted.values()):
        raise ValueError(tr('Invalid number of hours'))
    if a.cmd == 'notify':
        if a.snap:
            wanted['snap'] = a.snap == 'on'
        if a.fallback_minutes is not None:
            if not 1 <= a.fallback_minutes <= 1440:
                raise ValueError(tr('--fallback-minutes: between 1 and 1440'))
            wanted['fallback_minutes'] = a.fallback_minutes
        if a.idle_minutes is not None:
            if not 0.5 <= a.idle_minutes <= 1440:
                raise ValueError(tr('--idle-minutes: between 0.5 and 1440'))
            wanted['idle_minutes'] = a.idle_minutes
        if a.quiet:
            hours = re.fullmatch(r'(\d\d:\d\d)-(\d\d:\d\d)', a.quiet)
            wanted['quiet'] = None if a.quiet == 'off' else {'from': hours[1], 'to': hours[2]} if hours else {}
            if wanted['quiet'] is not None and not is_quiet(wanted['quiet']):
                raise ValueError(tr('--quiet: as 22:00-07:00, or off'))
        if a.url:
            wanted['url'] = '' if a.url == 'off' else a.url
            if wanted['url'] and (not re.match(r'https?://[^\s#]+$', a.url) or len(a.url) > 300):
                raise ValueError(tr('--url: an http(s) address without #'))
        if a.contact:
            if a.contact != 'off' and not re.match(r'(mailto:[^\s@]+@[^\s@]+|https://\S+)$', a.contact):
                raise ValueError(tr('--contact: mailto:… or https://…, or off'))
            write_private(private_dir() / 'contact', b'' if a.contact == 'off' else (a.contact + '\n').encode())
    # Shared lock also gives each read a coherent snapshot.
    with locked():
        data = load()
        reads = a.cmd in ('list', 'show', 'pending', 'sweep', 'policy', 'snippet', 'tasks', 'notify', 'saved') or (a.cmd == 'space' and a.space_cmd == 'list')
        archived = sweep(data, ts, skip=None if reads else (a.id, a.into) if a.cmd == 'merge' else getattr(a, 'id', None))
        # A command that changes the thread decides who is told AFTER its change (in save), never before it.
        dirty = (reads and alerts(data, ts)) or bool(archived) or bool(waking) or bool(noting['voice']) or bool(tidied) or migrated_from is not None or mended
        if a.cmd == 'snippet':
            t = thread(data, a.id)
            msg = next((m for m in t['messages'] if m['id'] == a.msg_id), None)
            if msg is None:
                raise ValueError(tr('Message not found'))
            text = read_exact(snippet_path(t, msg))
            out.append(text[:-1] if text.endswith('\n') else text)
        elif a.cmd == 'tasks':
            rows = thread(data, a.id)['tasks']
            if a.json:
                emit(with_events(rows))     # all of them: an archived task carries `archived` (when it moved), each its events
            else:
                rows = [k for k in rows if a.all or not k.get('archived')]
                out.append('N\tSTATUS\tOWNER\tTEXT\tNOTE')
                out.extend(f"{k['n']}\t{k.get('status', '')}\t{k.get('owner', '')}\t{k.get('text', '')}\t{k.get('note', '')}" for k in rows)
        elif a.cmd == 'space' and a.space_cmd == 'list':
            rows = [{'id': 'main', 'name': tr('Main'), 'letter': 'S', 'color': '#6b3fa0', 'prefix': []}] + [dict(sp) for sp in spaces_of(data)]
            open_ids = sorted(tid for tid, t in data['threads'].items() if t['status'] == 'open')
            for row in rows:        # copies: the list is told, never stored with its threads
                row['threads'] = [tid for tid in open_ids if space_of(data, data['threads'][tid]) == row['id']]
            if a.json:
                emit(rows)
            else:
                out.extend(f"{r['id']}\t{r['name']}\t{','.join(r.get('prefix') or [])}\t{len(r['threads'])}" for r in rows)
        elif a.cmd == 'list':
            listing(data, a)
        elif a.cmd == 'show':
            showing(thread(data, a.id), a)
        elif a.cmd == 'pending':
            emit(pending_rows(data, tower=tower_role(a)))
        elif a.cmd == 'saved':
            rows = saved_rows(data, tower=tower_role(a))
            if a.json:
                emit(rows)
            else:
                out.extend(f"{r['thread']}\t{r['msg']}\t{r['from']}\t{preview(r['text'], 100)}" for r in rows)
        elif a.cmd == 'sweep':
            # The timer never looks at pull requests (suda m478: no updates for nothing): a chip is looked at when it
            # is written, when he opens or comes back to its thread, and a minute after he presses it (link-meta).
            woke = [tid for _, _, tid, kind in waking if kind == 'wake']
            if not a.quiet:
                emit(archived)
            elif archived or woke:
                parts = [f"{label}: {' '.join(ids)}" for label, ids in (('woke', woke), ('archived', archived)) if ids]
                out.append(time.strftime('%Y-%m-%d %H:%M:%S ', time.localtime(ts)) + '; '.join(parts))
        elif a.cmd == 'policy':
            data['policy'].update(wanted)
            if not wanted:
                emit(data['policy'])
            dirty = dirty or bool(wanted)
        elif a.cmd == 'notify':
            if wanted.get('snap') and not data['notify']['snap']:
                # Switched on: the phone hears of what comes from now on, not of everything that already waits.
                for t in data['threads'].values():
                    if thing(t):
                        old = t['alert'] if sound(t.get('alert')) and t['alert']['key'] == thing(t) else {}
                        t['alert'] = {'key': thing(t), 'pushed': old.get('pushed'), 'told': old.get('told') or ts, 'snapped': ts}
            data['notify'].update(wanted)
            dirty = dirty or bool(wanted)
            a.report = dict(data['notify'])
        else:
            dirty = change(data, a, ts) is not False or dirty
        if dirty:
            save(data)
            for job in after_save:
                job()
        elif a.cmd == 'sweep':      # nothing to save, but the chips are still looked after
            telling['links'] += noting['links']
            noting['links'] = []
    if a.cmd == 'notify':           # outside the lock: this may talk to the push service
        try:
            public = vapid_key(create=True)[1]
        except (OSError, subprocess.SubprocessError):
            public = None
        report = {**a.report, 'browsers': len(subscriptions()), 'push_key': bool(public), 'on_suda': on_suda(ts, a.report['idle_minutes'] * 60)}
        if a.test:
            report['test'] = [{'service': urllib.parse.urlsplit(endpoint).hostname, 'status': status} for endpoint, status in push_all()]
        emit(report)


def flush():
    """Print outside the lock: a reader that does not drain the pipe must not block the page."""
    if out:
        sys.stdout.write('\n'.join(out) + '\n')
        sys.stdout.flush()


def main():
    global migrated_from, mended, patient
    migrated_from, mended = None, False     # one command, one clean slate (also when called twice in one process)
    for kept in (out, errs, tidied, noting['links'], telling['links'], after_save, waking, mails, written, noting['phone'], telling['phone'], noting['voice'], telling['voice']):
        kept.clear()
    noting['push'] = telling['push'] = False
    a = parser().parse_args()
    patient = a.cmd in ('sweep', 'tell')     # nobody waits for these: a second try of his phone may take its time here
    detached = dict(start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if a.cmd == 'tell':                 # the detached half of a page action: deliver, print nothing
            telling.update(json.loads(a.what))
            tell()
            return 0
        if a.cmd == 'links':
            fetch_links()
            return 0
        if a.cmd == 'transcribe':
            try:
                transcribe(a.id, a.msg_id)
                for message, tag in mails:
                    send(message, tag)
                tell()
            finally:
                tidy_voice()            # only now: his words are stored before anything is cleaned
            return 0
        try:
            run(a)
        except BaseException:
            discard()                       # the message was never stored: neither are its files
            raise
        try:
            flush()
            if errs:
                print('\n'.join(errs), file=sys.stderr)
        finally:                            # a reader that went away loses the output, never the mail
            for message, tag in mails:
                send(message, tag)
            for tid, mid in telling['voice']:       # the words of a recording take minutes: never inside a command
                subprocess.Popen([sys.executable, os.path.realpath(__file__), 'transcribe', tid, mid], **detached)
            # Pull requests named by what was just stored (or due for another look): asked about in a process of its own.
            if telling['links'] and looks_up():
                want_links([url for url in telling['links'] if url != '-'], now(), limit=5 if a.cmd == 'sweep' else 100)
                if links_file()['wanted']:      # whatever waits, also from a worker that never got to it
                    subprocess.Popen([sys.executable, os.path.realpath(__file__), 'links'], **detached)
            if (telling['push'] or telling['phone']) and os.environ.get('THREADS_NOTIFY') != '0':
                if a.cmd == 'ingest':       # the board server waits for this process: his push must not hold the page
                    subprocess.Popen([sys.executable, os.path.realpath(__file__), 'tell', json.dumps({k: telling[k] for k in ('push', 'phone', 'at')})], **detached)
                else:
                    tell()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError, bl.LockTimeout,
            suda_store.sqlite3.Error) as exc:
        if a.cmd == 'ingest':
            # A refusal has its reason, and the page shows it. When the lock was not free in time, or the disk did
            # not answer, the next try may do better: the receipt says so (`again`), and the page sends once more
            # by itself. A request that cannot be read will not read better the next time, and never says so.
            plain = isinstance(exc, ValueError) and not isinstance(exc, (json.JSONDecodeError, UnicodeError))
            passing = isinstance(exc, (bl.LockTimeout, OSError, suda_store.sqlite3.Error))      # (a store that cannot be opened just now, as a disk)
            print(json.dumps({'ok': False, 'error': str(exc) if plain else tr('The message could not be read or saved'), **({'again': True} if passing else {}), **getattr(exc, 'extra', {})}))
        else:
            print(tr('Error: {error}', error=exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # A failure nobody foresaw, in a page action: the page still gets its one line (without it the page reads
        # a refusal, and a message of his would wait for his press), and may try again. Its kind is written down.
        if a.cmd != 'ingest':
            raise
        logged('ingest', type(exc).__name__)
        print(json.dumps({'ok': False, 'error': tr('The message could not be read or saved'), 'again': True}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
