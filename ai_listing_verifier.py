"""Evidence-constrained AI cross-check of extracted property listing cards.

This is a second-pass consistency check, not proof of legal ownership or a
closed transaction. Rows that cannot be checked against their captured public
listing-card text are quarantined instead of being silently treated as verified.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-mini"


def _text(payload: dict[str, Any]) -> str:
    parts = []
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                parts.append(part["text"])
    if not parts:
        raise ValueError("OpenAI returned no output_text")
    return "\n".join(parts)


def _safe_excerpt(value: str) -> str:
    # Listing-card text is public source content. Strip email addresses and
    # long phone-like sequences before sending it for extraction consistency.
    value = re.sub(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[redacted-email]", value or "")
    value = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "[redacted-phone]", value)
    return value[:1200]


def verify_rows(rows: list[dict], chunk_size: int = 20) -> dict[str, dict]:
    """Return record_id -> {status, issues}; raises if required AI verification fails."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    required = os.environ.get("OPENAI_REQUIRED", "false").strip().lower() == "true"
    if not api_key:
        if required:
            raise RuntimeError("OPENAI_REQUIRED=true but OPENAI_API_KEY is missing")
        return {
            str(row.get("record_id") or ""): {
                "status": "review",
                "issues": ["AI cross-check unavailable; no API key configured"],
            }
            for row in rows
        }

    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    results: dict[str, dict] = {}
    eligible_rows = []
    for row in rows:
        rid = str(row.get("record_id") or "")
        if not str(row.get("source_excerpt") or "").strip():
            results[rid] = {
                "status": "review",
                "issues": ["No captured source-card excerpt available to cross-check"],
            }
        else:
            eligible_rows.append(row)

    for start in range(0, len(eligible_rows), chunk_size):
        chunk = eligible_rows[start : start + chunk_size]
        payload_rows = []
        for row in chunk:
            rid = str(row.get("record_id") or "")
            excerpt = _safe_excerpt(str(row.get("source_excerpt") or ""))
            payload_rows.append({
                "record_id": rid,
                "source_card_text": excerpt,
                "extracted": {
                    "market_node": row.get("market_node"),
                    "transaction": row.get("transaction"),
                    "property_type": row.get("property_type"),
                    "bedrooms": row.get("bedrooms"),
                    "asking_price_ngn": row.get("asking_price_ngn"),
                    "size_sqm": row.get("size_sqm"),
                    "price_per_sqm_ngn": row.get("price_per_sqm_ngn"),
                    "listing_date": row.get("listing_date"),
                },
            })

        instructions = (
            "Cross-check extracted property-listing fields ONLY against the supplied "
            "public listing-card text. Do not use general market knowledge and do not "
            "invent missing values. Mark pass only if the displayed asking price and "
            "any displayed bedroom count/plot size do not contradict the extracted "
            "values, and the text clearly appears to describe the same transaction and "
            "property type. If price, unit, transaction type, or bedroom evidence is "
            "ambiguous, missing, or contradictory, mark review. Do not reject a record "
            "just because optional plot size is absent. A listing-card check is not "
            "proof of ownership or a closed deal. Return JSON object with a results "
            "array; each item has record_id, status (pass or review), issues (array of "
            "short evidence-based strings). Include every input record_id exactly once."
        )
        body = {
            "model": model,
            "instructions": instructions,
            "input": json.dumps(payload_rows, ensure_ascii=False),
            "max_output_tokens": max(1200, len(chunk) * 110),
            "store": False,
            "text": {"format": {"type": "json_object"}},
        }
        try:
            response = requests.post(
                RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=(10, 60),
            )
            if response.status_code >= 300:
                raise RuntimeError(
                    f"Responses API HTTP {response.status_code}: {response.text[:400]}"
                )
            parsed = json.loads(_text(response.json()))
            returned = parsed.get("results")
            if not isinstance(returned, list):
                raise ValueError("AI verification response lacks results array")
            expected_ids = {str(row.get("record_id") or "") for row in chunk}
            seen = set()
            for item in returned:
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("record_id") or "")
                if rid not in expected_ids or rid in seen:
                    continue
                seen.add(rid)
                status = str(item.get("status") or "").lower()
                issues = item.get("issues") if isinstance(item.get("issues"), list) else []
                if status != "pass":
                    status = "review"
                results[rid] = {
                    "status": status,
                    "issues": [str(issue)[:300] for issue in issues[:6]],
                }
            for rid in expected_ids - seen:
                results[rid] = {
                    "status": "review",
                    "issues": ["AI response omitted this record; unable to verify"],
                }
        except Exception as exc:
            if required:
                raise RuntimeError(
                    f"Required listing-level AI verification failed: {type(exc).__name__}: {exc}"
                ) from exc
            for row in chunk:
                rid = str(row.get("record_id") or "")
                results[rid] = {
                    "status": "review",
                    "issues": [f"AI verification unavailable: {type(exc).__name__}"],
                }

    # A blank excerpt is never treated as verified, even if the model says pass.
    for row in rows:
        rid = str(row.get("record_id") or "")
        if not str(row.get("source_excerpt") or "").strip():
            results[rid] = {
                "status": "review",
                "issues": ["No captured source-card excerpt available to cross-check"],
            }
    return results
