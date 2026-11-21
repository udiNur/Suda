"""The model call in a process of its own: `uv run --with anthropic python -m mdv.worker`.

Reads one request on stdin ({system, messages, max_tokens}) and writes the reply as JSON lines on stdout:
{"t": piece} as it comes, then {"end": true}, or {"error": "..."} (never with the key in it). The key is read
here, the way MDS reads it; the process that started the worker never sees it.
"""
import json
import sys

from . import model


def main() -> int:
    try:
        req = json.load(sys.stdin)
        for piece in model.stream_here(req['system'], req['messages'], int(req.get('max_tokens') or model.MAX_TOKENS)):
            sys.stdout.write(json.dumps({'t': piece}, ensure_ascii=False) + '\n')
            sys.stdout.flush()
        sys.stdout.write('{"end": true}\n')
    except Exception as e:  # noqa: BLE001 - an error is an answer
        text = model.clean_error(e)
        key = model.load_key()
        if key:
            text = text.replace(key, '[key]')
        sys.stdout.write(json.dumps({'error': text}) + '\n')
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
