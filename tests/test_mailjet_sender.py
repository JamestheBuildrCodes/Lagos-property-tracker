import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mailjet_sender


class MailjetSenderTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "MAILJET_API_KEY": "public-test-key",
            "MAILJET_SECRET_KEY": "private-test-key",
            "MAILJET_FROM_EMAIL": "sender@example.com",
            "MAILJET_FROM_NAME": "Master Builder",
            "GITHUB_RUN_ID": "123456",
        }
        self.previous = os.environ.copy()
        os.environ.update(self.env)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.previous)

    def test_success_response_is_verified_and_receipt_is_written(self):
        response_payload = {
            "Messages": [
                {
                    "Status": "success",
                    "To": [
                        {
                            "Email": "client@example.com",
                            "MessageUUID": "uuid-123",
                            "MessageID": 456,
                            "MessageHref": "https://api.mailjet.com/v3/message/456",
                        }
                    ],
                    "Cc": [
                        {
                            "Email": "copy@example.com",
                            "MessageUUID": "uuid-124",
                            "MessageID": 457,
                            "MessageHref": "https://api.mailjet.com/v3/message/457",
                        }
                    ],
                }
            ]
        }

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return response_payload

        with tempfile.TemporaryDirectory() as td, patch.object(
            mailjet_sender, "Path", lambda name: Path(td) / name
        ), patch.object(
            mailjet_sender.requests,
            "post",
            return_value=FakeResponse(),
        ) as mocked_post:
            receipt = mailjet_sender.send_message(
                to=["client@example.com"],
                cc=["copy@example.com", "client@example.com"],
                subject="Test subject",
                html_body="<p>Test</p>",
                text_body="Test",
                layer="test",
            )

            mocked_post.assert_called_once()
            self.assertEqual(receipt["http_status"], 200)
            self.assertEqual(receipt["message_results"][0]["status"], "success")
            self.assertEqual(
                receipt["message_results"][0]["recipients"][0]["message_id"],
                456,
            )
            self.assertTrue(receipt["custom_id"].startswith("lagos-property-test-"))
            receipt_path = Path(td) / "mailjet_test_receipt.json"
            self.assertTrue(receipt_path.exists())
            saved = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["message_results"][0]["recipients"][1]["message_uuid"], "uuid-124")

    def test_http_success_but_message_error_is_not_treated_as_sent(self):
        response_payload = {
            "Messages": [
                {
                    "Status": "error",
                    "Errors": [
                        {
                            "ErrorMessage": "Sender blocked",
                        }
                    ],
                }
            ]
        }

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return response_payload

        with patch.object(
            mailjet_sender.requests,
            "post",
            return_value=FakeResponse(),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Mailjet did not return a fully successful message result",
            ):
                mailjet_sender.send_message(
                    to=["client@example.com"],
                    subject="Test subject",
                    html_body="<p>Test</p>",
                    text_body="Test",
                    layer="test",
                )

    def test_recipient_normalization_deduplicates_case_insensitively_at_send_layer(self):
        self.assertEqual(
            mailjet_sender.recipients_from_values(
                "client@example.com, client@example.com",
                "copy@example.com",
            ),
            [
                "client@example.com",
                "copy@example.com",
            ],
        )


if __name__ == "__main__":
    unittest.main()
