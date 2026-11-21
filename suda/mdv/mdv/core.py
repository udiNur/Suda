"""The viewer's logic without a server: which files it may open, a document's blocks, how a saved translation lines
up with them, and how a translation is made block by block.

Files written next to a note use the formats of MDS (a markdown reader), so MDS and this viewer read each
other's work:
  foo.en.md               the translation, opened by a marker comment <!-- mds-translation source=... -->
  .foo.en.trans.json      {"v":1,"src_lang","tgt_lang","model","blocks":[{"s":source block,"t":its translation}]}
  .foo.summary.json       {"v":1,"sha","ts","model","truncated","summary"}
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path

MAX_DOC_BYTES = 5 * 1024 * 1024          # a document larger than this is not opened
MAX_TRANSLATE_CHARS = 400_000            # nor translated or summarized past this
BATCH_CHARS = 8000                       # one model call carries at most this much source text
BATCH_BLOCKS = 60                        # and at most this many blocks
LANG_NAMES = {'en': 'English', 'he': 'Hebrew'}
MD_SUFFIXES = ('.md', '.markdown')
MAX_SIDECAR_BYTES = 20 * 1024 * 1024    # a translation state or summary larger than this is not read


class Refused(Exception):
    """A path the viewer will not open. `code` is a short machine word, the message says why in English."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------- which files: the MDS roots, nothing else ----------

def load_roots(roots_json: Path, extra: list[Path]) -> list[Path]:
    """The real folders the viewer may read: every root in MDS's roots.json and the extra ones, resolved through
    symlinks, existing folders only. A broken or missing roots.json leaves only the extra ones."""
    found: list[Path] = []
    try:
        obj = json.loads(roots_json.read_text(encoding='utf-8'))
        for r in obj.get('roots', []) if isinstance(obj, dict) else []:
            if isinstance(r, dict) and isinstance(r.get('path'), str) and r['path'].strip():
                found.append(Path(os.path.expanduser(r['path'].strip())))
    except (OSError, ValueError):
        pass
    found.extend(extra)
    roots: list[Path] = []
    for p in found:
        if not p.is_absolute():
            continue
        real = Path(os.path.realpath(p))
        if real.is_dir() and real != Path('/') and real not in roots:
            roots.append(real)
    return roots


def expand(raw: str, home: Path) -> str:
    """A path as he or an agent writes it (absolute, or ~/...), as an absolute path. Raises Refused."""
    if not isinstance(raw, str) or not raw.strip():
        raise Refused('no-path', 'no path given')
    raw = raw.strip()
    if '\x00' in raw or len(raw) > 4096:
        raise Refused('bad-path', 'not a path')
    if raw == '~' or raw.startswith('~/'):
        raw = str(home) + raw[1:]
    if not raw.startswith('/'):
        raise Refused('bad-path', 'the path must be absolute or start with ~/')
    return raw


def _resolve(raw: str, roots: list[Path], home: Path, kind: str, max_bytes: int) -> tuple[Path, Path]:
    """(the real file, its root) for a path of `kind` ('md' or 'picture') inside one of the roots once every symlink
    is followed, with no hidden folder or file on the way, a regular file of at most `max_bytes`. Raises Refused."""
    def fits(name: str) -> bool:
        return name.lower().endswith(MD_SUFFIXES) if kind == 'md' else picture_type(name) is not None
    wrong = ('not-markdown', 'only .md files open here') if kind == 'md' else ('not-picture', 'only pictures are served here')
    path = expand(raw, home)
    if not fits(path):
        raise Refused(*wrong)
    real = Path(os.path.realpath(path))
    if not fits(real.name):
        raise Refused(*wrong)
    for root in roots:
        try:
            rel = real.relative_to(root)
        except ValueError:
            continue
        if any(part.startswith('.') for part in rel.parts):
            raise Refused('hidden', 'hidden files and folders are not opened')
        try:
            st = os.stat(real)
        except OSError:
            raise Refused('missing', 'no such file')
        if not stat.S_ISREG(st.st_mode):
            raise Refused('missing', 'not a file')
        if st.st_size > max_bytes:
            raise Refused('too-big', 'the file is too large to open here')
        return real, root
    # (the same answer whether or not such a file exists: nothing is told about files outside the roots)
    raise Refused('outside', 'the file is outside the folders the viewer may open')


def resolve(raw: str, roots: list[Path], home: Path) -> tuple[Path, Path]:
    """(the real file, its root) for a note he may open (see _resolve). Raises Refused."""
    return _resolve(raw, roots, home, 'md', MAX_DOC_BYTES)


# Pictures a note shows (suda-fixes task 45: a README's screenshots), served from the same folders by the same rules.
PICTURE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
                 '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml'}
MAX_PICTURE_BYTES = 25 * 1024 * 1024


def picture_type(path) -> str | None:
    """The picture's content type by its name, None for anything that is not a picture."""
    name = str(path)
    dot = name.rfind('.')
    return PICTURE_TYPES.get(name[dot:].lower()) if dot >= 0 and '/' not in name[dot:] else None


def resolve_asset(raw: str, roots: list[Path], home: Path) -> tuple[Path, Path]:
    """(the real picture, its root): a picture inside the roots, by the same rules as a note. Raises Refused."""
    return _resolve(raw, roots, home, 'picture', MAX_PICTURE_BYTES)


def read_bytes_capped(path: Path, cap: int) -> bytes | None:
    """A regular file's bytes, not following a symlink at its name, at most `cap`; None otherwise (never blocks)."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            return None
        chunks, size = [], 0
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            size += len(b)
            if size > cap:
                return None
            chunks.append(b)
        return b''.join(chunks)
    finally:
        os.close(fd)


def shown(path: Path, home: Path) -> str:
    """A path as he reads it: ~/... under his home folder."""
    try:
        return '~/' + str(path.relative_to(home))
    except ValueError:
        return str(path)


# ---------- a document's blocks (MDS's split, so the sidecars match) ----------

def blocks_of(text: str) -> list[str]:
    """Split Markdown into blocks on blank lines, a fenced block whole. The same split as MDS's _blocks_of."""
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False
    fence = ''
    for line in text.split('\n'):
        s = line.lstrip()
        if in_fence:
            cur.append(line)
            if s.startswith(fence):
                in_fence = False
            continue
        if s.startswith('```') or s.startswith('~~~'):
            in_fence = True
            fence = s[:3]
            cur.append(line)
            continue
        if line.strip() == '':
            if cur:
                blocks.append('\n'.join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append('\n'.join(cur))
    return blocks


def detect_lang(text: str) -> str:
    """'he' when the document has more Hebrew letters than Latin ones, else 'en' (MDS's rule)."""
    heb = sum(1 for ch in text if '\u0590' <= ch <= '\u05ff')
    latin = sum(1 for ch in text if ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'))
    return 'he' if heb > latin else 'en'


def other_lang(lang: str) -> str:
    return 'en' if lang == 'he' else 'he'


_LETTER = re.compile('[A-Za-z\u0590-\u05ff]')


def is_verbatim(block: str) -> bool:
    """A block that is copied, not translated: a fenced block (code, a diagram), or one without a letter."""
    s = block.lstrip()
    if s.startswith('```') or s.startswith('~~~'):
        return True
    return not _LETTER.search(block)


def plan_incremental(old_pairs: list[tuple[str, str]], new_blocks: list[str]) -> list[tuple]:
    """MDS's plan: per new block, ('reuse', src, old translation) when its source is unchanged, else ('translate', src)."""
    old_src = [s for s, _ in old_pairs]
    old_tr = [t for _, t in old_pairs]
    plan: list[tuple] = []
    for tag, a1, _a2, b1, b2 in difflib.SequenceMatcher(None, old_src, new_blocks, autojunk=False).get_opcodes():
        if tag == 'equal':
            for k in range(b2 - b1):
                plan.append(('reuse', new_blocks[b1 + k], old_tr[a1 + k]))
        elif tag in ('replace', 'insert'):
            for k in range(b1, b2):
                plan.append(('translate', new_blocks[k]))
    return plan


def context_from_pairs(pairs: list[tuple[str, str]]) -> str:
    """Already translated text before the next block (its nearest heading and the block just before), so a block
    translated alone keeps the document's words. As MDS does."""
    parts: list[str] = []
    heading = None
    for s, t in reversed(pairs):
        if s.lstrip().startswith('#'):
            heading = t
            break
    if heading is not None:
        parts.append(heading)
    if pairs and pairs[-1][1] is not heading:
        parts.append(pairs[-1][1])
    return '\n\n'.join(parts).strip()


# ---------- files next to a note ----------

def _md(real: Path) -> bool:
    return real.name.lower().endswith('.md')


def _stem(real: Path) -> str:
    """The note's name without its suffix. A .md note's files are named as MDS names them; a .markdown note's
    files carry "markdown" where no .md note's files can, so foo.md, foo.markdown and foo.markdown.md never share
    a translation, a state or a summary."""
    n = real.name
    return n[:-3] if _md(real) else n[: -len('.markdown')]


def sibling_path(real: Path, lang: str) -> Path:
    return real.with_name(_stem(real) + '.' + lang + ('.md' if _md(real) else '.markdown'))


def state_path(real: Path, lang: str) -> Path:
    return real.with_name('.' + _stem(real) + '.' + lang + ('' if _md(real) else '.markdown') + '.trans.json')


def summary_path(real: Path) -> Path:
    return real.with_name('.' + _stem(real) + ('.summary.json' if _md(real) else '.summary.markdown.json'))


_TRANSLATION_NAME = re.compile(r'^(?P<base>.+)\.(?P<lang>en|he)\.(?P<ext>md|markdown)$', re.IGNORECASE)
_MARKER = re.compile(r'\A\s*<!--\s*mds-translation\b(?P<attrs>[^>]*)-->\s*', re.IGNORECASE)
_MTIME = re.compile(r'source_mtime="(?P<v>[0-9.]+)"')
_MODEL = re.compile(r'model="(?P<v>[^"]*)"')


def split_marker(text: str) -> tuple[dict | None, str]:
    """A translation file's marker (source_mtime, model) and its text without it. (None, text) when it has none."""
    m = _MARKER.match(text)
    if not m:
        return None, text
    attrs = m.group('attrs')
    info: dict = {}
    mt = _MTIME.search(attrs)
    if mt:
        try:
            info['source_mtime'] = float(mt.group('v'))
        except ValueError:
            pass
    md = _MODEL.search(attrs)
    if md:
        info['model'] = md.group('v')
    return info, text[m.end():]


def original_of(real: Path) -> Path | None:
    """foo.md for a translation foo.en.md that carries MDS's marker and whose foo.md exists, else None."""
    m = _TRANSLATION_NAME.match(real.name)
    if not m:
        return None
    orig = real.with_name(m.group('base') + '.' + m.group('ext'))
    if not orig.is_file():
        return None
    try:
        with open(real, encoding='utf-8', errors='replace') as f:
            head = f.read(600)
    except OSError:
        return None
    return orig if _MARKER.match(head) else None


def make_marker(source_name: str, src_mtime: float, model: str) -> str:
    safe = source_name.replace('"', '').replace('-->', '')
    return ('<!-- mds-translation source="%s" source_mtime="%.0f" model="%s" -->\n\n'
            % (safe, src_mtime, model.replace('"', '')))


def read_capped(path: Path, cap: int, dir_fd: int | None = None) -> str | None:
    """A regular file's text, read without following a symlink at its name, at most `cap` bytes; None when it is
    missing, not a regular file, or larger than `cap`. Never blocks on a FIFO."""
    target = path.name if dir_fd is not None else str(path)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            return None
        chunks, size = [], 0
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            size += len(b)
            if size > cap:
                return None
            chunks.append(b)
        return b''.join(chunks).decode('utf-8', errors='replace')
    finally:
        os.close(fd)


def load_state(path: Path, dir_fd: int | None = None) -> dict | None:
    """A translation state sidecar, or None when it is missing or not of the right shape (never raises)."""
    try:
        raw = read_capped(path, MAX_SIDECAR_BYTES, dir_fd)
        if raw is None:
            return None
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get('blocks'), list):
        return None
    for b in obj['blocks']:
        if not (isinstance(b, dict) and isinstance(b.get('s'), str) and isinstance(b.get('t'), str)):
            return None
    return obj


def load_summary(path: Path, dir_fd: int | None = None) -> dict | None:
    try:
        raw = read_capped(path, MAX_SIDECAR_BYTES, dir_fd)
        if raw is None:
            return None
        obj = json.loads(raw)
    except ValueError:
        return None
    if not (isinstance(obj, dict) and isinstance(obj.get('summary'), str) and isinstance(obj.get('sha'), str)):
        return None
    return obj


def content_sha(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()


class Folder:
    """The folder of a note, held open from the moment its path was checked. Every write beside the note goes
    through this handle, so a folder swapped for a symlink later (a checkout, a move) cannot send a write elsewhere.
    `mode`: the permission bits the files beside the note get, the note's own (a private note stays private)."""

    def __init__(self, real: Path, root: Path):
        fd = os.open(str(real.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            here = os.fstat(fd)
            again = os.path.realpath(real.parent)
            st = os.stat(again)
            Path(again).relative_to(root)
            if (st.st_dev, st.st_ino) != (here.st_dev, here.st_ino):
                raise OSError('the folder changed while it was opened')
            note = os.stat(real.name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(note.st_mode):
                raise OSError('the note is not a file any more')
        except (OSError, ValueError):
            os.close(fd)
            raise OSError('the folder of the note is not where it was checked')
        self.fd = fd
        self.mode = stat.S_IMODE(note.st_mode) & 0o666

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def atomic_write(folder: Folder, name: str, data: str) -> None:
    """Write `name` in the note's folder through a fresh temporary file and a rename. Nothing is written where a
    symlink, a folder or anything but a regular file stands."""
    try:
        st = os.stat(name, dir_fd=folder.fd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode):
            raise OSError('refusing to write over something that is not a file: ' + name)
    except FileNotFoundError:
        pass
    tmp = '.' + name + '.' + secrets.token_hex(6) + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, folder.mode, dir_fd=folder.fd)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            os.fchmod(f.fileno(), folder.mode)
            f.write(data)
        os.replace(tmp, name, src_dir_fd=folder.fd, dst_dir_fd=folder.fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=folder.fd)
        except OSError:
            pass
        raise


def is_ours(text: str | None) -> bool:
    """A translation file this viewer (or MDS) made: it opens with MDS's marker. One he wrote himself is never
    written over."""
    return text is None or split_marker(text)[0] is not None


def with_hand_edits(state: dict | None, sibling_text: str | None) -> dict | None:
    """The saved state, with the translation file's own blocks in it when the file was edited by hand and still has
    one block per pair: what he changed there is what is shown, and what the next run keeps."""
    if not state or not state.get('blocks') or sibling_text is None:
        return state
    body = split_marker(sibling_text)[1]
    tr = blocks_of(body)
    if len(tr) != len(state['blocks']):
        return state
    return {**state, 'blocks': [{'s': b['s'], 't': t} for b, t in zip(state['blocks'], tr)]}


# ---------- how a saved translation lines up with the document ----------

def translation_view(src_blocks: list[str], src_mtime: float, sibling_text: str | None,
                     state: dict | None) -> dict:
    """What the page shows beside each block.

    {"exists": False} with no translation file. Otherwise "aligned": True and "blocks": one entry per source block,
    {"t": text, "stale": bool} or None (no translation for it yet); or "aligned": False and "full": the whole
    translation, when it cannot be lined up block by block. "stale" counts the blocks whose source changed since."""
    if sibling_text is None:
        return {'exists': False}
    marker, body = split_marker(sibling_text)
    state = with_hand_edits(state, sibling_text)
    pairs = None
    if state and state.get('blocks'):
        pairs = [(b['s'], b['t']) for b in state['blocks']]
        # MDS keeps one opaque pair when it could not line a translation up: no blocks to show beside.
        if len(pairs) == 1 and len(blocks_of(pairs[0][0])) > 1:
            pairs = None
    if pairs is not None:
        out: list = [None] * len(src_blocks)
        old_src = [s for s, _ in pairs]
        for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old_src, src_blocks, autojunk=False).get_opcodes():
            if tag == 'equal':
                for k in range(b2 - b1):
                    out[b1 + k] = {'t': pairs[a1 + k][1], 'stale': False}
            elif tag == 'replace':
                for k in range(min(b2 - b1, a2 - a1)):
                    src = src_blocks[b1 + k]
                    out[b1 + k] = {'t': src if is_verbatim(src) else pairs[a1 + k][1], 'stale': not is_verbatim(src)}
        for i, src in enumerate(src_blocks):
            if out[i] is None and is_verbatim(src):
                out[i] = {'t': src, 'stale': False}
        return {'exists': True, 'aligned': True, 'blocks': out,
                'stale': sum(1 for x in out if x is None or x['stale'])}
    tr_blocks = blocks_of(body)
    old = bool(marker and marker.get('source_mtime') is not None and src_mtime > marker['source_mtime'] + 1.0)
    if len(tr_blocks) == len(src_blocks) and src_blocks:
        return {'exists': True, 'aligned': True, 'blocks': [{'t': t, 'stale': old} for t in tr_blocks],
                'stale': len(src_blocks) if old else 0}
    return {'exists': True, 'aligned': False, 'full': body.strip(), 'stale': 1 if old else 0}


# ---------- making a translation, block by block ----------

def translate_system(src: str, tgt: str) -> str:
    return (
        'You are a professional translator for a personal Markdown notes app. '
        'Translate Markdown blocks into %s (the source is mostly %s).\n\n'
        'The user message holds the blocks, each wrapped as <mdv-block n="NUMBER">...</mdv-block>.\n'
        'Rules:\n'
        '- Reply with every block, translated, each wrapped in the same tag with the same number, in the same '
        'order. Nothing before, between or after the blocks. Never merge, split, skip or add a block.\n'
        '- A block may mix Hebrew and English. Render all natural-language text in %s; technical terms with no '
        'good %s equivalent may stay in English.\n'
        '- Keep the Markdown structure of each block exactly: headings, lists, tables, quotes, task boxes, links.\n'
        '- Copy inline code spans, code, identifiers, commands, URLs, link targets, file paths, IDs and numbers '
        'unchanged. Translate only human-readable link text.\n'
        '- Do not wrap a block in a code fence.'
    ) % (LANG_NAMES[tgt], LANG_NAMES[src], LANG_NAMES[tgt], LANG_NAMES[tgt])


# A note may itself speak of <mdv-block> (this tool's own notes do): such text is sent escaped, so it can neither
# end its block early nor pass for another block's answer, and comes back exactly as it was. The escape is a
# stuffing: "<mdv-block" becomes "&lt;mdv-block", and "&lt;mdv-block", "&amp;lt;mdv-block", ... each gain one
# "amp;"; the way back removes exactly one. (The same for "</mdv-block".)
_ESC_RE = re.compile(r'(?:&((?:amp;)*)lt;|<)(/?)mdv-block')
_UNESC_RE = re.compile(r'&((?:amp;)*)lt;(/?)mdv-block')


def escape_tags(text: str) -> str:
    return _ESC_RE.sub(lambda m: ('&lt;' if m.group(1) is None else '&amp;' + m.group(1) + 'lt;')
                       + m.group(2) + 'mdv-block', text)


def unescape_tags(text: str) -> str:
    return _UNESC_RE.sub(lambda m: ('<' if not m.group(1) else '&' + m.group(1)[4:] + 'lt;')
                         + m.group(2) + 'mdv-block', text)


def wrap_blocks(items: list[tuple[int, str]]) -> str:
    return '\n\n'.join('<mdv-block n="%d">\n%s\n</mdv-block>' % (n, escape_tags(text)) for n, text in items)


# an answer runs to the first closing tag and holds no opening tag (an unclosed one does not swallow the next)
_BLOCK_OUT = re.compile(r'<mdv-block n="(\d+)">\n?((?:(?!<mdv-block).)*?)\n?</mdv-block>', re.DOTALL)


def parse_blocks(text: str, wanted: set[int]) -> dict[int, str]:
    """The finished blocks in a (possibly partial) reply: {number: translation}, only numbers that were asked for,
    the first answer for each, stripped. An empty translation is not an answer."""
    got: dict[int, str] = {}
    for m in _BLOCK_OUT.finditer(text):
        n = int(m.group(1))
        body = unescape_tags(m.group(2).strip())
        if n in wanted and n not in got and body:
            got[n] = body
    return got


def batches(items: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """The blocks to translate, in order, cut into calls of at most BATCH_CHARS / BATCH_BLOCKS (a longer block
    goes alone)."""
    out: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    size = 0
    for n, text in items:
        if cur and (size + len(text) > BATCH_CHARS or len(cur) >= BATCH_BLOCKS):
            out.append(cur)
            cur, size = [], 0
        cur.append((n, text))
        size += len(text)
    if cur:
        out.append(cur)
    return out


def messages_for(items: list[tuple[int, str]], context: str) -> list[dict]:
    body = wrap_blocks(items)
    context = escape_tags(context)            # the text before may speak of the tags too
    if context:
        return [
            {'role': 'user', 'content': 'For reference only: the text before the next blocks, ALREADY translated. '
                                        'It must NOT appear in your reply; use it to keep the words consistent.\n\n'
                                        + context},
            {'role': 'assistant', 'content': 'Understood. I will translate only the blocks of the next message.'},
            {'role': 'user', 'content': body},
        ]
    return [{'role': 'user', 'content': body}]


def translate_blocks(src_blocks: list[str], src_lang: str, tgt_lang: str, state: dict | None, model: str,
                     stream, on_block=None, should_stop=None) -> dict:
    """Translate a document's blocks, sending the model only what changed since the saved state.

    `stream(system, messages)` yields the reply's text in pieces (the model call, or a stand-in in tests).
    `on_block(i, text, how)` is told each block as soon as it is known (how: reuse, copy, model).
    Gives back {"pairs": [(src, translation)] for the state, "blocks": [translation or None per block],
    "sent": blocks sent to the model, "reused": n, "failed": [block numbers the model did not answer]}."""
    on_block = on_block or (lambda *_: None)
    should_stop = should_stop or (lambda: False)
    compatible = bool(state and state.get('src_lang') == src_lang and state.get('tgt_lang') == tgt_lang
                      and state.get('model') == model and state.get('blocks'))
    if compatible:
        plan = plan_incremental([(b['s'], b['t']) for b in state['blocks']], src_blocks)
    else:
        plan = [('translate', s) for s in src_blocks]
    result: list = [None] * len(src_blocks)
    todo: list[tuple[int, str]] = []
    reused = 0
    for i, op in enumerate(plan):
        if op[0] == 'reuse':
            result[i] = op[2]
            reused += 1
            on_block(i, op[2], 'reuse')
        elif is_verbatim(op[1]):
            result[i] = op[1]
            on_block(i, op[1], 'copy')
        else:
            todo.append((i, op[1]))
    system = translate_system(src_lang, tgt_lang)

    def pairs_before(i: int) -> list[tuple[str, str]]:
        return [(src_blocks[k], result[k]) for k in range(i) if result[k] is not None]

    def run(items: list[tuple[int, str]]) -> set[int]:
        wanted = {n for n, _ in items}
        buf = ''
        done: set[int] = set()
        for piece in stream(system, messages_for(items, context_from_pairs(pairs_before(items[0][0])))):
            if should_stop():
                raise InterruptedError('stopped')
            buf += piece
            for n, t in parse_blocks(buf, wanted - done).items():
                result[n] = t
                done.add(n)
                on_block(n, t, 'model')
        return done

    failed: list[int] = []
    for batch in batches(todo):
        done = run(batch)
        for n, text in batch:
            if n not in done:
                if not run([(n, text)]):
                    failed.append(n)
    pairs = [(src_blocks[i], result[i]) for i in range(len(src_blocks)) if result[i] is not None]
    return {'pairs': pairs, 'blocks': result, 'sent': len(todo), 'reused': reused, 'failed': failed}


def save_translation(real: Path, root: Path, src_text: str, src_mtime: float, src_lang: str, tgt_lang: str,
                     outcome: dict, model: str, folder: Folder | None = None) -> Path:
    """Write foo.<tgt>.md and its state, as MDS does. A block the model did not answer stands in the file in its
    own language and is left out of the state, so the next run sends it again. A foo.<tgt>.md he wrote himself
    (no marker) is never written over: OSError."""
    if folder is None:
        with Folder(real, root) as own:
            return save_translation(real, root, src_text, src_mtime, src_lang, tgt_lang, outcome, model, own)
    src_blocks = blocks_of(src_text)
    body = '\n\n'.join(t if t is not None else s for s, t in zip(src_blocks, outcome['blocks'])).strip()
    sib = sibling_path(real, tgt_lang)
    try:
        name = str(real.relative_to(root))
    except ValueError:
        name = real.name
    there = read_capped(sib, MAX_DOC_BYTES * 4, folder.fd)
    if (there is None and _exists(sib.name, folder)) or not is_ours(there):
        raise OSError(sib.name + ' is not a translation made here; it is left as it is')
    atomic_write(folder, sib.name, make_marker(name, src_mtime, model) + body + '\n')
    obj = {'v': 1, 'src_lang': src_lang, 'tgt_lang': tgt_lang, 'model': model,
           'blocks': [{'s': s, 't': t} for s, t in outcome['pairs']]}
    atomic_write(folder, state_path(real, tgt_lang).name, json.dumps(obj, ensure_ascii=False))
    return sib


def _exists(name: str, folder: Folder) -> bool:
    try:
        os.stat(name, dir_fd=folder.fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


# ---------- the summary ----------

SUMMARY_SYSTEM = (      # (in the installation's language: the server sends l10n.tr() of it)
    'You summarize documents. Read the document and return a short, clear summary **in English only**, '
    'even if the source is in another language.\n\n'
    'Format:\n'
    '- One paragraph of 2 to 3 sentences that says what this document is, the bottom line.\n'
    '- After it 3 to 7 bullet points with the essentials: decisions, numbers, dates, names, and what is open.\n'
    "- If there are tasks or next steps, end with a section '### Next steps'.\n\n"
    "Rules: return Markdown only, no preamble and no 'here is the summary'. Do not invent facts: "
    'if something is not written in the document, do not write it. Keep technical terms, paths, file names '
    'and numbers exactly as they are.'
)


def save_summary(folder: Folder, real: Path, text: str, summary: str, model: str) -> dict:
    obj = {'v': 1, 'sha': content_sha(text), 'ts': time.time(), 'model': model, 'truncated': False,
           'summary': summary}
    atomic_write(folder, summary_path(real).name, json.dumps(obj, ensure_ascii=False))
    return obj
