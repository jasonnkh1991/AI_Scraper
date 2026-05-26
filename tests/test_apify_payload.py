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
        os.environ.pop("TWITTER_SEARCH_QUERY", None)

    def test_scrapebadger_payload_uses_advanced_search(self) -> None:
        os.environ["TWITTER_SEARCH_QUERY"] = "from:elonmusk -filter:replies"
        payload = crawler.build_apify_payload()

        self.assertEqual(payload["mode"], "Advanced Search")
        self.assertEqual(payload["query"], "from:elonmusk -filter:replies")
        self.assertEqual(payload["query_type"], "Latest")
        self.assertEqual(payload["max_results"], crawler.FETCH_LIMIT)

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
