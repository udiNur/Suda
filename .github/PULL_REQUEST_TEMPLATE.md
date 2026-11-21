## What and why

<!-- What changes, and the problem it solves. Link the issue if there is one. -->

## Checklist

See [CONTRIBUTING.md](https://github.com/udiNur/Suda/blob/main/CONTRIBUTING.md).

- [ ] A test that fails on the old code comes first, then the change.
- [ ] The suites pass: `python3 tests/run_all.py --env SUDA_E2E_SERVER=own` (every test file, in parallel).
- [ ] If what Suda can do changed, SKILL.md says so in the same change.
- [ ] No new dependencies: standard library Python, single HTML pages, no build step, no CDN.
- [ ] Everything a person reads goes through `tr()` in English, with its line in every table in `suda/locales/`.
- [ ] No em dashes or en dashes in code, comments, docs or the commit message.
- [ ] Services still bind to 127.0.0.1 only.
