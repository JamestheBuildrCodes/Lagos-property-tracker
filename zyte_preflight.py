"""Source-aware paid connectivity check for Zyte before the full market scan.

A Website Ban (HTTP 520) is source-specific, not proof that Zyte credentials
are broken. Warn and continue if another approved source is reachable; fail
only when no configured source can be checked successfully.
"""
from __future__ import annotations

import os
import sys
import requests

URLS = [
    ("PropertyPro.ng", "https://propertypro.ng/property-for-sale/in/lagos/lekki/lekki-phase-1"),
    ("Estate Intel", "https://estateintel.com/insights/lekki-phase-1-residential-market-overview"),
]

key = os.environ.get("ZYTE_API_KEY", "").strip()
if not key:
    raise SystemExit("ZYTE_API_KEY is missing")

successes = []
failures = []
for source, url in URLS:
    print(f"[Zyte preflight] {source}: {url}")
    try:
        r = requests.post(
            "https://api.zyte.com/v1/extract",
            auth=(key, ""),
            json={"url": url, "browserHtml": True},
            timeout=90,
        )
    except requests.RequestException as exc:
        failures.append((source, str(exc)))
        print(f"  WARNING: {source} preflight request failed: {exc}")
        continue

    if r.status_code >= 400:
        detail = r.text[:500]
        # Zyte's 520 Website Ban means this target is blocked at present;
        # it must not prevent collection from other approved sources.
        if r.status_code == 520 and ("Website Ban" in detail or "temporary-error" in detail):
            failures.append((source, f"HTTP 520 Website Ban: {detail}"))
            print(f"  WARNING: {source} is currently banned by the target site (HTTP 520). Skipping this preflight target.")
            continue
        if r.status_code in (401, 402, 403):
            raise SystemExit(f"Zyte preflight authentication/account failure HTTP {r.status_code}: {detail}")
        failures.append((source, f"HTTP {r.status_code}: {detail}"))
        print(f"  WARNING: {source} preflight failed: HTTP {r.status_code}: {detail}")
        continue

    try:
        body = r.json()
    except ValueError:
        failures.append((source, "Zyte returned non-JSON response"))
        print(f"  WARNING: {source} preflight returned non-JSON response.")
        continue
    html = body.get("browserHtml") or body.get("httpResponseBody")
    if not html:
        failures.append((source, "Zyte returned no HTML"))
        print(f"  WARNING: {source} preflight returned no HTML.")
        continue
    successes.append(source)
    print(f"  OK: {len(html)} HTML characters")

if not successes:
    print("Zyte preflight failed: no approved source returned usable HTML.")
    for source, reason in failures:
        print(f"  {source}: {reason}")
    raise SystemExit(1)

print("Zyte preflight passed for: " + ", ".join(successes))
if failures:
    print("Source-specific warnings (collection should continue for reachable sources):")
    for source, reason in failures:
        print(f"  {source}: {reason}")
