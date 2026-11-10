import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_market_interpreter
import scraper


class MarketCommentaryFallbackTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "listings_tracked": 12,
            "areas_monitored": 10,
            "sources": 2,
            "source_names": ["Nigeria Property Centre", "PropertyPro.ng"],
            "scorecard": [
                {"market_node": "Lekki Phase 1", "listing_count": 8},
                {"market_node": "Victoria Island", "listing_count": 4},
            ],
            "analysis_notes": ["Validated observations increased in the tracked sample."],
        }

    @patch.dict(os.environ, {"GROQ_AI_COMMENTARY_ENABLED": "true"}, clear=True)
    def test_missing_groq_key_returns_complete_deterministic_commentary(self):
        result = ai_market_interpreter.interpret_summary(self.summary)
        self.assertEqual(result["commentary_mode"], "deterministic")
        self.assertTrue(result["executive_takeaway"])
        self.assertTrue(result["key_findings"])
        self.assertTrue(result["recommended_actions"])
        self.assertTrue(result["limitations"])

    @patch.dict(
        os.environ,
        {
            "GROQ_AI_COMMENTARY_ENABLED": "true",
            "GROQ_AI_COMMENTARY_REQUIRED": "true",
            "GROQ_API_KEY": "test-only-not-a-real-key",
        },
        clear=True,
    )
    @patch("ai_market_interpreter.requests.post")
    def test_groq_rate_limit_returns_deterministic_commentary(self, post):
        post.return_value = SimpleNamespace(status_code=429, text="rate limited")
        result = ai_market_interpreter.interpret_summary(self.summary)
        self.assertEqual(result["commentary_mode"], "deterministic")
        self.assertTrue(result["recommended_actions"])


class AlternateTransportCircuitBreakerTests(unittest.TestCase):
    def setUp(self):
        with scraper.DISABLED_ALTERNATE_PROVIDERS_LOCK:
            scraper.DISABLED_ALTERNATE_PROVIDERS.clear()

    def tearDown(self):
        with scraper.DISABLED_ALTERNATE_PROVIDERS_LOCK:
            scraper.DISABLED_ALTERNATE_PROVIDERS.clear()

    @patch.dict(
        os.environ,
        {"ZENROWS_API_KEY": "test-zenrows-key", "SCRAPERAPI_API_KEY": ""},
        clear=False,
    )
    @patch("scraper.requests.get")
    def test_billing_failure_disables_provider_for_rest_of_scan(self, get):
        get.return_value = SimpleNamespace(status_code=402, text="quota exhausted")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                scraper._fetch_alternate_providers(
                    "https://example.com/listings", "Nigeria Property Centre"
                )
        self.assertEqual(get.call_count, 1)
        self.assertTrue(scraper._alternate_provider_disabled("ZenRows"))

    @patch.dict(
        os.environ,
        {
            "ZENROWS_API_KEY": "test-zenrows-key",
            "SCRAPERAPI_API_KEY": "test-scraperapi-key",
        },
        clear=False,
    )
    @patch("scraper.requests.get")
    def test_url_specific_404_falls_through_to_next_provider(self, get):
        first = SimpleNamespace(status_code=404, text="not found")
        second = SimpleNamespace(status_code=200, text="<html><body>listing</body></html>")
        get.side_effect = [first, second]
        result = scraper._fetch_alternate_providers(
            "https://example.com/listings", "Nigeria Property Centre"
        )
        self.assertIs(result, second)
        self.assertEqual(get.call_count, 2)
        self.assertFalse(scraper._alternate_provider_disabled("ZenRows"))


if __name__ == "__main__":
    unittest.main()
