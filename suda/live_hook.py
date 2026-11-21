#!/usr/bin/env python3
"""The live dot of Suda (task 111, thread suda m338 to m342): what every agent is doing right now.

A Claude Code hook (user settings, every agent) runs this on UserPromptSubmit, PreToolUse, PostToolUse, Stop,
StopFailure, Notification and SessionEnd. It keeps one small file per tuios pane (atomic write, private folder):

    {pane, session, state: working|idle|waiting|stuck, why, thread, by, what, ts, event}

and then writes the board's `live.json` (beside state.json, served read-only by the board server behind the
gateway): every agent tuios knows, its name, its state and the thread it works on. tuios fills in what a hook
cannot see: the window's name, and an agent that hit its usage limit or is near the end of its context.

The thread is taken from the last `threads` command the agent ran that writes into a thread (say, state, ask,
task add/set, …), so one chat that holds several threads is still told right. What the agent does is said in
a few words (the description of its shell command, the name of the file it reads), never the command itself.

It must never get in the way: it prints nothing, always exits 0, and gives up quietly on anything unexpected.
Only the standard library: it starts in a few milliseconds (python3 -I -S).
"""
import json
import os
import re
import stat
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:         # not on this Mac; the hook then simply does nothing
    fcntl = None

HOME = os.path.expanduser('~')
LIVE_DIR = os.environ.get('THREADS_LIVE_DIR') or os.path.join(HOME, '.local/state/threads-live')
OUT = os.environ.get('THREADS_LIVE_OUT') or os.path.join(
    os.environ.get('BOARDS_DIR') or os.path.join(HOME, 'Documents/mds/boards'), 'threads', 'live.json')
TUIOS = os.environ.get('THREADS_LIVE_TUIOS_CMD')        # a stand-in for tests; 'none' means no tuios at all

PANE = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{8,40}')
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,47}')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,59}')
STATES = ('working', 'idle', 'waiting', 'stuck')
WHAT_MAX = 80
KEEP = 7 * 86400            # a pane file nobody touched for a week is gone (its pane is long closed)
QUIET = 30 * 60             # "working" with no word for this long, while tuios does not say so either: idle
TUIOS_FRESH = 10            # seconds a snapshot of tuios is used before it is read again
AGENTS_MAX = 80
CONTEXT_FULL = 900_000      # tokens in the last request: an agent that stopped this full is stuck on its context
TRANSCRIPT_TAIL = 512 * 1024    # bytes of the transcript read from its end (it can be hundreds of megabytes)

# A threads command that writes into a thread: its id is the word after the verb.
VERBS = r'(?:say|state|ask|update|resolve|close|reopen|snooze|unsnooze|mute|rename|set|link|new|ack|task\s+(?:add|set))'
THREADS_CMD = re.compile(r'^\s*[({]?\s*(?:(?:exec|command|time|env)\s+)*(?:python3?\s+)?(?:[\w.~-]*/)*threads(?:\.py)?\s+'
                         + VERBS + r'\s+([a-z0-9][a-z0-9-]{0,47})(?![\w-])')
BY = re.compile(r'--by(?:=|\s+)[\'"]?([A-Za-z0-9][A-Za-z0-9_.-]{0,59})')
OTHER_BOARD = re.compile(r'\b(?:THREADS_SLUG|BOARDS_DIR)=')
SEGMENT = re.compile(r'&&|\|\||;|\||\n')


def now():
    return time.time()


_TABLE = None


def config_dir():
    """The private folder of the board this hook writes (as threads.py's private_dir for the slug "threads")."""
    if os.environ.get('THREADS_CONFIG_DIR'):
        return os.path.join(os.environ['THREADS_CONFIG_DIR'], 'threads')
    boards = os.environ.get('BOARDS_DIR')
    if boards and os.path.realpath(boards) != os.path.realpath(os.path.join(HOME, 'Documents/mds/boards')):
        return os.path.join(os.path.dirname(os.path.realpath(boards)), '.threads-config', 'threads')
    return os.path.join(HOME, '.config/threads/threads')


def tr(text, /, **values):
    """`text` in the installation's language (config.json "lang"; the table of locales/<lang>.json and its parts,
    as threads.py reads it), with {name} filled from `values`. English when anything is missing."""
    global _TABLE
    if _TABLE is None:
        _TABLE = {}
        try:
            with open(os.path.join(config_dir(), 'config.json'), encoding='utf-8') as f:
                conf = json.load(f)
            lang, named = conf.get('lang'), conf.get('locale_file')
            if isinstance(lang, str) and re.fullmatch(r'[a-z]{2}(-[A-Z]{2})?', lang) and lang != 'en':
                here = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'locales')
                places = [os.path.expanduser(named)] if isinstance(named, str) and named else \
                    [os.path.join(here, name) for name in [f'{lang}.json'] + sorted(
                        n for n in os.listdir(here) if re.fullmatch(re.escape(lang) + r'\..+\.json', n))]
                for where in places:
                    try:
                        with open(where, encoding='utf-8') as f:
                            raw = json.load(f)
                    except (OSError, ValueError):
                        continue
                    if isinstance(raw, dict):
                        _TABLE.update({k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)})
        except (OSError, ValueError, AttributeError):
            pass
    out = _TABLE.get(text, text)
    try:
        return out.format(**values) if values else out
    except (KeyError, IndexError, ValueError):
        return text.format(**values)


def thread_of(command):
    """(thread, by) from a shell command, or (None, None). The last writing threads command wins; one aimed at
    another board (THREADS_SLUG=…, BOARDS_DIR=…) is not his board's thread."""
    found = (None, None)
    if not isinstance(command, str) or OTHER_BOARD.search(command[:20000]):
        return found
    for part in SEGMENT.split(command[:20000]):
        if 'threads' not in part:
            continue
        part = part[:2000]          # a threads command is short; a huge argument is never scanned
        hit = THREADS_CMD.match(part)       # at the start of a command: words that only quote one are not one
        if hit:
            by = BY.search(part)
            found = (hit.group(1), by.group(1) if by else None)
    return found


def base(path):
    return os.path.basename(str(path).rstrip('/')) if path else ''


SECRETS = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'                     # an address
                     r'|\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs]|AKIA|AIza|eyJ)[\w-]{6,}'   # keys of known shapes
                     r'|\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{20,}\b'        # a long run of letters and digits: a token, a hash
                     r'|https?://\S+')


def redact(text):
    """What is published goes to his tailnet: an address, a key, a token or a link in an agent's words is not."""
    return SECRETS.sub('…', text)


def what_of(tool, data):
    """A few words on what the agent does: never a command line, a secret or a full path."""
    data = data if isinstance(data, dict) else {}
    if tool == 'Bash':
        said = data.get('description')
        text = said if isinstance(said, str) and said.strip() else tr('Running a command')
    elif tool in ('Read', 'NotebookRead'):
        text = tr('Reading {file}', file=base(data.get('file_path') or data.get('notebook_path')))
    elif tool in ('Edit', 'MultiEdit', 'Write', 'NotebookEdit'):
        text = tr('Editing {file}', file=base(data.get('file_path') or data.get('notebook_path')))
    elif tool in ('Grep', 'Glob'):
        text = tr('Searching the code')
    elif tool in ('Agent', 'Task'):
        said = data.get('description')
        text = tr('Subagent: {what}', what=said) if isinstance(said, str) and said.strip() else tr('Subagent')
    elif tool in ('WebFetch', 'WebSearch'):
        text = tr('Searching the web')
    elif isinstance(tool, str) and tool.startswith('mcp__'):
        text = tr('Tool {name}', name=tool.split('__')[1]) if tool.count('__') >= 2 else tr('An outside tool')
    else:
        text = tool if isinstance(tool, str) else ''
    text = redact(' '.join(str(text).split()))
    return text[:WHAT_MAX - 1] + '…' if len(text) > WHAT_MAX else text


def stuck_why(data):
    """StopFailure: the kind of error the turn ended on."""
    kind = ''
    for key in ('error_type', 'error', 'reason', 'matcher'):
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get('type') or value.get('error_type') or ''
        if isinstance(value, str) and value:
            kind = value
            break
    return 'limit' if re.search(r'rate.?limit|usage.?limit|billing|quota|overloaded', kind, re.I) else 'error'


def context_of(path):
    """How full the agent's context is, by its own transcript (thread suda m419: tuios said it was not).
    ('full', None): its newest reply is 'Prompt is too long' (nothing fits any more: /compact in its window).
    ('near', tokens): its newest real request held CONTEXT_FULL tokens or more. (None, tokens|None) otherwise.
    Only the main agent counts (a subagent's lines are skipped), only its newest reply, and nothing before a
    compaction. The file must be a regular .jsonl file; at most the last TRANSCRIPT_TAIL bytes are read, never
    blocking (a FIFO, a device, a link are refused)."""
    if not (isinstance(path, str) and path.endswith('.jsonl') and os.path.isabs(path) and '/../' not in path):
        return None, None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    except OSError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, None
        start = max(0, info.st_size - TRANSCRIPT_TAIL)
        raw = os.pread(fd, TRANSCRIPT_TAIL, start)
    except OSError:
        return None, None
    finally:
        os.close(fd)
    lines = raw.split(b'\n')                 # bytes: a raw U+2028 inside a reply is not a line of its own
    if start > 0:
        lines = lines[1:]                     # the first line of a cut tail is cut
    for line in reversed(lines):
        if b'"assistant"' not in line and b'compact' not in line.lower():
            continue
        try:
            entry = json.loads(line.decode('utf-8', 'replace'))
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get('isSidechain'):
            continue                          # a subagent's own conversation is not the agent's context
        if (entry.get('type') == 'system' and entry.get('subtype') == 'compact_boundary') or entry.get('isCompactSummary'):
            return None, None                 # compacted since: whatever came before says nothing now
        msg = entry.get('message')
        if entry.get('type') != 'assistant' or not isinstance(msg, dict):
            continue
        content = msg.get('content') if isinstance(msg.get('content'), list) else []
        said = ' '.join(c.get('text', '') for c in content if isinstance(c, dict) and isinstance(c.get('text'), str))
        if entry.get('isApiErrorMessage') or msg.get('model') == '<synthetic>':
            if 'prompt is too long' in said.lower():
                return 'full', None
            if entry.get('isApiErrorMessage'):
                return None, None             # another error says nothing about the context, and it is the newest reply
            continue                          # a synthetic line that is not an error ("No response requested.")
        usage = msg.get('usage') if isinstance(msg.get('usage'), dict) else {}
        tokens = sum(v for k, v in usage.items() if k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens') and isinstance(v, int))
        return ('near' if tokens >= CONTEXT_FULL else None), (tokens or None)
    return None, None


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            value = json.load(f)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_atomic(path, text, mode=0o600):
    folder = os.path.dirname(path)
    tmp = os.path.join(folder, '.%s.%s.tmp' % (os.path.basename(path), os.urandom(6).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.utime(tmp)       # its time is when it is put in place: pages ask live.json "changed since?" by it
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(event, data, pane, session, ts, ctx=None):
    """The pane's new record, or None when this event says nothing new (or the session ended)."""
    path = os.path.join(LIVE_DIR, pane + '.json')
    old = read_json(path) or {}
    rec = {k: old.get(k) for k in ('state', 'why', 'thread', 'by', 'what', 'ts', 'event', 'sid')}
    rec.update(v=1, pane=pane, session=session)
    sid = data.get('session_id') if isinstance(data.get('session_id'), str) else ''
    if sid and old.get('sid') and sid != old['sid']:
        if not (event == 'UserPromptSubmit' and old.get('state') != 'working'):
            return None         # another Claude in this pane while its own works: not this pane's agent
        rec.update(thread=None, by=None)        # a new session: what the old one worked on is not its own
    if sid:
        rec['sid'] = sid
    if event == 'SessionEnd':
        try:
            os.unlink(path)
        except OSError:
            pass
        return 'gone'
    if event == 'UserPromptSubmit':
        rec.update(state='working', why='', what='')
    elif event == 'PreToolUse':
        tool = data.get('tool_name')
        tin = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
        rec.update(state='working', why='', what=what_of(tool, tin))
        if tool == 'Bash':
            tid, by = thread_of(tin.get('command'))
            if tid:
                rec['thread'] = tid
                if by:
                    rec['by'] = by
    elif event == 'PostToolUse':
        if old.get('state') == 'working':
            return None             # nothing new: the next tool or the end of the turn will say what is
        rec.update(state='working', why='')
    elif event == 'Stop':
        rec.update(state='idle', why='', what='')
    elif event == 'StopFailure':
        rec.update(state='stuck', why=stuck_why(data))
    elif event == 'Notification':
        kind = data.get('notification_type') or ''
        message = data.get('message') if isinstance(data.get('message'), str) else ''
        if kind == 'permission_prompt' or (not kind and re.search(r'permission', message, re.I)):
            rec.update(state='waiting', why='approval')
        elif kind == 'elicitation_dialog':
            rec.update(state='waiting', why='question')
        elif kind == 'idle_prompt' or (not kind and re.search(r'waiting for your input', message, re.I)):
            if old.get('state') == 'stuck' and old.get('why') in ('context', 'near') and not (ctx or (None,))[0]:
                pass                # he compacted (no prompt fires for /compact): at rest again
            elif old.get('state') in ('waiting', 'stuck'):
                return None         # still stuck: idling at the prompt does not undo that
            rec.update(state='idle', why='', what='')
        else:
            return None
    else:
        return None
    if event in ('Stop', 'StopFailure'):
        kind, tokens = ctx or (None, None)
        if kind:
            rec.update(state='stuck', why='context' if kind == 'full' else 'near', what='')
        rec['tokens'] = tokens
    rec.update(ts=round(ts, 3), event=event)
    write_atomic(path, json.dumps(rec, ensure_ascii=False))
    return rec


def tuios_agents(force, ts):
    """Every agent tuios knows, read at most every few seconds (a snapshot is kept beside the pane files).
    None when tuios cannot be asked: then the pane files alone are told."""
    snap = os.path.join(LIVE_DIR, '.tuios.json')
    kept = read_json(snap)
    fresh = kept and isinstance(kept.get('at'), (int, float)) and 0 <= ts - kept['at'] < TUIOS_FRESH
    if fresh and (not force or kept.get('failed')):      # a tuios that did not answer is not asked again at once
        return kept.get('agents')
    if TUIOS == 'none':
        return None

    def failed():
        agents = kept.get('agents') if kept else None
        try:
            write_atomic(snap, json.dumps({'at': ts, 'agents': agents, 'failed': True}))
        except OSError:
            pass
        return agents
    cmd = TUIOS.split() if TUIOS else ['tuios', 'list-agents', '--all-sessions', '--json']
    env = dict(os.environ)
    env.pop('TUIOS_PANE_ID', None)
    env['PATH'] = env.get('PATH', '') + ':/opt/homebrew/bin:' + os.path.join(HOME, '.local/bin')
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1, env=env).stdout
        rows = json.loads(out).get('agents')
        if not isinstance(rows, list):
            return failed()
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return failed()
    agents = []
    for a in rows[:200]:
        if not isinstance(a, dict) or not isinstance(a.get('window_id'), str) or not PANE.fullmatch(a['window_id']):
            continue
        ctx = a.get('context') if isinstance(a.get('context'), dict) else {}
        at = a.get('agent_state_at')
        agents.append({'pane': a['window_id'], 'name': a.get('name') if isinstance(a.get('name'), str) else '',
                       'session': a.get('session') if isinstance(a.get('session'), str) else '',
                       'state': a.get('state') if isinstance(a.get('state'), str) else '',
                       'at': at / 1e9 if isinstance(at, (int, float)) and at > 1e15 else at if isinstance(at, (int, float)) else 0,
                       'limit': a.get('limit_resets') if isinstance(a.get('limit_resets'), str) else '',
                       'near': ctx.get('near') is True,
                       'blocked': a.get('blocked_by') if isinstance(a.get('blocked_by'), str) else ''})
    try:
        write_atomic(snap, json.dumps({'at': ts, 'agents': agents}, ensure_ascii=False))
    except OSError:
        pass
    return agents


def clean(text, limit):
    return ' '.join(text.split())[:limit] if isinstance(text, str) else ''


def merge(rec, tu, ts):
    """One agent as the page sees it: the hook's word, corrected by what tuios knows that is newer."""
    hook = rec or {}
    state = hook.get('state') if hook.get('state') in STATES else None
    why = hook.get('why') if isinstance(hook.get('why'), str) else ''
    at = hook.get('ts') if isinstance(hook.get('ts'), (int, float)) else 0
    if tu:
        tstate = {'working': 'working', 'needs_input': 'waiting', 'idle': 'idle', 'done': 'idle'}.get(tu.get('state'))
        newer = (tu.get('at') or 0) > at + 1
        if state is None and not tstate and tu.get('state') == 'unknown':
            # an agent tuios has not judged yet, and no hook of its own: at rest for the page, never missing (a dot
            # that came and went with tuios's moods made the list jump, thread suda m381); it never corrects a hook
            state, why, at = 'idle', '', tu.get('at') or 0
        elif state is None and tstate:
            state, why, at = tstate, 'approval' if tstate == 'waiting' else '', tu.get('at') or 0
        elif tstate and newer and state != tstate and state in ('working', 'waiting') and tstate in ('working', 'waiting', 'idle'):
            state, why, at = tstate, 'approval' if tstate == 'waiting' else '', tu['at']      # an approval given, a turn he interrupted
        if tu.get('limit') and state not in ('working', 'waiting'):
            state, why = 'stuck', 'limit'
        elif tu.get('near') and state == 'idle':
            state, why = 'stuck', 'near'
    if state is None:
        return None
    if state == 'working' and at and ts - at > QUIET and not (tu and tu.get('state') == 'working'):
        state, why = 'idle', ''
    out = {'pane': (rec or tu)['pane'], 'name': clean((tu or {}).get('name'), 60) or clean(hook.get('by'), 60),
           'session': clean((tu or {}).get('session') or hook.get('session'), 60),
           'state': state, 'why': why if state in ('waiting', 'stuck') else '',
           'thread': hook.get('thread') if isinstance(hook.get('thread'), str) and ID.fullmatch(hook['thread']) else '',
           'by': hook.get('by') if isinstance(hook.get('by'), str) and NAME.fullmatch(hook['by']) else '',
           'what': clean(hook.get('what'), WHAT_MAX) if state == 'working' else '',
           'ts': round(at, 3) if at else 0}
    if tu and tu.get('limit'):
        out['resets'] = clean(tu['limit'], 60)
    if isinstance(hook.get('tokens'), int) and hook['tokens'] > 0:
        out['tokens'] = hook['tokens']      # the real size of its last request, from its own transcript
    return out


def aggregate(ts, tu):
    """live.json: every agent. Called under the lock, so that two hooks at once do not write an older picture last.
    `tu` is what tuios said (read before the lock), or None."""
    if not os.path.isdir(os.path.dirname(OUT)):
        return
    if True:
        by_pane = {a['pane']: a for a in tu} if isinstance(tu, list) else None
        recs = {}
        for name in os.listdir(LIVE_DIR):
            if not name.endswith('.json') or name.startswith('.'):
                continue
            pane = name[:-5]
            if not PANE.fullmatch(pane):
                continue            # not a file of this hook: never touched
            path = os.path.join(LIVE_DIR, name)
            rec = read_json(path)
            gone = rec is None or not PANE.fullmatch(pane) or not isinstance(rec.get('ts'), (int, float)) or ts - rec['ts'] > KEEP
            if not gone and by_pane and pane not in by_pane and ts - rec['ts'] > 600:
                gone = True         # tuios lists agents and not this pane, for ten minutes: it was closed
            if gone:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                continue
            recs[pane] = rec
        agents = []
        for pane in sorted(set(recs) | set(by_pane or {})):
            row = merge(recs.get(pane), (by_pane or {}).get(pane), ts)
            if row:
                agents.append(row)
        agents.sort(key=lambda a: -a['ts'])
        body = {'version': 1, 'agents': agents[:AGENTS_MAX]}
        before = read_json(OUT)
        if before and before.get('version') == 1 and before.get('agents') == body['agents']:
            return          # nothing changed: the file (and every page reading it) is left alone
        body['ts'] = round(ts, 3)
        write_atomic(OUT, json.dumps(body, ensure_ascii=False, separators=(',', ':')) + '\n', 0o644)


def locked():
    """The hook's lock (a second at most: an agent never waits for the picture), or None."""
    lock = open(os.path.join(LIVE_DIR, '.lock'), 'a')
    end = time.monotonic() + 1
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except OSError:
            if time.monotonic() > end:
                lock.close()
                return None
            time.sleep(0.01)


def main():
    raw = sys.stdin.read(4_000_000)
    pane = os.environ.get('TUIOS_PANE_ID') or ''
    if not pane or not PANE.fullmatch(pane) or fcntl is None:
        return          # not an agent in a tuios pane: nobody could open its window, nothing to tell
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    event = data.get('hook_event_name') or (sys.argv[1] if len(sys.argv) > 1 else '')
    os.makedirs(LIVE_DIR, mode=0o700, exist_ok=True)
    ts = now()
    session = os.environ.get('TUIOS_SESSION') or ''
    tu = tuios_agents(event in ('Stop', 'StopFailure', 'Notification', 'SessionEnd', 'UserPromptSubmit'), ts) if os.path.isdir(os.path.dirname(OUT)) else None
    # the transcript is read before the lock too: whatever it costs, it never holds the other agents
    ctx = context_of(data.get('transcript_path')) if event in ('Stop', 'StopFailure', 'Notification') else None
    lock = locked()
    try:
        rec = record(event, data, pane, session if NAME.fullmatch(session or '-') else '', ts, ctx)
        if rec is not None and lock is not None:        # without the lock the pane's own file is still right; the picture waits for the next event
            aggregate(ts, tu)
    finally:
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    try:
        main()
    except BaseException:       # never the agent's problem
        pass
    sys.exit(0)
