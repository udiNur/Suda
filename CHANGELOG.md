# Changelog

All notable changes to Suda are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The site, [getsuda.dev](https://getsuda.dev/): one static English page, nothing loaded from another server.
- The README in Japanese, Korean, Brazilian Portuguese and Spanish, beside Hebrew and Simplified Chinese.
- The board in SQLite (`suda.db`): a save writes only the threads that changed, every change is numbered and kept
  30 days, and `threads export-state` / `import-state` move a whole board in and out as JSON.
- Saved messages: ☆ on any message keeps it, and one list holds them from every thread.
- A very long message folds, with a button that opens it; the length it folds from is a setting.
- Links between notes in the MD Viewer, with `#heading` targets, missing notes dashed, and Back.
- `/done` always ends the topic: an open question is closed unanswered and open tasks stay; agents end one over
  open tasks when he asked, with `--on-his-word mN`.
- A voice message keeps its length, in Suda's own player.

## [0.1.0] - 2026-11-20

First public release.

### Added

- One thread per topic, from the first request to the finished work, however many agents touch it (or none).
- Every thread says whose turn it is: On you, Working or Done, with a one-line note written for someone who will
  not open the thread. Only *On you* notifies, with mute, quiet hours and snooze.
- Tasks with an owner and a status stay with the topic; the CLI refuses to mark a thread done while tasks are open.
- Questions with numbered answer buttons and the agent's recommendation, up to five open per thread, with four
  seconds to undo a tap; forms with grouped checkboxes, notes and picture tiles.
- Agents answer with more than text: Mermaid diagrams, diffs, charts, interactive pages and what-if cards in a
  sandboxed frame with no network, and live status cards that update in place.
- Run blocks: approve an exact command with ▶; the server checks it against the text the tower wrote, and only
  the tower runs it. No command runs in the browser.
- Replies by voice (transcript and recording), pictures, quotes of the exact words, and side threads split off with
  a link back; each message shows received, picked up and done.
- The ⌘K palette, slash commands, bulk actions on many threads, spaces, urgent threads first, merge, reactions,
  light and dark themes and keyboard shortcuts.
- Phone first and desktop: one pane at a time on a phone, the list beside the conversation on wider screens.
- The `threads` CLI and [SKILL.md](suda/SKILL.md) for agents: any models, any orchestration. Python standard library
  only, one HTML page, a server on 127.0.0.1 only, translations in `suda/locales/` (Hebrew ships).

[Unreleased]: https://github.com/udiNur/Suda/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/udiNur/Suda/releases/tag/v0.1.0
