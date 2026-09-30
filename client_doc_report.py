"""Client-preferred weekly report — matches the exact template, fonts, and
colors of the reference document the client approved (Nigeria Real Estate
Market Snapshot style).

This is a SEPARATE, ADDITIONAL report — it does not replace the existing
automated executive brief (email_report.py / docs_writer.py). Both run
every week. This one is a BRAND NEW Google Doc every week (never updated
in place), matching what the client explicitly asked for.

SCOPE NOTE, stated plainly: the reference document covered Lagos, Abuja,
AND Port Harcourt. The live scraper (see market_analysis.py's NODES list)
only tracks 9 nodes across Lagos and Abuja — Port Harcourt is not a real
tracked source in this pipeline. This report covers what's actually
tracked. Adding Port Harcourt would mean adding real scraping targets for
it first, not just a formatting change — that's a separate decision.

Confirmed exact styling, extracted directly from the client's approved
reference document (python-docx style inspection, not guessed):
  Title:      Times New Roman, 28pt, black, bold=False (Word's Title style)
  Heading 1:  Times New Roman, 16pt, #2E74B5 (city names)
  Heading 2:  Times New Roman, 13pt, #2E74B5 (node/category subsections)
  Subtitle:   12pt, default color
  Date line:  10pt, #666666 (gray)
  Table header row: #D9D9D9 fill, bold text
  Table data cells: plain text, with a real hyperlink in the "Link" column

Run locally:
    pip install python-docx google-api-python-client google-auth
    export GOOGLE_SERVICE_ACCOUNT_JSON=...
    export MJ_APIKEY_PUBLIC=... MJ_APIKEY_PRIVATE=...
    export REPORT_CLIENT_EMAIL=... REPORT_TO_EMAIL=...
    python client_doc_report.py property_listings_2026-09-29.csv
"""
from __future__ import annotations
import json, os, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

from market_analysis import (
    NODES, clean_rows, fnum, fmt_naira, load_csv, normalize_node,
    transaction_label, is_apartment, build_summary,
)

BLUE = "2E74B5"
GRAY = "666666"
HEADER_FILL = "D9D9D9"

# Which nodes belong to which city, for section grouping — matches
# market_analysis.py's NODES list exactly (no Port Harcourt, see note above).
LAGOS_NODES = ["Banana Island", "Old Ikoyi", "Lekki Phase 1", "Victoria Island", "Eko Atlantic", "Ikeja GRA"]
ABUJA_NODES = ["Asokoro", "Maitama", "Wuse"]


def bedroom_breakdown(listings, node, txn_type):
    """Groups real listings for one node+transaction into per-bedroom-count
    rows: median price, sample size, and one representative real listing
    (the most recently scraped) to cite as an example — never presented as
    'the source of the average', just a real, checkable example from the
    group it's attached to."""
    listings = clean_rows(listings)
    by_beds = {}
    for row in listings:
        r = dict(row)
        r_node = normalize_node(r.get("market_node") or r.get("location"))
        url = (r.get("source_url") or "").strip()
        if r_node != node or transaction_label(r) != txn_type or not is_apartment(r):
            continue
        if not url.startswith(("https://", "http://")):
            continue
        beds = r.get("bedrooms")
        if beds in (None, ""):
            continue
        by_beds.setdefault(str(beds), []).append(r)

    rows = []
    for beds in sorted(by_beds.keys(), key=lambda x: fnum(x) or 0):
        group = by_beds[beds]
        priced = [r for r in group if fnum(r.get("asking_price_ngn")) and
                  (r.get("source_url") or "").strip().startswith(("https://", "http://"))]
        prices = [fnum(r.get("asking_price_ngn")) for r in priced]
        if not prices:
            continue
        med = statistics.median(prices)
        example = sorted(priced, key=lambda r: r.get("date_scraped") or "", reverse=True)[0]
        rows.append({
            "label": f"{beds} Bedroom — median asking {'rent' if txn_type == 'rent' else 'sale price'}",
            "value": fmt_naira(med) + ("/yr" if txn_type == "rent" else ""),
            "sample": f"{len(prices)} listing{'s' if len(prices) != 1 else ''}",
            "source_date": f"{example.get('source', 'Unknown')}, as of {example.get('date_scraped', 'unknown date')}",
            "link": example.get("source_url", ""),
        })
    return rows


def land_breakdown(listings, node):
    listings = clean_rows(listings)
    group = [r for r in listings if normalize_node(r.get("market_node") or r.get("location")) == node
             and transaction_label(r) == "land"
             and (r.get("source_url") or "").strip().startswith(("https://", "http://"))
             and fnum(r.get("asking_price_ngn"))]
    prices = [fnum(r.get("asking_price_ngn")) for r in group]
    if not prices:
        return []
    med = statistics.median(prices)
    example = sorted(group, key=lambda r: r.get("date_scraped") or "", reverse=True)[0]
    return [{
        "label": "Land — median asking price",
        "value": fmt_naira(med),
        "sample": f"{len(prices)} listing{'s' if len(prices) != 1 else ''}",
        "source_date": f"{example.get('source', 'Unknown')}, as of {example.get('date_scraped', 'unknown date')}",
        "link": example.get("source_url", ""),
    }]


def build_docx(listings, summary, output=None):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    output = output or f"Lagos_Property_Market_Snapshot_{datetime.now(timezone.utc):%Y-%m-%d}.docx"
    doc = Document()

    def set_font(run, size, color=None, name="Times New Roman"):
        run.font.name = name
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    title = doc.add_paragraph(style="Title")
    r = title.add_run("Lagos & Abuja Property Market Snapshot")
    set_font(r, 28, "000000")
    sub = doc.add_paragraph()
    r = sub.add_run("Weekly Intelligence Report — Real Tracked Listings, Linked to Source")
    set_font(r, 12)
    date_p = doc.add_paragraph()
    r = date_p.add_run(f"Data captured {datetime.now(timezone.utc):%d %B %Y}")
    set_font(r, 10, GRAY)

    def h1(text):
        p = doc.add_paragraph(style="Heading 1")
        r = p.add_run(text)
        set_font(r, 16, BLUE)
        return p

    def h2(text):
        p = doc.add_paragraph(style="Heading 2")
        r = p.add_run(text)
        set_font(r, 13, BLUE)
        return p

    def body(text):
        p = doc.add_paragraph()
        r = p.add_run(text)
        set_font(r, 11)
        return p

    def add_hyperlink(paragraph, url, text):
        part = paragraph.part
        r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        new_run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        color = OxmlElement("w:color"); color.set(qn("w:val"), "1155CC")
        u = OxmlElement("w:u"); u.set(qn("w:val"), "single")
        rPr.append(color); rPr.append(u)
        new_run.append(rPr)
        t = OxmlElement("w:t"); t.text = text
        new_run.append(t)
        hyperlink.append(new_run)
        paragraph._p.append(hyperlink)

    def data_table(rows):
        if not rows:
            body("No comparable listings for this category yet.")
            return
        t = doc.add_table(rows=1, cols=5)
        headers = ["Metric", "Value", "Sample", "Source & Date", "Link"]
        for i, htext in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = ""
            p = cell.paragraphs[0]
            r = p.add_run(htext)
            r.bold = True
            set_font(r, 10)
            tcPr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), HEADER_FILL)
            tcPr.append(shd)
        for row_data in rows:
            cells = t.add_row().cells
            for i, key in enumerate(["label", "value", "sample", "source_date"]):
                p = cells[i].paragraphs[0]
                r = p.add_run(str(row_data[key]))
                set_font(r, 10)
            link_p = cells[4].paragraphs[0]
            if row_data.get("link"):
                add_hyperlink(link_p, row_data["link"], "View source")
            else:
                r = link_p.add_run("—"); set_font(r, 10)
        doc.add_paragraph()

    body("Every price below is from a real, currently tracked listing — click \"View source\" on any row to see the exact listing it came from. These are asking prices, not confirmed closed transactions.")

    h1("Lagos")
    for node in LAGOS_NODES:
        rent_rows = bedroom_breakdown(listings, node, "rent")
        sale_rows = bedroom_breakdown(listings, node, "sale")
        land_rows = land_breakdown(listings, node)
        if not (rent_rows or sale_rows or land_rows):
            continue
        h2(node)
        if rent_rows:
            body("Rental Market (per annum)"); data_table(rent_rows)
        if sale_rows:
            body("Sales Market"); data_table(sale_rows)
        if land_rows:
            body("Land"); data_table(land_rows)

    h1("Abuja")
    for node in ABUJA_NODES:
        rent_rows = bedroom_breakdown(listings, node, "rent")
        sale_rows = bedroom_breakdown(listings, node, "sale")
        land_rows = land_breakdown(listings, node)
        if not (rent_rows or sale_rows or land_rows):
            continue
        h2(node)
        if rent_rows:
            body("Rental Market (per annum)"); data_table(rent_rows)
        if sale_rows:
            body("Sales Market"); data_table(sale_rows)
        if land_rows:
            body("Land"); data_table(land_rows)

    h1("What Stands Out This Week")
    sig = summary["signals"]
    for label, obj in [("Most expensive area", sig.get("most_expensive")), ("Strongest rental/yield screen", sig.get("investment")),
            ("Best buyer value screen", sig.get("buyer_value")), ("Lowest observed land ₦/sqm", sig.get("land_opportunity"))]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{label}: {obj['market_node'] if obj else 'Not enough data yet'}")
        set_font(r, 11)

    h1("Sources Used in This Report")
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run(", ".join(summary.get("source_names", [])) or "No sources recorded")
    set_font(r, 11)
    body("Every figure above links directly to the real listing it came from, so any number here can be independently checked.")

    doc.save(output)
    return output


def _iter_placeholder_paragraphs(docs, doc_id):
    doc = docs.documents().get(documentId=doc_id).execute()
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        text = "".join(r.get("textRun", {}).get("content", "") for r in para.get("elements", []))
        if text.strip().startswith("[[TABLE:"):
            yield el["startIndex"], el["endIndex"], text.strip()


def publish_google_doc(listings, summary):
    """Creates a BRAND NEW Google Doc every run (never reuses an existing
    doc ID) — matches the client's explicit 'every week a new document'
    request. Table insertion follows the same reverse-order index-safety
    pattern as docs_writer.py's _fill_table, generalized to handle many
    tables across the document. NOT tested against a live document in
    this session (no live API access here) — verify on first real run."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import json as _json
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        _json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"])
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Lagos & Abuja Property Market Snapshot — {date_str}"
    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # Build plain text with [[TABLE:key]] placeholders, tracking which
    # rows belong to each placeholder for the fill step.
    subtitle = "Weekly Intelligence Report — Real Tracked Listings, Linked to Source"
    lines = [title, subtitle, f"Data captured {datetime.now(timezone.utc):%d %B %Y}", "",
             "Every price below is from a real, currently tracked listing — click the source link on any row to see the exact listing it came from."]
    table_data = {}

    def add_city(city_name, node_list):
        lines.append(city_name)
        for node in node_list:
            rent_rows = bedroom_breakdown(listings, node, "rent")
            sale_rows = bedroom_breakdown(listings, node, "sale")
            land_rows = land_breakdown(listings, node)
            if not (rent_rows or sale_rows or land_rows):
                continue
            lines.append(node)
            if rent_rows:
                key = f"{node}_rent"; table_data[key] = rent_rows
                lines.append("Rental Market (per annum)"); lines.append(f"[[TABLE:{key}]]")
            if sale_rows:
                key = f"{node}_sale"; table_data[key] = sale_rows
                lines.append("Sales Market"); lines.append(f"[[TABLE:{key}]]")
            if land_rows:
                key = f"{node}_land"; table_data[key] = land_rows
                lines.append("Land"); lines.append(f"[[TABLE:{key}]]")

    add_city("Lagos", LAGOS_NODES)
    add_city("Abuja", ABUJA_NODES)
    lines.append("What Stands Out This Week")
    sig = summary["signals"]
    for label, obj in [("Most expensive area", sig.get("most_expensive")), ("Strongest rental/yield screen", sig.get("investment")),
            ("Best buyer value screen", sig.get("buyer_value")), ("Lowest observed land ₦/sqm", sig.get("land_opportunity"))]:
        lines.append(f"• {label}: {obj['market_node'] if obj else 'Not enough data yet'}")
    lines.append("Sources Used in This Report")
    lines.append("• " + (", ".join(summary.get("source_names", [])) or "No sources recorded"))

    text = "\n".join(lines)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]}).execute()

    # Text styling pass (title/headings), same named-style approach as
    # docs_writer.py — see that file's _format_requests for the pattern.
    style_requests = [{"updateTextStyle": {"range": {"startIndex": 1, "endIndex": len(text) + 1},
        "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 11, "unit": "PT"}},
        "fields": "weightedFontFamily,fontSize"}}]
    offset = 0
    for line in text.splitlines(True):
        raw = line.rstrip("\n")
        start, end = offset + 1, offset + 1 + len(raw)
        if raw == title:
            style_requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1}, "paragraphStyle": {"namedStyleType": "TITLE"}, "fields": "namedStyleType"}})
            style_requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 28, "unit": "PT"}, "foregroundColor": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}}, "bold": False}, "fields": "weightedFontFamily,fontSize,foregroundColor,bold"}})
        elif raw == subtitle:
            style_requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 12, "unit": "PT"}}, "fields": "weightedFontFamily,fontSize"}})
        elif raw.startswith("Data captured "):
            style_requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 10, "unit": "PT"}, "foregroundColor": {"color": {"rgbColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}}}, "fields": "weightedFontFamily,fontSize,foregroundColor"}})
        elif raw in ("Lagos", "Abuja", "What Stands Out This Week", "Sources Used in This Report"):
            style_requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1}, "paragraphStyle": {"namedStyleType": "HEADING_1"}, "fields": "namedStyleType"}})
            style_requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 16, "unit": "PT"}, "foregroundColor": {"color": {"rgbColor": {"red": 46/255, "green": 116/255, "blue": 181/255}}}}, "fields": "weightedFontFamily,fontSize,foregroundColor"}})
        elif raw in LAGOS_NODES + ABUJA_NODES:
            style_requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1}, "paragraphStyle": {"namedStyleType": "HEADING_2"}, "fields": "namedStyleType"}})
            style_requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 13, "unit": "PT"}, "foregroundColor": {"color": {"rgbColor": {"red": 46/255, "green": 116/255, "blue": 181/255}}}}, "fields": "weightedFontFamily,fontSize,foregroundColor"}})
        offset += len(line)
    if style_requests:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": style_requests}).execute()

    # Table fill pass — process placeholders BOTTOM-TO-TOP so each
    # insertion doesn't invalidate the indices of placeholders still
    # waiting to be processed above it.
    placeholders = list(_iter_placeholder_paragraphs(docs, doc_id))
    placeholders.sort(key=lambda x: x[0], reverse=True)

    for start, end, marker in placeholders:
        key = marker.replace("[[TABLE:", "").replace("]]", "")
        rows = table_data.get(key, [])
        if not rows:
            continue
        headers = ["Metric", "Value", "Sample", "Source & Date", "Link"]
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}},
            {"insertTable": {"location": {"index": start}, "rows": len(rows) + 1, "columns": len(headers)}},
        ]}).execute()

        doc_now = docs.documents().get(documentId=doc_id).execute()
        table_el = next((el for el in doc_now["body"]["content"] if el.get("table") and el["startIndex"] >= start - 5), None)
        if not table_el:
            continue
        cell_starts = []
        for r_idx, row in enumerate(table_el["table"]["tableRows"]):
            for c_idx, cell in enumerate(row["tableCells"]):
                cell_starts.append((r_idx, c_idx, cell["content"][0]["paragraph"]["elements"][0]["startIndex"]))
        all_values = [headers] + [[r["label"], r["value"], r["sample"], r["source_date"], "View source" if r.get("link") else "—"] for r in rows]
        cell_starts.sort(key=lambda x: x[2], reverse=True)
        fill_requests = []
        for r_idx, c_idx, idx in cell_starts:
            value = all_values[r_idx][c_idx]
            fill_requests.append({"insertText": {"location": {"index": idx}, "text": value}})
            if r_idx == 0:
                fill_requests.append({"updateTextStyle": {"range": {"startIndex": idx, "endIndex": idx + len(value)}, "textStyle": {"bold": True}, "fields": "bold"}})
            elif c_idx == 4 and r_idx > 0 and rows[r_idx - 1].get("link"):
                fill_requests.append({"updateTextStyle": {"range": {"startIndex": idx, "endIndex": idx + len(value)},
                    "textStyle": {"link": {"url": rows[r_idx - 1]["link"]}, "foregroundColor": {"color": {"rgbColor": {"blue": 0.8, "red": 0.07, "green": 0.33}}}, "underline": True},
                    "fields": "link,foregroundColor,underline"}})
        if fill_requests:
            docs.documents().batchUpdate(documentId=doc_id, body={"requests": fill_requests}).execute()
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [{
            "updateTableCellStyle": {
                "tableRange": {"tableCellLocation": {"tableStartLocation": {"index": table_el["startIndex"]}, "rowIndex": 0, "columnIndex": 0}, "rowSpan": 1, "columnSpan": len(headers)},
                "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": {"red": 217/255, "green": 217/255, "blue": 217/255}}},
                                   "paddingTop": {"magnitude": 4, "unit": "PT"}, "paddingBottom": {"magnitude": 4, "unit": "PT"}},
                "fields": "backgroundColor,paddingTop,paddingBottom"
            }
        }]}).execute()

    recipients = []
    for key in ("REPORT_CLIENT_EMAIL", "REPORT_TO_EMAIL"):
        recipients += [x.strip() for x in os.environ.get(key, "").split(",") if "@" in x]
    for email in dict.fromkeys(recipients):
        try:
            drive.permissions().create(fileId=doc_id, body={"type": "user", "role": "reader", "emailAddress": email}, sendNotificationEmail=False).execute()
        except HttpError as exc:
            raise RuntimeError(f"Could not grant viewer access to the new client report for {email}: {exc}") from exc

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    Path("client_doc_url.txt").write_text(url + "\n", encoding="utf-8")
    print(f"New weekly Google Doc published: {url}")
    return doc_id, url


def send_notification_email(doc_url):
    """Sends its own dedicated email with the new document's link — kept
    separate from email_report.py's existing executive brief email, per
    the client's explicit 'in addition to the other one' request."""
    import requests as req
    pub = os.environ.get("MAILJET_API_KEY")
    priv = os.environ.get("MAILJET_SECRET_KEY")
    if not (pub and priv):
        raise RuntimeError("MAILJET_API_KEY and MAILJET_SECRET_KEY are required to notify the client of the new Google Doc.")
    recipients = []
    for key in ("REPORT_CLIENT_EMAIL", "REPORT_TO_EMAIL"):
        recipients += [{"Email": x.strip()} for x in os.environ.get(key, "").split(",") if "@" in x]
    if not recipients:
        raise RuntimeError("REPORT_CLIENT_EMAIL or REPORT_TO_EMAIL is required for the client-document notification.")
    payload = {"Messages": [{
        "From": {"Email": os.environ.get("MAILJET_FROM_EMAIL", "").strip(), "Name": os.environ.get("MAILJET_FROM_NAME", "Master Builder").strip() or "Master Builder"},
        "To": recipients,
        "Subject": "Your Weekly Lagos & Abuja Property Market Snapshot",
        "HTMLPart": f"<p>This week's market snapshot document is ready.</p><p><a href='{doc_url}'>Open the report</a></p>",
    }]}
    sender = payload["Messages"][0]["From"]["Email"]
    if not sender or "@" not in sender:
        raise RuntimeError("MAILJET_FROM_EMAIL is missing or invalid; use an active verified Mailjet sender")
    resp = req.post("https://api.mailjet.com/v3.1/send", auth=(pub, priv), json=payload, timeout=30)
    resp.raise_for_status()
    response_data = resp.json()
    status = response_data.get("Messages", [{}])[0].get("Status", "unknown")
    if str(status).lower() != "success":
        raise RuntimeError(f"Mailjet did not accept the client-document notification: status={status}; response={response_data}")
    print(f"Notification email accepted by Mailjet: HTTP {resp.status_code}; status={status}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python client_doc_report.py <listings.csv>")
    raw_listings = load_csv(sys.argv[1])
    listings = clean_rows(raw_listings)
    if not listings:
        raise SystemExit("No validated node-consistent listings with auditable source URLs; refusing to publish client report.")
    print(f"Client report input rows: {len(raw_listings)}; validated rows: {len(listings)}")
    summary = build_summary(listings, [], sys.argv[1])

    docx_path = build_docx(listings, summary)
    print(f"DOCX created: {docx_path}")

    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        _, url = publish_google_doc(listings, summary)
        send_notification_email(url)
    else:
        print("GOOGLE_SERVICE_ACCOUNT_JSON not set — skipping Google Doc publish, DOCX only.")


if __name__ == "__main__":
    main()
