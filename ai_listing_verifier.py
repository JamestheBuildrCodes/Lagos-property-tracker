"""Source-evidence validation for scraped property listings.

Default mode is deterministic and free. An optional Groq second pass can only
send deterministic passes to review; it can never override a failed deterministic
check. This is a consistency check, not proof of ownership or a deal.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any

import requests


_CURRENCY_AMOUNT = re.compile(r"(?:₦|NGN\b|(?<!\w)N)\s*([\d][\d,]*(?:\.\d+)?)", re.I)
_UNIT_PRICE = re.compile(
    r"(?:₦|NGN\b|(?<!\w)N)\s*([\d][\d,]*(?:\.\d+)?)\s*(?:/|per)\s*"
    r"(?:sq\.?\s*m|sqm|square\s*met(?:re|er))\b", re.I,
)
_SIZE = re.compile(
    r"([\d,.]+)\s*(?:sqm|sq\.?\s*m|m²|m2)\b|"
    r"([\d,.]+)\s+square\s+met(?:re|er)s?\b", re.I,
)
_BEDROOM = re.compile(r"\b([1-5])[\s-]*(?:bedroom|bedrooms|bed)\b", re.I)
_BEDROOM_WORD = re.compile(
    r"\b(one|two|three|four|five)[ -]bed(?:room)?s?\b", re.I,
)
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "None"):
            return None
        return float(re.sub(r"[^\d.]", "", str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _numbers(pattern: re.Pattern, text: str, group: int = 1) -> list[float]:
    values = []
    for match in pattern.finditer(text or ""):
        value = _number(match.group(group))
        if value is not None and value > 0:
            values.append(value)
    return values


def _close(a: float, b: float, tolerance: float = 0.02) -> bool:
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=1.0)


def _transaction_expected(row: dict) -> str | None:
    transaction = str(row.get("transaction") or "").strip().lower()
    if "rent" in transaction or "let" in transaction:
        return "rent"
    if "sale" in transaction:
        return "sale"
    return None


def deterministic_verify_row(row: dict) -> dict:
    """Check price, transaction, bedroom and land-size evidence without an LLM."""
    issues: list[str] = []
    excerpt = str(row.get("source_excerpt") or "").strip()
    url = str(row.get("source_url") or row.get("listing_url") or "").strip()
    title = str(row.get("title") or "")
    evidence = f"{title} {excerpt}".strip()
    lower = evidence.lower()
    path = url.lower().split("?", 1)[0]

    if not excerpt:
        return {"status": "review", "issues": ["No captured source-card excerpt; cannot independently check extracted values"], "method": "deterministic"}
    if not url.startswith(("https://", "http://")):
        issues.append("Missing or non-HTTP source URL")
    if "propertypro.ng/agent/" in url.lower():
        issues.append("Source URL is an agent/profile page, not a listing detail page")

    expected_tx = _transaction_expected(row)
    url_sale = bool(re.search(r"(?:^|[/_-])for[-_]?sale(?:$|[/_-])", path))
    url_rent = bool(re.search(r"(?:^|[/_-])(?:for[-_]?rent|to[-_]?rent|for[-_]?let|to[-_]?let)(?:$|[/_-])", path))
    text_sale = bool(re.search(r"\b(?:for\s+sale|available\s+for\s+sale|sale\s+listing)\b", lower))
    text_rent = bool(re.search(r"\b(?:for\s+rent|to\s+let|for\s+let|available\s+to\s+let|annual\s+rent|rent\s+per\s+(?:annum|year))\b", lower))
    if (url_sale and url_rent) or (text_sale and text_rent):
        issues.append("Conflicting sale and rental markers in listing evidence")
    elif expected_tx == "rent" and (url_sale or text_sale):
        issues.append("Rental record conflicts with sale evidence in URL/card text")
    elif expected_tx == "sale" and (url_rent or text_rent):
        issues.append("Sale record conflicts with rental evidence in URL/card text")
    elif expected_tx == "rent" and not (url_rent or text_rent):
        issues.append("No clear rental evidence in URL/card text")
    elif expected_tx == "sale" and not (url_sale or text_sale):
        issues.append("No clear sale evidence in URL/card text")

    property_type = str(row.get("property_type") or "").lower()
    is_land = "land" in property_type or "land" in str(row.get("transaction") or "").lower()
    if is_land and re.search(r"\b(?:bedroom|bedrooms|flat|apartment)\b", lower):
        issues.append("Land record contains apartment/bedroom evidence")
    if not is_land and property_type in {"flat_apartment", "apartment", "flat"}:
        if re.search(r"\b(?:plot of land|vacant land|residential land|land for sale)\b", lower):
            issues.append("Apartment record contains land-listing evidence")

    expected_price = _number(row.get("asking_price_ngn"))
    currency_amounts = _numbers(_CURRENCY_AMOUNT, excerpt)
    unit_prices = _numbers(_UNIT_PRICE, excerpt)
    size = _number(row.get("size_sqm"))
    if expected_price is None or expected_price <= 0:
        issues.append("No valid extracted asking price")
    elif not currency_amounts:
        issues.append("No explicit currency asking-price evidence in captured card text")
    else:
        direct_match = any(_close(expected_price, amount) for amount in currency_amounts)
        total_from_unit_rate = (
            size is not None and size > 0
            and any(_close(expected_price, unit_rate * size, tolerance=0.03) for unit_rate in unit_prices)
        )
        if not direct_match and not (is_land and total_from_unit_rate):
            issues.append("Extracted asking price does not match any source-card currency amount or land unit-price × area")

    if not is_land and property_type in {"flat_apartment", "apartment", "flat"}:
        expected_bedrooms = _number(row.get("bedrooms"))
        found_bedrooms = [int(n) for n in _numbers(_BEDROOM, excerpt)]
        found_bedrooms.extend(_WORD_NUMBERS[m.group(1).lower()] for m in _BEDROOM_WORD.finditer(excerpt))
        if expected_bedrooms is not None and int(expected_bedrooms) not in found_bedrooms:
            issues.append("Extracted bedroom count is not evidenced in captured card text")
        elif expected_bedrooms is None and not found_bedrooms:
            issues.append("Bedroom count is missing from both extracted fields and card evidence")

    if is_land:
        sizes = _numbers(_SIZE, excerpt, group=1)
        # The size regex has alternative capture groups; include values captured
        # by either side of the alternation.
        sizes.extend(
            n for n in _numbers(_SIZE, excerpt, group=2)
            if not any(_close(n, prior, tolerance=0.001) for prior in sizes)
        )
        if size is not None and size > 0:
            if not sizes:
                issues.append("Extracted plot size is not evidenced in captured card text")
            elif not any(_close(size, visible, tolerance=0.01) for visible in sizes):
                issues.append("Extracted plot size conflicts with the size stated in captured card text")

    # Reject clearly implausible/non-finite numeric values instead of allowing
    # corrupt values to flow into medians and price-per-square-metre estimates.
    for field in ("asking_price_ngn", "size_sqm", "price_per_sqm_ngn"):
        value = _number(row.get(field))
        if value is not None and (not math.isfinite(value) or value <= 0):
            issues.append(f"{field} is not a positive finite value")

    return {
        "status": "pass" if not issues else "review",
        "issues": issues[:8],
        "method": "deterministic",
    }


def _safe_excerpt(value: str) -> str:
    value = re.sub(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[redacted-email]", value or "")
    value = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "[redacted-phone]", value)
    return value[:1200]


def _groq_verify_rows(rows: list[dict], chunk_size: int = 20) -> dict[str, dict]:
    """Optional Groq OpenAI-compatible JSON pass; callers must tolerate quota failures."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
    results: dict[str, dict] = {}
    eligible_rows = [row for row in rows if str(row.get("source_excerpt") or "").strip()]
    for start in range(0, len(eligible_rows), chunk_size):
        chunk = eligible_rows[start:start + chunk_size]
        payload_rows = [{
            "record_id": str(row.get("record_id") or ""),
            "source_card_text": _safe_excerpt(str(row.get("source_excerpt") or "")),
            "extracted": {key: row.get(key) for key in (
                "market_node", "transaction", "property_type", "bedrooms",
                "asking_price_ngn", "size_sqm", "price_per_sqm_ngn", "listing_date",
            )},
        } for row in chunk]
        instructions = (
            "Cross-check extracted property-listing fields only against the supplied public listing-card text. "
            "Do not invent values. Mark pass only if asking price, transaction, bedroom count, property type, "
            "and any stated plot size agree. Ambiguous or contradictory evidence must be review. "
            "Return a valid JSON object with a results array containing every record_id exactly once."
        )
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": "Validate the following JSON listing data and return a JSON object of results:\n" + json.dumps(payload_rows, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=(10, 60),
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Groq API HTTP {response.status_code}: {response.text[:400]}")
        choices = response.json().get("choices") or []
        if not choices or not isinstance(choices[0].get("message", {}).get("content"), str):
            raise ValueError("Groq response contains no assistant JSON content")
        parsed = json.loads(choices[0]["message"]["content"])
        returned = parsed.get("results")
        if not isinstance(returned, list):
            raise ValueError("Groq verification response lacks results array")
        expected_ids = {str(row.get("record_id") or "") for row in chunk}
        seen = set()
        for item in returned:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("record_id") or "")
            if rid not in expected_ids or rid in seen:
                continue
            seen.add(rid)
            issues = item.get("issues") if isinstance(item.get("issues"), list) else []
            status = str(item.get("status") or "").lower()
            if status != "pass" or issues:
                status = "review"
            results[rid] = {"status": status, "issues": [str(issue)[:300] for issue in issues[:6]], "method": "groq"}
        for rid in expected_ids - seen:
            results[rid] = {"status": "review", "issues": ["Groq response omitted this record; unable to verify"], "method": "groq"}
    return results


def verify_rows(rows: list[dict], chunk_size: int = 20) -> dict[str, dict]:
    """Return results from deterministic evidence checks; AI is opt-in and non-blocking."""
    results = {str(row.get("record_id") or ""): deterministic_verify_row(row) for row in rows}
    mode = os.environ.get("EVIDENCE_VERIFICATION_MODE", "deterministic").strip().lower()
    if mode != "groq":
        return results
    # Only send deterministic passes to the optional model for a second opinion.
    # Missing/conflicting source evidence is already quarantined without API use.
    eligible = [
        row for row in rows
        if results.get(str(row.get("record_id") or ""), {}).get("status") == "pass"
    ]
    if not eligible:
        return results
    try:
        ai_results = _groq_verify_rows(eligible, chunk_size=chunk_size)
    except Exception as exc:
        print(f"[Evidence verifier] Optional {mode} pass unavailable; keeping deterministic decisions: {type(exc).__name__}: {exc}")
        return results
    for row in eligible:
        rid = str(row.get("record_id") or "")
        deterministic = results.get(rid, {"status": "review", "issues": ["Missing deterministic result"]})
        ai = ai_results.get(rid)
        # Optional AI may send an evidence-passing row to review, but may never
        # override a deterministic failure into a pass.
        if ai and ai.get("status") != "pass":
            results[rid] = {
                "status": "review",
                "issues": list(deterministic.get("issues", [])) + list(ai.get("issues", ["Optional AI requested review"]))[:6],
                "method": f"deterministic+{mode}",
            }
        else:
            deterministic["method"] = f"deterministic+{mode}" if ai else "deterministic"
    return results
