import sys
import types
import unittest

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: object()
sys.modules.setdefault("supabase", supabase_stub)

import polymarket_monitor as pm


class PolymarketMonitorTests(unittest.TestCase):
    def test_parse_prices_from_json_string(self):
        self.assertEqual(pm.parse_prices('["0.42", "0.58"]'), (0.42, 0.58))

    def test_noise_market_is_filtered(self):
        self.assertIsNone(pm.normalize_market({"id": "1", "question": "Will an NBA team win tonight?"}, "test"))

    def test_investing_market_scores(self):
        market = pm.normalize_market(
            {
                "id": "1",
                "question": "Will the Fed cut rates in September?",
                "outcomePrices": '["0.45", "0.55"]',
                "volume24hr": "100000",
                "liquidity": "50000",
                "active": True,
                "closed": False,
            },
            "test",
        )
        self.assertIsNotNone(market)
        assert market is not None
        self.assertGreaterEqual(market["discovery_score"], 60)
        self.assertTrue(pm.eligible(market))

    def test_quality_score_penalizes_thin_market(self):
        score = pm.quality_score({"volume_24hr": 100, "liquidity": 100, "spread": 0.2}, 0.15, 60, "Fed rates")
        self.assertLess(score, 70)


if __name__ == "__main__":
    unittest.main()
