"""Publish the analyst report as a professionally formatted Google Doc."""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
SCOPES=["https://www.googleapis.com/auth/documents","https://www.googleapis.com/auth/drive"]
def creds_from_env():
    from google.oauth2.service_account import Credentials
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON","").strip()
    if not raw: raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    return Credentials.from_service_account_info(json.loads(raw),scopes=SCOPES)
def money(value):
    if value in (None,""): return "N/A"
    try: return f"₦{float(str(value).replace(',','')):,.0f}"
    except Exception: return str(value)
def report_text(summary):
    def node(obj): return obj["market_node"] if obj else "N/A"
    lines=["LAGOS PROPERTY MARKET","WEEKLY INTELLIGENCE REPORT",datetime.now(timezone.utc).strftime("%d %B %Y"),"","1. EXECUTIVE DECISION BRIEF","Purpose: Use this report to benchmark asking prices, identify meaningful market movement, compare locations and prioritise listings for deeper due diligence.","","MARKET SNAPSHOT",f"Comparable listings: {summary['listings_tracked']:,}",f"Areas monitored: {summary['areas_monitored']}",f"Sources referenced: {summary['sources']}",f"New listings: {summary['changes']['new_listings']:,}",f"Price reductions: {summary['changes']['price_reductions']:,}",f"Price increases: {summary['changes']['price_increases']:,}",f"Median apartment asking sale: {money(summary['median_apartment_sale'])}",f"Median annual apartment asking rent: {money(summary['median_annual_rent'])}",f"Median land asking price / sqm: {money(summary['median_land_ppsqm'])}","","2. WHAT CHANGED THIS WEEK"]
    lines += [f"• {x}" for x in summary.get("analysis_notes",[])[:6]] or ["• No interpretation available."]
    lines += ["","3. WHAT THIS MEANS FOR THE BUSINESS"]
    sig=summary.get("signals",{})
    if sig.get("most_expensive"):
        x=sig["most_expensive"]; lines.append(f"• Highest 3BR asking sale: {node(x)} at {money(x.get('sale_3br_median'))}.")
    if sig.get("investment"):
        x=sig["investment"]; lines.append(f"• Strongest rental-yield proxy: {node(x)} at {x.get('gross_rent_yield_proxy_pct'):.2f}%. This is annual asking rent divided by asking sale price, not net yield.")
    if sig.get("buyer_value"):
        x=sig["buyer_value"]; lines.append(f"• Lowest observed apartment sale ₦/sqm: {node(x)} at {money(x.get('sale_ppsqm_median'))} per sqm.")
    if sig.get("land_opportunity"):
        x=sig["land_opportunity"]; lines.append(f"• Lowest observed land ₦/sqm: {node(x)} at {money(x.get('land_ppsqm_median'))} per sqm.")
    lines += ["","4. RECOMMENDED ACTIONS"]
    monitoring=", ".join(x["market_node"] for x in sig.get("monitoring",[])); actions=[]
    if monitoring: actions.append(f"Use {monitoring} as watchlist areas where listing counts are thin.")
    if summary.get("changes",{}).get("price_reductions",0): actions.append(f"Review the {summary['changes']['price_reductions']} price reductions first; they are immediate negotiation leads.")
    if sig.get("buyer_value"): actions.append(f"Use {node(sig['buyer_value'])} as a relative-price benchmark when screening apartment asking prices.")
    actions.append("Open and verify the underlying source listing before relying on any high-value comparable.")
    lines += [f"{i}. {x}" for i,x in enumerate(actions[:4],1)]
    lines += ["","5. AREA SCORECARD"]
    for x in summary.get("scorecard",[]):
        if not x.get("listing_count"): continue
        tr=summary.get("trends",{}).get(x["market_node"],{}); sale_tr=f"{tr['sale_pct']:+.1f}%" if tr.get("sale_pct") is not None else "N/A"; yield_tr=f"{x['gross_rent_yield_proxy_pct']:.2f}%" if x.get("gross_rent_yield_proxy_pct") is not None else "N/A"
        lines.append(f"• {x['market_node']}: {x['listing_count']} listings | 3BR sale {money(x.get('sale_3br_median'))} | 3BR rent {money(x.get('rent_3br_median'))} | yield proxy {yield_tr} | 6-mo sale {sale_tr}")
    lines += ["","6. DATA QUALITY & METHODOLOGY"]
    q=summary.get("quality_gate",{})
    if q: lines.append(f"The quality gate reviewed {q.get('input_rows',0):,} raw rows, retained {q.get('output_rows',0):,}, removed {q.get('removed_rows',0):,} non-auditable/conflicting rows and corrected {q.get('fixed_rows',0):,} parsing issues.")
    lines += ["All figures are asking prices in Nigerian naira (₦), not confirmed closed transaction prices.","Median is preferred for skewed asking-price distributions. Thin samples are watchlist signals, not definitive market indices.","Estate Intel contributes public research context only; premium/login-gated content is not collected or bypassed.","Source URLs and collection dates are retained in the Current Listings sheet for auditability."]
    return "\n".join(lines)
def _format_requests(text):
    requests=[{"updateTextStyle":{"range":{"startIndex":1,"endIndex":len(text)+1},"textStyle":{"weightedFontFamily":{"fontFamily":"Aptos"},"fontSize":{"magnitude":10,"unit":"PT"}},"fields":"weightedFontFamily,fontSize"}},{"updateParagraphStyle":{"range":{"startIndex":1,"endIndex":len(text)+1},"paragraphStyle":{"lineSpacing":115,"spaceBelow":{"magnitude":6,"unit":"PT"}},"fields":"lineSpacing,spaceBelow"}}]
    offset=0; section_headings={"1. EXECUTIVE DECISION BRIEF","2. WHAT CHANGED THIS WEEK","3. WHAT THIS MEANS FOR THE BUSINESS","4. RECOMMENDED ACTIONS","5. AREA SCORECARD","6. DATA QUALITY & METHODOLOGY"}
    for line in text.splitlines(True):
        raw=line.rstrip("\n"); start=offset+1; end=start+len(raw)
        if raw in {"LAGOS PROPERTY MARKET","WEEKLY INTELLIGENCE REPORT"}:
            requests.append({"updateTextStyle":{"range":{"startIndex":start,"endIndex":end+1},"textStyle":{"bold":True,"fontSize":{"magnitude":20 if raw=="LAGOS PROPERTY MARKET" else 15,"unit":"PT"}},"fields":"bold,fontSize"}})
            requests.append({"updateParagraphStyle":{"range":{"startIndex":start,"endIndex":end+1},"paragraphStyle":{"alignment":"CENTER","spaceBelow":{"magnitude":4,"unit":"PT"}},"fields":"alignment,spaceBelow"}})
        elif raw in section_headings:
            requests.append({"updateParagraphStyle":{"range":{"startIndex":start,"endIndex":end+1},"paragraphStyle":{"namedStyleType":"HEADING_1","spaceAbove":{"magnitude":14,"unit":"PT"},"spaceBelow":{"magnitude":6,"unit":"PT"}},"fields":"namedStyleType,spaceAbove,spaceBelow"}})
        elif raw=="MARKET SNAPSHOT":
            requests.append({"updateParagraphStyle":{"range":{"startIndex":start,"endIndex":end+1},"paragraphStyle":{"namedStyleType":"HEADING_2","spaceAbove":{"magnitude":10,"unit":"PT"},"spaceBelow":{"magnitude":4,"unit":"PT"}},"fields":"namedStyleType,spaceAbove,spaceBelow"}})
        offset += len(line)
    return requests
def publish(summary, output_docx=None):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    credentials=creds_from_env(); docs=build("docs","v1",credentials=credentials,cache_discovery=False); drive=build("drive","v3",credentials=credentials,cache_discovery=False)
    doc_id=os.environ.get("GOOGLE_DOC_ID","").strip(); text=report_text(summary)
    if doc_id:
        doc=docs.documents().get(documentId=doc_id).execute(); body=doc.get("body",{}).get("content",[]); end=max((x.get("endIndex",1) for x in body),default=1)-1; requests=[]
        if end>1: requests.append({"deleteContentRange":{"range":{"startIndex":1,"endIndex":end}}})
        requests.append({"insertText":{"location":{"index":1},"text":text}}); requests += _format_requests(text); docs.documents().batchUpdate(documentId=doc_id,body={"requests":requests}).execute()
    else:
        title=f"Lagos Property Market — Weekly Intelligence Report — {datetime.now(timezone.utc):%Y-%m-%d}"; doc=docs.documents().create(body={"title":title}).execute(); doc_id=doc["documentId"]; requests=[{"insertText":{"location":{"index":1},"text":text}}]; requests += _format_requests(text); docs.documents().batchUpdate(documentId=doc_id,body={"requests":requests}).execute()
    recipients=[]
    for key in ("REPORT_CLIENT_EMAIL","REPORT_TO_EMAIL"): recipients += [x.strip() for x in os.environ.get(key,"").split(",") if "@" in x]
    for email in dict.fromkeys(recipients):
        try: drive.permissions().create(fileId=doc_id,body={"type":"user","role":"reader","emailAddress":email},sendNotificationEmail=False).execute()
        except HttpError as exc: print(f"Google Doc sharing skipped for {email}: {exc}")
    url=f"https://docs.google.com/document/d/{doc_id}/edit"; Path("google_doc_url.txt").write_text(url+"\n",encoding="utf-8"); print(f"Google Doc published: {url}")
    if output_docx: Path(output_docx).write_text(url,encoding="utf-8")
    return doc_id,url
def main():
    if len(sys.argv)!=2: raise SystemExit("Usage: python docs_writer.py market_intelligence.json")
    payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); publish(payload["summary"])
if __name__=="__main__": main()
