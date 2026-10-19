"""Audit Knight Frank Nigeria's public research page without bypassing gated downloads.

The public landing page is always recorded in a machine-readable source audit.
The report PDF is not downloaded through forms, credentials, or other access controls.
No listing-level prices are inferred from a research landing page.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

URL = "https://www.knightfrank.com.ng/research/lagos-market-update-13035.aspx"
OUT = Path("knight_frank_research_status.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NigeriaPropertyMarketResearch/1.0)"}


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "source": "Knight Frank Nigeria",
        "official_page": URL,
        "source_type": "Institutional market research",
        "checked_at_utc": now,
        "http_status": None,
        "page_title": "",
        "latest_publication": "Lagos Market Update H1 2026",
        "public_page_reachable": False,
        "download_access": "gated_or_form-mediated",
        "listing_feed": False,
        "comparable_listing_rows": 0,
        "published_figures_extracted": [],
        "assessment": "",
        "limitations": "",
        "status": "not_checked",
    }
    try:
        response = requests.get(URL, headers=HEADERS, timeout=30)
        result["http_status"] = response.status_code
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        result["page_title"] = (soup.title.get_text(" ", strip=True) if soup.title else "")
        visible_text = re.sub(r"\\s+", " ", soup.get_text(" ", strip=True))
        result["public_page_reachable"] = True
        result["status"] = "public_landing_page_reachable"
        if re.search(r"Lagos Market Update.{0,80}H1 2026", visible_text, re.I):
            result["latest_publication"] = "Lagos Market Update H1 2026"
        else:
            result["latest_publication"] = "Latest publication could not be confirmed from visible page text"
        pdf_links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(URL, a["href"])
            label = a.get_text(" ", strip=True)
            if urlparse(href).path.lower().endswith(".pdf") and "knightfrank" in urlparse(href).netloc.lower():
                pdf_links.append({"label": label or "PDF", "url": href})
        result["public_pdf_links"] = pdf_links
        if re.search(r"first name|email address|download", visible_text, re.I) and not pdf_links:
            result["download_access"] = "landing page requires contact form; no direct public PDF link exposed"
        elif pdf_links:
            result["download_access"] = "direct public PDF link exposed"
        result["assessment"] = (
            "Knight Frank is checked as a research/context source and its current public page status is recorded. "
            "The landing page is not a live listing feed, so it must not be counted as comparable listing rows."
        )
        result["limitations"] = (
            "Do not submit contact forms, bypass access controls, or treat market-level research as live listing prices. "
            "Any report figures must be extracted from a legally accessible publication and stored separately with period, unit, geography, and source page."
        )
    except Exception as exc:
        result["status"] = "fetch_failed"
        result["assessment"] = "The official Knight Frank page could not be fetched in this run; no data was inferred."
        result["limitations"] = f"{type(exc).__name__}: {exc}"
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # A failed third-party research page is recorded, not allowed to erase valid listing data.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
