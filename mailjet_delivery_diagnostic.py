"""Inspect recent Mailjet message records without running the property scraper."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
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


def _receipt_paths():
    return [Path("mailjet_layer1_receipt.json"), Path("data/mailjet_layer1_receipt.json")]


def _inspect_receipt_message_ids(public: str, private: str) -> bool:
    """Inspect message IDs from the send receipt directly; list API can lag."""
    receipt = None
    for path in _receipt_paths():
        if not path.exists():
            continue
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            print(f"Using Mailjet send receipt: {path}")
            break
        except (OSError, json.JSONDecodeError):
            continue
    if not isinstance(receipt, dict):
        return False

    lookup = {}
    for result in receipt.get("message_results", []) or []:
        for recipient in result.get("recipients", []) or []:
            message_id = str(recipient.get("message_id") or "").strip()
            if message_id:
                lookup.setdefault(message_id, []).append(recipient)
    if not lookup:
        print("The send receipt contains no message IDs to inspect.")
        return False

    found_any = False
    for message_id, recipients in lookup.items():
        try:
            response = requests.get(
                f"{MAILJET_MESSAGE_URL}information/{message_id}",
                auth=(public, private),
                timeout=30,
            )
        except requests.RequestException as exc:
            print(f"Message detail lookup failed for ID={message_id}: {type(exc).__name__}")
            continue
        if response.status_code >= 300:
            print(f"Message detail lookup for ID={message_id} returned HTTP {response.status_code}.")
            continue
        try:
            payload = response.json()
        except ValueError:
            print(f"Message detail lookup for ID={message_id} returned invalid JSON.")
            continue
        rows = payload.get("Data", []) if isinstance(payload, dict) else []
        if not rows:
            print(f"Mailjet returned no detail record for message ID={message_id}.")
            continue
        found_any = True
        for item in rows:
            print(
                "Receipt-linked message "
                f"ID={message_id} "
                f"status={item.get('Status', 'unknown')} "
                f"state_id={item.get('StateID', 'n/a')} "
                f"state={item.get('State', 'n/a')} "
                f"recipient={_mask(item.get('ContactAlt', ''))} "
                f"arrived={item.get('ArrivedAt', 'unknown')} "
                f"subject={item.get('Subject', receipt.get('subject', 'unknown'))}"
            )
        for recipient in recipients:
            print(
                f"Receipt recipient: field={recipient.get('field', 'unknown')} "
                f"email={_mask(str(recipient.get('email') or ''))}"
            )

    return found_any


def main() -> int:
    public = os.environ.get("MAILJET_API_KEY", "").strip()
    private = os.environ.get("MAILJET_SECRET_KEY", "").strip()
    if not public or not private:
        raise SystemExit(
            "MAILJET_API_KEY and MAILJET_SECRET_KEY are required"
        )

    if _inspect_receipt_message_ids(public, private):
        print("Direct receipt-linked lookup completed. Inspect each message state for delivery, bounce, blocked, or deferred status.")
        return 0

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
            "No matching Mailjet message record was found in the diagnostic window. "
            "This diagnostic is not authoritative for the current send; the workflow's "
            "message-level Mailjet receipt is the delivery-attempt source of truth. "
            "Check Mailjet's dashboard if recipient delivery state needs confirmation."
        )
        return 0

    print(
        "Note: a Mailjet message record proves processing/tracking; "
        "the status must be inspected for bounce, spam, blocked, or "
        "deferred states. Inbox placement is not guaranteed by API success."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
