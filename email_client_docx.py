"""Email the final enhanced DOCX report as an attachment with a Mailjet receipt."""
from __future__ import annotations
import base64
import mimetypes
import os
import sys
from pathlib import Path
from mailjet_sender import recipients_from_values, send_message, valid_email

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python email_client_docx.py final_report.docx")
    path = Path(sys.argv[1])
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit("Refusing to send a missing or empty client DOCX.")
    client = os.environ.get("REPORT_CLIENT_EMAIL", "").strip()
    internal = os.environ.get("REPORT_TO_EMAIL", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    doc_url_path = Path("client_doc_url.txt")
    if not valid_email(client):
        raise SystemExit("REPORT_CLIENT_EMAIL is missing or malformed.")
    if not valid_email(internal):
        raise SystemExit("REPORT_TO_EMAIL is missing or malformed.")
    if not sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID is required to include the spreadsheet link.")
    if not doc_url_path.is_file():
        raise SystemExit("Verified client_doc_url.txt is required to include the Google Doc link.")
    doc_url = doc_url_path.read_text(encoding="utf-8").strip()
    if not doc_url.startswith("https://docs.google.com/document/d/"):
        raise SystemExit("client_doc_url.txt does not contain a valid Google Doc URL.")
    mime = mimetypes.guess_type(path.name)[0] or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    sheet_url = "https://docs.google.com/spreadsheets/d/" + sheet_id + "/edit"
    sheet_status = {"status": "not_verified"}
    status_path = Path("google_sheet_update_status.json")
    if status_path.is_file():
        try:
            import json
            sheet_status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            sheet_status = {"status": "unknown"}
    workbook_candidates = list(Path(".").glob("market_intelligence_*.xlsx")) + list(Path("data").glob("market_intelligence_*.xlsx"))
    workbook = max(workbook_candidates, key=lambda item: (item.name, item.parent == Path("."))) if workbook_candidates else None
    attachments = [{
        "ContentType": mime,
        "Filename": path.name,
        "Base64Content": base64.b64encode(path.read_bytes()).decode("ascii"),
    }]
    if workbook and workbook.is_file() and workbook.stat().st_size > 0:
        workbook_mime = mimetypes.guess_type(workbook.name)[0] or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        attachments.append({
            "ContentType": workbook_mime,
            "Filename": workbook.name,
            "Base64Content": base64.b64encode(workbook.read_bytes()).decode("ascii"),
        })
        print(f"Attaching client XLSX workbook: {workbook}")
    else:
        print("No generated market intelligence XLSX found; sending the enhanced DOCX only.")
    send_message(
        to=[client],
        cc=[internal],
        subject="Final Weekly Nigeria Property Market Snapshot — Word Report Attached",
        text_body=(
            "Attached are the final enhanced Word report and, when generated, the market-intelligence Excel workbook with charts and source-level data. "
            "The Word report includes sample-size notes, land plot-size/price-per-sqm analysis where available, and a data-quality exception review. "
            "Asking prices are not completed transaction prices. Please use original listing links to verify material figures.\n\n"
            f"Spreadsheet/dashboard ({sheet_status.get('status', 'not_verified')} this run): {sheet_url}\n"
            f"Google Doc: {doc_url}\n"
            "The attached Excel workbook is the authoritative snapshot if the live sheet update was not verified.\n"
            "Reporting schedule: Monday at 08:00 Africa/Lagos. Provider acceptance is recorded "
            "in the run audit; it does not prove inbox placement or reading."
        ),
        html_body=(
            "<p>Attached are the final enhanced Word report and, when generated, the market-intelligence Excel workbook with charts and source-level data. "
            "The Word report includes sample-size notes, land plot-size/price-per-sqm analysis where available, and a data-quality exception review.</p>"
            "<p><b>Important:</b> asking prices are not completed transaction prices. Verify "
            "material figures against original listing links.</p>"
            f'<p><a href="{sheet_url}">Open the spreadsheet and dashboard (update status: {sheet_status.get("status", "not_verified")})</a></p>'
            f'<p><a href="{doc_url}">Open the client Google Doc</a></p>'
            "<p>The attached Excel workbook is the authoritative snapshot if the live sheet update was not verified this run.</p>"
            "<p>Reporting schedule: Monday at 08:00 Africa/Lagos. Provider acceptance is recorded "
            "in the run audit; it does not prove inbox placement or reading.</p>"
        ),
        layer="client_docx",
        attachments=attachments,
    )

if __name__ == "__main__":
    main()
