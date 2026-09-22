import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

live = load("live_round_persistent", ROOT / "scripts" / "live_round.py")
settle = load("settle_round_persistent", ROOT / "scripts" / "settle_round.py")

class PersistentAccountTests(unittest.TestCase):
    def packet(self):
        return {
            "round_id": "TEST",
            "frozen_at": "2026-09-22T13:20:00Z",
            "quotes": {
                "AAPL": {"observed_price": 110.0, "change_pct_vs_previous_close": 1.0},
                "NVDA": {"observed_price": 210.0, "change_pct_vs_previous_close": 1.0},
                "AMZN": {"observed_price": 310.0, "change_pct_vs_previous_close": 1.0},
                "META": {"observed_price": 410.0, "change_pct_vs_previous_close": 1.0},
            },
        }

    def test_snapshot_marks_existing_position(self):
        account = {
            "cash_usd": 9000.0,
            "realized_pnl_usd": 0.0,
            "positions": {"AAPL": {"qty": 10.0, "avg_cost": 100.0}},
            "source_round": "YESTERDAY",
        }
        p = live.mark_account_for_packet(account, self.packet())
        self.assertAlmostEqual(p["holdings_usd"], 1100.0)
        self.assertAlmostEqual(p["equity_usd"], 10100.0)
        self.assertEqual(p["positions"]["AAPL"]["qty"], 10.0)

    def test_add_compounds_existing_position(self):
        positions = {"AAPL": {"qty": 10.0, "avg_cost": 100.0}}
        cash, positions, realized, order = settle.apply_action(
            ticker="AAPL", action="ADD", execution={"price": 110.0},
            start_equity=10100.0, cash=9000.0, positions=positions, realized_pnl=0.0,
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertGreater(positions["AAPL"]["qty"], 10.0)
        self.assertGreater(positions["AAPL"]["avg_cost"], 100.0)
        self.assertAlmostEqual(cash, 7990.0)

    def test_reduce_never_goes_short(self):
        positions = {"AAPL": {"qty": 1.0, "avg_cost": 100.0}}
        cash, positions, realized, order = settle.apply_action(
            ticker="AAPL", action="REDUCE", execution={"price": 110.0},
            start_equity=10000.0, cash=0.0, positions=positions, realized_pnl=0.0,
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertNotIn("AAPL", positions)
        self.assertGreater(cash, 0.0)
        self.assertGreater(realized, 0.0)

    def test_no_show_keeps_market_exposure(self):
        state = {"contestants": {"deepseek": {"name": "DeepSeek", "model_id": "model"}}}
        start = {
            "cash_usd": 9000.0,
            "equity_usd": 10000.0,
            "realized_pnl_usd": 0.0,
            "positions": {"AAPL": {"qty": 10.0, "avg_cost": 100.0}},
        }
        market = {
            t: {"execution_reference": {"price": 110.0}, "mark": {"price": 120.0}}
            for t in settle.TICKERS
        }
        a = settle.account_after_actions(
            cid="deepseek", start=start, bundle=None, error="provider down",
            market=market, state=state,
        )
        self.assertEqual(a["status"], "NO_SHOW")
        self.assertEqual(a["positions"]["AAPL"]["qty"], 10.0)
        self.assertAlmostEqual(a["equity_usd"], 10200.0)
        self.assertAlmostEqual(a["pnl_usd"], 200.0)

if __name__ == "__main__":
    unittest.main()
