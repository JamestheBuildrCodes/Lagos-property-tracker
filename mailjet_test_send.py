"""Send a zero-cost manual verification email through the shared Mailjet sender."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from mailjet_sender import recipients_from_values, send_message


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python mailjet_test_send.py <recipient>")

    recipient = recipients_from_values(sys.argv[1])
    if not recipient:
        raise SystemExit("A valid test recipient email is required.")

    report_url = ""
    path = Path("data/client_doc_url.txt")
    if path.exists():
        report_url = path.read_text(encoding="utf-8").strip()

    text = (
        "Lagos & Abuja Property Market — Verification Email\n\n"
        "This is a delivery test for the Lagos Property Tracker.\n"
    )
    if report_url:
        text += f"\nCurrent weekly report: {report_url}\n"

    html = (
        "<p><strong>Lagos &amp; Abuja Property Market — Verification Email</strong></p>"
        "<p>This is a delivery test for the Lagos Property Tracker.</p>"
    )
    if report_url:
        html += f"<p><a href='{report_url}'>Open the current weekly report</a></p>"

    send_message(
        to=recipient,
        subject="Lagos Property Tracker — Email Verification",
        html_body=html,
        text_body=text,
        layer="manual-test",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
