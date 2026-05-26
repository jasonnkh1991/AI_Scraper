import os
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

openai_stub = types.ModuleType("openai")
openai_stub.OpenAI = object
sys.modules.setdefault("openai", openai_stub)

supabase_stub = types.ModuleType("supabase")
supabase_stub.Client = object
supabase_stub.create_client = lambda *_args, **_kwargs: object()
sys.modules.setdefault("supabase", supabase_stub)

import crawler


def ny_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 27, hour, minute, tzinfo=ZoneInfo("America/New_York"))


class TruthSocialTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("BYPASS_MARKET_WINDOW", None)

    def test_normalize_truth_post(self) -> None:
        post = crawler.normalize_truth_post({
            "id": "114723536228494118",
            "created_at": "2026-05-27T12:00:00.000Z",
            "content": "<p>Tariffs are coming &amp; China knows it.</p>",
            "url": "https://truthsocial.com/@realDonaldTrump/posts/114723536228494118",
            "account": {
                "username": "realDonaldTrump",
                "display_name": "Donald J. Trump",
                "followers_count": 100,
            },
        })

        assert post is not None
        self.assertEqual(post["tweet_id"], "truth-114723536228494118")
        self.assertEqual(post["author_handle"], "truth:realDonaldTrump")
        self.assertEqual(post["tweet_text"], "Tariffs are coming & China knows it.")

    def test_truth_social_runs_hourly_by_default(self) -> None:
        self.assertTrue(crawler.should_run_truth_social(ny_time(9, 7)))
        self.assertFalse(crawler.should_run_truth_social(ny_time(9, 22)))
        self.assertFalse(crawler.should_run_truth_social(ny_time(2, 7)))

    def test_truth_social_payload_uses_actor_url_objects(self) -> None:
        captured = {}

        def fake_run_actor(actor_id, payload, limit):
            captured["actor_id"] = actor_id
            captured["payload"] = payload
            captured["limit"] = limit
            return []

        original = crawler.run_apify_actor
        try:
            crawler.run_apify_actor = fake_run_actor
            crawler.fetch_truth_posts_from_apify()
        finally:
            crawler.run_apify_actor = original

        self.assertEqual(captured["actor_id"], crawler.TRUTH_SOCIAL_ACTOR_ID)
        self.assertEqual(captured["limit"], crawler.TRUTH_SOCIAL_FETCH_LIMIT)
        self.assertEqual(captured["payload"]["startUrls"], [crawler.canonical_truth_social_url(crawler.TRUTH_SOCIAL_URL)])
        self.assertTrue(captured["payload"]["flattenOutput"])
        self.assertTrue(captured["payload"]["includeMuted"])

    def test_canonical_truth_social_url(self) -> None:
        self.assertEqual(
            crawler.canonical_truth_social_url("https://www.truthsocial.com/realDonaldTrump/"),
            "https://truthsocial.com/@realDonaldTrump",
        )
        self.assertEqual(
            crawler.canonical_truth_social_url("https://truthsocial.com/@realDonaldTrump"),
            "https://truthsocial.com/@realDonaldTrump",
        )


if __name__ == "__main__":
    unittest.main()
