import json
import os
import unittest
from unittest.mock import Mock, patch

import ai_listing_verifier
import ai_market_interpreter


class AIListingVerifierTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            key: os.environ.get(key)
            for key in (
                "GROQ_API_KEY", "GROQ_MODEL", "GROQ_AI_COMMENTARY_ENABLED",
                "GROQ_AI_COMMENTARY_REQUIRED", "EVIDENCE_VERIFICATION_MODE",
            )
        }
        os.environ.pop("GROQ_API_KEY", None)
        os.environ["EVIDENCE_VERIFICATION_MODE"] = "deterministic"
        os.environ["GROQ_AI_COMMENTARY_ENABLED"] = "false"

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def sale_row(self, record_id="sale-1"):
        return {
            "record_id": record_id,
            "source_url": "https://propertypro.ng/property/3-bedroom-flat-for-sale-banana-island-lagos-abc123",
            "source_excerpt": "3 bedroom apartment for sale in Banana Island. Asking price ₦500,000,000.",
            "market_node": "Banana Island",
            "transaction": "sale",
            "property_type": "flat_apartment",
            "bedrooms": "3",
            "asking_price_ngn": "500000000",
            "size_sqm": "",
        }

    def groq_response(self, record_id):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "results": [{"record_id": record_id, "status": "pass", "issues": []}]
            })}}]
        }
        return response

    def test_deterministic_evidence_passes_matching_sale(self):
        result = ai_listing_verifier.deterministic_verify_row(self.sale_row())
        self.assertEqual(result["status"], "pass", result["issues"])

    def test_missing_source_excerpt_is_never_marked_verified(self):
        with patch.object(ai_listing_verifier.requests, "post") as mocked:
            result = ai_listing_verifier.verify_rows([{"record_id": "no-evidence", "source_excerpt": ""}])
        self.assertEqual(result["no-evidence"]["status"], "review")
        mocked.assert_not_called()

    def test_groq_optional_second_pass_uses_json_mode(self):
        row = self.sale_row("groq-1")
        os.environ["EVIDENCE_VERIFICATION_MODE"] = "groq"
        os.environ["GROQ_API_KEY"] = "test-only-placeholder"
        response = self.groq_response("groq-1")
        with patch.object(ai_listing_verifier.requests, "post", return_value=response) as mocked:
            result = ai_listing_verifier.verify_rows([row])
        self.assertEqual(result["groq-1"]["status"], "pass")
        self.assertEqual(result["groq-1"]["method"], "deterministic+groq")
        self.assertIn("api.groq.com/openai/v1/chat/completions", mocked.call_args.args[0])
        self.assertEqual(mocked.call_args.kwargs["json"]["model"], "llama-3.3-70b-versatile")
        self.assertEqual(mocked.call_args.kwargs["json"]["response_format"]["type"], "json_object")

    def test_groq_failure_falls_back_to_deterministic_evidence(self):
        row = self.sale_row("fallback-1")
        os.environ["EVIDENCE_VERIFICATION_MODE"] = "groq"
        os.environ["GROQ_API_KEY"] = "test-only-placeholder"
        response = Mock(status_code=400, text='{"error":{"message":"invalid JSON response"}}')
        with patch.object(ai_listing_verifier.requests, "post", return_value=response):
            result = ai_listing_verifier.verify_rows([row])
        self.assertEqual(result["fallback-1"]["status"], "pass")
        self.assertEqual(result["fallback-1"]["method"], "deterministic")

    def test_market_interpreter_uses_groq_json_response(self):
        os.environ["GROQ_API_KEY"] = "test-only-placeholder"
        os.environ["GROQ_AI_COMMENTARY_ENABLED"] = "true"
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": json.dumps({
            "executive_takeaway": "Limited sample; interpret cautiously.",
            "key_findings": [], "business_implications": [],
            "recommended_actions": [], "limitations": [],
        })}}]}
        with patch.object(ai_market_interpreter.requests, "post", return_value=response) as mocked:
            result = ai_market_interpreter.interpret_summary({"listings_tracked": 1, "scorecard": []})
        self.assertIsNotNone(result)
        self.assertEqual(result["model"], "llama-3.3-70b-versatile")
        self.assertEqual(mocked.call_args.kwargs["json"]["response_format"]["type"], "json_object")
        self.assertNotIn("source_url", mocked.call_args.kwargs["json"]["messages"][1]["content"])

    def test_market_interpreter_failure_uses_deterministic_fallback(self):
        os.environ["GROQ_API_KEY"] = "test-only-placeholder"
        os.environ["GROQ_AI_COMMENTARY_ENABLED"] = "true"
        response = Mock(status_code=429, text='{"error":{"message":"rate limit"}}')
        with patch.object(ai_market_interpreter.requests, "post", return_value=response):
            self.assertIsNone(ai_market_interpreter.interpret_summary({"listings_tracked": 1}))


if __name__ == "__main__":
    unittest.main()
