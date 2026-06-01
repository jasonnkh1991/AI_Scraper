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

    def test_study_only_signal_message_marks_quiet_mode(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"])]
        merged = crawler.merge_group_insight(group)

        message = crawler.build_study_only_signal_message(group, merged, 1, 1)

        self.assertIn("Study-only 市場訊號", message)
        self.assertIn("已收錄至 Study/Digest", message)
        self.assertIn("https://x.com/source/status/1", message)

    def test_immediate_telegram_threshold(self) -> None:
        self.assertTrue(crawler.is_immediate_telegram_alert({"impact_score": 8, "confidence_score": 7}))
        self.assertFalse(crawler.is_immediate_telegram_alert({"impact_score": 8, "confidence_score": 6}))
        self.assertTrue(crawler.is_immediate_telegram_alert({"impact_score": 9, "confidence_score": 3}))

    def test_power_hour_digest_message_title(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"])]
        message = crawler.build_power_hour_digest_message([group])

        self.assertIn("Midday / Power Hour Prep", message)
        self.assertIn("來源：", message)

    def test_event_cluster_payload_merges_sources(self) -> None:
        group = [
            record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"]),
            record("2", "AWS signs AI infrastructure agreement", ["AMZN"]),
        ]
        merged = crawler.merge_group_insight(group)
        payload = crawler.event_cluster_payload(group, merged, "tickers:AMZN,SNOW")

        self.assertEqual(payload["fingerprint"], "tickers:AMZN,SNOW")
        self.assertEqual(payload["source_count"], 2)
        self.assertEqual(payload["tickers"], ["AMZN", "SNOW"])
        self.assertEqual(payload["tweet_ids"], ["1", "2"])

    def test_cluster_rows_render_as_digest_groups(self) -> None:
        rows = [{
            "id": 10,
            "fingerprint": "tickers:SNOW",
            "title": "SNOW AI deal",
            "summary_zh": "Snowflake 簽下 AI 基建合作",
            "why_it_matters_zh": "雲端 AI demand 被強化",
            "market_mechanism_zh": "提升 GPU/CPU 需求預期",
            "trading_action": "留意 SNOW、AMZN、NVDA",
            "risk_zh": "估值已高",
            "impact_max": 8,
            "confidence_avg": 7,
            "confidence_max": 7,
            "source_quality": "reputable_media",
            "time_horizon": "days",
            "tickers": ["SNOW"],
            "sectors": ["AI Infrastructure"],
            "tweet_ids": ["1"],
            "source_handles": ["@source"],
            "source_tweet_urls": ["https://x.com/source/status/1"],
            "source_count": 1,
            "last_seen_at": "2026-05-29T01:00:00+00:00",
        }]

        groups = crawler.cluster_rows_to_groups(rows)
        message = crawler.build_premarket_digest_message(groups)

        self.assertIn("Pre-Market Brief", message)
        self.assertIn("SNOW", message)
        self.assertIn("https://x.com/source/status/1", message)

    def test_priority_scoring_catches_jensen_rubin(self) -> None:
        score, reasons = crawler.calculate_priority({
            "author_handle": "business",
            "author_name": "Bloomberg Business",
            "tweet_text": "Nvidia's Jensen Huang discusses Vera Rubin and a new AI chip at Computex. $NVDA",
            "tweet_created_at": "2026-06-01T04:28:57+00:00",
        })

        self.assertGreaterEqual(score, 50)
        self.assertTrue(any("jensen" in reason for reason in reasons))
        self.assertTrue(any("nvidia" in reason for reason in reasons))

    def test_digest_message_includes_pending_section(self) -> None:
        group = [record("1", "Snowflake AWS AI compute deal", ["SNOW", "AMZN"])]
        message = crawler.build_digest_message(
            "Test Digest",
            [group],
            crawler.localized_now("Asia/Hong_Kong"),
            crawler.localized_now("Asia/Hong_Kong"),
            [{
                "author_handle": "business",
                "priority_score": 70,
                "priority_reason": ["entity:jensen_huang:25"],
                "tweet_text": "Nvidia Jensen Huang mentions Vera Rubin.",
                "tweet_url": "https://x.com/business/status/1",
            }],
        )

        self.assertIn("High-priority pending", message)
        self.assertIn("待分析但值得跟進", message)
        self.assertIn("Vera Rubin", message)


    def test_dynamic_watch_terms_extract_new_candidate_name(self) -> None:
        terms = crawler.extract_dynamic_terms_from_text(
            "Trump names Kevin Hassett as a possible Federal Reserve chair successor after Powell."
        )

        self.assertIn("Kevin Hassett", terms)

    def test_dynamic_watch_terms_boost_priority(self) -> None:
        active_terms = {
            "helios alpha": {
                "term": "Helios Alpha",
                "score": 20,
                "hits": 2,
                "sources": ["AI:cluster"],
                "reasons": ["cluster:8:confidence:7"],
                "first_seen_at": "2026-06-01T00:00:00+00:00",
                "last_seen_at": crawler.datetime.now(crawler.timezone.utc).isoformat(),
            }
        }

        score, reasons = crawler.calculate_priority({
            "author_handle": "unknown",
            "author_name": "Unknown",
            "tweet_text": "Helios Alpha wins a new AI infrastructure contract.",
            "tweet_created_at": crawler.datetime.now(crawler.timezone.utc).isoformat(),
        }, active_terms)

        self.assertGreaterEqual(score, 40)
        self.assertTrue(any(reason.startswith("dynamic:Helios Alpha") for reason in reasons))

    def test_cleanup_old_records_uses_safe_filters(self) -> None:
        class FakeResponse:
            data = []

        class FakeQuery:
            def __init__(self, calls, table_name):
                self.calls = calls
                self.table_name = table_name

            def delete(self):
                self.calls.append((self.table_name, "delete"))
                return self

            def lt(self, column, value):
                self.calls.append((self.table_name, "lt", column, value))
                return self

            def eq(self, column, value):
                self.calls.append((self.table_name, "eq", column, value))
                return self

            def neq(self, column, value):
                self.calls.append((self.table_name, "neq", column, value))
                return self

            def execute(self):
                self.calls.append((self.table_name, "execute"))
                return FakeResponse()

        class FakeSupabase:
            def __init__(self):
                self.calls = []

            def table(self, table_name):
                return FakeQuery(self.calls, table_name)

        fake = FakeSupabase()

        deleted = crawler.cleanup_old_records(fake)

        self.assertEqual(deleted["tweet_queue_stale"], 0)
        self.assertIn(("tweet_queue", "eq", "status", "processed"), fake.calls)
        self.assertIn(("tweet_queue", "eq", "is_stale", True), fake.calls)
        self.assertIn(("tweet_queue", "eq", "is_stale", False), fake.calls)
        self.assertNotIn(("tweet_queue", "eq", "status", "pending"), fake.calls)


if __name__ == "__main__":
    unittest.main()
