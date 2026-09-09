"""Production Nigeria property market collector.

The collector is manifest-driven and uses Zyte API only for protected-source collection. Manifest discovery never spends Zyte credits.

Key reliability rules:
- Never invent source URLs.
- One category page is enough to classify 1-5BR; no bedroom-specific URL calls.
- Parse listing cards from the category page first. Detail pages are optional
  and disabled by default to control cost/latency.
- Estate Intel is public research only; premium values are ignored.
- A failed category does not crash the entire run. The final report records
  source/category failures separately.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse, urlencode, parse_qsl

import requests
from bs4 import BeautifulSoup

ZYTE_ENDPOINT = "https://api.zyte.com/v1/extract"
ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY", "").strip()
MAX_LISTING_AGE_DAYS = int(os.environ.get("MAX_LISTING_AGE_DAYS", "31"))
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", "0.5"))
MAX_PAGES_PER_CATEGORY = int(os.environ.get("MAX_PAGES_PER_CATEGORY", "1"))
MAX_LISTINGS_PER_CATEGORY = int(os.environ.get("MAX_LISTINGS_PER_CATEGORY", "12"))
MAX_DETAIL_FETCHES_PER_CATEGORY = int(os.environ.get("MAX_DETAIL_FETCHES_PER_CATEGORY", "0"))
WORKERS = max(1, int(os.environ.get("SCRAPER_WORKERS", "3")))
ZYTE_TIMEOUT = int(os.environ.get("ZYTE_TIMEOUT_SECONDS", "90"))
ZYTE_BROWSER_HTML = os.environ.get("ZYTE_BROWSER_HTML", "true").lower() == "true"
PAID_SOURCE_FAILURE = threading.Event()
MANIFEST = Path("data/source_manifest.json")

FIELDNAMES = [
    "record_id", "date_scraped", "city", "market_node", "transaction",
    "property_type", "bedrooms", "title", "asking_price_ngn", "size_sqm",
    "price_per_sqm_ngn", "location", "listing_date", "listing_age_days",
    "listing_date_type", "is_within_31_days", "source", "source_url",
]
RESEARCH_FIELDS = [
    "date_scraped", "market", "market_node", "title", "url", "date_added",
    "last_updated", "location", "property_type", "size_units",
    "land_area_sqm", "public_sale_price_ngn", "notes",
]
ALLOWED_HOSTS = {
    "PropertyPro.ng": {"propertypro.ng", "www.propertypro.ng"},
    "Nigeria Property Centre": {"nigeriapropertycentre.com", "www.nigeriapropertycentre.com"},
    "Estate Intel": {"estateintel.com", "www.estateintel.com"},
}


def clean_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def canonical_url(url: str) -> str:
    p = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(query), ""))


def record_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def parse_number(value: str) -> Optional[float]:
    try:
        return float(re.sub(r"[^\d.]", "", value.replace(",", "")))
    except (ValueError, AttributeError):
        return None


def parse_naira(text: str) -> Optional[int]:
    m = re.search(r"₦\s*([\d,]+(?:\.\d+)?)", text or "")
    if not m:
        # Some cards use N rather than the naira symbol.
        m = re.search(r"\bN\s*([\d,]+(?:\.\d+)?)\b", text or "", re.I)
    n = parse_number(m.group(1)) if m else None
    return int(n) if n is not None else None


def parse_price_per_sqm(text: str) -> Optional[int]:
    m = re.search(r"(?:₦|N)\s*([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*(?:sq\.?\s*m|sqm|square\s*met(?:re|er))", text or "", re.I)
    n = parse_number(m.group(1)) if m else None
    return int(n) if n is not None else None


def parse_size_sqm(text: str) -> Optional[float]:
    for pattern in (
        r"([\d,.]+)\s*(?:sqm|sq\.?\s*m|m²|m2)\b",
        r"([\d,.]+)\s+square\s+met(?:re|er)s?\b",
    ):
        m = re.search(pattern, text or "", re.I)
        if m:
            n = parse_number(m.group(1))
            if n:
                return n
    return None


def parse_bedrooms(text: str) -> Optional[int]:
    m = re.search(r"\b([1-5])\s*(?:bedroom|bedrooms|bed)\b", text or "", re.I)
    return int(m.group(1)) if m else None


def parse_date(text: str) -> tuple[Optional[datetime], Optional[str]]:
    if not text:
        return None, None
    now = datetime.now(timezone.utc)
    t = clean_text(text)
    explicit = re.search(
        r"\b(Added|Updated|Posted|Listed)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        t, re.I,
    )
    if explicit:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(explicit.group(2), fmt).replace(tzinfo=timezone.utc), explicit.group(1).lower()
            except ValueError:
                pass
    relative = re.search(r"\b(\d+)\s+(day|days|week|weeks)\s+ago\b", t, re.I)
    if relative:
        n = int(relative.group(1))
        days = n if relative.group(2).lower().startswith("day") else n * 7
        return now - timedelta(days=days), "relative"
    if re.search(r"\btoday\b", t, re.I):
        return now, "relative"
    if re.search(r"\byesterday\b", t, re.I):
        return now - timedelta(days=1), "relative"
    return None, None


def calculate_price_per_sqm(price: Optional[int], size: Optional[float], explicit_ppsqm: Optional[int] = None) -> Optional[float]:
    if explicit_ppsqm:
        return float(explicit_ppsqm)
    return round(price / size, 2) if price is not None and size and size > 0 else None


def load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        raise RuntimeError("data/source_manifest.json is missing. Run: python discover_sources.py")
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    if not entries:
        raise RuntimeError("Source manifest is empty. Run: python discover_sources.py")
    allowed = set(payload.get("policy", {}).get("allowed_sources", []))
    approved = [e for e in entries if e.get("verified") is True and e.get("source") in allowed]
    if len(approved) != len(entries):
        raise RuntimeError("Manifest contains unapproved/unverified entries; refusing to scrape.")
    for e in approved:
        source = e["source"]
        url = e["url"]
        host = urlparse(url).netloc.lower()
        if host not in ALLOWED_HOSTS[source]:
            raise RuntimeError(f"Manifest URL host is not allowed for {source}: {url}")
        if source == "Estate Intel":
            lowered_url = url.lower()
            prohibited_url_tokens = (
                "premium",
                "login",
                "signin",
                "sign-in",
                "account",
                "register",
                "signup",
                "sign-up",
                "checkout",
                "subscription",
            )
            if any(token in lowered_url for token in prohibited_url_tokens):
                raise RuntimeError(
                    f"Estate Intel premium/login/account URL is prohibited: {url}"
                )
    return approved


def fetch_page(url: str, source: str) -> requests.Response:
    """Fetch a manifest URL using the cheapest valid transport.

    NPC is reachable directly from GitHub Actions, so it must never consume
    Zyte credits. PropertyPro and Estate Intel are Cloudflare-protected on the
    runner and use Zyte browser HTML. A Zyte billing/authorization failure is
    fail-fast and never retried.
    """
    host = urlparse(url).netloc.lower()
    if host not in ALLOWED_HOSTS[source]:
        raise ValueError(f"Manifest URL host is not allowed for {source}: {url}")

    if source == "Nigeria Property Centre":
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; LagosPropertyTracker/1.0)",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=30,
                allow_redirects=True,
            )
            if response.status_code >= 400:
                response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise RuntimeError(f"Nigeria Property Centre direct request failed: {exc}") from exc

    if not ZYTE_API_KEY:
        raise RuntimeError("ZYTE_API_KEY is missing")
    if PAID_SOURCE_FAILURE.is_set():
        raise RuntimeError("Zyte transport is unavailable after a previous billing/authorization failure; skipping further paid requests.")

    payload = {"url": url, "browserHtml": ZYTE_BROWSER_HTML}
    last_exc = None
    for attempt in range(1, 3):
        if PAID_SOURCE_FAILURE.is_set():
            raise RuntimeError("Zyte transport is unavailable after a previous billing/authorization failure; skipping further paid requests.")
        try:
            print(f"[Zyte] {source} attempt={attempt} url={url}")
            response = requests.post(
                ZYTE_ENDPOINT,
                auth=(ZYTE_API_KEY, ""),
                json=payload,
                timeout=ZYTE_TIMEOUT,
            )
            if response.status_code in (401, 402, 403):
                PAID_SOURCE_FAILURE.set()
                raise RuntimeError(
                    f"Zyte HTTP {response.status_code}: authorization/account access failed. "
                    "Check ZYTE_API_KEY and Zyte account credit/plan. "
                    "The scraper will not retry billing/authorization failures."
                )
            if 400 <= response.status_code < 500:
                raise RuntimeError(f"Zyte HTTP {response.status_code}: {response.text[:300]}")
            if response.status_code < 500:
                response.raise_for_status()
                body = response.json()
                html = body.get("browserHtml") or body.get("httpResponseBody")
                if not html:
                    raise RuntimeError("Zyte returned no browserHtml/httpResponseBody for the requested URL")
                wrapped = requests.Response()
                wrapped.status_code = response.status_code
                wrapped.url = url
                wrapped.headers = response.headers
                wrapped.encoding = "utf-8"
                wrapped._content = html.encode("utf-8", errors="replace") if isinstance(html, str) else bytes(html)
                return wrapped
            last_exc = RuntimeError(f"Zyte HTTP {response.status_code}: {response.text[:300]}")
        except RuntimeError as exc:
            if "HTTP 401" in str(exc) or "HTTP 402" in str(exc) or "HTTP 403" in str(exc):
                raise
            last_exc = exc
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
        if attempt < 2:
            time.sleep(2)
    raise RuntimeError(str(last_exc))


def add_page_param(url: str, page: int) -> str:
    if page == 1:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={page}"


def looks_like_listing_url(url: str, source: str) -> bool:
    path = urlparse(url).path.lower()
    if source == "PropertyPro.ng":
        if any(x in path for x in ("/property-for-sale/", "/property-for-rent/", "/property-for/",
                                    "/login", "/register", "/contact", "/about")):
            return False
        return bool(re.search(r"(?:-[a-z0-9]{4,})$", path))
    if source == "Nigeria Property Centre":
        return ("/for-sale/" in path or "/for-rent/" in path) and "/showtype" not in path
    return False


def candidate_cards(html: str, source: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc.lower()
    seen = set()
    cards: list[tuple[str, str]] = []

    for a in soup.find_all("a", href=True):
        href = canonical_url(urljoin(base_url, a["href"].strip()))
        if urlparse(href).netloc.lower() != host or not looks_like_listing_url(href, source):
            continue
        # Climb a few levels to capture the complete listing card.
        node = a
        best = ""
        for _ in range(6):
            if node is None:
                break
            txt = clean_text(node.get_text(" ", strip=True))
            if len(txt) > len(best):
                best = txt
            # Stop when we have a compact but information-rich card.
            if len(best) >= 80 and (("₦" in best or "N" in best) and
                                    ("Added" in best or "Updated" in best or "Bedroom" in best or "Beds" in best)):
                break
            node = node.parent
        if href not in seen:
            seen.add(href)
            cards.append((href, best))
    return cards


def parse_card(card_text: str, listing_url: str, target: dict) -> Optional[dict]:
    text = clean_text(card_text)
    if len(text) < 20:
        return None
    listing_dt, date_type = parse_date(text)
    now = datetime.now(timezone.utc)
    age = (now.date() - listing_dt.date()).days if listing_dt else None
    recent = bool(listing_dt and 0 <= age <= MAX_LISTING_AGE_DAYS)

    title = None
    for pattern in (
        r"(?:Image:\s*)?(.{10,180}?)(?=\s+(?:₦|N)\s*[\d,])",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            title = clean_text(m.group(1))
            break
    if not title:
        title = text[:180]

    bedrooms = parse_bedrooms(text)
    size = parse_size_sqm(text)
    price = parse_naira(text)
    explicit_ppsqm = parse_price_per_sqm(text)

    # Keep only the requested apartment bedroom bands. Land has no bedroom
    # restriction; if the page text has a bedroom count, it is irrelevant.
    if target["property_type"] == "flat_apartment":
        if bedrooms not in (1, 2, 3, 4, 5):
            return None
        if target.get("bedrooms") and bedrooms != int(target["bedrooms"]):
            return None

    # If the category is a bedroom-specific manifest entry, the row must match.
    if target.get("bedrooms") and bedrooms != int(target["bedrooms"]):
        return None

    # Location is deliberately kept as the market node when a card does not
    # expose a clean address. The source URL remains the audit trail.
    location = target["node"]

    return {
        "record_id": record_id(listing_url),
        "date_scraped": now.date().isoformat(),
        "city": target["market"],
        "market_node": target["node"],
        "transaction": target["transaction"],
        "property_type": target["property_type"],
        "bedrooms": bedrooms if bedrooms is not None else target.get("bedrooms"),
        "title": title,
        "asking_price_ngn": price,
        "size_sqm": size,
        "price_per_sqm_ngn": calculate_price_per_sqm(price, size, explicit_ppsqm),
        "location": location,
        "listing_date": listing_dt.date().isoformat() if listing_dt else None,
        "listing_age_days": age,
        "listing_date_type": date_type,
        "is_within_31_days": recent,
        "source": target["source"],
        "source_url": listing_url,
    }


def scrape_category(target: dict) -> tuple[list[dict], dict]:
    stats = {"source": target["source"], "node": target["node"], "category": target["category"],
             "url": target["url"], "pages": 0, "cards": 0, "rows": 0, "error": None}
    rows: list[dict] = []
    seen = set()

    for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
        try:
            response = fetch_page(add_page_param(target["url"], page), target["source"])
        except Exception as exc:
            stats["error"] = str(exc)
            return rows, stats

        stats["pages"] += 1
        cards = candidate_cards(response.text, target["source"], target["url"])
        stats["cards"] += len(cards)

        for listing_url, card_text in cards:
            if listing_url in seen:
                continue
            seen.add(listing_url)
            row = parse_card(card_text, listing_url, target)
            if row and row["is_within_31_days"]:
                rows.append(row)
                if len(rows) >= MAX_LISTINGS_PER_CATEGORY:
                    break
        if len(rows) >= MAX_LISTINGS_PER_CATEGORY:
            break
        if not cards:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    stats["rows"] = len(rows)
    return rows, stats


def scrape_estate_intel(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    rows = []
    stats = []

    # Deduplicate by public URL. Premium data is intentionally ignored.
    unique = {}
    for e in entries:
        unique.setdefault(e["url"], e)

    for url, e in unique.items():
        s = {
            "source": "Estate Intel",
            "node": e["node"],
            "url": url,
            "rows": 0,
            "error": None,
        }

        try:
            # Public-only policy:
            # - Never bypass authentication.
            # - Never request premium/login/account URLs.
            # - Never treat an authentication/subscription wall as public research.
            r = fetch_page(url, "Estate Intel")

            soup = BeautifulSoup(r.text, "html.parser")
            text = clean_text(soup.get_text(" ", strip=True))

            title_node = soup.find("h1") or soup.find("h2") or soup.title
            title = (
                clean_text(title_node.get_text(" ", strip=True))
                if title_node
                else ""
            )

            # Detect an actual access wall, rather than merely finding a
            # navigation link containing words such as "login".
            title_lower = title.lower()
            text_lower = text.lower()

            gated_title_markers = (
                "login",
                "log in",
                "sign in",
                "signin",
                "subscribe",
                "subscription required",
                "premium content",
            )

            gated_body_markers = (
                "please log in to continue",
                "please sign in to continue",
                "login to continue",
                "sign in to continue",
                "you must be logged in",
                "you must sign in",
                "create an account to continue",
                "subscribe to continue",
                "subscription required to view",
                "premium content requires",
                "premium content is available",
            )

            if (
                any(marker in title_lower for marker in gated_title_markers)
                or any(marker in text_lower for marker in gated_body_markers)
            ):
                s["error"] = (
                    "Estate Intel page appears authentication/subscription gated; "
                    "public-only policy blocked collection."
                )
                stats.append(s)
                continue

            added = re.search(
                r"DATE ADDED\s+([A-Za-z]+\s+\d{4})",
                text,
                re.I,
            )
            updated = re.search(
                r"last updated\s+([^\n]+?)(?=\s+[A-Z][a-z]+,\s+Nigeria|\s+Overview)",
                text,
                re.I,
            )
            size_units = re.search(
                r"Total Size\s+([\d,]+)\s+units",
                text,
                re.I,
            )
            land = re.search(
                r"land area\s+([\d,.]+)\s*SQM",
                text,
                re.I,
            )
            public_price = re.search(
                r"Sale price from:\s*₦\s*([\d,.]+)",
                text,
                re.I,
            )

            rows.append({
                "date_scraped": datetime.now(timezone.utc).date().isoformat(),
                "market": e["market"],
                "market_node": e["node"],
                "title": title,
                "url": url,
                "date_added": added.group(1) if added else None,
                "last_updated": updated.group(1).strip() if updated else None,
                "location": e["node"],
                "property_type": "public_research",
                "size_units": (
                    int(size_units.group(1).replace(",", ""))
                    if size_units
                    else None
                ),
                "land_area_sqm": (
                    float(land.group(1).replace(",", ""))
                    if land
                    else None
                ),
                "public_sale_price_ngn": (
                    int(float(public_price.group(1).replace(",", "")))
                    if public_price
                    else None
                ),
                "notes": (
                    "Public Estate Intel page only. "
                    "Premium/login-gated values are not collected or bypassed."
                ),
            })
            s["rows"] = 1

        except Exception as exc:
            s["error"] = str(exc)

        stats.append(s)

    return rows, stats

def save_csv(rows: list[dict], filename: str, fields: list[str]) -> str:
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {filename}")
    return filename


def run() -> None:
    if not ZYTE_API_KEY:
        raise RuntimeError("ZYTE_API_KEY is missing")

    approved = load_manifest()
    # Collapse the five bedroom manifest rows to one category request. Bedroom
    # classification happens on the category cards, so this is the key cost
    # control that prevents five paid requests per node/category.
    category_targets = {}
    for e in approved:
        if e["source"] in ("PropertyPro.ng", "Nigeria Property Centre") and e["category"] in ("sale", "rent", "land_sale"):
            key = (e["source"], e["market"], e["node"], e["category"], e["url"])
            # The category URL is shared by 1-5BR. Remove the manifest's
            # bedroom specialization for the paid request so one request
            # captures all requested bedroom bands.
            target = dict(e)
            target["bedrooms"] = None
            category_targets.setdefault(key, target)

    print(f"Manifest entries: {len(approved)}")
    print(f"Paid category requests planned: {len(category_targets)}")
    print(f"Workers: {WORKERS} | pages/category: {MAX_PAGES_PER_CATEGORY} | max rows/category: {MAX_LISTINGS_PER_CATEGORY}")

    all_rows: list[dict] = []
    category_stats = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(scrape_category, e): e for e in category_targets.values()}
        for future in as_completed(futures):
            rows, stats = future.result()
            all_rows.extend(rows)
            category_stats.append(stats)
            status = "OK" if not stats["error"] else "FAILED"
            print(f"[{status}] {stats['source']} / {stats['node']} / {stats['category']} -> {stats['rows']} rows")
            if stats["error"]:
                print(f"  {stats['error']}")

    ei_rows, ei_stats = scrape_estate_intel([e for e in approved if e["source"] == "Estate Intel"])

    # De-duplicate listings across category overlaps.
    unique_rows = {}
    for row in all_rows:
        unique_rows[row["record_id"]] = row
    all_rows = list(unique_rows.values())

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    listing_output = save_csv(all_rows, f"property_listings_{today}.csv", FIELDNAMES)
    save_csv(ei_rows, f"estateintel_public_research_{today}.csv", RESEARCH_FIELDS)

    failures = [x for x in category_stats if x["error"]] + [x for x in ei_stats if x["error"]]
    report = {
        "date": today,
        "manifest_entries": len(approved),
        "category_requests": len(category_targets),
        "listing_rows": len(all_rows),
        "estate_intel_rows": len(ei_rows),
        "failures": failures,
    }
    Path("scrape_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 70)
    print(f"SCRAPE COMPLETE: {len(all_rows)} recent comparable listings")
    print(f"LISTING OUTPUT: {listing_output}")
    print(f"ESTATE INTEL PUBLIC RESEARCH: {len(ei_rows)} rows")
    print(f"CATEGORY/RESEARCH FAILURES: {len(failures)}")
    if failures:
        print("Failures were isolated; successful source/category data was preserved.")


if __name__ == "__main__":
    run()
