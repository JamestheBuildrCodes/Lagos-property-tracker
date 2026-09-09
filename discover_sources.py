"""Build the production source manifest without paid discovery calls.

The manifest is the zero-cost discovery/taxonomy layer. It contains only
reviewed canonical category URLs for the three approved sources. The first
production fetch of each unique category URL is also the transport-validation
step: the collector must receive HTML from the allowed host before it parses
listings. This prevents speculative URL generation and avoids duplicate paid
validation requests.

No paid API calls are made here. No premium/login-gated Estate Intel content
is approved.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "data" / "source_manifest.json"

NODES = [
    # (display node, market, PropertyPro path, NPC path)
    ("Banana Island", "Lagos", "ikoyi/banana-island", "lagos/ikoyi/banana-island"),
    ("Old Ikoyi", "Lagos", "ikoyi/old-ikoyi", "lagos/ikoyi/old-ikoyi"),
    ("Lekki Phase 1", "Lagos", "lekki/lekki-phase-1", "lagos/lekki/lekki-phase-1"),
    ("Victoria Island", "Lagos", "victoria-island/victoria-island", "lagos/victoria-island"),
    ("Eko Atlantic", "Lagos", "victoria-island/eko-atlantic", "lagos/victoria-island/eko-atlantic"),
    ("Ikeja GRA", "Lagos", "ikeja/ikeja-gra", "lagos/ikeja/ikeja-gra"),
    ("Asokoro", "Abuja", "asokoro", "abuja/asokoro-district"),
    ("Maitama", "Abuja", "maitama", "abuja/maitama-district"),
    ("Wuse", "Abuja", "wuse", "abuja/wuse"),
]
BEDROOMS = [1, 2, 3, 4, 5]

PROPERTYPRO = "https://propertypro.ng"
NPC = "https://nigeriapropertycentre.com"

# These are real public Estate Intel pages. Some expose useful public project
# metadata while their detailed pricing is premium-gated; we never bypass it.
ESTATE_INTEL_PUBLIC = [
    ("Banana Island", "Lagos", "https://estateintel.com/app/projects/g34-residence-banana-island-lagos"),
    ("Old Ikoyi", "Lagos", "https://estateintel.com/insights/ikoyi-residential-market-overview"),
    ("Lekki Phase 1", "Lagos", "https://estateintel.com/insights/lekki-phase-1-residential-market-overview"),
    ("Victoria Island", "Lagos", "https://estateintel.com/app/projects/bluerock-residences-vi-victoria-island-lagos"),
    ("Eko Atlantic", "Lagos", "https://estateintel.com/insights/eko-pearl-eko-atlantic"),
    ("Ikeja GRA", "Lagos", "https://estateintel.com/app/projects/eso-close-ikeja-gra-lagos"),
    ("Asokoro", "Abuja", "https://estateintel.com/app/projects/plot-no-2779-asokoro"),
    ("Maitama", "Abuja", "https://estateintel.com/insights/maitama-is-the-ikoyi-of-abuja-heres-how-the-highbrow-residential-market-is-performing"),
    ("Wuse", "Abuja", "https://estateintel.com/insights/here-is-what-you-need-to-know-about-wuse-the-commercial-hub-of-abuja"),
]


@dataclass
class ManifestEntry:
    source: str
    market: str
    node: str
    category: str
    property_type: str
    bedrooms: int | None
    transaction: str
    url: str
    canonical_url: str
    http_status: int | None
    verified: bool
    verification: str
    discovered_from: str
    last_checked: str
    notes: str = ""


def entry(source: str, market: str, node: str, category: str,
          property_type: str, bedrooms: int | None, transaction: str,
          url: str, notes: str = "") -> ManifestEntry:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Invalid canonical URL: {url}")
    return ManifestEntry(
        source=source, market=market, node=node, category=category,
        property_type=property_type, bedrooms=bedrooms, transaction=transaction,
        url=url.rstrip("/"), canonical_url=url.rstrip("/"), http_status=None,
        verified=True,
        verification="canonical URL approved; transport is validated by the first production fetch before parsing",
        discovered_from="deterministic_source_catalog",
        last_checked=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )


def build_propertypro(rows: list[ManifestEntry]) -> None:
    for node, market, pp_path, npc_path in NODES:
        for transaction, tx_path in (
            ("sale", "property-for-sale"),
            ("rent", "property-for-rent"),
        ):
            url = f"{PROPERTYPRO}/{tx_path}/flat-apartment/in/{market.lower()}/{pp_path}"
            for bedroom in BEDROOMS:
                rows.append(entry(
                    "PropertyPro.ng", market, node, transaction, "flat_apartment",
                    bedroom, transaction, url,
                    "One real category URL serves 1-5BR; bedroom is classified from listing text.",
                ))
        land = f"{PROPERTYPRO}/property-for-sale/land/residential-land/in/{market.lower()}/{pp_path}"
        rows.append(entry(
            "PropertyPro.ng", market, node, "land_sale", "land", None, "land_sale",
            land, "Residential-land category; size and asking price are extracted from listing cards.",
        ))


def build_npc(rows: list[ManifestEntry]) -> None:
    for node, market, pp_path, npc_path in NODES:
        for transaction, tx_path in (("sale", "for-sale"), ("rent", "for-rent")):
            url = f"{NPC}/{tx_path}/flats-apartments/{npc_path}/showtype"
            # The site exposes bedroom counts on the category page. Do not
            # manufacture bedroom-specific URLs.
            for bedroom in BEDROOMS:
                rows.append(entry(
                    "Nigeria Property Centre", market, node, transaction,
                    "flat_apartment", bedroom, transaction, url,
                    "One real category URL serves 1-5BR; bedroom is classified from listing text.",
                ))
        land = f"{NPC}/for-sale/land/residential-land/{npc_path}/showtype"
        rows.append(entry(
            "Nigeria Property Centre", market, node, "land_sale", "land", None, "land_sale",
            land, "Residential-land category; size and asking price are extracted from listing cards.",
        ))


def build_estate_intel(rows: list[ManifestEntry]) -> None:
    for node, market, url in ESTATE_INTEL_PUBLIC:
        rows.append(entry(
            "Estate Intel", market, node, "public_research", "market_research",
            None, "research", url,
            "Public page only. Premium/login-gated values are never collected or bypassed.",
        ))


def main() -> None:
    rows: list[ManifestEntry] = []
    build_propertypro(rows)
    build_npc(rows)
    build_estate_intel(rows)

    # Exact duplicate protection is an invariant, not a network check.
    seen = set()
    output = []
    for row in rows:
        key = (row.source, row.market, row.node, row.category,
               row.property_type, row.bedrooms, row.transaction, row.url)
        if key in seen:
            continue
        seen.add(key)
        output.append(asdict(row))

    policy = {
        "allowed_sources": ["Nigeria Property Centre", "PropertyPro.ng", "Estate Intel"],
        "only_catalog_approved_urls_are_scraped": True,
        "transport_validation_before_parse": True,
        "canonical_urls_are_structurally_validated": True,
        "raw_http_discovery_is_not_a_gate": True,
        "no_speculative_urls": True,
        "cloudflare_protected_sources_use_zyte": True,
        "estate_intel_premium_bypass": False,
        "estate_intel_public_only": True,
        "discovery_uses_zyte": False,
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_listing_age_days": 31,
        "nodes": [x[0] for x in NODES],
        "entries": output,
        "policy": policy,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== SOURCE MANIFEST BUILD ===")
    print("No network requests. No Zyte credits consumed.")
    print(f"Manifest written: {MANIFEST_PATH}")
    print(f"Entries: {len(output)}")
    for source in ("PropertyPro.ng", "Nigeria Property Centre", "Estate Intel"):
        source_rows = [x for x in output if x["source"] == source]
        print(f"  {source}: {len(source_rows)} canonical entries")
    if len(output) != 207:
        raise SystemExit(f"Manifest invariant failed: expected 207 entries, got {len(output)}")


if __name__ == "__main__":
    main()
