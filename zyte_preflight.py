"""Small paid connectivity check for Zyte before the full market scan."""
from __future__ import annotations

import os
import sys
import requests

URLS = [
    "https://propertypro.ng/property-for-sale/in/lagos/lekki/lekki-phase-1",
    "https://estateintel.com/insights/lekki-phase-1-residential-market-overview",
]

key = os.environ.get("ZYTE_API_KEY", "").strip()
if not key:
    raise SystemExit("ZYTE_API_KEY is missing")

for url in URLS:
    print(f"[Zyte preflight] {url}")
    r = requests.post(
        "https://api.zyte.com/v1/extract",
        auth=(key, ""),
        json={"url": url, "browserHtml": True},
        timeout=90,
    )
    if r.status_code >= 400:
        raise SystemExit(f"Zyte preflight failed: HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    html = body.get("browserHtml") or body.get("httpResponseBody")
    if not html:
        raise SystemExit("Zyte preflight failed: no HTML returned")
    print(f"  OK: {len(html)} HTML characters")

print("Zyte preflight passed for PropertyPro and Estate Intel.")
