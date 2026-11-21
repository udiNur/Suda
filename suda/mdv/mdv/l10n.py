"""The viewer's language: the installation's, as `threads install` wrote it beside the viewer (l10n.json, made by
sync.localize from Suda's locales/); without it, English, the language the code says everything in. MDV_L10N
names another such file (the tests).

The page gets it as static/l10n.js (`MDV_LANG`, `MDV_L10N`), read before Suda's pure code, whose tr() then speaks
it; the server's own words to the model (the summary's instructions) go through tr() here."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent       # the viewer's folder (mdv/, or the installed copy)
ENGLISH = {'lang': 'en', 'dir': 'ltr', 'table': {}}


def settings() -> dict:
    """{lang, dir, table} of this installation (read on each call: a new install needs no restart)."""
    where = Path(os.environ['MDV_L10N']) if os.environ.get('MDV_L10N') else HERE / 'l10n.json'
    try:
        raw = json.loads(where.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ENGLISH
    if not isinstance(raw, dict) or not isinstance(raw.get('lang'), str) or not re.fullmatch(r'[a-z]{2}(-[A-Z]{2})?', raw['lang']):
        return ENGLISH
    table = raw.get('table') if isinstance(raw.get('table'), dict) else {}
    return {'lang': raw['lang'], 'dir': 'rtl' if raw.get('dir') == 'rtl' else 'ltr',
            'table': {k: v for k, v in table.items() if isinstance(k, str) and isinstance(v, str)}}


def tr(text: str, **values) -> str:
    """`text` (English, as the code says it) in this installation's language, with {name} filled from `values`."""
    out = settings()['table'].get(text, text)
    return out.format(**values) if values else out


def script() -> bytes:
    """static/l10n.js: the language and the table, for the page."""
    s = settings()
    esc = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).replace('<', '\\u003c')
    return ('var MDV_LANG=%s,MDV_DIR=%s,MDV_L10N=%s;\n' % (esc(s['lang']), esc(s['dir']), esc(s['table']))).encode('utf-8')


def html_tag() -> str:
    s = settings()
    return '<html lang="%s" dir="%s">' % (s['lang'], s['dir'])
