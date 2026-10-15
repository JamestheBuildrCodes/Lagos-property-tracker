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
    if not valid_email(client):
        raise SystemExit("REPORT_CLIENT_EMAIL is missing or malformed.")
    if not valid_email(internal):
        raise SystemExit("REPORT_TO_EMAIL is missing or malformed.")
    if not sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID is required to include the spreadsheet link.")
    mime = mimetypes.guess_type(path.name)[0] or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    sheet_url = "https://docs.google.com/spreadsheets/d/" + sheet_id + "/edit"
    send_message(
        to=[client],
        cc=[internal],
        subject="Final Weekly Nigeria Property Market Snapshot — Word Report Attached",
        text_body=(
            "Attached is the final enhanced weekly property market report, including charts, "
            "sample-size notes, land plot-size/price-per-sqm analysis where available, and a "
            "data-quality exception review. Asking prices are not completed transaction prices. "
            "Please use original listing links to verify material figures.\n\n"
            f"Live spreadsheet and dashboard: {sheet_url}\n"
            "Reporting schedule: Monday at 08:00 Africa/Lagos. Provider acceptance is recorded "
            "in the run audit; it does not prove inbox placement or reading."
        ),
        html_body=(
            "<p>Attached is the final enhanced weekly property market report, including charts, "
            "sample-size notes, land plot-size/price-per-sqm analysis where available, and a "
            "data-quality exception review.</p>"
            "<p><b>Important:</b> asking prices are not completed transaction prices. Verify "
            "material figures against original listing links.</p>"
            f'<p><a href="{sheet_url}">Open the live spreadsheet and dashboard</a></p>'
            "<p>Reporting schedule: Monday at 08:00 Africa/Lagos. Provider acceptance is recorded "
            "in the run audit; it does not prove inbox placement or reading.</p>"
        ),
        layer="client_docx",
        attachments=[{
            "ContentType": mime,
            "Filename": path.name,
            "Base64Content": base64.b64encode(path.read_bytes()).decode("ascii"),
        }],
    )

if __name__ == "__main__":
    main()
