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
    if not valid_email(client):
        raise SystemExit("REPORT_CLIENT_EMAIL is missing or malformed.")
    if not valid_email(internal):
        raise SystemExit("REPORT_TO_EMAIL is missing or malformed.")

    # Google publication can legitimately fall back to a DOCX attachment.
    # Never turn the fallback sentinel into a broken Google Docs hyperlink.
    doc_url_path = Path("client_doc_url.txt")
    if not doc_url_path.is_file():
        raise SystemExit("client_doc_url.txt is missing; report publication status is unknown.")
    doc_url = doc_url_path.read_text(encoding="utf-8").strip()
    if not doc_url.startswith("https://docs.google.com/document/d/"):
        if doc_url != "ATTACHED_DOCX_FALLBACK":
            raise SystemExit("client_doc_url.txt contains neither a verified Google Doc URL nor the explicit DOCX fallback marker.")
        doc_url = ""

    sheet_status = {"status": "not_verified"}
    status_path = Path("google_sheet_update_status.json")
    if status_path.is_file():
        try:
            import json
            candidate = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                sheet_status = candidate
        except Exception:
            sheet_status = {"status": "unknown"}
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    sheet_url = (
        "https://docs.google.com/spreadsheets/d/" + sheet_id + "/edit"
        if sheet_id and sheet_status.get("status") == "success"
        else ""
    )

    mime = mimetypes.guess_type(path.name)[0] or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    workbook_candidates = (
        list(Path(".").glob("market_intelligence_*.xlsx"))
        + list(Path("data").glob("market_intelligence_*.xlsx"))
    )
    workbook = max(
        workbook_candidates,
        key=lambda item: (item.name, item.parent == Path(".")),
    ) if workbook_candidates else None
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

    sheet_note = (
        "The existing live Google Sheet was updated and verified in this run."
        if sheet_url
        else "The existing live Google Sheet was not updated and verified in this run. Use the attached Excel workbook as the current data snapshot; no live-sheet link is provided."
    )
    doc_note = (
        f"Google Doc: {doc_url}\\n"
        if doc_url
        else "Google Docs publication was unavailable; the enhanced Word report is attached.\\n"
    )
    html_links = (
        f'<p><a href="{sheet_url}">Open the updated spreadsheet and dashboard</a></p>'
        if sheet_url else
        "<p><b>Spreadsheet:</b> The live Google Sheet was not updated and verified in this run. Use the attached Excel workbook as the current snapshot.</p>"
    )
    if doc_url:
        html_links += f'<p><a href="{doc_url}">Open the client Google Doc</a></p>'
    else:
        html_links += "<p><b>Google Doc:</b> Not published in this run; the enhanced Word report is attached.</p>"

    send_message(
        to=[client],
        cc=[internal],
        subject="Final Weekly Nigeria Property Market Snapshot — Word Report Attached",
        text_body=(
            "Attached are the final enhanced Word report and, when generated, "
            "the market-intelligence Excel workbook with charts and source-level data. "
            "The Word report includes sample-size notes, land plot-size/price-per-sqm "
            "analysis where available, and a data-quality exception review. "
            "Asking prices are not completed transaction prices. Verify material "
            "figures using original listing links.\\n\\n"
            + sheet_note + "\\n"
            + doc_note
            + "Reporting schedule: Monday at 08:00 Africa/Lagos. Mailjet acceptance "
            "is recorded in the run audit; it does not prove inbox placement or reading."
        ),
        html_body=(
            "<p>Attached are the final enhanced Word report and, when generated, "
            "the market-intelligence Excel workbook with charts and source-level data. "
            "The Word report includes sample-size notes, land plot-size/price-per-sqm "
            "analysis where available, and a data-quality exception review.</p>"
            "<p><b>Important:</b> asking prices are not completed transaction prices. "
            "Verify material figures against original listing links.</p>"
            + html_links
            + "<p>Reporting schedule: Monday at 08:00 Africa/Lagos. Mailjet acceptance "
              "is recorded in the run audit; it does not prove inbox placement or reading.</p>"
        ),
        layer="client_docx",
        attachments=attachments,
    )


if __name__ == "__main__":
    main()
