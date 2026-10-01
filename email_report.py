"""Send Layer 1 executive brief using Mailjet's transactional Send API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from mailjet_sender import recipients_from_values, send_message
from report_builder import build_executive_html


def send_report(client_email: str, cc_email: str, html_body: str) -> None:
    to = recipients_from_values(client_email)
    cc = recipients_from_values(cc_email)

    text_body = (
        "Lagos & Abuja Property Market — Weekly Intelligence Brief\n\n"
        "This week's property market intelligence brief is ready. "
        "The HTML version contains the complete executive summary and "
        "auditable source references."
    )

    send_message(
        to=to,
        cc=cc,
        subject="Lagos & Abuja Property Market — Weekly Intelligence Brief",
        html_body=html_body,
        text_body=text_body,
        layer="layer1",
    )


def run() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python email_report.py "
            "<listings.csv> [changes.csv] [client_email] [html_path]"
        )

    listings = sys.argv[1]
    changes = sys.argv[2] if len(sys.argv) > 2 else "none"
    client_email = (
        sys.argv[3]
        if len(sys.argv) > 3
        else os.environ.get("REPORT_CLIENT_EMAIL", "")
    )
    html_path = sys.argv[4] if len(sys.argv) > 4 else ""

    html = (
        Path(html_path).read_text(encoding="utf-8")
        if html_path and Path(html_path).exists()
        else build_executive_html(listings, changes)
    )

    send_report(
        client_email,
        os.environ.get("REPORT_TO_EMAIL", ""),
        html,
    )


if __name__ == "__main__":
    run()
