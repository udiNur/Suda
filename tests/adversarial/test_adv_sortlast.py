import _paths  # tests/_paths.py: the test folders on sys.path, APP = suda/
import unittest
from test_slack import SlackPageTests as Base


class AdvSortLast(Base):
    def test_summary_and_whole_agree_on_last(self):
        self.pure_js(r"""
        const whole=[{id:'m1',from:'a',ts:100,v:'x1',text:'a'},{id:'m2',from:'owner',ts:300,v:'x2',text:'b'},{id:'m3',from:'system',ts:500,v:'x3',text:'merged'}];
        const stamps=whole.map(m=>[m.id,m.from,m.ts,m.v]);
        const summary=normalize({threads:{s:{title:'s',status:'open',stamps,messages:whole.slice(-1)}}}).threads.s;
        const closed=normalize({threads:{s:{title:'s',status:'closed',stamps,messages:[]}}}).threads.s;
        const full=normalize({threads:{s:{title:'s',status:'open',stamps,messages:[]}}},new Map([['s',whole]])).threads.s;
        const old=normalize({threads:{s:{title:'s',status:'open',messages:whole}}}).threads.s;
        for(const t of [summary,closed,full,old])assert.strictEqual(lastShown(t),500);
        assert.ok(closed.partial&&closed.messages.every(m=>m.light));
        """)

    def test_bad_ts_never_poisons_the_order(self):
        self.pure_js(r"""
        const t=normalize({threads:{a:{title:'a',status:'open',updated:40,messages:[{id:'m1',from:'a',ts:30,text:''},{id:'m2',from:'a',ts:'999',text:''},{id:'m3',from:'a',text:''},null]}}}).threads.a;
        assert.strictEqual(lastShown(t),30);
        assert.strictEqual(lastShown({messages:[{ts:'abc'}],updated:'7'}),7);
        assert.strictEqual(lastShown({}),0);assert.strictEqual(lastShown({messages:null,created:5}),5);
        const r=(id,slot,t)=>({t:{id,...t},slot});
        const out=sectionOrder([r('a',1,{messages:[{ts:NaN}]}),r('b',2,{updated:Infinity}),r('c',3,{messages:[{ts:10}]}),r('d',4,{})],'recent').map(x=>x.t.id).join('');
        assert.strictEqual(out,'bcad',out);
        """)

    def test_zero_ts_row_time_vs_order(self):
        # lastShown 0 -> rowNode shows now(), while the order puts it at the bottom
        self.pure_js(r"""
        assert.strictEqual(lastShown({messages:[{ts:0}],updated:900}),0);
        """)

if __name__ == '__main__':
    unittest.main()
