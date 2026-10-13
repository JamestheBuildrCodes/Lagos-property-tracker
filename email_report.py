"""Send Layer 1 executive brief using Mailjet's transactional Send API."""
from __future__ import annotations

import os
import sys
from html import escape as html_escape
from pathlib import Path

from mailjet_sender import recipients_from_values, send_message, valid_email
from report_builder import build_executive_html


def send_report(client_email: str, cc_email: str, html_body: str, doc_url: str = "", sheet_url: str = "") -> None:
    # The client is the primary recipient; the internal mailbox is a CC.
    # Fail closed rather than silently sending without either intended party.
    if not valid_email(client_email):
        raise ValueError("REPORT_CLIENT_EMAIL must be a valid client email address")
    if not valid_email(cc_email):
        raise ValueError("REPORT_TO_EMAIL must be a valid internal-copy email address")
    if client_email.strip().lower() == cc_email.strip().lower():
        raise ValueError("Client recipient and internal-copy recipient must be different")

    to = recipients_from_values(client_email)
    cc = recipients_from_values(cc_email)
    if len(to) != 1 or len(cc) != 1:
        raise ValueError("Email routing must resolve to exactly one client To and one internal CC")

    data_note = os.environ.get("REPORT_EMAIL_NOTE", "").strip()
    if data_note:
        html_body = (
            '<div style="margin:0 0 18px;padding:14px;background:#fff4d6;'
            'border-left:4px solid #9a6700;color:#3f2f00">'
            '<strong>Data availability note:</strong> '
            + html_escape(data_note)
            + '</div>'
            + html_body
        )

    if doc_url or sheet_url:
        html_body += '<div style="margin:24px 0;padding:16px;background:#f6f8fb;border-top:3px solid #0d2340"><h2>Full report and evidence</h2><p>Open the analyst report for context and the Google Sheet for property-level evidence.</p>'
        if doc_url:
            html_body += f'<p><a href="{doc_url}">Open the full weekly report</a></p>'
        if sheet_url:
            html_body += f'<p><a href="{sheet_url}">Open the property data sheet</a></p>'
        html_body += '</div>'

    text_body = (
        ("DATA AVAILABILITY NOTE: " + data_note + "\n\n") if data_note else ""
    ) + (
        "Lagos & Abuja Property Market — Weekly Intelligence Brief\n\n"
        "This week's property market intelligence brief is ready. "
        "The HTML version contains the executive summary and recommended actions. "
        + (f"Full report: {doc_url}. " if doc_url else "")
        + (f"Property data sheet: {sheet_url}." if sheet_url else "")
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
    doc_url = sys.argv[5] if len(sys.argv) > 5 else ""
    sheet_url = sys.argv[6] if len(sys.argv) > 6 else ""

    html = (
        Path(html_path).read_text(encoding="utf-8")
        if html_path and Path(html_path).exists()
        else build_executive_html(listings, changes)
    )

    send_report(
        client_email,
        os.environ.get("REPORT_TO_EMAIL", ""),
        html,
        doc_url=doc_url,
        sheet_url=sheet_url,
    )


if __name__ == "__main__":
    run()
