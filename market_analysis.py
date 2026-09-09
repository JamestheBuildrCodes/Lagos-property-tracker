"""Shared market analytics for the 3-layer Nigeria property intelligence system."""
from __future__ import annotations
import csv, glob, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

NODES = [
    "Banana Island", "Old Ikoyi", "Lekki Phase 1", "Victoria Island",
    "Eko Atlantic", "Ikeja GRA", "Asokoro", "Maitama", "Wuse",
]

def fnum(v):
    try:
        if v in (None, "", "None"): return None
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError): return None

def fint(v):
    n=fnum(v); return int(n) if n is not None else None

def fmt_naira(v, compact=False):
    n=fnum(v)
    if n is None: return "N/A"
    if compact:
        if n >= 1_000_000_000: return f"₦{n/1_000_000_000:.1f}bn"
        if n >= 1_000_000: return f"₦{n/1_000_000:.1f}m"
        if n >= 1_000: return f"₦{n/1_000:.0f}k"
    return f"₦{n:,.0f}"

def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f: return list(csv.DictReader(f))

def median(values):
    vals=[v for v in (fnum(x) for x in values) if v is not None and v>0]
    return statistics.median(vals) if vals else None

def pct_change(new, old):
    if new is None or old in (None, 0): return None
    return round((new-old)/old*100, 1)

def transaction_label(row):
    t=(row.get("transaction") or "").lower()
    if t in {"sale","for_sale","sales"}: return "sale"
    if t in {"rent","rental","for_rent"}: return "rent"
    if "land" in (row.get("property_type") or "").lower() or "land" in t: return "land"
    return t or "other"

def is_apartment(row):
    return (row.get("property_type") or "").lower() in {"flat_apartment","apartment","flat"}

def normalize_node(value):
    value=(value or "").strip()
    # The production scraper already emits canonical nodes. Keep only harmless
    # historical compatibility aliases so archived snapshots remain usable.
    aliases={
        "Ikoyi - Banana Island":"Banana Island", "Ikoyi - Old Ikoyi":"Old Ikoyi",
        "Lekki - Lekki Phase 1":"Lekki Phase 1", "Ikeja - Ikeja GRA":"Ikeja GRA",
        "Abuja - Asokoro":"Asokoro", "Abuja - Maitama":"Maitama", "Abuja - Wuse":"Wuse",
    }
    return aliases.get(value, value)

def area_scorecard(rows):
    by_node=defaultdict(list)
    for row in rows:
        r=dict(row); r["market_node"]=normalize_node(r.get("market_node") or r.get("location"))
        by_node[r["market_node"]].append(r)
    result=[]
    for node in NODES:
        rs=by_node.get(node,[])
        sales3=[r for r in rs if transaction_label(r)=="sale" and is_apartment(r) and fint(r.get("bedrooms"))==3]
        rents3=[r for r in rs if transaction_label(r)=="rent" and is_apartment(r) and fint(r.get("bedrooms"))==3]
        sales=[r for r in rs if transaction_label(r)=="sale" and is_apartment(r)]
        rents=[r for r in rs if transaction_label(r)=="rent" and is_apartment(r)]
        land=[r for r in rs if transaction_label(r)=="land"]
        sale_ppsqm=median([r.get("price_per_sqm_ngn") for r in sales])
        rent_ppsqm=median([r.get("price_per_sqm_ngn") for r in rents])
        land_ppsqm=median([r.get("price_per_sqm_ngn") for r in land])
        sale_med=median([r.get("asking_price_ngn") for r in sales3]) or median([r.get("asking_price_ngn") for r in sales])
        rent_med=median([r.get("asking_price_ngn") for r in rents3]) or median([r.get("asking_price_ngn") for r in rents])
        yield_proxy=(rent_med/sale_med*100) if rent_med and sale_med else None
        result.append({
            "market_node":node,"listing_count":len(rs),"sale_3br_median":sale_med,
            "rent_3br_median":rent_med,"sale_ppsqm_median":sale_ppsqm,
            "rent_ppsqm_median":rent_ppsqm,"land_ppsqm_median":land_ppsqm,
            "gross_rent_yield_proxy_pct":round(yield_proxy,2) if yield_proxy is not None else None,
            "sale_count":len(sales),"rent_count":len(rents),"land_count":len(land),
        })
    return result

def change_counts(changes):
    return {
        "new_listings":sum(1 for c in changes if c.get("type")=="new_listing"),
        "price_reductions":sum(1 for c in changes if c.get("type")=="price_change" and fnum(c.get("pct_change")) is not None and fnum(c.get("pct_change"))<0),
        "price_increases":sum(1 for c in changes if c.get("type")=="price_change" and fnum(c.get("pct_change")) is not None and fnum(c.get("pct_change"))>0),
        "delisted":sum(1 for c in changes if c.get("type")=="delisted"),
    }

def decision_signals(scorecard):
    valid=[x for x in scorecard if x["listing_count"]>0]
    def max_by(key):
        vals=[x for x in valid if x.get(key) is not None]; return max(vals,key=lambda x:x[key]) if vals else None
    def min_by(key):
        vals=[x for x in valid if x.get(key) is not None]; return min(vals,key=lambda x:x[key]) if vals else None
    return {
        "most_expensive":max_by("sale_3br_median"),
        "strongest_rental":max_by("gross_rent_yield_proxy_pct") or max_by("rent_3br_median"),
        "best_relative_value":min_by("sale_ppsqm_median") or min_by("sale_3br_median"),
        "land_opportunity":min_by("land_ppsqm_median"),
        "strongest_rental_activity":max_by("rent_count"),
        "monitoring":sorted(valid,key=lambda x:x["listing_count"])[:3],
    }

def snapshot_metrics(rows):
    return {
        "sale":median([r.get("asking_price_ngn") for r in rows if transaction_label(r)=="sale" and is_apartment(r)]),
        "rent":median([r.get("asking_price_ngn") for r in rows if transaction_label(r)=="rent" and is_apartment(r)]),
        "land_ppsqm":median([r.get("price_per_sqm_ngn") for r in rows if transaction_label(r)=="land"]),
    }

def load_history(current_path,max_months=6):
    current=Path(current_path).resolve(); candidates=[]
    patterns=[current.parent/"property_listings_*.csv", current.parent/"data"/"property_listings_*.csv"]
    seen=set()
    for pattern in patterns:
        for path in glob.glob(str(pattern)):
            p=Path(path).resolve()
            if p==current or not p.exists() or p in seen: continue
            seen.add(p)
            try: d=datetime.strptime(p.stem.rsplit("_",1)[-1],"%Y-%m-%d").date()
            except ValueError: continue
            try: current_date=datetime.strptime(current.stem.rsplit("_",1)[-1],"%Y-%m-%d").date()
            except ValueError: current_date=datetime.now(timezone.utc).date()
            if d >= current_date: continue
            candidates.append((d,p))
    candidates.sort()
    cutoff=datetime.now(timezone.utc).date()-timedelta(days=max_months*31)
    return [(d,load_csv(str(p))) for d,p in candidates if d>=cutoff]

def previous_snapshot(current_path):
    hist=load_history(current_path,max_months=12)
    return hist[-1] if hist else (None,None)

def six_month_area_trends(current_path,current_rows):
    history=load_history(current_path,6)
    snapshots=[(datetime.now(timezone.utc).date(),current_rows)]+history
    snapshots.sort(key=lambda x:x[0])
    if len(snapshots)<2: return {}
    first_date,first_rows=snapshots[0]; last_date,last_rows=snapshots[-1]
    first={x["market_node"]:x for x in area_scorecard(first_rows)}
    last={x["market_node"]:x for x in area_scorecard(last_rows)}
    return {node:{
        "from_date":first_date.isoformat(),"to_date":last_date.isoformat(),
        "sale_pct":pct_change(last.get(node,{}).get("sale_3br_median"),first.get(node,{}).get("sale_3br_median")),
        "rent_pct":pct_change(last.get(node,{}).get("rent_3br_median"),first.get(node,{}).get("rent_3br_median")),
        "land_ppsqm_pct":pct_change(last.get(node,{}).get("land_ppsqm_median"),first.get(node,{}).get("land_ppsqm_median")),
        "snapshots":len(snapshots)} for node in NODES}

def weekly_comparison(current_path,current_rows):
    prev_date,prev_rows=previous_snapshot(current_path)
    if not prev_rows: return {"available":False,"previous_date":None,"metrics":{},"narrative":[]}
    cur=snapshot_metrics(current_rows); prev=snapshot_metrics(prev_rows)
    metrics={}
    labels={"sale":"median apartment asking sale price","rent":"median annual apartment rent","land_ppsqm":"median land asking price per sqm"}
    for key,label in labels.items():
        metrics[key]={"label":label,"current":cur[key],"previous":prev[key],"pct_change":pct_change(cur[key],prev[key])}
    listing_pct=pct_change(len(current_rows),len(prev_rows))
    metrics["listings"]={"label":"comparable listings tracked","current":len(current_rows),"previous":len(prev_rows),"pct_change":listing_pct}
    narrative=[]
    for key in ("sale","rent","land_ppsqm"):
        m=metrics[key]
        if m["pct_change"] is not None:
            direction="increased" if m["pct_change"]>0 else "decreased" if m["pct_change"]<0 else "held"
            narrative.append(f"{m['label'].capitalize()} {direction} {abs(m['pct_change']):.1f}% week on week.")
    if listing_pct is not None:
        delta=len(current_rows)-len(prev_rows)
        if delta>0: narrative.append(f"The scan captured {delta} more comparable listings than the previous snapshot.")
        elif delta<0: narrative.append(f"The scan captured {abs(delta)} fewer comparable listings than the previous snapshot.")
        else: narrative.append("The scan captured the same number of comparable listings as the previous snapshot.")
    return {"available":True,"previous_date":prev_date.isoformat(),"metrics":metrics,"narrative":narrative}

def natural_language_interpretation(summary):
    if not summary.get("listings_tracked"): return ["No comparable listings were returned, so no market conclusion is published."]
    score=summary["scorecard"]; populated=[x for x in score if x["listing_count"]]
    out=[]
    wow=summary.get("week_on_week",{})
    if wow.get("available"):
        for sentence in wow.get("narrative",[]): out.append(sentence)
    if populated:
        top=sorted(populated,key=lambda x:x["listing_count"],reverse=True)[:3]
        out.append("The deepest comparable coverage this week is in " + ", ".join(x["market_node"] for x in top) + ".")
    thin=sorted(populated,key=lambda x:x["listing_count"])[:3]
    if thin: out.append("Thin coverage in " + ", ".join(x["market_node"] for x in thin) + " means those areas should be treated as watchlist signals rather than firm pricing conclusions.")
    sig=summary["signals"]
    if sig.get("strongest_rental"):
        out.append(f"{sig['strongest_rental']['market_node']} currently shows the strongest rental pricing/yield proxy among areas with usable observations.")
    if sig.get("best_relative_value"):
        out.append(f"{sig['best_relative_value']['market_node']} currently screens as the lowest observed apartment sale ₦/sqm among areas with usable data.")
    if sig.get("investment"):
        out.append(f"{sig['investment']['market_node']} currently screens strongest on the rental-yield proxy, subject to the available comparable sample.")
    if sig.get("seller_momentum"):
        out.append(f"{sig['seller_momentum']['market_node']} shows the strongest positive six-month sale-price movement among areas with sufficient sale observations.")
    return out

def build_summary(listings,changes,current_path=None):
    scorecard=area_scorecard(listings); cc=change_counts(changes)
    sale=median([r.get("asking_price_ngn") for r in listings if transaction_label(r)=="sale" and is_apartment(r)])
    rent=median([r.get("asking_price_ngn") for r in listings if transaction_label(r)=="rent" and is_apartment(r)])
    land=median([r.get("price_per_sqm_ngn") for r in listings if transaction_label(r)=="land"])
    sources=sorted({r.get("source") for r in listings if r.get("source")})
    signals=decision_signals(scorecard)
    valid=[x for x in scorecard if x["listing_count"]>0]
    yield_candidates=[x for x in valid if x.get("gross_rent_yield_proxy_pct") is not None and x.get("rent_count",0)>=2 and x.get("sale_count",0)>=2]
    investor=sorted(yield_candidates,key=lambda x:x["gross_rent_yield_proxy_pct"],reverse=True)[0] if yield_candidates else signals.get("strongest_rental")
    buyer=sorted([x for x in valid if x.get("sale_ppsqm_median") is not None and x.get("sale_count",0)>=2],key=lambda x:x["sale_ppsqm_median"])[:1]
    seller_candidates=[x for x in valid if x.get("sale_count",0)>=2 and six_month_area_trends(current_path,listings).get(x["market_node"],{}).get("sale_pct") is not None] if current_path else []
    seller=sorted(seller_candidates,key=lambda x:six_month_area_trends(current_path,listings)[x["market_node"]]["sale_pct"],reverse=True)[:1] if seller_candidates else []
    signals["investment"]=investor
    signals["buyer_value"]=buyer[0] if buyer else signals.get("best_relative_value")
    signals["seller_momentum"]=seller[0] if seller else None
    s={"listings_tracked":len(listings),"areas_monitored":len(NODES),"sources":len(sources),"source_names":sources,
       "median_apartment_sale":sale,"median_annual_rent":rent,"median_land_ppsqm":land,
       "changes":cc,"scorecard":scorecard,"signals":signals,
       "trends":six_month_area_trends(current_path,listings) if current_path else {},
       "week_on_week":weekly_comparison(current_path,listings) if current_path else {"available":False},
       "analysis_notes":[]}
    s["analysis_notes"]=natural_language_interpretation(s)
    return s

def trend_label(current,previous):
    p=pct_change(current,previous)
    if p is None:return "→"
    if p>=3:return f"↑ {p:.1f}%"
    if p<=-3:return f"↓ {abs(p):.1f}%"
    return "→"
