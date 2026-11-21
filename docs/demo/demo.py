#!/usr/bin/env python3
"""A demo board for Suda, with invented content only: the README's screenshots are taken from it.

    python3 docs/demo/demo.py            # builds the board, serves it on 127.0.0.1, prints the address
    python3 docs/demo/demo.py --keep DIR # the same, in DIR (kept after exit)

It runs Suda's own board server (server.py) on loopback, on a free port, over a temporary BOARDS_DIR, installs the pages there with THREADS_SLUG=readme-demo, and fills the board through
the threads CLI. Nothing here reads or writes a real board, and nothing is reachable from another machine.
"""
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / 'suda'        # the app's folder
CLI = APP / 'threads.py'
SLUG = 'readme-demo'

LOG = '\n'.join(
    f'2026-11-12T02:{m // 60:02d}:{m % 60:02d}Z worker-{m % 4} ' + (
        'ERROR export failed: upstream timed out after 30s (attempt 3/3)' if m % 97 == 0 else
        'WARN slow query orders_by_day took 2.4s' if m % 13 == 0 else
        f'INFO exported batch {m} (500 rows)')
    for m in range(1, 1800)) + '\n'

DIAGRAM = '''Here is how a reply travels, end to end:

```mermaid
flowchart LR
  P[Phone or desktop page] -->|POST /api/state| S[Board server]
  S -->|on-state.sh| T[threads ingest]
  T -->|state.json| D[(Board folder)]
  T -->|mail| W[Tower agent]
  W -->|threads say| D
  D -->|summary.json| P
```

The page never runs anything: it only writes a request, and the CLI decides.'''

TABLE = '''**Release 2.4 is ready for a decision.**

| Check | Result | Notes |
|---|---|---|
| Unit tests | 412 passed | 3 new for the retry policy |
| Integration | 38 passed | sandbox card network |
| Load test | p95 180 ms | was 210 ms |
| Error budget | 0.4% used | well inside |

```diff
- maxRetries: 1
+ maxRetries: 3
+ backoff: exponential(base=400ms, cap=5s)
```'''

RUN = '''Staging is green. To deploy it, approve the command below: it runs on the Mac only after you confirm the exact text.

```sh
! make deploy ENV=staging VERSION=2.4.0
! make smoke ENV=staging
```'''

REVIEW = """The change is small. One file, the retry policy:

```diff
diff --git a/src/payments/retry.js b/src/payments/retry.js
--- a/src/payments/retry.js
+++ b/src/payments/retry.js
@@ -8,9 +8,11 @@ export function retryPolicy(order) {
   const declined = order.lastError === 'card_declined';
   if (!declined) return null;
   return {
-    maxRetries: 1,
-    delayMs: 400,
+    maxRetries: 3,
+    delayMs: backoff(order.attempt, 400, 5000),
+    jitter: true,
   };
 }
+const backoff = (n, base, cap) => Math.min(cap, base * 2 ** n);
```

https://github.com/example/shop/pull/214
"""

STATUS = """```status
{"title":"Rollout of 2.4","state":"running",
 "lines":[{"label":"Build","value":"passed in 4 min","state":"ok"},{"label":"Canary, 5% of traffic","value":"healthy for 30 min","state":"ok"},
          {"label":"Europe","value":"60% of servers","state":"running"},{"label":"Americas","value":"waiting","state":"waiting"}],
 "progress":0.6,"note":"This card updates in place"}
```
"""

MIGRATION = """```status
{"title":"Orders table migration","state":"running",
 "lines":[{"label":"Backup","value":"done in 6 min","state":"ok"},{"label":"Copy to the new schema","value":"3.1 of 5.2 million rows","state":"running"},
          {"label":"Check counts","value":"waiting","state":"waiting"},{"label":"Switch reads","value":"waiting","state":"waiting"}],
 "progress":0.6,"note":"Nothing for you yet: this card updates in place"}
```
"""

TICKS = [{'title': 'Regions', 'items': [{'text': 'Europe', 'recommended': True}, {'text': 'Americas', 'recommended': True}, 'Asia']},
         {'title': 'After the rollout', 'items': [{'text': 'Send the release notes', 'recommended': True}, 'Remove the old flag']}]

CHART = """Moving the workers to Spot cut the bill by more than half. Month by month:

```chart
{"type":"bar","title":"Monthly cost","labels":["September","October","November"],
 "series":[{"name":"On demand","values":[4120,3980,1650]},{"name":"Spot","values":[0,310,720]}],"prefix":"$"}
```
"""

WIDGET = """Move the sliders to see what each mix would cost:

```widget
{"title":"Cost simulator","note":"Estimate for 30 days",
 "inputs":[{"id":"workers","label":"Workers","min":2,"max":40,"step":1,"value":12},
           {"id":"spot","label":"Share on Spot","min":0,"max":100,"step":5,"value":60,"suffix":"%"}],
 "outputs":[{"label":"Monthly cost","formula":"workers*30*(4.6*(100-spot)/100+1.4*spot/100)","prefix":"$","decimals":0},
            {"label":"Saved against on demand","formula":"workers*30*4.6-workers*30*(4.6*(100-spot)/100+1.4*spot/100)","prefix":"$","decimals":0}]}
```
"""

FLOW = """This is the flow I plan to build:

```mermaid
flowchart TD
  A[Customer reports a double charge] --> B{Second payment found?}
  B -->|yes| C[Refund the second payment]
  B -->|no| D[Ask for the receipt]
  C --> E[Mail the customer]
  D --> E
```
"""


def run(env, *args, input=None):
    r = subprocess.run([sys.executable, str(CLI), *args], env=env, input=input, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('threads ' + ' '.join(args[:3]) + ': ' + (r.stderr or r.stdout).strip())
    return r.stdout.strip()


def seed(env, scratch):
    say = lambda tid, who, text, state, note, *more: run(env, 'say', tid, '--from', who, '-', '--state', state, '--note', note,
                                                         '--by', 'demo', *more, input=text)
    own = lambda tid, text: run(env, 'say', tid, '--from', 'owner', '-', input=text)      # the owner's words carry no turn
    run(env, 'space', 'add', 'support', 'Support', '--prefix', 'demo-ticket-', '--letter', 'S', '--color', '#2f73c9')

    # a release: tasks of every colour, a table, a diff, then a question with buttons
    run(env, 'new', 'demo-release', 'Release 2.4: checkout retries', '--summary', 'Retry declined card payments with backoff',
        '--state', 'working', '--note', 'Preparing the release', '--by', 'demo')
    for text, owner, status in (('Retry policy for declined cards', 'fork', 'done'), ('Integration tests on the sandbox', 'fork', 'building'),
                                ('Release notes', 'fork', 'working'), ('Approve the rollout window', 'owner', 'on-owner'),
                                ('Dashboard for the retry rate', 'fork', 'todo')):
        n = run(env, 'task', 'add', 'demo-release', text, '--owner', owner)
        if status != 'todo':
            run(env, 'task', 'set', 'demo-release', n, status)
    say('demo-release', 'fork', TABLE, 'working', 'Waiting for the load test')
    run(env, 'ask', 'demo-release', 'Ship 2.4 today, or wait for the QA run?', '--options', 'Ship today,Wait for QA,Ship behind a flag',
        '--recommended', 'Ship behind a flag', '--from', 'fork')

    # the tower: a command he approves with one press
    run(env, 'new', 'demo-deploy', 'Staging deploy', '--summary', 'Deploy 2.4 to staging', '--state', 'working', '--note', 'Building', '--by', 'demo')
    say('demo-deploy', 'tower', RUN, 'on-owner', 'Approve the staging deploy')

    # a diagram
    run(env, 'new', 'demo-architecture', 'How a reply travels', '--summary', 'The page, the server, the CLI and the agents',
        '--state', 'working', '--note', 'Drawing it', '--by', 'demo')
    own('demo-architecture', 'Can you draw how my reply reaches the agent?')
    say('demo-architecture', 'fork', DIAGRAM, 'done', 'Diagram posted')

    # a long log as a snippet
    log = scratch / 'nightly-export.log'
    log.write_text(LOG, encoding='utf-8')
    run(env, 'new', 'demo-nightly', 'Nightly export failed', '--summary', 'Three batches timed out upstream', '--state', 'working',
        '--note', 'Reading the log', '--by', 'demo')
    say('demo-nightly', 'fork', 'The whole log is attached. The failures are all upstream timeouts after 30 s; I am adding a retry.',
        'working', 'Adding a retry', '--snippet', str(log))


    # a few more, in different states
    for tid, title, state, note in (('demo-search', 'Search ranking tweaks', 'working', 'Testing on last week\'s queries'),
                                    ('demo-onboarding', 'Onboarding copy', 'on-owner', 'Pick one of the two headlines'),
                                    ('demo-billing', 'Invoice PDF layout', 'done', 'Merged and deployed')):
        run(env, 'new', tid, title, '--state', state, '--note', note, '--by', 'demo')
    say('demo-onboarding', 'fork', 'Two headlines for the first screen:\n\n1. **Everything your agents need from you, in one place**\n2. **Answer your agents from your phone**',
        'on-owner', 'Pick one of the two headlines')

    # the support space, and an urgent ticket
    run(env, 'new', 'demo-ticket-1042', 'Ticket 1042: refund not received', '--summary', 'Customer paid twice on 11 Nov',
        '--state', 'on-owner', '--note', 'Approve a manual refund of 18.00', '--by', 'demo')
    run(env, 'urgent', 'demo-ticket-1042')
    run(env, 'new', 'demo-ticket-1043', 'Ticket 1043: login link expired', '--state', 'working', '--note', 'Sending a new link', '--by', 'demo')
    own('demo-search', 'Try boosting exact title matches before the fuzzy ones.')
    showcase(env, scratch)


def showcase(env, scratch):
    """The threads of the README's screenshots (docs/demo/capture.py, the show-*.png): what an agent can show."""
    say = lambda tid, text, state, note, *more: run(env, 'say', tid, '--from', 'fork', '-', '--state', state, '--note', note,
                                                    '--by', 'demo', *more, input=text)
    topic = lambda tid, title: run(env, 'new', tid, title, '--state', 'working', '--note', 'Preparing', '--by', 'demo')
    topic('demo-review', 'Review: retry policy')
    say('demo-review', REVIEW, 'on-owner', 'Approve the retry change')
    topic('demo-pricing', 'Pricing page mock-up')
    say('demo-pricing', 'Here is the pricing page as a working mock-up. Tap the plans and the billing switch.', 'on-owner',
        'Try the mock-up and say what to change', '--html', str(HERE / 'pricing.html'))
    topic('demo-rollout', 'Rollout of 2.4')
    say('demo-rollout', STATUS, 'working', 'Rolling out', '--live')
    ticks = scratch / 'ticks.json'
    ticks.write_text(json.dumps(TICKS), encoding='utf-8')
    run(env, 'ask', 'demo-rollout', 'What goes out tonight?', '--multi', '--groups-file', str(ticks), '--from', 'fork')
    topic('demo-migration', 'Orders table migration')
    say('demo-migration', MIGRATION, 'working', 'Copying rows, nothing for you yet', '--live')
    topic('demo-costs', 'Cloud costs: November')
    say('demo-costs', CHART, 'done', 'Bill cut by more than half')
    topic('demo-sim', 'Workers: how many on Spot?')
    say('demo-sim', WIDGET, 'on-owner', 'Pick how many workers to keep on demand')
    topic('demo-refund', 'Refund flow for double charges')
    say('demo-refund', FLOW, 'on-owner', 'Is this the flow you want?')
    # his reply that quotes the exact words it answers, as the page sends it (a request the CLI takes in)
    request = {'op': 'reply', 'thread': 'demo-nightly', 'text': 'Retry only the upstream timeouts, not every error. And cap it at 3 attempts.',
               'cid': 'c-quote-1', 'reply_to': 'm1', 'quote': 'The failures are all upstream timeouts after 30 s'}
    body = Path(env['BOARDS_DIR']) / SLUG / 'state/state.json'
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(json.dumps(request), encoding='utf-8')
    run(env, 'ingest')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--keep', metavar='DIR', help='build the board in DIR and keep it')
    ap.add_argument('--port', type=int, default=0, help='port on 127.0.0.1 (default: a free one)')
    a = ap.parse_args()
    holder = None if a.keep else tempfile.TemporaryDirectory(prefix='suda-demo-')
    root = Path(a.keep or holder.name)
    boards = root / 'boards'
    boards.mkdir(parents=True, exist_ok=True)
    (root / 'config' / SLUG).mkdir(parents=True, exist_ok=True)
    (root / 'config' / SLUG / 'config.json').write_text(json.dumps({'owner_name': 'Dana'}, ensure_ascii=False), encoding='utf-8')
    for key in ('THREADS_NOTIFY_CMD', 'THREADS_SNAP_CMD', 'THREADS_PUSH_CMD', 'THREADS_SONIOX_CMD', 'TUIOS_PANE_ID', 'THREADS_SECURE_HOME'):
        os.environ.pop(key, None)
    os.environ.update(BOARDS_DIR=str(boards), THREADS_SLUG=SLUG, THREADS_CONFIG_DIR=str(root / 'config'), THREADS_NOTIFY='0')
    env = dict(os.environ)

    spec = importlib.util.spec_from_file_location('suda_server_demo', APP / 'server.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.bl.BOARDS_DIR, mod.SLUG = boards, SLUG
    server = mod.Server(('127.0.0.1', a.port), mod.Handler)       # loopback only
    threading.Thread(target=server.serve_forever, daemon=True).start()

    run(env, 'install')
    if not (boards / SLUG / 'state.json').is_file() or not json.loads((boards / SLUG / 'state.json').read_text())['threads']:
        seed(env, root)
    url = f'http://127.0.0.1:{server.server_address[1]}/{SLUG}/suda.html'
    print(url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        if holder:
            holder.cleanup()


if __name__ == '__main__':
    main()
