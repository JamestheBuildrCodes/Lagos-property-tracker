"""Source-aware paid connectivity check for Zyte before the full market scan.

HTTP 520 is a temporary website-ban response. Zyte recommends retrying ban
responses, so preflight retries those responses before warning and continuing
with other approved sources.
"""
from __future__ import annotations

import os
import time
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
    last_detail = None

    for attempt in range(1, 4):
        try:
            r = requests.post(
                "https://api.zyte.com/v1/extract",
                auth=(key, ""),
                json={"url": url, "browserHtml": True},
                timeout=90,
            )
        except requests.RequestException as exc:
            last_detail = str(exc)
            if attempt < 3:
                time.sleep(3 * attempt)
                continue
            failures.append((source, last_detail))
            print(f"  WARNING: {source} preflight request failed: {last_detail}")
            break

        if r.status_code >= 400:
            detail = r.text[:500]
            if r.status_code in (401, 402, 403):
                raise SystemExit(
                    f"Zyte preflight authentication/account failure HTTP "
                    f"{r.status_code}: {detail}"
                )
            if r.status_code == 520 and (
                "Website Ban" in detail or "temporary-error" in detail
            ):
                last_detail = f"HTTP 520 Website Ban: {detail}"
                if attempt < 3:
                    wait = 3 * attempt
                    print(
                        f"  WARNING: {source} returned HTTP 520 Website Ban; "
                        f"retrying in {wait}s."
                    )
                    time.sleep(wait)
                    continue
                failures.append((source, last_detail))
                print(
                    f"  WARNING: {source} is currently banned by the target site "
                    "(HTTP 520) after 3 attempts. Skipping this preflight target."
                )
                break
            failures.append((source, f"HTTP {r.status_code}: {detail}"))
            print(
                f"  WARNING: {source} preflight failed: "
                f"HTTP {r.status_code}: {detail}"
            )
            break

        try:
            body = r.json()
        except ValueError:
            failures.append((source, "Zyte returned non-JSON response"))
            print(f"  WARNING: {source} preflight returned non-JSON response.")
            break

        html = body.get("browserHtml") or body.get("httpResponseBody")
        if not html:
            failures.append((source, "Zyte returned no HTML"))
            print(f"  WARNING: {source} preflight returned no HTML.")
            break

        successes.append(source)
        print(f"  OK: {len(html)} HTML characters")
        break

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
