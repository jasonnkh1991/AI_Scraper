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

from crawler import cap_new_tweets_for_run, current_x_fetch_limit, is_hkt_quiet_window, should_run_market_window, should_run_tier2, should_run_truth_social, should_send_market_open_digest, should_send_overnight_digest, should_send_power_hour_digest, should_send_premarket_digest


def ny_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 25, hour, minute, tzinfo=ZoneInfo("America/New_York"))


def hkt_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 25, hour, minute, tzinfo=ZoneInfo("Asia/Hong_Kong"))


class MarketWindowTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("BYPASS_MARKET_WINDOW", None)

    def test_runs_during_high_frequency_window_outside_hkt_quiet_mode(self) -> None:
        self.assertTrue(should_run_market_window(ny_time(6, 0)))
        self.assertTrue(should_run_market_window(ny_time(7, 15)))
        self.assertTrue(should_run_market_window(ny_time(11, 45)))

    def test_runs_every_30_minutes_during_low_frequency_window(self) -> None:
        self.assertTrue(should_run_market_window(ny_time(20, 7)))
        self.assertFalse(should_run_market_window(ny_time(20, 22)))
        self.assertTrue(should_run_market_window(ny_time(20, 37)))
        self.assertFalse(should_run_market_window(ny_time(23, 52)))

    def test_runs_every_30_minutes_overnight_for_x_only(self) -> None:
        self.assertFalse(should_run_market_window(ny_time(0, 0)))
        self.assertTrue(should_run_market_window(ny_time(0, 7)))
        self.assertFalse(should_run_market_window(ny_time(0, 22)))
        self.assertTrue(should_run_market_window(ny_time(5, 37)))
        self.assertFalse(should_run_truth_social(ny_time(0, 7)))
        self.assertFalse(should_run_truth_social(ny_time(5, 37)))

    def test_hkt_quiet_mode_runs_hourly_with_quiet_fetch_limit(self) -> None:
        import crawler

        self.assertTrue(is_hkt_quiet_window(hkt_time(1, 7)))
        self.assertTrue(should_run_market_window(hkt_time(1, 7)))
        self.assertFalse(should_run_market_window(hkt_time(1, 22)))
        self.assertEqual(current_x_fetch_limit(hkt_time(1, 7)), crawler.QUIET_FETCH_LIMIT)

    def test_overnight_uses_reduced_x_fetch_limit_outside_hkt_quiet_mode(self) -> None:
        import crawler

        self.assertEqual(current_x_fetch_limit(hkt_time(13, 7)), crawler.OVERNIGHT_FETCH_LIMIT)
        self.assertEqual(current_x_fetch_limit(ny_time(6, 7)), crawler.FETCH_LIMIT)

    def test_tier2_runs_hourly_outside_overnight(self) -> None:
        self.assertTrue(should_run_tier2(ny_time(6, 7)))
        self.assertFalse(should_run_tier2(ny_time(6, 22)))
        self.assertTrue(should_run_tier2(ny_time(20, 7)))
        self.assertFalse(should_run_tier2(ny_time(23, 37)))
        self.assertFalse(should_run_tier2(ny_time(0, 7)))
        self.assertFalse(should_run_tier2(hkt_time(1, 7)))


    def test_digest_runs_at_hkt_0807(self) -> None:
        self.assertTrue(should_send_overnight_digest(hkt_time(8, 7)))
        self.assertFalse(should_send_overnight_digest(hkt_time(8, 22)))
        self.assertFalse(should_send_overnight_digest(hkt_time(7, 7)))

    def test_power_hour_digest_runs_after_hkt_0230(self) -> None:
        self.assertFalse(should_send_power_hour_digest(hkt_time(2, 22)))
        self.assertTrue(should_send_power_hour_digest(hkt_time(2, 37)))
        self.assertFalse(should_send_power_hour_digest(hkt_time(2, 52)))

    def test_premarket_digest_runs_after_hkt_2030(self) -> None:
        self.assertFalse(should_send_premarket_digest(hkt_time(20, 22)))
        self.assertTrue(should_send_premarket_digest(hkt_time(20, 37)))
        self.assertFalse(should_send_premarket_digest(hkt_time(20, 52)))

    def test_market_open_digest_runs_after_hkt_2315(self) -> None:
        self.assertFalse(should_send_market_open_digest(hkt_time(23, 7)))
        self.assertTrue(should_send_market_open_digest(hkt_time(23, 22)))
        self.assertFalse(should_send_market_open_digest(hkt_time(23, 37)))

    def test_caps_backlog_to_oldest_tweets_for_queue_drain(self) -> None:
        tweets = [{"tweet_id": str(index)} for index in range(20)]

        capped = cap_new_tweets_for_run(tweets, limit=5)

        self.assertEqual([tweet["tweet_id"] for tweet in capped], ["0", "1", "2", "3", "4"])

    def test_bypass_market_window(self) -> None:
        os.environ["BYPASS_MARKET_WINDOW"] = "true"
        self.assertTrue(should_run_market_window(ny_time(2, 0)))


if __name__ == "__main__":
    unittest.main()
