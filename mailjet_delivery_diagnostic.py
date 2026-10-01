"""Inspect recent Mailjet message records without running the property scraper."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

MAILJET_MESSAGE_URL = "https://api.mailjet.com/v3/REST/message"
TARGET_SUBJECTS = {
    "Lagos & Abuja Property Market — Weekly Intelligence Brief",
    "Your Weekly Lagos & Abuja Property Market Snapshot",
}


def _mask(value: str) -> str:
    if "@" not in value:
        return value or "(unknown)"
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _since() -> str:
    configured = os.environ.get("MAILJET_DIAGNOSTIC_SINCE", "").strip()
    if configured:
        return configured
    return (
        datetime.now(timezone.utc) - timedelta(hours=48)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    public = os.environ.get("MAILJET_API_KEY", "").strip()
    private = os.environ.get("MAILJET_SECRET_KEY", "").strip()
    if not public or not private:
        raise SystemExit(
            "MAILJET_API_KEY and MAILJET_SECRET_KEY are required"
        )

    params = {
        "FromTS": _since(),
        "ShowContactAlt": "true",
        "ShowSubject": "true",
        "Limit": "100",
    }

    response = requests.get(
        MAILJET_MESSAGE_URL,
        auth=(public, private),
        params=params,
        timeout=30,
    )

    if response.status_code >= 300:
        detail = response.text[:1000].replace("\n", " ")
        raise SystemExit(
            f"Mailjet message lookup failed ({response.status_code}): {detail}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SystemExit(
            "Mailjet message lookup returned invalid JSON"
        ) from exc

    messages = [
        item
        for item in data.get("Data", [])
        if item.get("Subject") in TARGET_SUBJECTS
    ]

    print(f"Mailjet diagnostic window: FromTS={params['FromTS']}")
    print(f"Relevant report messages found: {len(messages)}")

    for item in messages:
        message_id = item.get("ID", "unknown")
        detail = {}

        if message_id != "unknown":
            detail_response = requests.get(
                f"{MAILJET_MESSAGE_URL}information/{message_id}",
                auth=(public, private),
                timeout=30,
            )
            if detail_response.status_code < 300:
                try:
                    detail_data = detail_response.json()
                    rows = detail_data.get("Data", [])
                    if rows:
                        detail = rows[0]
                except ValueError:
                    pass

        print(
            "Message "
            f"ID={message_id} "
            f"status={item.get('Status', detail.get('Status', 'unknown'))} "
            f"state_id={detail.get('StateID', 'n/a')} "
            f"state={detail.get('State', 'n/a')} "
            f"recipient={_mask(item.get('ContactAlt', ''))} "
            f"arrived={item.get('ArrivedAt', 'unknown')} "
            f"subject={item.get('Subject', 'unknown')}"
        )

    if not messages:
        print(
            "No matching Mailjet message record was found in the "
            "diagnostic window. Check the Mailjet account, sender, "
            "recipient, and time window."
        )
        return 2

    print(
        "Note: a Mailjet message record proves processing/tracking; "
        "the status must be inspected for bounce, spam, blocked, or "
        "deferred states. Inbox placement is not guaranteed by API success."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
