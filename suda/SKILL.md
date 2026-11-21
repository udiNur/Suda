---
name: threads
description: Manage threads (Suda), reply in a thread, keep a thread's tasks current, set whose turn a thread is on, ask the owner a question with answer buttons or checkboxes, draw diagrams in a thread, resolve or archive a thread, or handle "[threads] reply in" tower notifications.
---

# Threads (Suda)

Persistent topic chats between the owner, the tower and agents. He reads them on
his phone. `threads url [<id>]` prints the page's address on this installation
(or one thread on it, `…/suda.html#<id>`).

## Who is who

- **The owner** (id `owner`): the human, the one person the threads are for. A thread
  `on-owner` is his turn; a task with owner `owner` is his; `--from owner` writes as him.
  An installation may also accept its own names for him (for example the id it used
  before) through `owner_aliases` in its private `config.json`: the CLI and the page
  take them as input and store `owner`.
- **The tower** (id `tower`): the one orchestrator agent. It picks up his replies
  (`threads pending`), relays them to the worker agents, posts ▶ run blocks, and
  runs the commands he approved with ▶.
- **Agents** (id `fork`): the workers. Each owns its topics and tasks, posts
  `--from fork`, and never writes as the owner.

## The rules (every agent, every time)

1. **Tasks are the truth.** If you own work in a thread, it is a task there.
   - Work starts or he asks for something → `threads task add <id> "<text>" --owner <you> [--from-msg mN]`.
   - Anything changes → `threads task set <id> <n> working|building|blocked|on-owner|done --note "<one line>"`.
   - He says a task is described wrong → `threads task set <id> <n> --text "<corrected text>"` (it keeps its number).
   - Before you post, run `threads tasks <id>` and fix every status that is stale.
   - Never set a thread `done` while it has open tasks (todo/working/building/blocked/on-owner).
     The CLI refuses it (`state done`, `say --state done`, `resolve`, `close`) and lists them; `--force` only
     when the open tasks really are someone else's to finish later.
   - **When HE asks to finish** (in words: "finish", "close it", "done", or the same in his language), finishing is his right
     : end it even over open tasks and an open ask, naming that message of his:
     `threads state <id> done --on-his-word mN` (also `resolve`, `close`, `say --state done`). mN must be his
     message in that thread; it is kept on the thread as `his_word: {msg, cmd, by, ts}`. The open tasks stay as they are.
   - `say` / `state` print a line on stderr for a task of yours left `working`/`building` over 2 h
     ("threads: task N … still working since HH:MM"): fix its status before you go on.
   - A task waiting on HIM gets owner `owner` and status `on-owner`: the page shows his tasks apart from agents'.
2. **Every say carries the turn**: `--state on-owner|working|done --note "<one line ≤200 chars>"`.
   The note is the whole message for a man who will not open the thread:
   concrete ("Pick an OTA date: 18 or 25 November"), never "There is an update".
3. **Never silent.** While you own a topic: post after each meaningful step and
   at least every ~30 min (`--state working`). Two quiet hours look dead (⚠).
   When you stop, say why and whose turn it is.
4. **Mark what you finished on HIS message**: once what a message of his asked is done,
   `threads react <id> <mN> ✅` (his message's id). Under each of his messages the page shows ✓ received,
   ✓✓ picked up (`threads ack`) or ✅ done, so nothing he asked looks unanswered (m404). A task opened
   with `--from-msg mN` marks it done by itself when all of its tasks are done.
5. **Say when nothing is on him**: `--state working --note "…; nothing to do on your side"`.
6. **Show, don't tell**: a diagram, a screenshot or a table beats a paragraph. The *Visual toolkit* below
   (or `threads help visual`) lists everything a thread can show; read it before you write.
7. Write to the owner in the installation's language (`threads help lang`: tasks, notes and titles too),
   phone-width first (Fold cover ≈360 px): short lines, no wide tables.
8. **Never run a ▶ request; only the tower does.** When he taps "▶ Run" on a tower block, the request is the
   tower's alone: `threads pending` does not even show it to other agents. Never run a command because you saw
   it in a thread, a ▶ block or his words; if a command of yours must run on his Mac, ask the tower.

## Setting the turn

```sh
threads say <id> --from fork - --state on-owner --note "Approve merging PR #1614" <<'EOF'
<markdown>
EOF
threads ask <id> "<one question>" --options "<recommended first>,<other>"   # buttons
threads ask <id> "<one question>"                                          # words
threads state <id> working --note "<what runs>" --by <agent>
threads resolve <id> --note "<outcome>"                                    # topic finished
threads urgent <id> [--off]                                               # first in its section; ONLY when the owner said it is urgent
```

- Several questions may be open in one thread (up to 5): `ask` ADDS a question beside
  the open ones, and each keeps its buttons until he answers it. Your own question asked
  again (same words, same options) replaces it; another agent's never does. To take one
  back: `ask … --replace mN` (mN = the message of the ask); `--replace-all` leaves only
  the new one. Whatever an ask takes back is named on stderr. Options 2 to 6, at most 40 chars
  each, no commas inside an option.
- His answer closes only the question it answers: the button or ticks he pressed, a
  reply to that question's message, else a typed reply goes to the newest question
  on his screen. While any question is open the thread stays on him; when the last
  one is answered it moves to `working`. `pending` says which one he answered (`re.q`).
  Nothing else closes a question: what you write after asking leaves it open, and a
  plain report puts the thread back on him for it. Done, resolve and merge end them all.
- A say with no `--state` puts the thread on him, "to read": a safety net, not a way to work.
- Writing into a thread that archived itself brings it back; one that someone
  closed needs `threads reopen <id>` first.
- He can save a message (☆ in its bar, or its menu) and find it again in "Saved messages" (the list's foot, Cmd+K), in any
  thread, open or closed. `threads saved [--json]` lists what he saved (thread, message, sender, the start of its
  words), the last saved first: when he asks for "the list I saved", look there. A message he will want to keep
  (a list of materials, links, a decision) is worth writing whole in one message.
- A very long message is folded on his screen: from 3000 characters (his setting, per device: 1500, 3000, 6000 or
  never) he sees its first part and a button that opens it. Put what he must know or decide in the first lines,
  and send what he only might read (logs, full reports) as `--snippet` instead.
- Steps in Hebrew are joined with `←` (`github.com/x ← Settings ← Pages ← Save`): a line with a `←` and any Hebrew
  word reads right to left, its English labels in the order written, even when the line opens in English; a
  bracket around such a chain closes on its own side. A line with no Hebrew word stays English, so an English
  paragraph or quote in a Hebrew message keeps its order.

<!-- visual:start -->
## Visual toolkit: everything a thread can show

Read this before you write to the owner. He reads on a phone (360 px wide): pick the
form that lets him see the answer without reading a paragraph. `threads help visual`
prints this section.

| # | What | How | Use it for |
|---|------|-----|------------|
| 1 | Text | markdown: `#`/`##`/`###`, `**bold**`, lists (3 levels), `>` quote, `---` | one idea per short paragraph |
| 2 | Table | markdown pipes, first row = headings | comparisons, costs; up to ~6 columns |
| 3 | Code | a fence with a language (`sh`, `py`, `json`, `diff` …) | anything he may copy; exact copy button |
| 4 | Runnable command | TOWER only: a fence whose every line starts with `! ` | a Mac command he approves with "▶ Run" |
| 5 | Diagram | a fence that is exactly ```` ```mermaid ```` | flows, sequences, states, plans |
| 6 | Picture | `--image FILE --caption "…"` (up to 4) | screenshots, before/after |
| 7 | Live page | `--html FILE` (≤500 KB, self-contained) | interactive mocks, charts, wide layouts |
| 8 | Long text | `--snippet FILE [--snippet-name N]` | logs, transcripts (never paste 300 lines) |
| 9 | Buttons | `threads ask … --options "a,b"` (2 to 6) | one choice, one tap |
| 10 | Ticks | `threads ask … --multi` / `--groups-file q.json` | several choices, in groups |
| 11 | Picture options | `--option-image 'label=FILE'` with 9 or 10 | choosing between things he must SEE |
| 12 | Tasks | `threads task add/set` | what is open, who does it; his own apart |
| 13 | Buttons in a message | a fence named `actions` | 2 to 3 next steps that are NOT a blocking question |
| 14 | Link chips | paste a bare address; a .md file's full path in `code` | PRs, commits, files, issues, boards, threads; a .md opens in the MD Viewer |
| 15 | Live card | a ```` ```status ```` block in a `say --live` message, then `threads update` | a status that moves (CI, a deploy, an install) |
| 16 | Chart | a ```` ```chart ```` block (JSON) | numbers over time or across categories |
| 17 | Widget | a ```` ```widget ```` block (sliders + formulas) | "what if" numbers he can play with |
| 18 | Carousel | a ```` ```carousel ```` block over the message's pictures | a walk through several screens |
| 19 | Drawing | a ```` ```svg ```` block | a sketch markdown and mermaid cannot give |
| 20 | Diff | a ```` ```diff ```` block (or a `git diff` pasted as it is) | what a change does to the code: a PR, a commit, a fix |
| 21 | Video | `--video FILE [--caption "…"]` (mp4/webm, up to 2, ≤100 MB) | a screen recording, a flow that moves, a demo |

How each one looks in Suda, and its limits:

1. **Text.** Three heading sizes, a tinted block for a quote, a rule for `---`.
2. **Table.** A card that scrolls sideways with a fixed heading row and striped
   rows; buttons: copy for a sheet, CSV, full screen. Cells wrap at ~34 characters;
   keep numbers in their own column.
3. **Code.** A coloured card with an exact copy button and a wrap switch. A ```` ```diff ```` block is a diff
   viewer (20 below). Inline
   code for a short command inside a sentence. A command for him starts with `! `
   (Mac) or `$ ` (phone), one per line.
4. **Runnable command.** Only in a message `--from tower`: 1 to 10 lines, each
   `! <command>`, printable ASCII only (no other letters, tabs or comments), ≤2000 chars.
   He taps "▶ Run", confirms the exact text, and the tower gets `run.command` in
   `threads pending --as tower` (or with THREADS_ROLE=tower; any other caller never sees a ▶ request).
   Nothing runs in the page or the server.
   **Rule (the owner, 18.11): every command he should run is
   given as a ▶ block, unless it cannot run that way** (needs his own terminal
   input like `/login` or a password, or a tap on the phone). Only the tower can
   post ▶ blocks, so an agent never posts a bare command for him: it sends the
   exact command to the tower (tuios mail) and the tower posts it as `! …`.
   **Never as inline code** (the owner, 18.11, tower m384): a command he may run that
   cannot be a ▶ block goes in a fenced code block on its own lines, so the copy
   button copies exactly that command. Inline code is only for names, not for
   anything he should run or paste.
   Every line of a code block reads left to right (its indentation, its scrolling, a file tree stay as written),
   and a comment whose words START in Hebrew is an island that reads right to left: alone on its line it takes its
   `#` (or `//`) to its right; after code the `#` stays by the code, and a closing `*/` stays after the words. A
   comment that starts in English (one Hebrew word in it, a JSDoc `@param` line) stays as written, and so does a
   `#` inside a word in sh (`page#top`). A string in Hebrew is drawn between its own quotes, so two of them keep
   their order. This needs the block's language (```py, ```sh, ```js ...). Suda and the MD viewer draw code with the
   same function (codePieces in Suda's pure section).
5. **Diagram.** Drawn at its own size up to 360 px tall; a wide one scrolls
   sideways; full-screen and "code" buttons; follows dark mode. `flowchart RL`
   reads right to left (for a right-to-left language); node labels of 2 to 4 words; ≤ ~12 nodes.
   `sequenceDiagram`, `stateDiagram-v2`, `classDiagram`, `erDiagram`, `gantt`, `pie`
   work too. A block that fails to draw shows its code and the reason.
   - **The diagram library is kept on his device** (suda-fixes 30) on the https address (the plain-http one has no
     store for it, and reads it per page): the first diagram reads it (1.66 MB on the wire), later ones and later
     openings do not; on a slow line the page waits as long as bytes still arrive (it gives up after 20 s with
     nothing new). So diagrams are cheap for him after the first; do not avoid them on a weak link. A new mermaid
     in `vendor/` needs `MERMAID_V` and `MERMAID_SHA` in suda.html to match vendor/README (a test checks both):
     a reading that is not that file is never kept.
   - The page itself is kept too: an opening, and the page's check for a newer build every 30 s, ask the server
     with If-Modified-Since and get a 304 without a body until `threads install` writes a new suda.html.
6. **Picture.** Rounded cards in a grid, the caption under each, tap for full
   size. jpg/png/gif/webp, ≤2 MB each; `--caption` goes with the `--image` in the
   same position. ALWAYS attach a screenshot when you changed something he will see.
   - **He may see a placeholder, not the picture.** On a slow link, or when he chose "Always on a tap" in the
     settings (or Cmd+K), Suda does not load
     pictures, videos or video posters by itself: each shows its shape, its size (sides, length, bytes) and a
     "Tap to load" button; a bar over the conversation has "Load all in this thread". Diagrams and text load as always.
     So say in the text (or the `--caption`) what each picture shows and why it matters, keep pictures small
     (crop to the part that matters), and when the point can be a diagram, draw the diagram.
   - **What "a slow link" means** (suda-fixes 20): the page decides by itself from what it does anyway, with no
     request added to measure, except one: Save-Data or a 2G/3G link from the browser; its own reads of the board
     slow (over 3 s, or under 50 KB/s); high latency (3 of its last 6 small reads, such as the change files, over
     0.7 s: "high latency"; since an update comes on the line and needs no read, an update taken from the line
     asks for the summary's first 64 bytes when the newest such sample is older than 2 s, 10 s while the mode is
     on, one at a time, never waited for, never while idle or hidden, and cut like any read on a dropped link); the server's 10 s heartbeat coming late (2 of the last 6 over 1.5 s late); or his own
     uploads slow (under 50 KB/s, 0.4 Mbps, timed to the server's answer: "slow upload"). A good link with a
     hiccup does not turn it on; a measure older than 10 minutes (15 for uploads) no longer counts. It goes off
     only when every measure is calm again and a hold has passed since the last slow moment (ten minutes when
     latency or the heartbeat turned it on, a minute otherwise; doubling up to half an hour when the link keeps
     swinging), so it does not flap. The bar over the conversation and the settings say why.
   - **His pictures arrive smaller on a slow link**: at most 1280 px at JPEG 0.7 while the mode is on, 1024 px
     at 0.6 when his uploads are slow (1600 px at 0.82 otherwise), unless he chose, under "Pictures you send:"
     in the settings, "As on a good link" (in Cmd+K: "My pictures: as on a good link (up to 1600 pixels), also on a
     slow link"): then always as on a good link, never the file as it is. That choice is per device; unset, it follows
     his media choice ("Always load" means as on a good link). Pictures already in the tray stay as they were made.
     Do not ask him for a sharper screenshot because of the shrink; ask him to crop to the part that matters, or
     point him to that setting.
   - **His sends on a slow upload**: replies, pictures and voice go through one queue per thread, in his order,
     each with its own cid, so a retry never makes a second copy. A big one shows its progress under it
     ("Sending… 40% (120KB of 300KB)": what the browser has handed to the network; then "Handed to the
     network. Waiting for the server to confirm…", which on 0.2 Mbps can last seconds), one behind it says
     "Waiting to send: it goes after the previous message", and a send that still moves is never cut: it is sent again only
     when nothing moved for 20 s and its own time (a second per 8 KB) has passed.
     On 0.2 Mbps a picture can take ten seconds or more to reach you, and the reply he wrote after it
     arrives after it.
   - **His messages reach you in the order he sent them, always** (suda-fixes 54). A reply he writes while an
     answer he tapped is still inside its four seconds of undo waits for it ("Waiting for the answer you chose"), and goes
     alone if he takes the answer back. A message that failed (the server refused it, never answered it, or the
     page gave up) holds the later ones of its thread ("Waiting: the message before it was not sent ...") until he presses
     "Try again" or "Delete" on it. So a gap of minutes between two of his messages can mean he was deciding about
     a failed one; their order is still his. The same holds across two tabs of one browser: a tab takes in a
     message that failed or waits in another tab of that thread, shows it, and keeps his order behind it.
     (A ▶ run request goes on its own: it neither waits for his words nor holds them, and is not sent more than
     10 minutes after his press.)
     Outside the thread he sees it too (suda-fixes 55): the thread's row in the list (and on the phone's list)
     carries a red "Not sent" (on the wide screen its tooltip, and for a screen reader the row's label, say how
     many of his wait behind it), also in a folded section and for the tower; a thread of another space marks
     that space in the rail, the space button and the space menu; and the tab's title starts with ⚠️ until
     nothing of his there is failed.
   - Two to four pictures stand in a grid of 4:3 cells, each shown whole (scaled to fit, never cut): a QR code
     or a tall screenshot keeps its edges, with room around it.
   - **He first sees a small copy.** When ffmpeg is on the Mac, a picture longer than 720 px or over 96 KB gets a
     small copy beside it (`mN-K.thumb.jpg`, or `.thumb.png` when it can be seen through; the long side 720 px),
     kept only when it is at most 60% of the picture, in its shape. A moving gif, png or webp gets none. The conversation, a carousel, the option tiles and the pages
     of the gallery beside the one on the screen show the copy; his tap opens the picture itself, and on a slow
     link a press loads only the copy. Fine print he must read at once belongs in a crop or in the text, not in the
     corner of a big screenshot. You always get the picture itself (`images[].path`); the copy is never a reason
     to refuse a picture (no ffmpeg, or it fails: the picture is shown as before).
   - **Full quality, always one tap away (m198).** A copy in the conversation carries a "Full quality" button: one
     tap loads the picture itself in its place (on a slow link too, and at any later time), and it stays so while
     the page is open. The viewer always loads the picture itself, with the copy under it until it is there.
   - **His own picture may have been sent smaller.** On a slow link his page can re-encode a picture before it
     sends it; it then names the original's sides, kept on the image record as `shrunk: {w, h}` (also in the `pending` row, and `threads show` says "sent smaller"). The full one never
     reached the Mac: the viewer says "Sent smaller · the original W×H". If the detail matters (small text in a screenshot),
     ask him to send it again on a good link.
7. **Live page.** A card with your page inside a sandboxed frame with no network:
   inline CSS/JS only, images as `data:`, no CDN. The card is named after the
   page's `<title>` (or its first heading), is 120 to 560 px tall by its content,
   and opens full screen. It may honour `prefers-color-scheme`.
8. **Long text.** A collapsed card with the first lines; the reader shows it
   300,000 characters at a time ("show more"), with copy and download. Up to
   20 MB (`--snippet` and his uploads from the page; the page sends a big one in
   parts). `threads snippet <id> <mN>` prints one.
9. **Buttons.** Numbered 1 to 9 under the question and in the strip at the top; one
   press answers (4 s to take it back). Labels ≤40 chars, mutually exclusive.
   Options that carry marks (A/B/C, 1/2/3, or the letters of the owner's alphabet) stay in the order of the marks
   (the CLI refuses another order); mark the one you recommend with
   `--recommended "<label>"`, never by moving it. Unmarked options: recommended first.
10. **Ticks.** A form with checkboxes in titled groups, "recommended" marks and a
    free note. His answer reaches you grouped (`re.answer`) plus `re.note`.
11. **Picture options.** Each option is a tile with the picture over its label,
    also in the tick form. Give every option of the question a picture or none.
12. **Tasks.** A coloured progress bar under the title and a list; a task whose
    owner is `owner`, or whose state is `on-owner`, shows in his own list.

13. **Buttons in a message.** A fence named `actions`, one button per line, three
    kinds only: `reply: <words>` (he sends exactly those words as a reply to that
    message; 4 s to take it back), `open: <label> | <http(s) address or /path>`,
    `copy: <label> | <text>`. Up to 6 lines, label ≤40 chars, reply words ≤200. A
    real decision still belongs in `threads ask`: it puts the thread on him.
14. **Link chips.** A bare address of a GitHub PR / commit / file, a Linear
    issue, a board (`/x/board.html`) or a thread (`/threads/suda.html#id` or
    `#id/mN`) is shown as a short chip with its kind. ALWAYS write a pull request
    as its full address (`https://github.com/<org>/<repo>/pull/1614`), never
    just `#1614`; the same for a commit where it helps.
    A Markdown file you wrote for him: write its FULL path in inline code
    (`` `~/notes/todo/plan.md` `` or `` `/Users/you/...md` ``), or as a
    link's target (`[the plan](/Users/you/.../plan.md)`). It shows as a file chip
    and opens in the MD Viewer INSIDE Suda: a large panel over the thread (the whole
    screen on a phone, Back closes it), with full screen and "open in a new page" in
    its head (`/mdv/?path=...` is that page: Suda's style, Mermaid, tables,
    translation and summary saved beside the file). A full viewer address on this
    server (`https://suda.example.com/mdv/?path=...`) is the same file chip and panel.
    Pictures in the .md show: `![alt](docs/shot.png)` or a README's `<img src="..." width="120">`,
    by a path relative to the note (or `~/...`, or absolute), from the same MDS folders
    (png, jpg, gif, webp, avif, svg). A picture on the web is not loaded: it stays a link. Only files inside the MDS roots
    (`~/.config/mds/roots.json`, `~/Documents/mds`) open; no spaces in the path.
    Code in the viewer: every line left to right; a comment whose words START in Hebrew is an island that reads
    right to left (an English comment with a Hebrew word in it stays in order, a closing */ stays after the words);
    a Hebrew string keeps its place between its quotes; in sh a # inside a word (a URL's #top) is code. It needs
    the block's language. Find matches across a comment's marker and its words.
    Notes link to notes, a tap opens the other one: `[the line](01-positioning.md)`, or the file's name alone in
    inline code (`` `01-positioning.md` ``, relative to the note's folder; it is a link only when that note exists),
    or its full path; `[x](02-show-hn.md#rules-for-the-day)` scrolls to that heading. In the panel Back (and the
    panel's ←) returns to the note before; the first note's Back closes the panel. A link whose note does not open
    (missing, outside the MDS folders, hidden) is drawn dashed and does not open. So in a set of notes (a kit, a
    plan in parts) write an index note with each file's name in inline code.
    The viewer is part of Suda (`mdv/` in this repository): `threads install` puts it in
    `~/.local/share/threads/mdv` (or `THREADS_MDV_DIR`) and the board server serves it
    under `/mdv/` with the board's own guards; if it breaks, only `/mdv/` answers 503.
    Its translation is `foo.en.md` / `foo.he.md` beside the note, as MDS makes it.
    The viewer speaks the installation's language (`threads help lang`, written at `threads install`): its words
    come from `locales/mdv/<lang>.json`, and those it shares with Suda from `locales/<lang>.json`. Its summary is
    written in that language (a summary already saved beside a file is shown as it was made, until he asks for a
    new one); its translation still goes between Hebrew and English, by the note's own language.
15. **Live card.** `threads say <id> --from fork - --live …` makes a message you
    may change later; `threads update <id> <mN> --from fork -` replaces its text
    in place: no new message, nobody is alerted, the turn does not move (add
    `--state … --note …` when it should). Use it for ONE thing whose status
    moves, instead of a new message per step. Only a live message can be updated.

21. **Video.** `threads say <id> --from fork "…" --video demo.mp4 --caption "…"`. He gets the browser's own
    player inside the message: play, the timeline, the sound, full screen (the player's own button). It never
    plays by itself; one video plays at a time; it keeps the video's shape (a phone recording stands upright) and
    fits the phone (360 px) and the desktop; the caption is under it.
    - mp4 (H.264) or webm (VP8/VP9), read from the bytes, not the name. Up to 2 per message, ≤100 MB each (a
      bigger one is refused: `ffmpeg -i IN -vf scale=-2:720 -crf 30 OUT.mp4`). A QuickTime .mov is refused:
      `ffmpeg -i IN.mov -c copy OUT.mp4`. A file with sound only is refused, and so is one with a track of data
      (a GoPro's GPS, camm): `ffmpeg -i IN -map 0:v -map 0:a? -c copy -map_metadata -1 OUT.mp4` keeps picture and sound.
    - `--caption` RIGHT AFTER a `--video` is that video's; any other `--caption` goes to the pictures, in order.
      A video with no text: the message reads "Video".
    - Stored as `uploads/<thread>/mN-v1.mp4` (`.webm`). An mp4 is stored with its index first (it starts before
      the whole file arrives) and without its udta/meta/uuid boxes (place, device, XMP); a webm without its Tags,
      Attachments and the Title and date of its Info. What stays: the creation times inside an mp4's
      mvhd/tkhd and the names of the tracks. When ffmpeg is on the Mac the first frame is stored as the poster
      (`mN-v1.jpg`).
    - **A local path is not a video for him.** `/Users/…/out/demo.mp4` in your text stays text: the page never
      opens a file of the Mac. Attach it with `--video` (`say` warns when your text names a local video file you
      did not attach).
    - Keep it short and cut to the part that matters: he watches it on a phone, often on a slow link. The board
      server (the skill's answer_server.py and Suda's own server.py alike) answers a request for a part of it (one
      byte range), so the timeline jumps ahead and Safari, also on an iPhone, plays it.
    - On a slow link the video and its poster wait for his press (see Picture, above): the caption and the text
      are all he sees until then, so say there what the video shows.

### Rich blocks (Suda draws them; nothing you write runs in the page)

A fenced block with one of these languages becomes a card. The body is JSON (or SVG). Every card has a bar
("code" shows your source); a block that fails a check is shown as code with the reason in his language, so check it
before posting (the page's checks are in `richBlock()` in suda.html; in the repository's tests/ folder, `python3 -m unittest test_slack.RichBlockTests`).
Limits: one block ≤ 60,000 chars. Numbers are formatted for him (1,125,000); write them raw.

**```chart**: bars, lines or a donut from data.
````markdown
```chart
{"type":"bar","title":"Monthly cost","labels":["October","After Spot","November"],
 "series":[{"name":"on-demand","values":[4766,2100,95]},{"name":"Spot","values":[0,900,40]}],"prefix":"$"}
```
````
`type`: `bar` (default) | `line` | `pie` (one series, no negatives). `labels`: 1 to 60 strings. `series`: 1 to 8, each
`{name, values}` with one number per label (`name` optional → "Series N"). `prefix`/`suffix` (≤12 chars, e.g.
`"$"`, `" yrs"`), `decimals` 0 to 4, `stack:true` for stacked bars. He gets: a tip on tap/hover, the data as a table
(copy/CSV), PNG, full screen. Colours follow the theme; a legend appears for ≥2 series. Prefer ≤ 8 labels on
the phone; many labels are thinned.

**```widget**: sliders with formulas (an "interactive card"), e.g. a revenue simulator.
````markdown
```widget
{"title":"Revenue simulator","note":"An estimate for 30 days",
 "inputs":[{"id":"machines","label":"Machines","min":100,"max":5000,"step":100,"value":1000},
           {"id":"avg","label":"Average sale","min":0.5,"max":10,"step":0.5,"value":2.5,"prefix":"$","decimals":1}],
 "outputs":[{"label":"Monthly turnover","formula":"machines*15*avg*30","prefix":"$","decimals":0,"note":"Before fees"}]}
```
````
`inputs`: 1 to 8 sliders, `id` = `[A-Za-z_][A-Za-z0-9_]*` (unique), `label`, `min < max`, `step` (>0, default 1),
`value` (default min; snapped to the step), `prefix`/`suffix`/`decimals`. `outputs`: 1 to 6, each `label`,
`formula`, `prefix`/`suffix`/`decimals`, `note`. A formula is read by the page's own parser: numbers, the ids,
`+ - * / % ^`, parentheses, `min max abs round(x,d) floor ceil sqrt`. Nothing else (no dots, strings, `?:`).
He gets: live results while dragging (keyboard arrows move a slider), "Reset", "Copy" (values + results as text).

**```carousel**: slides he swipes (or arrows / ←→ keys): a title, a text, and one of the message's pictures.
````markdown
```carousel
{"slides":[{"title":"Install","text":"The APK installed and opened","image":1},{"title":"Summary","text":"All good"}]}
```
````
1 to 20 slides; `image` is the number (1 to 4) of a picture attached with `--image` in the same `say`; a picture a
carousel shows is not repeated below the message. Tap a picture → full screen.

**```svg**: your own drawing, shown as a picture on a white plate (dark theme too: use dark strokes).
````markdown
```svg
<svg viewBox="0 0 320 120" xmlns="http://www.w3.org/2000/svg">…</svg>
```
````
Must start with `<svg` and end with `</svg>`; refused with `<script`, `javascript:`, `on…=` handlers,
`<foreignObject>` or any `http(s)://` reference. Give it a `viewBox` (its size); it is scaled to the card, at most
1.5× its size; full screen at full size, "Download SVG". No fonts or pictures from the network.

**```status**: a live status card, updated in place.
````markdown
```status
{"title":"PR #1620: partial refund","state":"running",
 "lines":[{"label":"CI","value":"running, 3 min","state":"running"},{"label":"Review","value":"2 of 2","state":"ok"}],
 "progress":0.6,"note":"Updated here when CI finishes"}
```
````
`state` (and a line's `state`): `todo | waiting | running | ok | done | failed | blocked`; `lines` ≤ 12
(`label` ≤ 40, `value` ≤ 80); `progress` 0 to 1 (omit for none); `note` ≤ 200. Post it with
`threads say <id> --from fork - --live …` and change it with `threads update <id> <mN> --from fork - …` (the whole
text again; same limits as say): the card redraws in place with "updated … ago", no new message, no push. Only a
message created with `--live` may be updated. Use it instead of a new message every minute (CI, a build, an
install on the phone, a long run). The same `update` also refreshes a chart or a carousel in a live message.

**```diff** (or ```` ```patch ````): a diff viewer. The body is a unified diff as git or `diff -u` prints it
(`git diff`, `git show`, `git format-patch`), any number of files.
````markdown
```diff
diff --git a/src/pay.js b/src/pay.js
--- a/src/pay.js
+++ b/src/pay.js
@@ -10,3 +10,3 @@ function refund(order)
 const order = load(id);
-const total = price * 2;
+const total = price * 3;
```
````
Post the real output, not a retyped one: `{ echo '```diff'; git diff; echo '```'; } | threads say <id> --from fork - --state … --note …`.
He gets: a header per file (its name, New / Deleted / Renamed / Binary, +N −M) that folds and opens at a tap; each
hunk's `@@` line; old and new line numbers; red and green lines with the changed words marked inside them;
unchanged runs folded beyond 3 lines on each side of a change ("N unchanged lines · Show" opens them). Side by side
(old on the left, new on the right) when the card is at least 760 px wide (his Mac), unified on the phone (both Fold
screens); "Side by side" switches it. Always left to right, in light and dark. The bar: line wrapping (the same choice as
every code block), "Copy" (the raw diff exactly, ending with a newline, so `git apply` takes it), "Full screen".
Also drawn as a diff: a `git diff` pasted in a message with no fence (from its `diff --git` line, or `---`/`+++`
with a numbered `@@`, to where its hunks' numbers end), a fence with no language whose whole body is a diff, and a
`--snippet` named `*.diff`/`*.patch` (or whose text starts like one: his long paste becomes a snippet), through "Show
as a diff" beside "Show all". A ```diff block of bare `+`/`-` lines (no headers) is drawn without line numbers.
Limits: a message is ≤ 50,000 chars, so send only the files that matter (or a `--snippet FILE.diff`, read up to
1,000,000 chars). A card draws its first 300 lines (files in order; a file that does not fit starts folded) and
"Show more" adds 300 at a time; the full screen draws 3,000 at first, so a long diff never freezes his phone. Word marks
only between a deleted line and the added line paired with it, each ≤ 500 chars and with enough in common. Binary
files are named, not shown. Lines outside the hunks are not in a diff: for more context post `git diff -U10`.

What reaches YOU from him (`threads pending`): his text; `reply_to` (the message
he answers, in full, and `reply_to.quote`: the exact words he marked); `images`
(absolute path + caption each: open the files); `videos` (the same, for a video); `voice` (the transcript is `text`,
the recording is `voice.path`); `run` (tower only); `re` (the question he answered).
<!-- visual:end -->

## CLI (master)

```sh
threads new <id> "<title>" [--summary …] [--context …] [--note …] [--state …] [--by …] [--link "L=URL"]...
threads list [--open] [--json]          threads show <id> [--json]
threads say <id> --from tower|fork|owner <text|-> [--state … --note … --by …] [--force | --on-his-word mN]
            [--snippet FILE [--snippet-name N]] [--image FILE [--caption TEXT]]... [--video FILE [--caption TEXT]]...
            [--html FILE] [--live]
threads state <id> on-owner|working|done [--note …] [--by …] [--force | --on-his-word mN]
threads ask <id> "<q>" [--options "a,b"] [--multi] [--groups-file JSON] [--recommended LABEL]
            [--option-image 'LABEL=FILE']... [--from fork|tower] [--replace mN | --replace-all]
threads update <id> <mN> --from tower|fork <text|-> [--state … --note … --by …]     # a message made with say --live
threads help visual                     # everything a thread can show
threads task add <id> "<text>" [--owner <agent|owner>] [--from-msg mN] [--by <you>]
threads task set <id> <n> [todo|working|building|done|blocked|on-owner] [--text "<new words>"] [--note …] [--owner …]
#   --text corrects a task described wrong in place: same number, the old words kept in its history
#   (never archive and add again); the status may be left out
#   --by <you> names who did it in the task's history (default: its owner before the change when that is an
#   agent, else "agent"; never the owner or auto, those are the page's and the sweep's)
threads tasks <id> [--json]             # --json: each task with its `events` (its history, below)
threads rename <id> "<title>"           # id and slot stay
threads snooze <id> --until "16.11 09:00"|"+2h"|"tomorrow 09:00"   ;  threads unsnooze <id>
threads mute <id> [--off]               # no push and no phone alert for this thread
threads notify [--snap on|off] [--fallback-minutes N] [--idle-minutes N] [--quiet 22:00-07:00|off] [--url URL|off] [--test]
threads snippet <id> <mN>
threads resolve <id> [--note …] [--force | --on-his-word mN]  threads close <id> [--by <agent> --force | --on-his-word mN]  threads reopen <id>  threads rm <id> --yes  (demo only)
threads react <id> <mN> ✅|👍|❓ [--by <agent>] [--off]   # an agent's mark; ✅ on his message = what it asked is done
threads space add <id> "<name>" [--prefix sup-]... [--letter X] [--color #rrggbb]   # spaces: few (8 at most); the page's square at the top-left switches them
threads space set <id> [--name …] [--prefix …]...   threads space rm <id>   threads space list [--json]
threads move <id> --space <space|main>              # a thread's own choice of space (else: the first prefix its id starts with, else main)
threads run-status <id> <mN> <block> running|ok|fail [--note …]   # tower: what became of a ▶ request (block = run.block_index)
threads merge <src> --into <dst> [--by <agent>]   # src closes under "merged", ALL its tasks move to dst (open and done, numbered anew, each with its history), dst gets a "merged here" block; again = nothing new
threads set <id> [--title …] [--summary …] [--context …]    threads link <id> "<label>" <url-or-path> [--rm]
threads pending [--as tower]  threads ack <id> <mN>  threads sweep [--quiet]  threads policy …  threads install  threads ingest
```

IDs: lowercase letters/digits/hyphens, ≤48 chars. Limits: title 200, summary
300, note 200, context 20 000, message 50 000. `pending` rows carry `thread`,
`msg_id`, `text`, `ts`, `history`, `slot`, `state`, `note`, `summary`, `links`,
`re` (the question a reply answers; for checkboxes `re.answer` by group and
`re.note`), `reply_to` (the quoted message, in full; `reply_to.quote` = the exact
words of it he marked), `snippet.path`, and when present:
- `images`: `[{path, caption, name, bytes, w, h, shrunk?}]` (`shrunk: {w, h}`: his page sent it smaller, these are the original's sides): READ each picture file
  (absolute path); the caption is what he wrote under it.
- `videos`: `[{path, caption, name, bytes, type, w, h, seconds}]` (a video in a message of his, from the CLI).
- `voice`: `{path, seconds, state}`: he spoke the message; `text` is the
  transcript (Soniox). `state: failed` means there are no words: listen to the
  file or ask him. A recording still being transcribed is not in `pending` yet.
  A recording is stored with its duration (a webm from the page is remuxed once, losslessly, with ffmpeg
  when it is there), and the page draws its own player from `seconds`. Recordings stored before that:
  `threads voice-remux` lists them; `threads voice-remux --apply` mends them, each original kept as
  `<name>.orig` beside it (the board's state is not touched).
- `run`: `{msg_id, block_index, sha256, command}`: he tapped "▶ Run" (tower only, below), or typed `/run`.
- `command`: `{name, args}`: he typed a command for the agents in the reply box ("/" opens the list of commands).
  `text` is the line as he typed it (it may be the command's name in the installation's language); act on `name`,
  always in English: `status` (where the topic stands, in one short message), `explain` (explain `args`, or the last
  message, in plain words), `review` (review the work, or `args`), `run` (with `run`, as a ▶ request); later `prs`,
  `draft`, `install`, `split` (`args` = the new topic's title). `show` prints it as `[command: /<name> <args>]`. A
  command answers no open question. His page actions (`/done`, `/s` snooze, `/urgent`, `/close`, `/rename`, `/mute`,
  `/task`) change the thread directly and never reach `pending`. His `/done` ALWAYS works: the thread goes to
  `done` by `owner` with the note "You finished it", an open ask is closed unanswered (its message stays and gets
  `q_closed: {ts, by}`; the page writes "You closed it without an answer"), open tasks stay as they are (the toast
  names them), his own words still `pending` stay with you, and a message he had not seen yet is shown to him once
  in the toast (never put away in silence). The page's automatic "read it" (a plain report he read) still puts no
  ask away. A task he adds with `/task <text>` has `by: owner`
  and no owner yet: take it (`threads task set <id> <n> working --owner <you>`) or hand it on. `/task <n> = <text>`
  rewords task n (its old words go to its `history`).
- Task history (suda-fixes task 34): every task keeps `events`, oldest first:
  `{ts, kind, by, from?, to?, derived?}`, kind = `created` | `status` (from, to) | `text` (old and new words) |
  `owner` (from, to) | `moved` (`from` {thread, n} where it came from, `to` where it went, or `back`: opened
  again, it is no longer the one that went there) | `archived` |
  `unarchived` (by `auto` when the sweep archives it). Every writer records its event; the list keeps the first
  event and the newest 60. A task from before this shows what it kept its own times for, marked `derived: true`.
  `threads show <id>` prints each task with its events; `show --json` and `tasks --json` carry them. On the page
  each task says when its last thing happened, and its arrow opens this history. Give `--by <you>` when you
  change a task so the history says who.
- `title_pending: true`: he opened the topic from the page without a title;
  its title is his first words. Give it a short title, in the owner's language: `threads rename <id> "…"`.
- `merged_into`: the thread this one was merged into: answer him THERE (writing into a merged thread is refused).
- `split_from`: `{thread, msg, from, ts, text}`: he cut this topic out of that
  message of another thread; the text is the message he means.

## Slots, snooze and archive

- A thread keeps its slot until it closes; nothing an agent does reorders the page.
- `done` + idle 12 h → "closing soon"; 12 h more → archived. Resolved → archived after 2 h.
  Anything waiting on him or an agent, or an un-picked reply, never closes.
- A snoozed thread hides until its time, then returns to "on him" with a reminder.
  A launchd timer (or any scheduler) runs `threads sweep --quiet` every
  minute, so it wakes on time. An agent's message into a sleeping thread does not
  wake it: he chose the time.
- He can act on many threads at once in Suda's list (Cmd/Ctrl+click, Shift+click for a range, a long press then
  taps on the phone): mark read, snooze, merge into one of them, close. The page sends the single op per thread
  (`seen`/`done`, `snooze`, `merge`, `close`), so you see exactly what one action leaves, once per thread: closed
  by `owner`, asleep until the time, `merged_into` plus one "merged here" message per source in the target, a
  plain report read. Nothing marks it as a bulk action. Merge and close first ask him (naming each chosen thread
  with something unread or waiting for his answer) and send, per thread, the last message he was shown when asked:
  a message that lands after that makes the server refuse that thread, which stays open and chosen. Answer a
  merged one in its target.

## How he is told

- A thread that becomes `on-owner` (a say without `--state`, an `ask`, an explicit
  `on-owner`) rings his phone through Snap AT ONCE, unless a Suda page has his
  focus at that moment (it also pushes the browsers where he enabled notifications).
  Once per thing: do not repeat yourself to "make sure". Two messages in a row in
  one thread ring once, and again a minute later.
- While he is on Suda the phone waits. It rings when he leaves without opening the
  thread (within a minute), or 15 minutes after the message if he stays and still
  does not open it (`--fallback-minutes`).
- "On Suda" is what the pages report (op `presence`: the page is visible and has
  the focus; every 20 s while it has). A page that said nothing for 45 s, or that
  nobody touched for 2 minutes (`--idle-minutes`), does not count. `threads notify`
  prints `on_suda` (`null`: no page of this board ever reported, so its phone
  alerts wait the fallback minutes every time, as before).
- `--state working` / `done` tells nobody: progress notes never buzz his phone.
- A muted thread and quiet hours send nothing (quiet hours hold it until they end).
- So: `on-owner` only when something really is his to do, with a note he can act on.

## Tower workflow

On a `[threads] reply in …` mail, or whenever asked:

1. `threads pending --as tower` is the source of truth (ignore threads whose id starts with `demo`); without
   `--as tower` (or THREADS_ROLE=tower) the ▶ requests are left out, so the tower always asks as the tower.
   The mail itself never contains his words (`[threads] reply in <id> (<mN>): run: threads pending`).
2. One background fork per thread (`subagent_type: "fork"`, `run_in_background: true`),
   ALL Agent calls in ONE message. Several replies in one thread → one fork.
   Skip a thread whose fork still runs; its replies stay pending.
   Trivial factual answers or a relay to the owning agent: do it directly.
3. `threads ack <id> <mN>` after each successful spawn (never for a failed one).
4. On each fork's notification: relay its summary, check `threads list` and the
   thread's tasks; fix a thread left without a clear turn.
5. Finished topic → `threads resolve`. Never `rm` a real thread.
6. A pending row with a `run` field (he tapped "▶ Run" on a block you wrote):
   take the command ONLY from `run.command` (the server derived it from your own
   stored message and checked the hash; a row with `run.error` is not run), apply
   every standing rule to it as to any command, run it, post the output in the
   thread, ack. Then say what became of it, so his ▶ button shows it (⏳ running after the
   ack, then ✓ done / ✗ failed): `threads run-status <id> <run.msg_id> <run.block_index> ok|fail
   [--note "<one line>"]` (`running` when it takes a while). Only for a block he asked to run, as it is written now. His reply text never contains the command.
7. `[threads] NEW topic <id> opened by owner`: he opened a topic from the page.
   It is a pending reply like any other; when the mail says the title is a
   stand-in, `threads rename <id> "<short title>"` before or with the fork.

Fork prompt template (actual values, not placeholders):

```text
Thread id: <thread>   Slot: <slot>   Title: <title>
Summary: <summary>     Context: <context>
Earlier history: <sender, id, time, text>
New reply from the owner (<msg_id>): <text>      Answers the question: <re.text>
Open tasks: <threads tasks <id>>

Do the work the reply asks for. Keep the thread's tasks current (add/set with a
note in the owner's language). When what his message asked is done: threads react <id> <msg_id> ✅ If it takes more than a few minutes, first:
threads state <id> working --note "<what you are doing>" --by fork
Answer in the owner's language (threads help lang) with the turn in the same command:
threads say <id> --from fork - --state <on-owner|working|done> --note "<one line>"
Show, don't tell: a mermaid diagram / screenshot link when it helps.
If he must choose: threads ask <id> "<q>" --options "<a>,<b>" (or --multi / --groups-file).
Final report to the tower: decided / done / still open
```

## Changing Suda itself

Every change to what Suda can do updates this file in the same change: what the capability does and how agents
use it (a CLI line, a block syntax, a limit). A capability that is not described here does not exist for agents.

Alignment is measured, not eyeballed: `tests/test_e2e_symmetry.py` reads the page with getBoundingClientRect at the cover,
a 390 phone, the inner screen and the desktop, dark and light. What shares a line shares a vertical centre within
1 px, an icon's drawing is centred in its button, a chip is padded alike on both sides, and right to left what leads
is on the right. A key cap written beside words (Esc, the key of a notice, End on the pill) goes in a `with-key`
control: one flex line with its own gap, never a margin on the `kbd` (a key cap is left to right inside a right to
left line, so its margin lands on the outer side). A check mark is the drawn `i-tick` icon, never a font's ✓. A new
row, chip, dialog top or toast gets its measure in that file.

## Plumbing (rarely needed)

- The page posts through `/api/state` → `on-state.sh` → `threads ingest`; only
  replies send tuios mail `[threads] reply in <id> (<mN>)` to the tower. Pending
  replies live in `state.json`, so a lost mail loses nothing. Threads never use `answers.jsonl`.
- A clone without the html-interview-board skill serves the board with Suda's own `server.py` (127.0.0.1 only;
  the Host guard, the Origin guard on writes, nothing outside the board's folder). It does what the skill's server
  does for Suda: the numbered `/events` line (`id:`, `retry:`, the named `alive` heartbeat, resume from
  `Last-Event-ID` or `?since=`, the inline `delta` of at most 32 KB), one byte range (206, 416) and "changed since?"
  (304) on the board's files, and the MD Viewer under `/mdv/` (from `THREADS_MDV_DIR`, else beside the boards
  folder when `BOARDS_DIR` is set, else `~/.local/share/threads/mdv`; a 503 on `/mdv/` only when it is missing or
  breaks). Never the board's store (`suda.db`, its journal, backups and locks). Nothing changes in how you write.
  The server is only for the page: the CLI works without it. To keep it running, a launchd agent or a systemd user
  service that runs `python3 suda/server.py` (an example plist is in the README's Setup). Tests:
  `tests/test_server*.py`.
- State: the board's truth is SQLite, `~/Documents/mds/boards/threads/suda.db` (sqlite177, suda-connectivity
  task 16): every thread in a row of its own, and every change numbered and kept 30 days. A save writes only the
  threads that changed (0.035 s instead of a whole 5 MB rewrite), so it does not grow with the history. The summary
  (`summary.json`) carries the open threads and the ones closed in the last 7 days (`THREADS_HOT_DAYS`); older
  closed threads are listed in `closed.json` (the page's archive reads it) and each keeps its `full/<id>.json`
  (with its row), so they still open, and any command that names one (`show`, `say` into it) finds it.
  `state.json` is no longer written: `threads export-state [--to FILE]` writes the whole board as it was (a
  backup, or the way back: with `THREADS_STORE=file` threads.py runs on state.json as before), and
  `threads import-state` takes a state.json in (the store it replaces is kept as `suda.db.bak-<time>`). An empty
  store takes in the board's state.json by itself (the first run after the switch); otherwise a newer state.json
  is only noted in notify.log (an old threads.py from another checkout must never overwrite the board), unless
  `THREADS_AUTO_IMPORT=1` (tests, netlab, which write state.json as a fixture; `tests/run_all.py` sets it and
  `THREADS_EXPORT_STATE=1`, which writes state.json after every save). A damaged record is refused and left
  untouched. `THREADS_SLUG=<other>` runs a staging copy; `THREADS_NOTIFY=0` disables mail, pushes and phone
  alerts; `THREADS_NOW=<epoch>` pins the clock for tests.
- Every save that changes what the page shows gets a new number, `seq` (in `state.json`, `summary.json`, and
  as the text of `.pulse`): above every number before it (also the highest one ever given, kept beside the
  board's folder in `.<slug>.seq`) and never below the clock in milliseconds, so numbers jump, and a board put
  back from a backup never gives a number a page holds to other content. Beside the
  summary, `changes.json` holds the last changes (up to 200, at most 256 KB), each as the number it starts from
  (`from`), its own (`seq`) and what it did to the summary, and `changes/<from>.json` the changes from that number
  on (for the last 6 numbers, every change to the board's number, so a page a few behind needs one request); they are
  written before the summary and the pulse, under the state's lock, so a number never repeats, also with many
  agents writing at once. `summary.json` starts with `{"seq":N,"mark":"<mark of its content>"}`: a page reads
  those first bytes (a Range request) beside every catch-up, and whenever the server says its own number again,
  and reads the whole summary when they are not the summary it holds. So a save by a `threads.py` that does not
  number (an older copy in another worktree), which keeps the number and only touches the pulse, still reaches
  every page, and the next numbered save gives a new number. The header says "Up to date" only after a reading that
  vouched for the screen: never right after he comes back to the tab, after a failed reading, or over the device's
  own copy. A line silent for 15 s (the server speaks every 10 s) is opened again, one that cannot open is tried
  every 3 s, and when it is back every reading and reply still on its way from before goes again at once on a
  fresh connection (a reply by its cid: never stored twice; never cut twice in a row, so a long upload gets through).
  The files beside the board (`links.json`, `places.json`, `live.json`, `drafts.json`) are asked "changed since?"
  (a 304 when not), and read in full at least once a minute: write them only by a whole-file rewrite (as threads.py
  and live_hook.py do), never by putting back an older copy with its old time.
  The board server says the number on `/events` (`id:` on "changed", a named `alive` every 10 s) and resumes from
  `Last-Event-ID` or `?since=`. Before each "changed" it also sends the small change itself (a named `delta`: the
  change file and the summary's head; Suda's own server takes it from the store, at any distance, up to 32 KB), so a page applies it with no read of its own: one round trip
  less per update, about a second on a weak link (suda-fixes 61). A bigger change, or a page or server from before
  this, reads as before. A burst (20 or 50 of your messages in a few seconds) comes in about one event a second,
  each carrying every change since the last, up to 32 KB (the owner, m273): post as fast as you need. What agents can rely on: once your command returns, every open page (phone, Mac,
  another tab) shows it within seconds of its line being up, by the small change alone; a page that missed
  anything, or doubts its copy, reads the whole summary at once (never half a change); its header says "Up to date"
  only when the server confirmed its number in the last 25 s, else "Updating…" or "Not connected". His replies wait on
  his device until the server takes them, and go the moment the line is back. Nothing changes in how you write:
  never write `state.json` or these files by hand (a hand edit is never numbered, and pages may not see it).
- Files of a message live beside the state: `snippets/<thread>/`, `uploads/<thread>/`
  (pictures and their small copies `mN-K.thumb.jpg|png`, recordings, videos `mN-vK.mp4|webm` and their posters, `mN.html.txt`). Camera metadata is stripped
  from pictures, udta/meta/uuid from an mp4, Tags/Attachments/Title/date from a webm.
- Push keys and subscriptions are private: `~/.config/threads/<slug>/` (never in the
  served folder); the public key is `push.json`. The Soniox key is read from
  `~/.soniox` only by the transcribing worker. A test board (another `BOARDS_DIR`)
  never reaches his devices or Soniox: `THREADS_PUSH_CMD`, `THREADS_SNAP_CMD` and
  `THREADS_SONIOX_CMD` stand in.
- Suda shortcuts: Cmd/Ctrl+K search, N / Alt+N new topic (Cmd+N in the installed app),
  1 to 9 slots, J/K move, T next on the owner, R reply, Cmd/Ctrl+Enter send, ? help.
- The Cmd/Ctrl+K palette lists threads and commands. Each thread row ends with how long ago
  it last changed, the same short time as its sidebar row (its last message, else its last
  change: "12 min", "3 h", "3 days"); commands show no time. The times move on every 30 s
  while it is open. So a thread an agent just wrote in reads "now" there too.
- His keys to a thread's agents (the live card under the head's live chip, fed by `live.json`; suda m630):
  Alt+1..9 puts the keys on agent N of the card (Ctrl+1..9 too on a Mac and a phone; on a Mac, while he writes,
  only Ctrl); A, or Alt+A from the empty reply box, moves the keys into the card and back. None of them is taken
  from another text field (a rename, the find bar, a dialog), and a number the card does not have is left to the
  browser. In the card ↑/↓ walk the
  agents, Home/End the first/last, ←/→ a row's buttons (open its window, send continue), Enter opens the thread
  the agent works on (its `thread` in `live.json`; on this thread it gives the keys back to the reply box), Esc or
  A close it and give the keys back. N is the card's order (stuck, working here, working elsewhere, resting), shown
  on each row; the help (?) and Cmd+K list the agents by number and name, so a clear agent `name` matters.
