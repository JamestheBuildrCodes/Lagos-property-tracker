"""Optional Groq interpretation with a deterministic, publication-safe fallback.

Only aggregate metrics are sent to Groq. Raw listings, URLs, agent contacts and
recipient addresses are never sent. Missing keys, rate limits and malformed
responses fall back to deterministic commentary instead of blocking reporting.
"""
from __future__ import annotations

import json
import os
from typing import Any

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b"


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


def _deterministic_commentary(summary: dict[str, Any]) -> dict[str, Any]:
    """Create report commentary from computed data without relying on an LLM."""
    try:
        listings = max(0, int(summary.get("listings_tracked") or 0))
    except (TypeError, ValueError):
        listings = 0
    try:
        areas = max(0, int(summary.get("areas_monitored") or 0))
    except (TypeError, ValueError):
        areas = 0
    source_names = [
        str(x).strip() for x in (summary.get("source_names") or [])
        if str(x).strip()
    ]
    scorecard = [
        x for x in (summary.get("scorecard") or [])
        if isinstance(x, dict) and int(x.get("listing_count") or 0) > 0
    ]
    scorecard.sort(
        key=lambda x: int(x.get("listing_count") or 0), reverse=True
    )
    analysis_notes = [
        str(x).strip() for x in (summary.get("analysis_notes") or [])
        if str(x).strip()
    ]
    populated_areas = len(scorecard)

    if listings:
        takeaway = (
            f"The scan contains {listings:,} validated comparable asking-price "
            f"observations across {populated_areas} of {areas or populated_areas} "
            "monitored areas. These are advertised asking prices, not confirmed "
            "completed transactions."
        )
    else:
        takeaway = (
            "The scan contains no validated comparable listings. It is not "
            "possible to draw a reliable current pricing conclusion from this run."
        )

    findings = analysis_notes[:5]
    if not findings:
        findings = [
            f"Validated comparable listings in this run: {listings:,}.",
            f"Areas with usable comparable observations: {populated_areas}.",
        ]

    implications = []
    if scorecard:
        leaders = ", ".join(
            f"{x.get('market_node', 'Unspecified area')} "
            f"({int(x.get('listing_count') or 0)} listings)"
            for x in scorecard[:3]
        )
        implications.append(
            "The largest observed samples are in " + leaders +
            "; comparisons in these areas have more listing coverage than "
            "areas with smaller samples."
        )
    if populated_areas < areas:
        implications.append(
            f"{areas - populated_areas} monitored area(s) have no usable "
            "comparable observations in this scan; do not infer their prices."
        )
    if not implications:
        implications.append(
            "Treat the available scan as a monitoring input, not a complete "
            "market census or a substitute for property-level due diligence."
        )

    actions = [
        "Verify the live listing, asking price, property details and availability with the advertiser before relying on an individual observation.",
        "Treat segments with fewer than five comparable listings as thin evidence; avoid presenting them as stable market benchmarks.",
        "Continue consistent weekly collection to build a comparable history and distinguish short-term noise from directional movement.",
    ]
    if not listings:
        actions.insert(
            0,
            "Restore at least one approved listing source and rerun collection before issuing market-price conclusions.",
        )

    return {
        "model": "deterministic-rules",
        "commentary_mode": "deterministic",
        "executive_takeaway": takeaway[:900],
        "key_findings": findings,
        "business_implications": implications[:4],
        "recommended_actions": actions[:5],
        "limitations": [
            "All figures are advertised asking prices, not verified completed transaction prices.",
            "Observed listings are not a complete census of the market; sample sizes vary by area and category.",
            "A listing absent from a later scan is not proof that it was sold, withdrawn or rented.",
            "Rental yield figures are gross asking-price proxies, not net investment returns.",
            "Any trend is limited to the dates and snapshots actually present in the archive.",
        ],
    }


def interpret_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return Groq commentary when available; otherwise return deterministic analysis."""
    fallback = _deterministic_commentary(summary)
    enabled = os.environ.get(
        "GROQ_AI_COMMENTARY_ENABLED", "false"
    ).strip().lower() == "true"
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not enabled or not api_key:
        print(
            "[Market commentary] Groq is disabled or not configured; "
            "using deterministic report commentary."
        )
        return fallback

    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    instructions = (
        "Act as a cautious Nigerian property-market research analyst. Interpret only "
        "the aggregate JSON provided; do not invent events, causes, prices, comparables, "
        "or external facts. Monetary values are Nigerian naira. These are asking prices, "
        "not confirmed transactions or a complete market census. A missing URL means "
        "not observed this scan, not sold or withdrawn. Mention sample sizes and "
        "historical periods. Treat any segment with fewer than five comparables as thin "
        "evidence. The gross rent yield proxy is not net yield. If evidence is insufficient, "
        "say so. Return one JSON object with keys: executive_takeaway (string), "
        "key_findings (array of strings), business_implications (array of strings), "
        "recommended_actions (array of strings), limitations (array of strings)."
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": (
                    "Interpret this aggregate JSON and return only the required JSON object:\n"
                    + json.dumps(_safe_payload(summary), ensure_ascii=False)
                ),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 1400,
    }
    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=(10, 50),
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Groq API HTTP {response.status_code}")
        choices = response.json().get("choices") or []
        content = (
            choices[0].get("message", {}).get("content")
            if choices else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned no assistant JSON content")
        parsed = json.loads(content)
        expected = {
            "executive_takeaway": str,
            "key_findings": list,
            "business_implications": list,
            "recommended_actions": list,
            "limitations": list,
        }
        for key, kind in expected.items():
            if not isinstance(parsed.get(key), kind):
                raise ValueError(f"Invalid Groq response field: {key}")
        if not parsed["executive_takeaway"].strip():
            raise ValueError("Groq returned an empty executive takeaway")
        for key in ("key_findings", "recommended_actions"):
            if not any(str(item).strip() for item in parsed[key]):
                raise ValueError(f"Groq returned an empty {key} array")

        return {
            "model": model,
            "commentary_mode": "groq",
            "executive_takeaway": parsed["executive_takeaway"][:900],
            "key_findings": [str(x)[:400] for x in parsed["key_findings"][:5]],
            "business_implications": [
                str(x)[:400] for x in parsed["business_implications"][:4]
            ],
            "recommended_actions": [
                str(x)[:400] for x in parsed["recommended_actions"][:5]
            ],
            "limitations": [str(x)[:400] for x in parsed["limitations"][:6]],
        }
    except Exception as exc:
        # Rate limits, provider outages and malformed model output must not
        # prevent the deterministic reports from being created or delivered.
        print(
            "[Market commentary] Groq unavailable; using deterministic "
            f"commentary ({type(exc).__name__})."
        )
        return fallback
