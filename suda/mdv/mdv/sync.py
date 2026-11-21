"""Suda's own pieces for the viewer, taken from suda.html: its style sheet, its icons and its pure (DOM-free) code.
The viewer draws a document the way Suda draws a message, so it uses these as they are, never a re-written copy.
`threads install` writes them into the installed viewer; tests write them into the repository's mdv/static (they
are not committed: they come from suda.html, so they never drift).

The installation's language goes in beside them (`localize`): l10n.json, which mdv/l10n.py reads. (This file is
loaded on its own by threads.py, so it imports nothing from the package.)"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

NAMES = ('suda.css', 'suda-pure.js', 'icons.svg.html')
L10N_NAME = 'l10n.json'
# suda.html's pure section starts in English; in the viewer it takes the language l10n.js names (mdv/l10n.py)
PURE_LANG = "var LANG='en',L10N={};"
VIEWER_LANG = ("var LANG=typeof MDV_LANG==='string'?MDV_LANG:'en',"
               "L10N=typeof MDV_L10N==='object'&&MDV_L10N?MDV_L10N:{};")


def pieces(page: str) -> dict:
    """The three pieces of a suda.html, as text. Raises ValueError when one is missing."""
    try:
        style = page.split('<style>', 1)[1].split('</style>', 1)[0]
        pure = page.split('// <pure>', 1)[1].split('// </pure>', 1)[0]
        at = page.index('<svg width="0" height="0" style="position:absolute" aria-hidden="true">')
        sprite = page[at:page.index('</svg>', at) + len('</svg>')]
    except (IndexError, ValueError) as e:
        raise ValueError('suda.html has not got the expected style, pure section or icon sprite') from e
    return {'suda.css': style, 'suda-pure.js': pure.replace(PURE_LANG, VIEWER_LANG, 1), 'icons.svg.html': sprite}


def write(static: Path, suda_html: Path) -> None:
    """Write the pieces of `suda_html` into `static`."""
    head = 'From suda.html, written by threads install. Do not edit here.'
    for name, text in pieces(suda_html.read_text(encoding='utf-8')).items():
        note = ('<!-- %s -->\n' if name.endswith('.html') else '/* %s */\n') % head
        (static / name).write_text(note + text.strip('\n') + '\n', encoding='utf-8')


def _table(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(raw, dict) else {}


def table(locales: Path, lang: str, texts: str, named: Path = None) -> dict:
    """The viewer's translations into `lang`, {English: translation}: Suda's own (locales/<lang>.json, or the
    installation's own table, config.json "locale_file", as `named`) for the words the viewer's files say (`texts`:
    its page and scripts, Suda's pure code among them), and the viewer's own (locales/mdv/<lang>.json). The
    installation's own table has the last word. English needs none."""
    if lang == 'en':
        return {}
    base = _table(named) if named else _table(locales / f'{lang}.json')
    out = {k: v for k, v in base.items() if not k.startswith('_') and (k in texts or k.replace("'", "\\'") in texts)}
    out.update({k: v for k, v in _table(locales / 'mdv' / f'{lang}.json').items() if not k.startswith('_')})
    if named:
        out.update({k: v for k, v in base.items() if not k.startswith('_')})
    return out


def localize(viewer: Path, lang: str, locales: Path, named: Path = None) -> None:
    """Write the installation's language into an installed viewer (`viewer`/l10n.json; after `write`, whose
    pieces it reads for the words they say). English (the code's own words) writes none. `named`: the
    installation's own table (config.json "locale_file"), as the board page takes it."""
    target = viewer / L10N_NAME
    if not re.fullmatch(r'[a-z]{2}(-[A-Z]{2})?', lang or '') or lang == 'en':
        if target.exists():
            target.unlink()
        return
    static = viewer / 'static'
    texts = ''.join(p.read_text(encoding='utf-8', errors='replace') for p in sorted(static.glob('*.js')) + [static / 'index.html'] if p.is_file())
    direction = 'rtl' if _table(named or locales / f'{lang}.json').get('_dir') == 'rtl' else 'ltr'
    body = json.dumps({'lang': lang, 'dir': direction, 'table': table(locales, lang, texts, named)}, ensure_ascii=False, sort_keys=True)
    tmp = target.with_name(target.name + '.%d' % os.getpid())
    tmp.write_text(body + '\n', encoding='utf-8')
    os.replace(tmp, target)
