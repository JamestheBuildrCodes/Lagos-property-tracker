"""Mirror the reporting workbook into the existing Google Sheet with a client-first layout."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
DESIRED=["Executive Summary","Area Scorecard","Current Listings","Weekly Changes","Estate Intel Public","Additional Sources","Source Health","Methodology"]
NAVY={"red":0.05,"green":0.14,"blue":0.25}; LIGHT={"red":0.91,"green":0.94,"blue":0.97}; WHITE={"red":1,"green":1,"blue":1}; TEXT={"red":0.09,"green":0.13,"blue":0.20}
def _retry_sheets_write(label, operation, *args, max_attempts=6, **kwargs):
    """Retry transient Google Sheets write failures with exponential backoff.

    Sheets enforces per-user write quotas. Waiting for the quota window to roll
    over is safer than failing the entire weekly report on a temporary HTTP 429.
    Non-quota API errors are raised immediately.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return operation(*args, **kwargs)
        except gspread.exceptions.APIError as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None) or getattr(exc, "code", None)
            message = str(exc).lower()
            retryable = status in {429, 500, 502, 503, 504} or (
                "quota exceeded" in message or "rate limit" in message
            )
            if not retryable or attempt >= max_attempts:
                raise
            # 5s, 10s, 20s, 40s, then up to 60s: lets a per-minute
            # quota window reset while retaining a bounded overall wait.
            delay = min(60, 5 * (2 ** (attempt - 1)))
            print(
                f"Google Sheets write '{label}' hit a temporary API limit "
                f"(HTTP {status or 'unknown'}); retrying in {delay}s "
                f"(attempt {attempt}/{max_attempts - 1})."
            )
            time.sleep(delay)


def get_client():
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON","").strip()
    if not raw: raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    data=json.loads(raw); email=data.get("client_email") or "unknown"; project=data.get("project_id") or "unknown"
    print(f"Google service account: {email} | project: {project}")
    return gspread.authorize(Credentials.from_service_account_info(data,scopes=SCOPES)),email
def share_viewer(sheet_id,email):
    if not email or "@" not in email:
        raise RuntimeError("REPORT_CLIENT_EMAIL is missing or invalid; cannot verify client Sheet access.")
    from googleapiclient.discovery import build
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON","").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    credentials=Credentials.from_service_account_info(json.loads(raw),scopes=SCOPES)
    drive=build("drive","v3",credentials=credentials,cache_discovery=False)
    def find_permission():
        permissions=drive.permissions().list(
            fileId=sheet_id,
            fields="permissions(id,type,role,emailAddress,deleted)",
            supportsAllDrives=True,
        ).execute().get("permissions",[])
        return next((p for p in permissions if p.get("type")=="user"
            and str(p.get("emailAddress","")).lower()==email.lower()
            and not p.get("deleted",False)),None)
    permission=find_permission()
    if permission is None:
        drive.permissions().create(
            fileId=sheet_id,
            body={"type":"user","role":"reader","emailAddress":email},
            sendNotificationEmail=True,
            supportsAllDrives=True,
            fields="id,type,role,emailAddress",
        ).execute()
        permission=find_permission()
    if permission is None or permission.get("role") not in {"owner","organizer","fileOrganizer","writer","commenter","reader"}:
        raise RuntimeError(f"Google Drive did not confirm client viewer access for {email}.")
    print(f"Google Sheet viewer access verified: {email}; role={permission.get('role')}")
def style(ws,name,rows,cols):
    _retry_sheets_write(f"{name}: clear filter", ws.clear_basic_filter)
    _retry_sheets_write(
        f"{name}: freeze header", ws.freeze,
        rows=3 if name=="Executive Summary" else 1
    )
    _retry_sheets_write(
        f"{name}: style title",
        ws.format,
        f"A1:{gspread.utils.rowcol_to_a1(1,cols)}",
        {"backgroundColor":NAVY,"textFormat":{"foregroundColor":WHITE,"bold":True,"fontSize":11},"verticalAlignment":"MIDDLE"}
    )
    if name=="Executive Summary":
        _retry_sheets_write(
            f"{name}: style date", ws.format, "A2:C2",
            {"textFormat":{"foregroundColor":TEXT,"italic":True}}
        )
        _retry_sheets_write(
            f"{name}: style column headings", ws.format, "A3:C3",
            {"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True},"horizontalAlignment":"LEFT"}
        )
        _retry_sheets_write(
            f"{name}: style decision signals", ws.format, "A14:C14",
            {"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True,"fontSize":12}}
        )
        _retry_sheets_write(
            f"{name}: style market interpretation", ws.format, "A21:C21",
            {"backgroundColor":LIGHT,"textFormat":{"foregroundColor":NAVY,"bold":True,"fontSize":12}}
        )
    _retry_sheets_write(
        f"{name}: wrap worksheet", ws.format,
        f"A1:{gspread.utils.rowcol_to_a1(rows,cols)}",
        {"wrapStrategy":"WRAP","verticalAlignment":"TOP","textFormat":{"foregroundColor":TEXT}}
    )
    # Emphasise the headline metric values on the Executive Summary.
    if name=="Executive Summary":
        _retry_sheets_write(
            f"{name}: emphasize headline metrics", ws.format, "B4:B12",
            {"textFormat":{"bold":True,"foregroundColor":NAVY}}
        )
    try:
        _retry_sheets_write(
            f"{name}: auto resize columns", ws.columns_auto_resize, 0, cols
        )
    except Exception as exc:
        print(f"Column auto-resize skipped for {name}: {exc}")

def add_live_chart_dashboard(sheet):
    """Create/update the chart dashboard with quota-aware Google Sheets writes."""
    score = sheet.worksheet("Area Scorecard")
    try:
        dashboard = sheet.worksheet("Charts & Commentary")
    except gspread.WorksheetNotFound:
        dashboard = _retry_sheets_write(
            "create Charts & Commentary dashboard",
            sheet.add_worksheet, title="Charts & Commentary", rows=60, cols=16
        )

    # The dashboard contains fixed explanatory copy and embedded charts. Do not
    # clear or resize it on every weekly run; that adds two quota-consuming
    # writes without changing the layout. Overwrite the five populated cells.
    _retry_sheets_write(
        "update dashboard commentary",
        dashboard.update,
        [
            ["Charts & Commentary — current asking-price observations"],
            ["These graphs compare the validated listing sample; they are not closed transaction prices or a full-market census."],
            ["Read with Area Scorecard sample counts. Segments with fewer than five comparables are thin and should be treated as directional."],
            ["Source assessment: Knight Frank Nigeria research is contextual only; C&W Nigeria/Lagos comparable coverage remains unverified."],
            ["Distribution: weekly Monday 08:00 Lagos time; the send receipt verifies provider acceptance, not final inbox placement. Estate Intel commercial status requires direct confirmation."],
        ],
        "A1"
    )
    _retry_sheets_write(
        "format dashboard title", dashboard.format, "A1:P1",
        {"backgroundColor": NAVY, "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 13}}
    )
    _retry_sheets_write(
        "format dashboard commentary", dashboard.format, "A2:P5",
        {"wrapStrategy": "WRAP", "verticalAlignment": "TOP", "textFormat": {"foregroundColor": TEXT}}
    )

    metadata = sheet.fetch_sheet_metadata()
    requests = []
    for tab in metadata.get("sheets", []):
        if tab.get("properties", {}).get("sheetId") == dashboard.id:
            for chart in tab.get("charts", []):
                chart_id = chart.get("chartId")
                if chart_id is not None:
                    requests.append({"deleteEmbeddedObject": {"objectId": chart_id}})
    chart_specs = [
        ("Three-bedroom sale asking price by area", 2, 5, 0),
        ("Three-bedroom annual rent asking price by area", 3, 23, 0),
        ("Land asking price per sqm by area", 7, 43, 0),
    ]
    for title, source_col, anchor_row, anchor_col in chart_specs:
        requests.append({
            "addChart": {
                "chart": {
                    "spec": {
                        "title": title,
                        "basicChart": {
                            "chartType": "BAR",
                            "legendPosition": "NO_LEGEND",
                            "headerCount": 1,
                            "domains": [{"domain": {"sourceRange": {"sources": [{
                                "sheetId": score.id, "startRowIndex": 0, "endRowIndex": 10,
                                "startColumnIndex": 0, "endColumnIndex": 1,
                            }]}}}],
                            "series": [{"series": {"sourceRange": {"sources": [{
                                "sheetId": score.id, "startRowIndex": 0, "endRowIndex": 10,
                                "startColumnIndex": source_col, "endColumnIndex": source_col + 1,
                            }]}}, "targetAxis": "BOTTOM_AXIS"}],
                            "axis": [
                                {"position": "BOTTOM_AXIS", "title": "Asking price (NGN)"},
                                {"position": "LEFT_AXIS", "title": "Area"},
                            ],
                        },
                    },
                    "position": {"overlayPosition": {
                        "anchorCell": {"sheetId": dashboard.id, "rowIndex": anchor_row, "columnIndex": anchor_col},
                        "widthPixels": 620, "heightPixels": 340,
                    }},
                }
            }
        })
    _retry_sheets_write(
        "refresh dashboard charts", sheet.batch_update, {"requests": requests}
    )
    print("Google Sheets chart dashboard updated with three live area-comparison charts.")


def _verify_sheet_readback(name, expected_values, written_values):
    """Compare a worksheet write while accounting for Sheets omitting trailing empty cells.

    The Google Sheets values API may omit empty cells at the end of each row and
    entirely empty trailing rows. Normalize both grids to the workbook's expected
    rectangle, but still fail on any missing or changed non-empty value.
    """
    row_count = len(expected_values)
    width = max((len(row) for row in expected_values), default=0)

    def normalize(value):
        # Compare underlying values, not display formatting. Google Sheets can
        # return numbers as floats while Excel stores the same values as ints;
        # its formatted-value mode can also add commas, currency symbols, or
        # rounding based on stale formatting on an existing worksheet.
        if value is None or value == "":
            return ("blank", "")
        if isinstance(value, bool):
            return ("bool", value)
        if isinstance(value, (int, float)):
            return ("number", float(value))
        if isinstance(value, str):
            return ("string", value)
        return ("string", str(value))

    def rectangular_grid(grid):
        normalized = []
        for row_index in range(row_count):
            row = grid[row_index] if row_index < len(grid) else []
            normalized.append([
                normalize(row[col_index] if col_index < len(row) else None)
                for col_index in range(width)
            ])
        return normalized

    expected = rectangular_grid(expected_values)
    actual = rectangular_grid(written_values)
    for row_index, (expected_row, actual_row) in enumerate(zip(expected, actual), start=1):
        for col_index, (expected_cell, actual_cell) in enumerate(zip(expected_row, actual_row), start=1):
            equal = expected_cell == actual_cell
            if expected_cell[0] == actual_cell[0] == "number":
                equal = abs(expected_cell[1] - actual_cell[1]) <= max(
                    1e-9, abs(expected_cell[1]) * 1e-12
                )
            if not equal:
                cell = gspread.utils.rowcol_to_a1(row_index, col_index)
                raise RuntimeError(
                    f"Google Sheet readback mismatch in worksheet '{name}' at {cell}; "
                    f"value types {expected_cell[0]} vs {actual_cell[0]} (values omitted from log)."
                )


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
        try:
            ws=sheet.worksheet(name)
            _retry_sheets_write(f"{name}: clear previous values", ws.clear)
        except gspread.WorksheetNotFound:
            ws=_retry_sheets_write(
                f"{name}: create worksheet", sheet.add_worksheet,
                title=name, rows=max(len(values)+10,100),
                cols=max(max(len(r) for r in values),10)
            )
        rows=max(len(values)+5,25); cols=max(max((len(r) for r in values),default=1)+2,10)
        _retry_sheets_write(f"{name}: resize worksheet", ws.resize, rows=rows, cols=cols)
        _retry_sheets_write(f"{name}: write workbook values", ws.update, values, "A1")
        # Read back the written range from the live Google Sheet and compare
        # it with the exact workbook values. This catches partial writes,
        # row/column drift, and stale-tab updates before the run is reported
        # as successful.
        written = ws.get(
            f"A1:{gspread.utils.rowcol_to_a1(len(values), max(len(r) for r in values))}",
            value_render_option="UNFORMATTED_VALUE",
        )
        _verify_sheet_readback(name, values, written)
        style(ws,name,rows,cols)
        if name in {"Current Listings","Weekly Changes","Estate Intel Public"}: ws.freeze(rows=1)
        if name=="Current Listings":
            try:
                header=[str(x or "").lower() for x in values[0]]
                for idx,h in enumerate(header,1):
                    if "asking_price" in h or "price_per_sqm" in h or "rent" in h:
                        _retry_sheets_write(
                            f"Current Listings: currency format column {idx}",
                            ws.format,
                            f"{gspread.utils.rowcol_to_a1(1,idx).replace('1','')}2:{gspread.utils.rowcol_to_a1(rows,idx)}",
                            {"numberFormat":{"type":"NUMBER","pattern":"₦#,##0"}}
                        )
            except Exception as exc: print(f"Currency formatting skipped: {exc}")
    add_live_chart_dashboard(sheet)
    client_email=os.environ.get("REPORT_CLIENT_EMAIL","").strip()
    if client_email:
        try:
            share_viewer(sheet_id,client_email)
        except Exception as exc:
            raise RuntimeError(f"Could not verify client access to the Google Sheet; refusing to email an inaccessible link: {exc}") from exc
    print(f"Google Sheets updated and styled: {sheet.title}")
if __name__=="__main__": run()
