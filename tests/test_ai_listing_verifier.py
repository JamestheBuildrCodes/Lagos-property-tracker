import json
import os
import unittest
from unittest.mock import Mock, patch

import ai_listing_verifier
import ai_market_interpreter


class AIListingVerifierTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get("OPENAI_API_KEY")
        self.old_model = os.environ.get("OPENAI_MODEL")
        self.old_required = os.environ.get("OPENAI_REQUIRED")
        self.old_mode = os.environ.get("EVIDENCE_VERIFICATION_MODE")
        self.old_commentary_enabled = os.environ.get("OPENAI_AI_COMMENTARY_ENABLED")
        os.environ["OPENAI_API_KEY"] = "test-only-placeholder"
        os.environ["OPENAI_MODEL"] = "gpt-4.1-mini"
        os.environ["OPENAI_REQUIRED"] = "true"
        os.environ["EVIDENCE_VERIFICATION_MODE"] = "openai"
        os.environ["OPENAI_AI_COMMENTARY_ENABLED"] = "true"

    def tearDown(self):
        for key, value in (
            ("OPENAI_API_KEY", self.old_key),
            ("OPENAI_MODEL", self.old_model),
            ("OPENAI_REQUIRED", self.old_required),
            ("EVIDENCE_VERIFICATION_MODE", self.old_mode),
            ("OPENAI_AI_COMMENTARY_ENABLED", self.old_commentary_enabled),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_verified_result_is_mapped_by_record_id(self):
        row = {
            "record_id": "abc123",
            "source_url": "https://propertypro.ng/property/3-bedroom-flat-for-sale-banana-island-lagos-abc123",
            "source_excerpt": "3 bedroom apartment for sale in Banana Island. Asking price ₦500,000,000.",
            "market_node": "Banana Island",
            "transaction": "sale",
            "property_type": "flat_apartment",
            "bedrooms": "3",
            "asking_price_ngn": "500000000",
            "size_sqm": "",
        }
        response = Mock(status_code=200)
        response.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "results": [{
                            "record_id": "abc123",
                            "status": "pass",
                            "issues": [],
                        }]
                    }),
                }],
            }]
        }
        with patch.object(ai_listing_verifier.requests, "post", return_value=response) as mocked:
            result = ai_listing_verifier.verify_rows([row])

        self.assertEqual(result["abc123"]["status"], "pass")
        body = mocked.call_args.kwargs["json"]
        self.assertIn("json", body["instructions"].lower())
        self.assertIn("json", body["input"].lower())
        self.assertEqual(body["text"]["format"]["type"], "json_object")
        sent = body["input"]
        self.assertNotIn("source_url", sent)
        self.assertIn("source_card_text", sent)

    def test_market_interpreter_input_explicitly_identifies_json(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "executive_takeaway": "Cautious finding.",
                        "key_findings": [],
                        "business_implications": [],
                        "recommended_actions": [],
                        "limitations": [],
                    }),
                }],
            }]
        }
        with patch.object(ai_market_interpreter.requests, 'post', return_value=response) as mocked:
            result = ai_market_interpreter.interpret_summary({
                "listings_tracked": 1,
                "scorecard": [],
            })
        self.assertIsNotNone(result)
        self.assertIn("json", mocked.call_args.kwargs["json"]["input"].lower())

    def test_missing_source_excerpt_is_never_marked_verified(self):
        row = {"record_id": "no-evidence", "source_excerpt": ""}
        with patch.object(ai_listing_verifier.requests, "post") as mocked:
            result = ai_listing_verifier.verify_rows([row])
        self.assertEqual(result["no-evidence"]["status"], "review")
        mocked.assert_not_called()

    def test_api_quota_failure_falls_back_to_deterministic_evidence_check(self):
        row = {
            "record_id": "fallback-1",
            "source_url": "https://propertypro.ng/property/3-bedroom-flat-for-sale-banana-island-lagos-abc123",
            "source_excerpt": "3 bedroom apartment for sale in Banana Island. Asking price ₦500,000,000.",
            "transaction": "sale",
            "property_type": "flat_apartment",
            "bedrooms": "3",
            "asking_price_ngn": "500000000",
        }
        response = Mock(status_code=429, text='{"error":{"message":"credit_balance_exhausted"}}')
        with patch.object(ai_listing_verifier.requests, "post", return_value=response):
            result = ai_listing_verifier.verify_rows([row])
        self.assertEqual(result["fallback-1"]["status"], "pass")
        self.assertEqual(result["fallback-1"]["method"], "deterministic")

    def test_mismatched_extracted_price_is_quarantined(self):
        row = {
            "record_id": "bad-price",
            "source_url": "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/victoria-island/listing-1",
            "source_excerpt": "1 bedroom apartment for rent in Victoria Island. Asking rent ₦9,000,000 per annum.",
            "transaction": "rent",
            "property_type": "flat_apartment",
            "bedrooms": "1",
            "asking_price_ngn": "299500000",
        }
        result = ai_listing_verifier.deterministic_verify_row(row)
        self.assertEqual(result["status"], "review")
        self.assertTrue(any("asking price" in issue.lower() for issue in result["issues"]))

    def test_land_total_can_be_verified_from_unit_price_and_plot_area(self):
        row = {
            "record_id": "land-unit-rate",
            "source_url": "https://nigeriapropertycentre.com/for-sale/land/residential-land/lagos/ikoyi/banana-island/listing-2",
            "source_excerpt": "Residential land for sale in Banana Island, 500 sqm. Asking price ₦90,000 per sqm.",
            "transaction": "land_sale",
            "property_type": "land",
            "size_sqm": "500",
            "asking_price_ngn": "45000000",
            "price_per_sqm_ngn": "90000",
        }
        result = ai_listing_verifier.deterministic_verify_row(row)
        self.assertEqual(result["status"], "pass", result["issues"])

    def test_deterministic_default_does_not_call_paid_api(self):
        old_mode = os.environ.get("EVIDENCE_VERIFICATION_MODE")
        os.environ["EVIDENCE_VERIFICATION_MODE"] = "deterministic"
        os.environ.pop("OPENAI_API_KEY", None)
        row = {
            "record_id": "free-1",
            "source_url": "https://propertypro.ng/property/3-bedroom-flat-for-sale-banana-island-lagos-abc123",
            "source_excerpt": "3 bedroom apartment for sale in Banana Island. Asking price ₦500,000,000.",
            "transaction": "sale",
            "property_type": "flat_apartment",
            "bedrooms": "3",
            "asking_price_ngn": "500000000",
        }
        try:
            with patch.object(ai_listing_verifier.requests, "post") as mocked:
                result = ai_listing_verifier.verify_rows([row])
            mocked.assert_not_called()
            self.assertEqual(result["free-1"]["status"], "pass")
        finally:
            if old_mode is None:
                os.environ.pop("EVIDENCE_VERIFICATION_MODE", None)
            else:
                os.environ["EVIDENCE_VERIFICATION_MODE"] = old_mode


if __name__ == "__main__":
    unittest.main()
