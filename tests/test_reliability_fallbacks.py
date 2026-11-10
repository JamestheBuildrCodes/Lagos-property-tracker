import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_market_interpreter
import enhance_client_report
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


class ClientDocumentCommentaryFallbackTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "ANTHROPIC_API_KEY": "test-only-not-a-real-key",
            "ANTHROPIC_MODEL": "test-model",
        },
        clear=True,
    )
    @patch("enhance_client_report.requests.post")
    def test_claude_rate_limit_does_not_block_client_report(self, post):
        response = SimpleNamespace()
        response.raise_for_status = lambda: (_ for _ in ()).throw(
            RuntimeError("HTTP 429 rate limited")
        )
        post.return_value = response
        result = enhance_client_report.ai_commentary({
            "report_date": "2026-11-10",
            "validated_listing_count": 4,
            "category_samples": {},
            "quality_findings": [],
        })
        self.assertEqual(result["provider"], "deterministic_fallback")
        self.assertTrue(result["commentary"])



class ClientAttachmentFallbackTests(unittest.TestCase):
    def test_docx_and_xlsx_send_without_broken_google_links_when_publication_not_verified(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import email_client_docx

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "client_doc_url.txt").write_text("ATTACHED_DOCX_FALLBACK", encoding="utf-8")
            (root / "google_sheet_update_status.json").write_text(
                json.dumps({"status": "not_updated"}), encoding="utf-8"
            )
            (root / "market_intelligence_2026-11-10.xlsx").write_bytes(b"xlsx-test")
            report = root / "client-report.docx"
            report.write_bytes(b"docx-test")

            with patch("email_client_docx.Path", Path), patch(
                "email_client_docx.send_message"
            ) as send, patch("email_client_docx.sys.argv", ["email_client_docx.py", str(report)]), patch.dict(
                os.environ,
                {
                    "REPORT_CLIENT_EMAIL": "client@example.com",
                    "REPORT_TO_EMAIL": "owner@example.com",
                    "GOOGLE_SHEET_ID": "sheet-id",
                },
            ), patch("email_client_docx.Path", side_effect=lambda value: root / value if not Path(value).is_absolute() else Path(value)):
                old_cwd = os.getcwd()
                os.chdir(root)
                try:
                    email_client_docx.main()
                finally:
                    os.chdir(old_cwd)

            kwargs = send.call_args.kwargs
            self.assertEqual(len(kwargs["attachments"]), 2)
            self.assertNotIn("docs.google.com", kwargs["text_body"])
            self.assertNotIn("spreadsheets/d/", kwargs["text_body"])
            self.assertIn("was not updated and verified", kwargs["text_body"])
            self.assertIn("attached Excel workbook", kwargs["text_body"])



if __name__ == "__main__":
    unittest.main()
