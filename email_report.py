"""Send Layer 1 executive brief using Mailjet's transactional Send API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

from report_builder import build_executive_html

MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"


def _valid_email(value: str) -> bool:
    value = (value or "").strip()
    return "@" in value and " " not in value and "." in value.split("@", 1)[-1]


def _emails(*values: str) -> list[str]:
    raw = ",".join(value or "" for value in values)
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if _valid_email(item.strip())))


def send_report(client_email: str, cc_email: str, html_body: str) -> None:
    api_key = os.environ.get("MAILJET_API_KEY", "").strip()
    secret_key = os.environ.get("MAILJET_SECRET_KEY", "").strip()
    sender = os.environ.get("MAILJET_FROM_EMAIL", "").strip()
    sender_name = os.environ.get("MAILJET_FROM_NAME", "Master Builder").strip() or "Master Builder"

    if not api_key or not secret_key:
        raise RuntimeError("MAILJET_API_KEY and MAILJET_SECRET_KEY are required")
    if not _valid_email(sender):
        raise RuntimeError("MAILJET_FROM_EMAIL is missing or invalid; use an active Mailjet sender address")

    to = _emails(client_email)
    cc = _emails(cc_email)
    if not to:
        raise RuntimeError("REPORT_CLIENT_EMAIL is missing or invalid")

    # Do not send the same address in both To and Cc.
    cc = [address for address in cc if address.lower() not in {item.lower() for item in to}]

    message = {
        "From": {"Email": sender, "Name": sender_name},
        "To": [{"Email": address} for address in to],
        "Subject": "Lagos Property Market — Weekly Intelligence Brief",
        "HTMLPart": html_body,
        "CustomID": "lagos-property-market-weekly-intelligence",
    }
    if cc:
        message["Cc"] = [{"Email": address} for address in cc]

    response = requests.post(
        MAILJET_SEND_URL,
        auth=(api_key, secret_key),
        json={"Messages": [message]},
        timeout=30,
    )
    if response.status_code >= 300:
        detail = response.text[:1000].replace("\n", " ")
        raise RuntimeError(f"Mailjet send failed ({response.status_code}): {detail}")

    print("Executive brief sent to client: " + ", ".join(to))
    if cc:
        print("Executive brief CC: " + ", ".join(cc))


def run() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python email_report.py <listings.csv> [changes.csv] [client_email] [html_path]")

    listings = sys.argv[1]
    changes = sys.argv[2] if len(sys.argv) > 2 else "none"
    client_email = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("REPORT_CLIENT_EMAIL", "")
    html_path = sys.argv[4] if len(sys.argv) > 4 else ""

    html = (
        Path(html_path).read_text(encoding="utf-8")
        if html_path and Path(html_path).exists()
        else build_executive_html(listings, changes)
    )
    send_report(client_email, os.environ.get("REPORT_TO_EMAIL", ""), html)


if __name__ == "__main__":
    run()
