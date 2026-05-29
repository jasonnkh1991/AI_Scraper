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

    def test_event_fingerprint_prefers_tickers(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"])]
        for item in group:
            item["tokens"] = crawler.signal_tokens(item["tweet"], item["insight"])

        self.assertEqual(crawler.event_fingerprint(group), "tickers:AMZN,SNOW")

    def test_mark_event_status_detects_prior_session_update(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW"])]
        for item in group:
            item["tokens"] = crawler.signal_tokens(item["tweet"], item["insight"])
        merged = crawler.merge_group_insight(group)
        recent = {"tickers:SNOW": "2026-05-29T01:00:00+00:00"}

        statuses = crawler.mark_event_status([group], [merged], recent)

        self.assertTrue(statuses[0]["is_update"])
        self.assertEqual(statuses[0]["previous_seen_at"], "2026-05-29T01:00:00+00:00")
        self.assertIn("tickers:SNOW", recent)

    def test_digest_message_includes_source_links(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"])]
        message = crawler.build_overnight_digest_message([group])

        self.assertIn("Overnight Market Digest", message)
        self.assertIn("來源：", message)
        self.assertIn("https://x.com/source/status/1", message)
        self.assertIn("@source", message)

    def test_telegram_html_to_markdown_keeps_links(self) -> None:
        message = '<b>Alert</b> <a href="https://x.com/a/status/1">原文</a>'

        markdown = crawler.telegram_html_to_markdown(message)

        self.assertIn("Alert", markdown)
        self.assertIn("原文 (https://x.com/a/status/1)", markdown)

    def test_daily_study_markdown_groups_alerts(self) -> None:
        alerts = [
            {
                "alert_type": "group_alert",
                "title": "AI deal",
                "message_markdown": "SNOW signs AI deal",
                "source_tweet_urls": ["https://x.com/source/status/1"],
                "impact_max": 8,
                "confidence_avg": 7,
                "tickers": ["SNOW"],
                "sectors": ["AI Infrastructure"],
                "period_start": "2026-05-29T01:00:00+08:00",
                "created_at": "2026-05-29T01:00:00+08:00",
            }
        ]

        markdown = crawler.build_daily_study_markdown(alerts, "2026-05-29")

        self.assertIn("Daily Market Study Brief", markdown)
        self.assertIn("Overnight 00:00-08:00", markdown)
        self.assertIn("SNOW signs AI deal", markdown)
        self.assertIn("https://x.com/source/status/1", markdown)


if __name__ == "__main__":
    unittest.main()
