#!/usr/bin/env python3
"""Run every Suda test file once, in parallel, and say what failed (the owner, suda m756: one final run, fast).

Each test file runs as its own process: the e2e harness already gives each process its own agent-browser session
(named by pid), its own temp board and a free port, so files do not share state. A file that fails is run once more on
its own at the end (the known timing flakes under load), and both results are reported.

Usage (from the repo root):  python3 tests/run_all.py [-j N] [--e2e-jobs M] [--env KEY=VALUE ...] [paths or globs ...]
  -j          parallel non-browser files (default: number of CPUs)
  --e2e-jobs  parallel browser files (default: 6; each holds a headless Chrome)
  --env       extra environment for every file (for example SUDA_E2E_SERVER=own, THREADS_BOARDLIB_DIR=...)
Exit code 0 only when every file passed (first try or the rerun).
"""
import argparse
import concurrent.futures as cf
import glob
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path.cwd()
BROWSER = re.compile(r'test_e2e|_e2e\b|e2e_|test_adv_.*(page|ui|e2e)|test_english|test_mdv_e2e')


def files(patterns):
    found = []
    for pattern in patterns or ['test_*.py', 'adv_*.py', 'tests/test_*.py', 'tests/adversarial/test_*.py', 'tests/**/test_*.py']:
        found += glob.glob(pattern, recursive=True)
    return sorted({str(Path(f)) for f in found if not f.endswith('__init__.py')})


def is_browser(path):
    name = Path(path).name
    if BROWSER.search(name):
        return True
    try:
        head = Path(path).read_text(encoding='utf-8', errors='replace')[:20000]
    except OSError:
        return False
    return 'test_e2e' in head or 'agent-browser' in head or 'Browser(' in head


def run(path, env, timeout):
    start = time.monotonic()
    try:
        r = subprocess.run([sys.executable, path], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        out, code = (r.stdout + r.stderr), r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = ((e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')) + '\nTIMEOUT', 124
    summary = next((line for line in reversed(out.splitlines()) if re.match(r'^(OK|FAILED|Ran )', line)), out.strip().splitlines()[-1] if out.strip() else '')
    return path, code, round(time.monotonic() - start, 1), summary, out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-j', type=int, default=os.cpu_count() or 4)
    p.add_argument('--e2e-jobs', type=int, default=6)
    p.add_argument('--timeout', type=int, default=1800)
    p.add_argument('--env', action='append', default=[])
    p.add_argument('--no-rerun', action='store_true')
    p.add_argument('patterns', nargs='*')
    a = p.parse_args()
    env = dict(os.environ)
    # sqlite177: the board's truth is suda.db; the tests read state.json after a command (and write it as a
    # fixture, which the next command takes in), so every save also writes it here
    env.setdefault('THREADS_EXPORT_STATE', '1')
    env.setdefault('THREADS_AUTO_IMPORT', '1')       # (and a state.json a test writes is taken in by the next command)
    for kv in a.env:
        k, _, v = kv.partition('=')
        env[k] = v
    todo = files(a.patterns)
    browser = [f for f in todo if is_browser(f)]
    plain = [f for f in todo if f not in browser]
    print(f'{len(todo)} files: {len(plain)} plain (x{a.j}), {len(browser)} browser (x{a.e2e_jobs})', flush=True)
    results = {}
    started = time.monotonic()
    with cf.ThreadPoolExecutor(a.j) as plain_pool, cf.ThreadPoolExecutor(a.e2e_jobs) as browser_pool:
        futures = [plain_pool.submit(run, f, env, a.timeout) for f in plain] + [browser_pool.submit(run, f, env, a.timeout) for f in browser]
        for fut in cf.as_completed(futures):
            path, code, secs, summary, out = fut.result()
            results[path] = (code, secs, summary, out)
            print(f"{'ok  ' if code == 0 else 'FAIL'} {secs:7.1f}s  {path}  {summary}", flush=True)
    failed = [f for f, (code, *_) in results.items() if code != 0]
    rerun = {}
    if failed and not a.no_rerun:
        print(f'\nrerunning {len(failed)} failed file(s) alone:', flush=True)
        for f in failed:
            path, code, secs, summary, out = run(f, env, a.timeout)
            rerun[f] = (code, summary, out)
            print(f"{'ok  ' if code == 0 else 'FAIL'} {secs:7.1f}s  {f}  {summary}", flush=True)
    still = [f for f in failed if rerun.get(f, (1,))[0] != 0]
    logdir = ROOT / '.test-logs'
    if failed:
        logdir.mkdir(exist_ok=True)
        for f in failed:
            (logdir / (Path(f).stem + '.log')).write_text(results[f][3] + ('\n\n=== RERUN ===\n' + rerun[f][2] if f in rerun else ''), encoding='utf-8')
    print(f'\n{len(todo)} files in {round(time.monotonic() - started)}s: '
          f'{len(todo) - len(failed)} passed, {len(failed) - len(still)} passed on rerun, {len(still)} failed'
          + (f' (logs in {logdir})' if failed else ''))
    for f in still:
        print('  STILL FAILING:', f)
    sys.exit(1 if still else 0)


if __name__ == '__main__':
    main()
