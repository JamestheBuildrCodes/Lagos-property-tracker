"""Quality gate for normalized property listings."""
from __future__ import annotations
import csv,json,re,sys
from pathlib import Path
def num(v):
    try:return float(str(v).replace(",","").strip())
    except (TypeError,ValueError):return None
def is_propertypro_agent(url):return "propertypro.ng/agent/" in (url or "").lower()

def is_bulk_multi_unit_listing(row):
    """Reject bulk blocks from per-apartment comparisons pending manual review."""
    text = " ".join(str(row.get(key) or "") for key in ("title", "source_excerpt")).lower()
    if not text.strip():
        return False
    return bool(re.search(
        r"\b\d+\s+(?:units|apartments|flats)\b|"
        r"\b(?:block of flats|block of apartments|entire block|whole building|"
        r"multi[- ]unit|bulk (?:rent|sale|letting)|all units)\b",
        text,
    ))
def process(path):
    with open(path,newline="",encoding="utf-8-sig") as f:rows=list(csv.DictReader(f))
    kept=[];removed=[];fixed=[];pre_review=[]
    for i,row in enumerate(rows,1):
        url=row.get("source_url","")
        if row.get("source")=="PropertyPro.ng" and is_propertypro_agent(url):
            removed.append({"row":i,"reason":"non-auditable PropertyPro agent/profile URL","url":url});continue
        if (row.get("property_type") or "").lower() in {"flat_apartment","apartment","flat"} and is_bulk_multi_unit_listing(row):
            row["_pre_review_reason"] = (
                "Bulk multi-unit block listing is not comparable to a single-apartment bedroom segment; manual classification required."
            )
            pre_review.append(row)
            continue
        if (row.get("property_type") or "").lower()=="land":
            if row.get("bedrooms") not in (None,"","0"):
                row["bedrooms"]="";fixed.append({"row":i,"fix":"removed bedroom value from land record"})
            size=num(row.get("size_sqm"));price=num(row.get("asking_price_ngn"));ppsqm=num(row.get("price_per_sqm_ngn"))
            if size and size>0:
                if ppsqm and price and abs(ppsqm-price)<=max(1,price*0.0001):
                    total=round(ppsqm*size,2);row["asking_price_ngn"]=str(int(total) if total.is_integer() else total);fixed.append({"row":i,"fix":"converted parsed land unit price into total asking price"})
                elif price:
                    calculated=round(price/size,2)
                    if not ppsqm or abs(ppsqm-calculated)>max(1,calculated*0.05):
                        row["price_per_sqm_ngn"]=str(calculated);fixed.append({"row":i,"fix":"recomputed land price per sqm from total asking price and land area"})
        kept.append(row)
    unique={};duplicates=0
    for row in kept:
        # Never collapse unrelated records under an empty identifier. Prefer stable IDs,
        # then canonical source URLs, and finally a conservative composite key.
        key = (row.get("record_id") or "").strip()
        if not key:
            key = (row.get("source_url") or "").strip().split("?")[0].rstrip("/")
        if not key:
            key = "|".join(str(row.get(k) or "").strip().lower() for k in
                           ("source", "title", "market_node", "property_type",
                            "transaction_type", "asking_price_ngn", "date_scraped"))
        if key in unique:
            duplicates += 1
            continue
        unique[key] = row
    kept=list(unique.values())

    # Free deterministic evidence check against the exact captured listing-card text.
    # Optional AI is disabled by default. Rows with missing or conflicting evidence
    # are preserved in a separate review file rather than included in comparisons.
    from ai_listing_verifier import verify_rows
    verification = verify_rows(kept)
    verified_rows=[];review_rows=[]
    for row in pre_review:
        row["evidence_verification_status"]="review"
        row["evidence_verification_issues"]=row.pop("_pre_review_reason", "Bulk multi-unit listing needs manual review")
        review_rows.append(row)
    for row in kept:
        rid=str(row.get("record_id") or "")
        result=verification.get(rid, {"status":"review","issues":["No verifier result returned"]})
        row["evidence_verification_status"]=result.get("status","review")
        row["evidence_verification_issues"]="; ".join(result.get("issues",[]))
        if row["evidence_verification_status"] == "pass":
            verified_rows.append(row)
        else:
            review_rows.append(row)

    fields=list(rows[0].keys()) if rows else []
    for extra in ("evidence_verification_status","evidence_verification_issues"):
        if extra not in fields:
            fields.append(extra)
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(verified_rows)
    review_fields=list(dict.fromkeys(fields + ["review_reason"]))
    with open("market_output_review.csv","w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=review_fields,extrasaction="ignore");w.writeheader()
        for row in review_rows:
            w.writerow({**row,"review_reason":row.get("evidence_verification_issues","Evidence review required")})
    report={"input_rows":len(rows),"output_rows":len(verified_rows),"evidence_verified_rows":len(verified_rows),"verification_method":"deterministic_source_evidence","quarantined_for_review":len(review_rows),"removed_rows":len(removed),"fixed_rows":len(fixed),"duplicates_removed":duplicates,"removals":removed[:200],"fixes":fixed[:200],"review_sample":[{"record_id":r.get("record_id"),"source":r.get("source"),"source_url":r.get("source_url"),"issues":r.get("evidence_verification_issues")} for r in review_rows[:100]]}
    Path("market_output_quality.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(report,indent=2))

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: python quality_gate.py property_listings_YYYY-MM-DD.csv")
    process(sys.argv[1])
