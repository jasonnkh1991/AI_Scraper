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


if __name__ == "__main__":
    unittest.main()
