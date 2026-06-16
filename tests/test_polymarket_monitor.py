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

    def test_chat_completions_url_appends_endpoint(self):
        self.assertEqual(
            pm.chat_completions_url("https://api.example.com/v1"),
            "https://api.example.com/v1/chat/completions",
        )

    def test_signal_message_includes_bilingual_market_title(self):
        message = pm.signal_message({
            "question": "Will the Fed cut rates in September?",
            "question_zh": "聯儲局會否在九月減息？",
            "old_probability": 0.42,
            "new_probability": 0.56,
            "probability_change": 0.14,
            "signal_type": "1h_shock",
            "quality_score": 80,
            "market_implication_zh": "市場正在重新定價減息機率。",
            "trading_lens_zh": "觀察 TLT、QQQ、DXY。",
            "source_url": "https://polymarket.com/event/test",
        })
        self.assertIn("EN：Will the Fed cut rates in September?", message)
        self.assertIn("聯儲局會否在九月減息？", message)
        self.assertNotIn("中：", message)

    def test_topic_for_market_classifies_geo_energy(self):
        self.assertEqual(
            pm.topic_for_market("US-Iran diplomatic meeting by June 19"),
            "Iran / Israel / Oil",
        )

    def test_digest_candidate_filters_meme_market(self):
        self.assertFalse(pm.is_digest_candidate(
            {"question": "Will bitcoin hit $1m before GTA VI?"},
            {"yes_price": 0.49, "volume_24hr": 100000, "liquidity": 100000},
        ))

    def test_choose_digest_topics_limits_markets_per_topic(self):
        original_limit = pm.POLYMARKET_DIGEST_MARKETS_PER_TOPIC
        try:
            pm.POLYMARKET_DIGEST_MARKETS_PER_TOPIC = 2
            items = [
                {"topic": "Rates / Fed", "score": 50, "market": {}, "snapshot": {}},
                {"topic": "Rates / Fed", "score": 40, "market": {}, "snapshot": {}},
                {"topic": "Rates / Fed", "score": 30, "market": {}, "snapshot": {}},
            ]
            topics = pm.choose_digest_topics(items)
            self.assertEqual(len(topics), 1)
            self.assertEqual(len(topics[0][1]), 2)
        finally:
            pm.POLYMARKET_DIGEST_MARKETS_PER_TOPIC = original_limit

    def test_digest_message_explains_odds_and_omits_chinese_label(self):
        message = pm.build_polymarket_digest_message(None, [(
            "Rates / Fed",
            [{
                "market": {
                    "market_id": "1",
                    "question": "Will there be no change in Fed interest rates?",
                    "question_zh": "聯儲局會否維持利率不變？",
                    "source_url": "https://polymarket.com/event/test",
                },
                "snapshot": {"yes_price": 0.945, "volume_24hr": 120000, "liquidity": 50000},
                "move_1h": None,
                "move_24h": 0.01,
                "move_7d": 0.02,
                "score": 80,
            }],
        )])
        self.assertIn("Odds = 市場隱含機率", message)
        self.assertIn("Will there be no change in Fed interest rates?", message)
        self.assertIn("聯儲局會否維持利率不變？", message)
        self.assertNotIn("中：", message)

    def test_send_telegram_chunked_splits_long_message(self):
        sent = []
        original = pm.send_telegram
        try:
            pm.send_telegram = sent.append
            count = pm.send_telegram_chunked("a" * 10 + "\n\n" + "b" * 10, max_chars=15)
            self.assertEqual(count, 2)
            self.assertEqual(len(sent), 2)
            self.assertIn("Part 1/2", sent[0])
            self.assertIn("Part 2/2", sent[1])
        finally:
            pm.send_telegram = original


if __name__ == "__main__":
    unittest.main()
