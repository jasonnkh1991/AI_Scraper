import os
import sys
import types
import unittest

openai_stub = types.ModuleType("openai")
openai_stub.OpenAI = object
sys.modules.setdefault("openai", openai_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: object()
sys.modules.setdefault("supabase", supabase_stub)

import crawler


class ApifyPayloadTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("TIER1_TWITTER_SEARCH_QUERY", None)
        os.environ.pop("TIER2_TWITTER_SEARCH_QUERY", None)
        os.environ.pop("BYPASS_MARKET_WINDOW", None)

    def test_scrapebadger_payload_uses_advanced_search(self) -> None:
        payload = crawler.build_apify_payload(12, "from:elonmusk -filter:replies")

        self.assertEqual(payload["mode"], "Advanced Search")
        self.assertEqual(payload["query"], "from:elonmusk -filter:replies")
        self.assertEqual(payload["query_type"], "Latest")
        self.assertEqual(payload["max_results"], 12)

    def test_default_tier_queries_match_watchlist(self) -> None:
        self.assertIn("from:DeItaone", crawler.tier_twitter_query(1))
        self.assertIn("from:Benzinga", crawler.tier_twitter_query(1))
        self.assertIn("from:sama", crawler.tier_twitter_query(2))
        self.assertIn("from:FirstSquawk", crawler.tier_twitter_query(2))

    def test_fetch_tweets_runs_both_tiers_when_bypassed(self) -> None:
        captured = []

        def fake_run_actor(actor_id, payload, limit):
            captured.append((payload["query"], limit))
            return [{"id": str(limit), "text": "test", "user": {"username": "tester"}}]

        original = crawler.run_apify_actor
        os.environ["BYPASS_MARKET_WINDOW"] = "true"
        try:
            crawler.run_apify_actor = fake_run_actor
            items = crawler.fetch_tweets_from_apify()
        finally:
            crawler.run_apify_actor = original

        self.assertEqual(len(items), 2)
        self.assertEqual(captured[0][1], crawler.FETCH_LIMIT)
        self.assertEqual(captured[1][1], crawler.TIER2_FETCH_LIMIT)
        self.assertIn("from:DeItaone", captured[0][0])
        self.assertIn("from:sama", captured[1][0])

    def test_normalize_tweet_supports_scrapebadger_like_fields(self) -> None:
        tweet = crawler.normalize_tweet({
            "id": "1234567890",
            "text": "NVDA raises guidance",
            "user": {"username": "DeitaOne", "name": "Walter Bloomberg"},
            "created_at": "2026-05-26T12:00:00+00:00",
            "url": "https://x.com/DeitaOne/status/1234567890",
        })

        assert tweet is not None
        self.assertEqual(tweet["tweet_id"], "1234567890")
        self.assertEqual(tweet["author_handle"], "DeitaOne")
        self.assertEqual(tweet["author_name"], "Walter Bloomberg")


if __name__ == "__main__":
    unittest.main()
