# Contributing

Thanks for looking. Suda is small and opinionated; a few rules keep it that way.

- **Where things are.** The app is in `suda/` (the CLI `threads.py`, the page `suda.html`, the server `server.py`,
  [SKILL.md](suda/SKILL.md), the translations), the tests in `tests/` (hostile ones in `tests/adversarial/`).
- **Tests first.** A change starts with a test that fails on the old code: `tests/test_threads.py` for the CLI and
  the server side, `tests/test_slack.py` for the page's pure functions (run under node), `tests/test_e2e*.py` for the
  page in a headless browser (agent-browser) against the real board server on loopback.
- **Run the suites** before a pull request, every test file in parallel (failures are run again alone):
  ```sh
  python3 tests/run_all.py --env SUDA_E2E_SERVER=own
  ```
  One file on its own: `python3 tests/test_slack.py`.
- **No new dependencies.** The pages are single HTML files with no build step and no CDN; the CLI is one Python
  file using the standard library.
- **Bind to 127.0.0.1 only**, and read [SECURITY.md](SECURITY.md) before touching what the page may ask the server.
- **English in the code, translations in `suda/locales/`.** Everything a person reads is written in English through
  `tr()` (in `threads.py` and in the pages), and the interface is left to right. A translation is a table in
  `suda/locales/`, keyed by the English text: `suda/locales/<lang>.json` for the pages, `suda/locales/<lang>.cli.json` for the
  CLI and `suda/locales/mdv/<lang>.json` for the MD Viewer's own words (Hebrew, right to left, is the one that ships:
  `suda/locales/he.json`, `suda/locales/he.cli.json`, `suda/locales/mdv/he.json`). A new string adds
  its line to every table; `test_english.py` fails on a string of another language in the code.
- **Plain writing.** No em dashes or en dashes in code, comments, docs or commit messages.
