"""Hostile review of big137 (big text snippets in parts). FAIL = a real hole."""
import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import json, time, unittest
import test_threads, test_slack


class AdvBig(test_threads.ThreadsTests):
    def part(self, cid, i, n, text, tid='topic', **kw):
        return {'op': 'snippet-part', 'thread': tid, 'cid': cid, 'i': i, 'n': n, 'text': text, **kw}

    def parts_left(self):
        return sorted(p.name for p in (self.root / '.threads-config').rglob('*.part'))

    def test_adv_one_cid_cannot_stash_more_than_the_limit(self):
        """take_part never adds up what a cid already holds: 100 parts x 1.5 MB = 150 MB per cid are taken,
        though the reply can never accept more than 20 MB. The part that crosses 20 MB must be refused."""
        e = self.at
        self.new()
        big = 'x' * 1_500_000
        answers = [self.post(self.part('c', i, 14, big), ok=None, env=e(1)) for i in range(14)]
        self.assertTrue(all(a['ok'] for a in answers[:13]))
        self.assertFalse(answers[13]['ok'], 'the 14th part (21 MB in total) was kept')

    def test_adv_retry_after_success_then_close_is_still_dup(self):
        """The page re-sends the parts first, always (deliver). If the reply was stored but its answer was lost and
        the thread was closed (or merged) since, the first re-sent part is refused 'closed' and the page shows
        the message as not sent, although it is on the server: the dup rule ('answered as the first time,
        whatever happened to the thread since') does not hold for a big text."""
        e = self.at
        self.new()
        for i, p in enumerate(['a' * 10, 'b' * 10]):
            self.assertTrue(self.post(self.part('k', i, 2, p), env=e(1))['ok'])
        reply = {'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'k', 'under': None, 'snippet': {'parts': 2}}
        self.assertFalse(self.post(reply, env=e(1))['dup'])
        self.run_cli('close', 'topic', env=e(1.1))
        again = self.post(self.part('k', 0, 2, 'a' * 10), ok=None, env=e(1.2))
        self.assertTrue(again['ok'], 'retry of a stored big message refused: ' + str(again))

    def test_adv_bad_thread_type_answers_cleanly(self):
        e = self.at
        self.new()
        for tid in (['topic'], {'a': 1}, None, 5):
            got = self.post(self.part('c', 0, 1, 'x', tid=tid), ok=False, env=e(1))
            self.assertFalse(got['ok'])
        self.assertEqual(self.parts_left(), [])

    def test_adv_lone_surrogate_part_refused_nothing_kept(self):
        e = self.at
        self.new()
        got = self.post(self.part('c', 0, 2, 'ab\ud800cd'), ok=False, env=e(1))
        self.assertFalse(got['ok'])
        self.assertEqual(self.parts_left(), [])

    def test_adv_parts_of_other_thread_or_merged(self):
        e = self.at
        self.new('topic'); self.new('other')
        self.assertTrue(self.post(self.part('same', 0, 1, 'AAAA', tid='topic'), env=e(1))['ok'])
        self.assertTrue(self.post(self.part('same', 0, 1, 'BBBB', tid='other'), env=e(1))['ok'])
        r = self.post({'op': 'reply', 'thread': 'other', 'text': '', 'cid': 'same', 'under': None, 'snippet': {'parts': 1}}, env=e(1))
        m = self.thread('other', env=e(1))['messages'][0]
        self.assertEqual((self.board / m['snippet']['file']).read_text(), 'BBBB')
        # the topic's parts are untouched
        self.assertEqual(len(self.parts_left()), 1)
        # fewer / more parts than sent
        self.assertTrue(self.post(self.part('z', 0, 3, 'a'), env=e(1))['ok'])
        self.assertTrue(self.post(self.part('z', 1, 3, 'b'), env=e(1))['ok'])
        self.assertTrue(self.post(self.part('z', 2, 3, 'c'), env=e(1))['ok'])
        for n in (2, 4):
            self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'z', 'under': None, 'snippet': {'parts': n}}, ok=False, env=e(1))['ok'])
        # n changes: start over, the old parts never mix in
        self.assertTrue(self.post(self.part('z', 0, 2, 'X'), env=e(1))['ok'])
        self.assertFalse(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'z', 'under': None, 'snippet': {'parts': 2}}, ok=False, env=e(1))['ok'])
        self.assertTrue(self.post(self.part('z', 1, 2, 'Y'), env=e(1))['ok'])
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 'z', 'under': None, 'snippet': {'parts': 2}}, env=e(1))['ok'])
        m = self.thread('topic', env=e(1))['messages'][-1]
        self.assertEqual((self.board / m['snippet']['file']).read_text(), 'XY')
        # merged thread takes no parts
        self.run_cli('merge', 'other', '--into', 'topic', env=e(1))
        self.assertFalse(self.post(self.part('w', 0, 1, 'q', tid='other'), ok=False, env=e(1))['ok'])

    def test_adv_dup_with_text_and_parts_resent_leaves_nothing(self):
        e = self.at
        self.new()
        reply = {'op': 'reply', 'thread': 'topic', 'text': 'מילים', 'cid': 'd', 'under': None, 'snippet': {'name': 'a.log', 'parts': 2}}
        for _ in range(2):
            self.assertTrue(self.post(self.part('d', 0, 2, 'one '), env=e(1))['ok'])
            self.assertTrue(self.post(self.part('d', 1, 2, 'two'), env=e(1))['ok'])
            self.post(reply, env=e(1))
            self.assertEqual(self.parts_left(), [])
        # and with no parts at all (gone), the dup still answers
        self.assertTrue(self.post(reply, env=e(1))['dup'])
        self.assertEqual(len(self.thread(env=e(1))['messages']), 1)
        self.assertEqual((self.board / 'state/state.json').read_text().strip(), '{}')

    def test_adv_join_20mb_time(self):
        """The board server gives on-state.sh 60 s, per request."""
        e = self.at
        self.new()
        p = 'אב' * 250_000 + 'x' * 400_000     # 1.4 MB
        n = 14
        t0 = time.time()
        for i in range(n):
            self.assertTrue(self.post(self.part('t', i, n, p), env=e(1))['ok'])
        t1 = time.time()
        self.assertTrue(self.post({'op': 'reply', 'thread': 'topic', 'text': '', 'cid': 't', 'under': None, 'snippet': {'parts': n}}, env=e(1))['ok'])
        t2 = time.time()
        print(f'\n  parts: {(t1 - t0) / n:.2f}s each, join+store: {t2 - t1:.2f}s')
        self.assertLess(t2 - t1, 30)

    def post(self, payload, ok=True, env=None):
        if ok is None:      # either way, give the answer
            path = self.board / 'state/state.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
            import subprocess, sys
            r = subprocess.run([sys.executable, str(test_threads.CLI), 'ingest'], env=env or self.env, capture_output=True, text=True)
            return json.loads(r.stdout)
        return super().post(payload, ok=ok, env=env)


class AdvPage(test_slack.SlackPageTests):
    def test_adv_snippet_parts_edges(self):
        self.pure_js(r"""
        assert.deepStrictEqual(snippetParts(''),[]);
        // surrogate pairs at every boundary
        for(const max of [6,7,8,9,10,11]){
          const t='a😀'.repeat(50)+'😀'.repeat(50),ps=snippetParts(t,max);
          assert.strictEqual(ps.join(''),t);
          assert.ok(ps.every(p=>!/[\uD800-\uDBFF]$/.test(p)&&!/^[\uDC00-\uDFFF]/.test(p)),'cut pair max='+max);
          assert.ok(ps.every(p=>utf8Bytes(JSON.stringify(p))<=max),'over max='+max);
        }
        // a lone high surrogate before a normal char, and a lone low one
        {const t='ab\uD800cd\uDC00ef'.repeat(30),ps=snippetParts(t,9);assert.strictEqual(ps.join(''),t);}
        // performance on 20 MB of mixed content, and the worst: control characters (6 bytes each as JSON)
        for(const [name,t] of [['ascii','x'.repeat(20000000)],['heb','א'.repeat(10000000)],['emoji','😀'.repeat(5000000)],['ctl','\u0001'.repeat(3300000)],['mixed',('x'.repeat(1000000)+'\u0001'.repeat(300000)).repeat(6)]]){
          const t0=Date.now(),ps=snippetParts(t);const ms=Date.now()-t0;
          assert.ok(ps.every(p=>utf8Bytes(JSON.stringify(p))<=PART_BYTES),name);
          assert.ok(ps.length<=100,name+' parts '+ps.length);
          console.error(name,ps.length,'parts',ms,'ms');
          assert.ok(ms<5000,name+' slow '+ms);
        }
        """)


# The scenarios of the base classes belong to their files; here the classes only lend their boards and helpers.
for _base, _cls in ((test_threads.ThreadsTests, AdvBig), (test_slack.SlackPageTests, AdvPage)):
    for _name in dir(_base):
        if _name.startswith('test') and _name not in _cls.__dict__:
            setattr(_cls, _name, None)


if __name__ == '__main__':
    unittest.main()
