# The MD Viewer (part of Suda)

One Markdown file read in Suda's style: `/mdv/?path=<absolute or ~/ path to a .md in the MDS roots>`, on the board
server's own address (suda-fixes m149: inside Suda, no service of its own).

- `mdv_web.py`: what the board server imports (`answer_server.py`: `THREADS_MDV_DIR`, else
  `~/.local/share/threads/mdv`). `threads install` copies this folder there whole, and writes Suda's own style sheet,
  icons and pure code (`suda.css`, `icons.svg.html`, `suda-pure.js`) into `static/` from `suda.html`.
- `mdv/core.py`: which files may open (MDS roots, real paths, no symlink out, no hidden folder), the blocks (MDS's
  split), how a saved translation lines up, the translator (only the blocks that changed are sent; code is copied).
  Files beside a note are MDS's: `foo.en.md`, `.foo.en.trans.json`, `.foo.summary.json`.
- `mdv/model.py`, `mdv/worker.py`: Claude through the official SDK, with MDS's key. The board server's Python has no
  SDK, so the call runs in `uv run --with anthropic python -m mdv.worker`; the board process never holds the key.
- `mdv/server.py`, `mdv/web.py`: the requests (`/mdv/`, `/mdv/api/doc|events|translate|summary`). `web.handle()` runs
  one on the board server's connection; an exception there is a 503 on `/mdv/` only.
- `static/`: the page (`index.html`, `app.js`, `mdv-pure.js`, `app.css`) and Mermaid.
- `mdv/l10n.py`: the installation's language. The code says everything in English, through Suda's `tr()`;
  `threads install` writes `l10n.json` beside the viewer (`sync.localize`: Suda's `locales/<lang>.json` for the words
  the viewer shares with Suda, `locales/mdv/<lang>.json` for its own), the page reads it as `static/l10n.js`, and the
  summary's instructions to the model go out in that language. Without it the viewer is English, left to right.

Tests: `tests/test_mdv_*.py`, `tests/adversarial/test_adv_mdv_*.py` (the stand-in model: `MDV_FAKE_MODEL=1`, no network, no key). The board
server's side: `test_mdv_routes.py` in the board repository.
