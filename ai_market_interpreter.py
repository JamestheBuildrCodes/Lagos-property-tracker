"""Optional evidence-constrained AI interpretation of aggregate property metrics.

Only aggregate statistics are sent to the model. Individual listing URLs,
agent contacts, recipient addresses and raw scraped rows are not submitted.
If the API key is absent or the API fails, the deterministic report continues.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-6-luna"


def _response_text(payload: dict[str, Any]) -> str:
    chunks = []
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                chunks.append(part["text"])
    if not chunks:
        raise ValueError("No output_text was returned by the Responses API")
    return "\n".join(chunks)


def _safe_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """Whitelist aggregate values; never send raw listings or source URLs."""
    changes = summary.get("changes", {}) or {}
    scorecard = []
    for row in summary.get("scorecard", []) or []:
        scorecard.append({
            "area": row.get("market_node"),
            "listing_count": row.get("listing_count"),
            "sale_3br_median_ngn": row.get("sale_3br_median"),
            "rent_3br_median_ngn": row.get("rent_3br_median"),
            "land_median_ngn_per_sqm": row.get("land_ppsqm_median"),
            "gross_rent_yield_proxy_pct": row.get("gross_rent_yield_proxy_pct"),
            "sale_sample_count": row.get("sale_count"),
            "rent_sample_count": row.get("rent_count"),
            "land_sample_count": row.get("land_count"),
        })
    trends = {}
    for area, trend in (summary.get("trends", {}) or {}).items():
        trends[area] = {key: trend.get(key) for key in (
            "from_date", "to_date", "period_days", "full_six_month",
            "sale_pct", "rent_pct", "land_ppsqm_pct", "snapshots",
        )}
    return {
        "listings_tracked": summary.get("listings_tracked"),
        "areas_monitored": summary.get("areas_monitored"),
        "source_count": summary.get("sources"),
        "source_names": summary.get("source_names", []),
        "median_apartment_sale_ngn": summary.get("median_apartment_sale"),
        "median_annual_rent_ngn": summary.get("median_annual_rent"),
        "median_land_ngn_per_sqm": summary.get("median_land_ppsqm"),
        "changes": {
            "new_listings": changes.get("new_listings", 0),
            "price_reductions": changes.get("price_reductions", 0),
            "price_increases": changes.get("price_increases", 0),
            "not_observed_in_current_scan": changes.get(
                "not_observed", changes.get("delisted", 0)
            ),
        },
        "scorecard": scorecard,
        "historical_trends": trends,
        "limitations": [
            "Prices are online asking prices, not confirmed transaction prices.",
            "Sample sizes may be small and source inventories can change.",
            "A missing URL is not proof of sale or withdrawal.",
            "The gross yield proxy is not net yield.",
        ],
    }


def interpret_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    instructions = (
        "Act as a cautious Nigerian property-market research analyst. Interpret only "
        "the aggregate JSON provided; do not invent events, causes, prices, comps, or "
        "external facts. Monetary values are Nigerian naira. These are asking prices, "
        "not confirmed transactions or a complete census of Lagos/Abuja. A missing URL "
        "means 'not observed this scan', not sold/withdrawn. Mention sample sizes and "
        "historical periods. Treat any segment with fewer than five comparables as thin "
        "evidence. The gross rent yield proxy is not net yield. If the evidence cannot "
        "support a conclusion, say so. Return one JSON object with keys: "
        "executive_takeaway (string), key_findings (array of strings), "
        "business_implications (array of strings), recommended_actions (array of strings), "
        "limitations (array of strings). Keep advice concrete and decision-useful for a "
        "property acquisition, investment, leasing, or research team."
    )
    body = {
        "model": model,
        "instructions": instructions,
        "input": json.dumps(_safe_payload(summary), ensure_ascii=False),
        "max_output_tokens": 1400,
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
            timeout=(10, 50),
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"Responses API HTTP {response.status_code}: {response.text[:400]}"
            )
        parsed = json.loads(_response_text(response.json()))
        expected = {
            "executive_takeaway": str,
            "key_findings": list,
            "business_implications": list,
            "recommended_actions": list,
            "limitations": list,
        }
        for key, kind in expected.items():
            if not isinstance(parsed.get(key), kind):
                raise ValueError(f"Invalid AI response field: {key}")
        return {
            "model": model,
            "executive_takeaway": parsed["executive_takeaway"][:900],
            "key_findings": [str(x)[:400] for x in parsed["key_findings"][:5]],
            "business_implications": [str(x)[:400] for x in parsed["business_implications"][:4]],
            "recommended_actions": [str(x)[:400] for x in parsed["recommended_actions"][:5]],
            "limitations": [str(x)[:400] for x in parsed["limitations"][:6]],
        }
    except Exception as exc:
        print(f"[AI analysis unavailable; using deterministic narrative] {type(exc).__name__}: {exc}")
        return None
