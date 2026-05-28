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


def record(tweet_id, text, tickers):
    return {
        "tweet": {
            "tweet_id": tweet_id,
            "tweet_text": text,
            "author_handle": "source",
            "author_name": "Source",
            "tweet_url": f"https://x.com/source/status/{tweet_id}",
        },
        "insight": {
            "impact_score": 8,
            "confidence_score": 7,
            "source_quality": "reputable_media",
            "time_horizon": "days",
            "target_sectors": ["AI Infrastructure"],
            "affected_tickers": tickers,
            "summary_zh": text,
            "original_zh": text,
            "why_it_matters_zh": text,
            "market_mechanism_zh": text,
            "trading_action": "watch",
            "risk_zh": "risk",
        },
    }


class AlertGroupingTest(unittest.TestCase):
    def test_groups_records_with_shared_tickers(self) -> None:
        groups = crawler.group_high_impact_records([
            record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"]),
            record("2", "AWS signs large AI infrastructure agreement", ["AMZN"]),
            record("3", "Oil ceasefire headline moves energy", ["XOM"]),
        ])

        self.assertEqual([len(group) for group in groups], [2, 1])

    def test_keeps_unrelated_records_separate(self) -> None:
        groups = crawler.group_high_impact_records([
            record("1", "Snowflake AWS AI compute deal", ["SNOW"]),
            record("2", "Fed bill auction rates liquidity", []),
        ])

        self.assertEqual(len(groups), 2)


if __name__ == "__main__":
    unittest.main()
