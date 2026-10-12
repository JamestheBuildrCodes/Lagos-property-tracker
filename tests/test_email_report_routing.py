import unittest
from unittest.mock import patch

import email_report


class EmailReportRoutingTests(unittest.TestCase):
    def test_client_is_to_and_internal_recipient_is_cc(self):
        with patch.object(email_report, "send_message") as mocked_send:
            email_report.send_report(
                "client@example.com",
                "internal@example.com",
                "<p>Weekly report</p>",
                doc_url="https://docs.example.com/report",
                sheet_url="https://docs.example.com/sheet",
            )

        kwargs = mocked_send.call_args.kwargs
        self.assertEqual(kwargs["to"], ["client@example.com"])
        self.assertEqual(kwargs["cc"], ["internal@example.com"])
        self.assertEqual(kwargs["layer"], "layer1")
        self.assertIn("https://docs.example.com/report", kwargs["html_body"])
        self.assertIn("https://docs.example.com/sheet", kwargs["html_body"])

    def test_missing_internal_copy_fails_closed(self):
        with patch.object(email_report, "send_message") as mocked_send:
            with self.assertRaisesRegex(ValueError, "REPORT_TO_EMAIL"):
                email_report.send_report(
                    "client@example.com", "", "<p>Weekly report</p>"
                )
        mocked_send.assert_not_called()

    def test_invalid_client_address_fails_closed(self):
        with patch.object(email_report, "send_message") as mocked_send:
            with self.assertRaisesRegex(ValueError, "REPORT_CLIENT_EMAIL"):
                email_report.send_report(
                    "not-an-email", "internal@example.com", "<p>Weekly report</p>"
                )
        mocked_send.assert_not_called()

    def test_same_client_and_internal_address_fails_closed(self):
        with patch.object(email_report, "send_message") as mocked_send:
            with self.assertRaisesRegex(ValueError, "must be different"):
                email_report.send_report(
                    "same@example.com", "SAME@example.com", "<p>Weekly report</p>"
                )
        mocked_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
