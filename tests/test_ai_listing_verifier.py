import json
import os
import unittest
from unittest.mock import Mock, patch

import ai_listing_verifier


class AIListingVerifierTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.get("OPENAI_API_KEY")
        self.old_model = os.environ.get("OPENAI_MODEL")
        self.old_required = os.environ.get("OPENAI_REQUIRED")
        os.environ["OPENAI_API_KEY"] = "test-only-placeholder"
        os.environ["OPENAI_MODEL"] = "gpt-4.1-mini"
        os.environ["OPENAI_REQUIRED"] = "true"

    def tearDown(self):
        for key, value in (
            ("OPENAI_API_KEY", self.old_key),
            ("OPENAI_MODEL", self.old_model),
            ("OPENAI_REQUIRED", self.old_required),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_verified_result_is_mapped_by_record_id(self):
        row = {
            "record_id": "abc123",
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
        self.assertIn("json", body["instructions"])
        self.assertEqual(body["text"]["format"]["type"], "json_object")
        sent = body["input"]
        self.assertNotIn("source_url", sent)
        self.assertIn("source_card_text", sent)

    def test_missing_source_excerpt_is_never_marked_verified(self):
        row = {"record_id": "no-evidence", "source_excerpt": ""}
        with patch.object(ai_listing_verifier.requests, "post") as mocked:
            result = ai_listing_verifier.verify_rows([row])
        self.assertEqual(result["no-evidence"]["status"], "review")
        mocked.assert_not_called()

    def test_required_verification_fails_if_api_key_missing(self):
        os.environ.pop("OPENAI_API_KEY", None)
        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is missing"):
            ai_listing_verifier.verify_rows([{
                "record_id": "abc123",
                "source_excerpt": "Public listing text",
            }])


if __name__ == "__main__":
    unittest.main()
