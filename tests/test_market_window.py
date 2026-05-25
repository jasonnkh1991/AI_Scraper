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

from crawler import should_run_market_window


def ny_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 5, 25, hour, minute, tzinfo=ZoneInfo("America/New_York"))


class MarketWindowTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("BYPASS_MARKET_WINDOW", None)

    def test_runs_during_high_frequency_window(self) -> None:
        self.assertTrue(should_run_market_window(ny_time(6, 0)))
        self.assertTrue(should_run_market_window(ny_time(13, 15)))
        self.assertTrue(should_run_market_window(ny_time(19, 45)))

    def test_runs_every_30_minutes_during_low_frequency_window(self) -> None:
        self.assertTrue(should_run_market_window(ny_time(20, 0)))
        self.assertFalse(should_run_market_window(ny_time(20, 15)))
        self.assertTrue(should_run_market_window(ny_time(20, 30)))
        self.assertFalse(should_run_market_window(ny_time(23, 45)))

    def test_stops_overnight(self) -> None:
        self.assertFalse(should_run_market_window(ny_time(0, 0)))
        self.assertFalse(should_run_market_window(ny_time(5, 45)))

    def test_bypass_market_window(self) -> None:
        os.environ["BYPASS_MARKET_WINDOW"] = "true"
        self.assertTrue(should_run_market_window(ny_time(2, 0)))


if __name__ == "__main__":
    unittest.main()
