"""Validate the normalized market snapshot before intelligence is published."""
from __future__ import annotations
import csv, json, sys
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
        if not r.get("source_url","").startswith("https://"): errors.append(f"row {i}: missing HTTPS source URL")
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
