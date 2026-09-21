import importlib.util, pathlib, unittest
p=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'live_round.py'
spec=importlib.util.spec_from_file_location('live_round',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class CoreTests(unittest.TestCase):
    def packet(self):
        return {"portfolio":{"positions":{}},"quotes":{t:{"change_pct_vs_previous_close":x} for t,x in zip(m.TICKERS,[2.0,0.2,-2.0,1.49])}}
    def test_commit_roundtrip(self):
        b={"decisions":{"AAPL":{"action":"HOLD"}}}; n='abc'; c=m.commitment(b,n)
        self.assertTrue(m.verify_commitment(b,n,c)); self.assertFalse(m.verify_commitment({"decisions":{"AAPL":{"action":"ADD"}}},n,c))
    def test_quant_is_deterministic(self):
        a=m.quant_decisions(self.packet()); b=m.quant_decisions(self.packet())
        self.assertEqual(a['decisions'],b['decisions']); self.assertEqual(a['decisions']['AAPL']['action'],'ADD'); self.assertEqual(a['decisions']['NVDA']['action'],'HOLD'); self.assertEqual(a['decisions']['AMZN']['action'],'ABSTAIN'); self.assertEqual(a['decisions']['META']['action'],'HOLD')
    def test_actions_are_bounded(self):
        q=m.quant_decisions(self.packet()); self.assertTrue(all(x['action'] in m.ACTIONS for x in q['decisions'].values()))
    def test_canonical_hash_stable(self):
        self.assertEqual(m.sha256_bytes(m.canonical_bytes({'b':2,'a':1})),m.sha256_bytes(m.canonical_bytes({'a':1,'b':2})))

if __name__=='__main__': unittest.main()
