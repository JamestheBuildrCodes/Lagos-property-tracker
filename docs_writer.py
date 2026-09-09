"""Publish the analyst report as a real Google Doc using the service account.

If GOOGLE_DOC_ID is set, that document is replaced in-place. Otherwise a new
weekly document is created. Optional REPORT_CLIENT_EMAIL / REPORT_TO_EMAIL
recipients receive viewer access to the created/updated document.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

SCOPES=[
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

def creds_from_env():
    from google.oauth2.service_account import Credentials
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON","").strip()
    if not raw: raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    return Credentials.from_service_account_info(json.loads(raw),scopes=SCOPES)

def report_text(summary):
    def n(obj): return obj["market_node"] if obj else "N/A"
    lines=[
        "LAGOS PROPERTY MARKET — WEEKLY INTELLIGENCE REPORT",
        datetime.now(timezone.utc).strftime("%d %B %Y"), "",
        "1. EXECUTIVE DECISION BRIEF",
        f"Listings tracked: {summary['listings_tracked']}",
        f"Areas monitored: {summary['areas_monitored']}",
        f"Sources: {summary['sources']}",
        f"New listings: {summary['changes']['new_listings']}",
        f"Price reductions: {summary['changes']['price_reductions']}",
        f"Price increases: {summary['changes']['price_increases']}",
        f"Median apartment asking sale: {summary['median_apartment_sale'] or 'N/A'}",
        f"Median annual apartment rent: {summary['median_annual_rent'] or 'N/A'}",
        f"Median land asking ₦/sqm: {summary['median_land_ppsqm'] or 'N/A'}", "",
        "2. WHAT HAPPENED THIS WEEK",
    ]
    lines += [f"• {x}" for x in summary.get("analysis_notes",[])] or ["• No interpretation available."]
    lines += ["","3. DECISION SIGNALS",
              f"Most expensive: {n(summary['signals'].get('most_expensive'))}",
              f"Rental / investment screen: {n(summary['signals'].get('investment'))}",
              f"Best buyer value screen: {n(summary['signals'].get('buyer_value'))}",
              f"Lowest observed land ₦/sqm: {n(summary['signals'].get('land_opportunity'))}",
              "Watch closely: "+(", ".join(x["market_node"] for x in summary["signals"].get("monitoring",[])) or "N/A"),"",
              "4. AREA SCORECARD"]
    for x in summary["scorecard"]:
        if x["listing_count"]:
            lines.append(f"{x['market_node']} — {x['listing_count']} listings | 3BR sale {x['sale_3br_median'] or 'N/A'} | 3BR rent {x['rent_3br_median'] or 'N/A'} | sale ₦/sqm {x['sale_ppsqm_median'] or 'N/A'} | land ₦/sqm {x['land_ppsqm_median'] or 'N/A'}")
    lines += ["","5. SIX-MONTH TREND VIEW"]
    trends=summary.get("trends",{})
    added=False
    for node,tr in trends.items():
        vals=[]
        for key,label in (("sale_pct","sale"),("rent_pct","rent"),("land_ppsqm_pct","land ₦/sqm")):
            if tr.get(key) is not None: vals.append(f"{label} {tr[key]:+.1f}%")
        if vals: lines.append(f"{node}: "+", ".join(vals)); added=True
    if not added: lines.append("Trend baseline is being established; future weekly runs will extend the six-month archive.")
    lines += ["","6. RECOMMENDED ACTIONS",
              "Use relative pricing and weekly movement to prioritise negotiations and areas for deeper diligence. Thinly sampled areas should be treated as watchlist signals, not definitive market indices.",
              "Prices are asking prices, not confirmed closed transactions. Estate Intel is public research only; premium/login-gated content is not collected or bypassed."]
    return "\n".join(lines)

def _format_requests(text):
    requests=[
        {"updateTextStyle":{"range":{"startIndex":1,"endIndex":len(text)+1},"textStyle":{"weightedFontFamily":{"fontFamily":"Arial"},"fontSize":{"magnitude":10,"unit":"PT"}},"fields":"weightedFontFamily,fontSize"}},
        {"updateParagraphStyle":{"range":{"startIndex":1,"endIndex":len(text)+1},"paragraphStyle":{"lineSpacing":115,"spaceBelow":{"magnitude":6,"unit":"PT"}},"fields":"lineSpacing,spaceBelow"}},
    ]
    offset=0
    lines=text.splitlines(True)
    for line in lines:
        raw=line.rstrip("\n")
        start=offset+1; end=start+len(raw)
        if raw.startswith("LAGOS PROPERTY MARKET"):
            requests.append({"updateTextStyle":{"range":{"startIndex":start,"endIndex":end+1},"textStyle":{"bold":True,"fontSize":{"magnitude":18,"unit":"PT"}},"fields":"bold,fontSize"}})
        elif raw[:2].isdigit() and ". " in raw[:5]:
            requests.append({"updateParagraphStyle":{"range":{"startIndex":start,"endIndex":end+1},"paragraphStyle":{"namedStyleType":"HEADING_1","spaceAbove":{"magnitude":10,"unit":"PT"},"spaceBelow":{"magnitude":4,"unit":"PT"}},"fields":"namedStyleType,spaceAbove,spaceBelow"}})
        offset += len(line)
    return requests

def publish(summary, output_docx=None):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    credentials=creds_from_env()
    docs=build("docs","v1",credentials=credentials,cache_discovery=False)
    drive=build("drive","v3",credentials=credentials,cache_discovery=False)
    doc_id=os.environ.get("GOOGLE_DOC_ID","").strip()
    title=f"Lagos Property Market — Weekly Intelligence Report — {datetime.now(timezone.utc):%Y-%m-%d}"
    text=report_text(summary)
    if doc_id:
        doc=docs.documents().get(documentId=doc_id).execute()
        body=doc.get("body",{}).get("content",[])
        end=max((x.get("endIndex",1) for x in body),default=1)-1
        requests=[]
        if end>1: requests.append({"deleteContentRange":{"range":{"startIndex":1,"endIndex":end}}})
        requests.append({"insertText":{"location":{"index":1},"text":text}})
        requests += _format_requests(text)
        docs.documents().batchUpdate(documentId=doc_id,body={"requests":requests}).execute()
    else:
        doc=docs.documents().create(body={"title":title}).execute()
        doc_id=doc["documentId"]
        requests=[{"insertText":{"location":{"index":1},"text":text}}]
        requests += _format_requests(text)
        docs.documents().batchUpdate(documentId=doc_id,body={"requests":requests}).execute()
    recipients=[]
    for key in ("REPORT_CLIENT_EMAIL","REPORT_TO_EMAIL"):
        recipients += [x.strip() for x in os.environ.get(key,"").split(",") if "@" in x]
    for email in dict.fromkeys(recipients):
        try:
            drive.permissions().create(fileId=doc_id,body={"type":"user","role":"reader","emailAddress":email},sendNotificationEmail=False).execute()
        except HttpError as exc:
            print(f"Google Doc sharing skipped for {email}: {exc}")
    url=f"https://docs.google.com/document/d/{doc_id}/edit"
    Path("google_doc_url.txt").write_text(url+"\n",encoding="utf-8")
    print(f"Google Doc published: {url}")
    if output_docx:
        Path(output_docx).write_text(url,encoding="utf-8")
    return doc_id,url

def main():
    if len(sys.argv)!=2: raise SystemExit("Usage: python docs_writer.py market_intelligence.json")
    payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    publish(payload["summary"])

if __name__=="__main__": main()
