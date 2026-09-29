"""Quality gate for normalized property listings."""
from __future__ import annotations
import csv,json,sys
from pathlib import Path
def num(v):
    try:return float(str(v).replace(",","").strip())
    except (TypeError,ValueError):return None
def is_propertypro_agent(url):return "propertypro.ng/agent/" in (url or "").lower()
def process(path):
    with open(path,newline="",encoding="utf-8-sig") as f:rows=list(csv.DictReader(f))
    kept=[];removed=[];fixed=[]
    for i,row in enumerate(rows,1):
        url=row.get("source_url","")
        if row.get("source")=="PropertyPro.ng" and is_propertypro_agent(url):
            removed.append({"row":i,"reason":"non-auditable PropertyPro agent/profile URL","url":url});continue
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
        key=row.get("record_id") or row.get("source_url")
        if key in unique:duplicates+=1;continue
        unique[key]=row
    kept=list(unique.values());fields=list(rows[0].keys()) if rows else []
    with open(path,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(kept)
    report={"input_rows":len(rows),"output_rows":len(kept),"removed_rows":len(removed),"fixed_rows":len(fixed),"duplicates_removed":duplicates,"removals":removed[:200],"fixes":fixed[:200]}
    Path("market_output_quality.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: python quality_gate.py property_listings_YYYY-MM-DD.csv")
    process(sys.argv[1])
