"""Shared Mailjet transactional sender with auditable API receipts.

The Mailjet Send API can return HTTP 200 even when the application has not
yet checked the message-level result. This module treats the documented
Send API response as part of the success contract and records Mailjet IDs so
the downstream delivery state can be audited later.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"


def valid_email(value: str) -> bool:
    value = (value or "").strip()
    if not value or " " in value or value.count("@") != 1:
        return False
    domain = value.split("@", 1)[1]
    return bool(domain and "." in domain)


def recipients_from_values(*values: str) -> list[str]:
    raw = ",".join(value or "" for value in values)
    return list(
        dict.fromkeys(
            item.strip()
            for item in raw.split(",")
            if valid_email(item.strip())
        )
    )


def _mask_email(value: str) -> str:
    local, domain = value.split("@", 1)
    if len(local) <= 1:
        masked = "*"
    elif len(local) == 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "***"
    return f"{masked}@{domain}"


def _custom_id(layer: str) -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip() or "local"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"lagos-property-{layer}-{run_id}-{stamp}"


def _mailjet_error(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:1000].replace("\n", " ")

    errors = body.get("Errors") if isinstance(body, dict) else None
    if isinstance(errors, list):
        messages = [
            str(item.get("ErrorMessage", "")).strip()
            for item in errors
            if isinstance(item, dict) and item.get("ErrorMessage")
        ]
        if messages:
            return "; ".join(messages)[:1000]

    if isinstance(body, dict) and body.get("ErrorMessage"):
        return str(body["ErrorMessage"])[:1000]

    return json.dumps(body, ensure_ascii=False)[:1000]


def _message_result_details(data: object) -> tuple[list[dict], list[str]]:
    if not isinstance(data, dict):
        return [], ["Mailjet returned a non-object JSON response"]

    messages = data.get("Messages")
    if not isinstance(messages, list) or not messages:
        return [], ["Mailjet response contained no Messages result"]

    details: list[dict] = []
    failures: list[str] = []

    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            failures.append(f"message {index} result is not an object")
            continue

        status = str(message.get("Status", "")).strip().lower()
        if status != "success":
            errors = message.get("Errors") or []
            error_text = "; ".join(
                str(item.get("ErrorMessage", "")).strip()
                for item in errors
                if isinstance(item, dict) and item.get("ErrorMessage")
            ).strip()
            failures.append(
                f"message {index} status={status or 'missing'}"
                + (f": {error_text[:500]}" if error_text else "")
            )

        recipients: list[dict] = []
        for field in ("To", "Cc", "Bcc"):
            for item in message.get(field, []) or []:
                if isinstance(item, dict):
                    recipients.append(
                        {
                            "field": field,
                            "email": item.get("Email", ""),
                            "message_id": item.get("MessageID"),
                            "message_uuid": item.get("MessageUUID"),
                        }
                    )

        if not recipients:
            failures.append(f"message {index} returned no recipient metadata")
            continue

        for item in recipients:
            if item["message_id"] in (None, "") and not item["message_uuid"]:
                failures.append(
                    f"recipient metadata missing MessageID/MessageUUID for "
                    f"{_mask_email(item['email']) if valid_email(item['email']) else 'unknown recipient'}"
                )

        details.append(
            {
                "status": status,
                "recipients": [
                    {
                        **item,
                        "email": _mask_email(item["email"])
                        if valid_email(item["email"])
                        else "invalid",
                    }
                    for item in recipients
                ],
            }
        )

    return details, failures


def send_message(
    *,
    to: Iterable[str],
    subject: str,
    html_body: str,
    text_body: str,
    layer: str,
    cc: Iterable[str] = (),
) -> dict:
    api_key = os.environ.get("MAILJET_API_KEY", "").strip()
    secret_key = os.environ.get("MAILJET_SECRET_KEY", "").strip()
    sender = os.environ.get("MAILJET_FROM_EMAIL", "").strip()
    sender_name = (
        os.environ.get("MAILJET_FROM_NAME", "Master Builder").strip()
        or "Master Builder"
    )

    if not api_key or not secret_key:
        raise RuntimeError(
            "MAILJET_API_KEY and MAILJET_SECRET_KEY are required"
        )

    if not valid_email(sender):
        raise RuntimeError(
            "MAILJET_FROM_EMAIL is missing or invalid; use an active "
            "Mailjet sender address"
        )

    to_list = recipients_from_values(*list(to))
    cc_list = recipients_from_values(*list(cc))
    cc_list = [
        address
        for address in cc_list
        if address.lower() not in {item.lower() for item in to_list}
    ]

    if not to_list:
        raise RuntimeError("No valid Mailjet recipient was supplied")

    custom_id = _custom_id(layer)

    message = {
        "From": {"Email": sender, "Name": sender_name},
        "To": [{"Email": address} for address in to_list],
        "Subject": subject,
        "TextPart": text_body,
        "HTMLPart": html_body,
        "CustomID": custom_id,
    }

    if cc_list:
        message["Cc"] = [{"Email": address} for address in cc_list]

    response = requests.post(
        MAILJET_SEND_URL,
        auth=(api_key, secret_key),
        json={"Messages": [message]},
        timeout=30,
    )

    if response.status_code >= 300:
        raise RuntimeError(
            f"Mailjet send failed ({response.status_code}): "
            f"{_mailjet_error(response)}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Mailjet returned HTTP success but no valid JSON response; "
            "the send cannot be treated as auditable."
        ) from exc

    details, failures = _message_result_details(data)
    if failures:
        raise RuntimeError(
            "Mailjet did not return a fully successful message result: "
            + "; ".join(failures)
        )

    receipt = {
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code,
        "custom_id": custom_id,
        "subject": subject,
        "layer": layer,
        "message_results": details,
    }

    receipt_path = Path(f"mailjet_{layer}_receipt.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    ids = []
    uuids = []
    for result in details:
        for recipient in result["recipients"]:
            if recipient.get("message_id") not in (None, ""):
                ids.append(str(recipient["message_id"]))
            if recipient.get("message_uuid"):
                uuids.append(str(recipient["message_uuid"]))

    masked_to = ", ".join(_mask_email(address) for address in to_list)
    print(
        f"Mailjet accepted {layer} email: HTTP {response.status_code}; "
        f"status=success; to={masked_to}; "
        f"MessageID(s)={','.join(dict.fromkeys(ids))}; "
        f"MessageUUID(s)={','.join(dict.fromkeys(uuids))}; "
        f"receipt={receipt_path}"
    )
    return receipt
