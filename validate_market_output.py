"""Validate the normalized market snapshot before intelligence is published."""
from __future__ import annotations
import csv, json, sys
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_SOURCES = {"Nigeria Property Centre", "PropertyPro.ng", "Estate Intel"}
# Canonical human-readable market nodes.
# These names are the single source of truth for the normalized output.
NODES = {
    "Banana Island",
    "Old Ikoyi",
    "Lekki Phase 1",
    "Victoria Island",
    "Eko Atlantic",
    "Ikeja GRA",
    "Asokoro",
    "Maitama",
    "Wuse",
}
NODE_SLUGS = {
    "Banana Island": "banana-island", "Old Ikoyi": "old-ikoyi",
    "Lekki Phase 1": "lekki-phase-1", "Victoria Island": "victoria-island",
    "Eko Atlantic": "eko-atlantic", "Ikeja GRA": "ikeja-gra",
    "Asokoro": "asokoro", "Maitama": "maitama", "Wuse": "wuse",
}
NODE_URL_PATTERNS = {
    "Banana Island": ("banana-island",),
    "Old Ikoyi": ("old-ikoyi",),
    "Lekki Phase 1": ("lekki-phase-1",),
    "Victoria Island": ("victoria-island",),
    "Eko Atlantic": ("eko-atlantic",),
    "Ikeja GRA": ("ikeja-gra", "ikeja/gra"),
    "Asokoro": ("asokoro",),
    "Maitama": ("maitama",),
    "Wuse": ("wuse",),
}


def age_days(value):
    if not value: return None
    d = datetime.strptime(value, "%Y-%m-%d").date()
    return (datetime.now(timezone.utc).date() - d).days


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python validate_market_output.py property_listings_YYYY-MM-DD.csv")
    path = Path(sys.argv[1])
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("Validation failed: snapshot is empty")

    errors=[]
    ids=set()
    for i,r in enumerate(rows,1):
        if r.get("source") not in ALLOWED_SOURCES: errors.append(f"row {i}: unapproved source {r.get('source')}")
        if r.get("market_node") not in NODES: errors.append(f"row {i}: unapproved node {r.get('market_node')}")
        url=r.get("source_url","")
        if not url.startswith("https://"): errors.append(f"row {i}: missing HTTPS source URL")
        else:
            path=urlparse(url).path.lower()
            source=r.get("source")
            if source=="PropertyPro.ng" and not path.startswith("/property/"):
                errors.append(f"row {i}: PropertyPro source URL is not a listing detail URL")
            if source=="Nigeria Property Centre" and ("/for-sale/" not in path and "/for-rent/" not in path):
                errors.append(f"row {i}: NPC source URL is not a listing detail URL")
            node=r.get("market_node")
            patterns=NODE_URL_PATTERNS.get(node, (NODE_SLUGS.get(node),))
            title_text=f"{r.get('title','')} {r.get('location','')}".lower()
            if node == "Eko Atlantic":
                matches_node = "eko-atlantic" in path or "eko atlantic" in title_text
            else:
                matches_node = any(pattern and pattern in path for pattern in patterns)
            if node in NODE_SLUGS and not matches_node:
                errors.append(f"row {i}: source URL/evidence does not match market node {node}")
        if r.get("record_id") in ids: errors.append(f"row {i}: duplicate record_id")
        ids.add(r.get("record_id"))
        if r.get("property_type") == "flat_apartment":
            try: br=int(float(r.get("bedrooms") or 0))
            except ValueError: br=0
            if br not in {1,2,3,4,5}: errors.append(f"row {i}: apartment outside 1-5BR")
        age=age_days(r.get("listing_date"))
        if age is not None and not 0 <= age <= 31: errors.append(f"row {i}: listing older than 31 days ({age})")
        if r.get("is_within_31_days") != "True": errors.append(f"row {i}: row is not marked within 31 days")
        if r.get("source") == "Estate Intel": errors.append(f"row {i}: Estate Intel must be in research output, not comparable listing output")
    if errors:
        print("MARKET OUTPUT VALIDATION FAILED")
        print("\n".join(errors[:50]))
        sys.exit(1)
    report={"file":str(path),"rows":len(rows),"validated_at":datetime.now(timezone.utc).isoformat(),"sources":sorted({r["source"] for r in rows}),"nodes":sorted({r["market_node"] for r in rows})}
    Path("market_output_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(f"Market output validation passed: {len(rows)} rows")

if __name__ == "__main__": main()
