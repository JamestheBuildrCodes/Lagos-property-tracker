"""Mirror the reporting workbook into the existing Google Sheet with a client-first layout."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
DESIRED=["Executive Summary","Area Scorecard","Current Listings","Weekly Changes","Estate Intel Public","Source Health","Methodology"]
NAVY={"red":0.05,"green":0.14,"blue":0.25}; LIGHT={"red":0.91,"green":0.94,"blue":0.97}; WHITE={"red":1,"green":1,"blue":1}; TEXT={"red":0.09,"green":0.13,"blue":0.20}
def get_client():
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON","").strip()
    if not raw: raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    data=json.loads(raw); email=data.get("client_email") or "unknown"; project=data.get("project_id") or "unknown"
    print(f"Google service account: {email} | project: {project}")
    return gspread.authorize(Credentials.from_service_account_info(data,scopes=SCOPES)),email
def share_viewer(sheet_id,email):
    if not email or "@" not in email:return
    from googleapiclient.discovery import build
    client,_=get_client(); drive=build("drive","v3",credentials=client.auth,cache_discovery=False)
    drive.permissions().create(fileId=sheet_id,body={"type":"user","role":"reader","emailAddress":email},sendNotificationEmail=False).execute(); print(f"Google Sheet viewer access granted: {email}")
def style(ws,name,rows,cols):
    ws.clear_basic_filter(); ws.freeze(rows=3 if name=="Executive Summary" else 1)
    ws.format(f"A1:{gspread.utils.rowcol_to_a1(1,cols)}",{"backgroundColor":NAVY,"textFormat":{"foregroundColor":WHITE,"bold":True,"fontSize":11},"verticalAlignment":"MIDDLE"})
    if name=="Executive Summary":
        ws.format("A2:C2",{"textFormat":{"foregroundColor":TEXT,"italic":True}})
        ws.format("A3:C3",{"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True},"horizontalAlignment":"LEFT"})
        ws.format("A14:C14",{"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True,"fontSize":12}})
        ws.format("A21:C21",{"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True,"fontSize":12}})
    ws.format(f"A1:{gspread.utils.rowcol_to_a1(rows,cols)}",{"wrapStrategy":"WRAP","verticalAlignment":"TOP","textFormat":{"foregroundColor":TEXT}})
    # Emphasise the headline metric values on the Executive Summary.
    if name=="Executive Summary": ws.format("B4:B12",{"textFormat":{"bold":True,"foregroundColor":NAVY}})
    try: ws.columns_auto_resize(0,cols)
    except Exception as exc: print(f"Column auto-resize skipped for {name}: {exc}")
def run():
    if len(sys.argv)<2: raise SystemExit("Usage: python sheets_writer.py <listings.csv> [changes.csv] [research.csv] [xlsx_path]")
    xlsx_path=sys.argv[4] if len(sys.argv)>4 else ""
    sheet_id=os.environ.get("GOOGLE_SHEET_ID","").strip()
    if not sheet_id: raise RuntimeError("GOOGLE_SHEET_ID is missing")
    if not xlsx_path or not Path(xlsx_path).exists(): raise RuntimeError("Layer 2 workbook is missing.")
    client,service_email=get_client()
    try: sheet=client.open_by_key(sheet_id)
    except Exception as exc: raise RuntimeError(f"Could not open Google Sheet. Confirm GOOGLE_SHEET_ID and share the existing sheet with {service_email} as Editor. Original error: {exc}") from exc
    from openpyxl import load_workbook
    wb=load_workbook(xlsx_path,data_only=False)
    for name in DESIRED:
        if name not in wb.sheetnames: continue
        values=[[cell.value for cell in row] for row in wb[name].iter_rows()]
        if not values: continue
        try: ws=sheet.worksheet(name); ws.clear()
        except gspread.WorksheetNotFound: ws=sheet.add_worksheet(title=name,rows=max(len(values)+10,100),cols=max(max(len(r) for r in values),10))
        rows=max(len(values)+5,20); cols=max(max((len(r) for r in values),default=1)+2,10); ws.resize(rows=rows,cols=cols); ws.update(values,"A1")
        style(ws,name,rows,cols)
        if name in {"Current Listings","Weekly Changes","Estate Intel Public"}: ws.freeze(rows=1)
        if name=="Current Listings":
            try:
                header=[str(x or "").lower() for x in values[0]]
                for idx,h in enumerate(header,1):
                    if "asking_price" in h or "price_per_sqm" in h or "rent" in h: ws.format(f"{gspread.utils.rowcol_to_a1(1,idx).replace('1','')}2:{gspread.utils.rowcol_to_a1(rows,idx)}",{"numberFormat":{"type":"NUMBER","pattern":"₦#,##0"}})
            except Exception as exc: print(f"Currency formatting skipped: {exc}")
    client_email=os.environ.get("REPORT_CLIENT_EMAIL","").strip()
    if client_email:
        try: share_viewer(sheet_id,client_email)
        except Exception as exc: print(f"Client Sheet sharing skipped: {exc}")
    print(f"Google Sheets updated and styled: {sheet.title}")
if __name__=="__main__": run()
