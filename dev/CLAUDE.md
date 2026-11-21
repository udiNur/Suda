# Working on Suda

- **Every change to what Suda can do updates SKILL.md in the same change** (standing rule from the owner): a new
  capability, or a changed one, gets its entry in SKILL.md saying what it does and how agents use it. A change that
  agents cannot learn about from SKILL.md is not finished.
- Tests first: a test that fails on the old code, then the change. Before publishing, a hostile review that tries
  to break it; every hole it finds becomes a test.
- What a person reads goes through `tr()` (threads.py and the pages), in English; its translation goes into
  `suda/locales/` (Hebrew: `suda/locales/he.json` for the pages, `suda/locales/he.cli.json` for the CLI). `tests/test_english.py` fails on
  Hebrew in the code.
- Services bind to 127.0.0.1 only. No em dashes or en dashes in code, comments, docs or commit messages.
- Where things are: the app in `suda/` (threads.py, the pages, SKILL.md, icons/, vendor/, mdv/; `threads install`
  copies from the folder threads.py is in), the tests in `tests/` and the hostile reviews' in `tests/adversarial/`
  (run one as `python3 tests/test_x.py` or `python3 tests/adversarial/test_adv_x.py`, or `python3 -m unittest test_x`
  in `tests/`; `tests/_paths.py` names the folders), these notes in `dev/`.
