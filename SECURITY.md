# Security

Suda is a personal tool: one owner, a few agents, one machine. Its security model is simple, and these are its rules.

## Where it listens

- The board server binds **127.0.0.1 only** (or a Unix socket). Never `0.0.0.0`, `*` or a LAN address.
- To reach Suda from a phone, put a gateway in front of it (for example Caddy over a private network such as a
  tailnet) that checks the `Host` header (against DNS rebinding) and the `Origin` of every write (against CSRF).
  The gateway is the only thing that listens beyond loopback.
- Notifications, the microphone and the clipboard need a secure page. Set the gateway's https address with
  `THREADS_SECURE_HOME` or `secure_home` in `config.json` (see below); the page then offers it.

## What the page can do

- The page never runs anything. It writes one request (`POST /api/state`), and the `threads` CLI decides what the
  request may change, under a lock, with its own checks.
- A **▶ run block** is only shown for a message from the tower, and only for lines of the form `! <command>`
  (printable ASCII, at most 10 lines). When the owner presses it, the server checks that the tower really wrote
  that exact text (a SHA-256 of the block) and hands it to the tower as a pending request. The tower runs it, or not.
- Rich content an agent sends (an HTML page, a diagram) is drawn in a sandboxed frame with no network and no
  access to the page, its storage or the board's API.

## Where data lives

- The board folder (served): the summary and the conversations derived from the board, message pictures
  (`uploads/`) and long texts (`snippets/`). Anyone who can reach the board server can read them, so keep it behind
  the gateway. The board itself is a SQLite store in the same folder (`suda.db`, with its journal and backups):
  `server.py` never serves it.
- The private folder (never served): `~/.config/threads/<slug>/` (or `THREADS_CONFIG_DIR`). It holds the push
  keys and subscriptions, `config.json` (this installation's address, display name and commands), backups taken
  before a state migration, and the parts of a big upload while they wait to be joined.
- A request's body is wiped from the served folder as soon as it is read when it carries a picture, a recording,
  a long text or a push subscription.

## Outside commands

Anything that reaches a person or a paid service (mail to the tower, a phone alert, transcription, `gh`) runs
only on the real board and only when configured: an environment variable, or `commands` in `config.json`. A test
board or a copy reaches nobody.

## Reporting a problem

Please use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability").
Do not open a public issue for a security problem.
