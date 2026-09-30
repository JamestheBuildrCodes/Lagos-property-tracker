"""Client-preferred weekly market report.

This report creates a BRAND-NEW Google Doc for every weekly run.

Google Drive authentication for this layer is OAuth 2.0 on behalf of a human
Google account. This is intentional: consumer Gmail accounts own the files and
the files consume that user's My Drive quota. The GitHub Actions service
account remains available for the existing Google Sheet/analyst-doc layers.

Required environment variables for publication:
- GOOGLE_OAUTH_TOKEN_JSON: serialized Google OAuth authorized-user token,
  including refresh_token, client_id, client_secret and token_uri.
- GOOGLE_WEEKLY_REPORT_FOLDER_ID: destination My Drive folder ID.
- REPORT_CLIENT_EMAIL / REPORT_TO_EMAIL: optional viewers.
- Mailjet variables for the notification email.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from market_analysis import (
    clean_rows,
    fnum,
    fmt_naira,
    load_csv,
    normalize_node,
    transaction_label,
    is_apartment,
    build_summary,
)

LAGOS_NODES = ["Banana Island", "Old Ikoyi", "Lekki Phase 1", "Victoria Island", "Eko Atlantic", "Ikeja GRA"]
ABUJA_NODES = ["Asokoro", "Maitama", "Wuse"]
BLUE = "2E74B5"


def bedroom_rows(listings, node, txn_type):
    by_beds = {}
    for row in clean_rows(listings):
        r = dict(row)
        if normalize_node(r.get("market_node") or r.get("location")) != node:
            continue
        if transaction_label(r) != txn_type or not is_apartment(r):
            continue
        if not (r.get("source_url") or "").startswith(("http://", "https://")):
            continue
        beds = r.get("bedrooms")
        price = fnum(r.get("asking_price_ngn"))
        if beds in (None, "") or not price:
            continue
        by_beds.setdefault(str(beds), []).append(r)

    out = []
    for beds, group in sorted(by_beds.items(), key=lambda x: fnum(x[0]) or 0):
        prices = [fnum(r.get("asking_price_ngn")) for r in group if fnum(r.get("asking_price_ngn"))]
        if not prices:
            continue
        example = sorted(group, key=lambda r: r.get("date_scraped") or "", reverse=True)[0]
        out.append({
            "label": f"{beds} Bedroom — median asking {'rent' if txn_type == 'rent' else 'sale price'}",
            "value": fmt_naira(statistics.median(prices)) + ("/yr" if txn_type == "rent" else ""),
            "sample": f"{len(prices)} listing{'s' if len(prices) != 1 else ''}",
            "source_date": f"{example.get('source', 'Unknown')}, {example.get('date_scraped', 'unknown date')}",
            "link": example.get("source_url", ""),
        })
    return out


def land_rows(listings, node):
    group = []
    for row in clean_rows(listings):
        r = dict(row)
        if normalize_node(r.get("market_node") or r.get("location")) != node:
            continue
        if transaction_label(r) != "land":
            continue
        if not (r.get("source_url") or "").startswith(("http://", "https://")):
            continue
        if not fnum(r.get("asking_price_ngn")):
            continue
        group.append(r)
    if not group:
        return []
    prices = [fnum(r.get("asking_price_ngn")) for r in group]
    example = sorted(group, key=lambda r: r.get("date_scraped") or "", reverse=True)[0]
    return [{
        "label": "Land — median asking price",
        "value": fmt_naira(statistics.median(prices)),
        "sample": f"{len(prices)} listing{'s' if len(prices) != 1 else ''}",
        "source_date": f"{example.get('source', 'Unknown')}, {example.get('date_scraped', 'unknown date')}",
        "link": example.get("source_url", ""),
    }]


def build_docx(listings, summary, output=None):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    output = output or f"Lagos_Property_Market_Snapshot_{datetime.now(timezone.utc):%Y-%m-%d}.docx"
    doc = Document()

    def font(run, size, color=None):
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)

    def heading(text, level, size, color=BLUE):
        p = doc.add_paragraph(style=f"Heading {level}")
        r = p.add_run(text)
        font(r, size, color)
        return p

    def body(text, size=11):
        p = doc.add_paragraph()
        r = p.add_run(text)
        font(r, size)
        return p

    def hyperlink(paragraph, url, label):
        rel = paragraph.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rel)
        run = OxmlElement("w:r")
        props = OxmlElement("w:rPr")
        color = OxmlElement("w:color"); color.set(qn("w:val"), "1155CC")
        underline = OxmlElement("w:u"); underline.set(qn("w:val"), "single")
        props.append(color); props.append(underline); run.append(props)
        t = OxmlElement("w:t"); t.text = label; run.append(t); link.append(run)
        paragraph._p.append(link)

    p = doc.add_paragraph(style="Title")
    r = p.add_run("Lagos & Abuja Property Market Snapshot")
    font(r, 28, "000000")
    body("Weekly Intelligence Report — Real Tracked Listings, Linked to Source", 12)
    body(f"Data captured {datetime.now(timezone.utc):%d %B %Y}", 10)
    body("Every price is an online asking price, not a confirmed closed transaction.")

    def table(rows):
        if not rows:
            body("No comparable listings for this category yet.")
            return
        t = doc.add_table(rows=1, cols=5)
        headers = ["Metric", "Value", "Sample", "Source & Date", "Link"]
        for i, text in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = text
            for run in cell.paragraphs[0].runs:
                run.bold = True; font(run, 10)
        for row in rows:
            cells = t.add_row().cells
            for i, key in enumerate(["label", "value", "sample", "source_date"]):
                cells[i].text = str(row[key])
                for run in cells[i].paragraphs[0].runs: font(run, 10)
            if row.get("link"):
                cells[4].text = ""
                hyperlink(cells[4].paragraphs[0], row["link"], "View source")
            else:
                cells[4].text = "—"
        doc.add_paragraph()

    for city, nodes in (("Lagos", LAGOS_NODES), ("Abuja", ABUJA_NODES)):
        heading(city, 1, 16)
        for node in nodes:
            rent = bedroom_rows(listings, node, "rent")
            sale = bedroom_rows(listings, node, "sale")
            land = land_rows(listings, node)
            if not (rent or sale or land):
                continue
            heading(node, 2, 13)
            if rent: body("Rental Market (per annum)"); table(rent)
            if sale: body("Sales Market"); table(sale)
            if land: body("Land"); table(land)

    heading("What Stands Out This Week", 1, 16)
    sig = summary.get("signals", {})
    for label, obj in [
        ("Most expensive area", sig.get("most_expensive")),
        ("Strongest rental/yield screen", sig.get("investment")),
        ("Best buyer value screen", sig.get("buyer_value")),
        ("Lowest observed land ₦/sqm", sig.get("land_opportunity")),
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{label}: {obj['market_node'] if obj else 'Not enough data yet'}")
        font(r, 11)

    heading("Sources Used in This Report", 1, 16)
    body(", ".join(summary.get("source_names", [])) or "No sources recorded")
    doc.save(output)
    return output


def _oauth_services():
    """Build Docs/Drive clients using a human user's OAuth refresh token."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    raw = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_JSON is missing")

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_JSON is not valid JSON") from exc

    required = ("refresh_token", "client_id", "client_secret", "token_uri")
    missing = [key for key in required if not info.get(key)]
    if missing:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is missing required fields: " + ", ".join(missing)
        )

    scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_authorized_user_info(info, scopes=scopes)
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError("OAuth credentials are expired and have no refresh token")
        creds.refresh(Request())

    return (
        build("docs", "v1", credentials=creds, cache_discovery=False),
        build("drive", "v3", credentials=creds, cache_discovery=False),
    )


def _report_text(listings, summary):
    lines = [
        "Lagos & Abuja Property Market Snapshot",
        "Weekly Intelligence Report — Real Tracked Listings, Linked to Source",
        f"Data captured {datetime.now(timezone.utc):%d %B %Y}",
        "",
        "Every price below is an online asking price, not a confirmed closed transaction.",
    ]
    for city, nodes in (("Lagos", LAGOS_NODES), ("Abuja", ABUJA_NODES)):
        lines += ["", city]
        for node in nodes:
            rent = bedroom_rows(listings, node, "rent")
            sale = bedroom_rows(listings, node, "sale")
            land = land_rows(listings, node)
            if not (rent or sale or land):
                continue
            lines += ["", node]
            for title, rows in (("Rental Market (per annum)", rent), ("Sales Market", sale), ("Land", land)):
                if not rows:
                    continue
                lines += [title, "Metric | Value | Sample | Source & Date | Link"]
                for row in rows:
                    lines.append(" | ".join([
                        row["label"], row["value"], row["sample"], row["source_date"], row.get("link", "")
                    ]))
    lines += ["", "What Stands Out This Week"]
    sig = summary.get("signals", {})
    for label, obj in [
        ("Most expensive area", sig.get("most_expensive")),
        ("Strongest rental/yield screen", sig.get("investment")),
        ("Best buyer value screen", sig.get("buyer_value")),
        ("Lowest observed land ₦/sqm", sig.get("land_opportunity")),
    ]:
        lines.append(f"• {label}: {obj['market_node'] if obj else 'Not enough data yet'}")
    lines += ["", "Sources Used in This Report", ", ".join(summary.get("source_names", [])) or "No sources recorded"]
    return "\n".join(lines) + "\n"


def publish_google_doc(listings, summary):
    """Create a new Google Doc inside the configured My Drive folder."""
    from googleapiclient.errors import HttpError

    docs, drive = _oauth_services()
    folder_id = os.environ.get("GOOGLE_WEEKLY_REPORT_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("GOOGLE_WEEKLY_REPORT_FOLDER_ID is required")

    title = f"Lagos & Abuja Property Market Snapshot — {datetime.now(timezone.utc):%Y-%m-%d}"
    try:
        created = drive.files().create(
            body={
                "name": title,
                "mimeType": "application/vnd.google-apps.document",
                "parents": [folder_id],
            },
            fields="id,name,webViewLink,parents",
        ).execute()
    except HttpError as exc:
        raise RuntimeError(
            "Could not create the weekly Google Doc in the configured Drive folder. "
            "Confirm the OAuth account owns/has Editor access to the folder and has available storage. "
            f"Google API error: {exc}"
        ) from exc

    doc_id = created["id"]
    text = _report_text(listings, summary)
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
    ).execute()

    # Make the report readable by the configured recipients without changing
    # ownership or creating any additional copies.
    recipients = []
    for key in ("REPORT_CLIENT_EMAIL", "REPORT_TO_EMAIL"):
        recipients.extend(
            x.strip() for x in os.environ.get(key, "").split(",") if "@" in x
        )
    for email in dict.fromkeys(recipients):
        try:
            drive.permissions().create(
                fileId=doc_id,
                body={"type": "user", "role": "reader", "emailAddress": email},
                sendNotificationEmail=False,
            ).execute()
        except HttpError as exc:
            print(f"Warning: could not grant viewer access to {email}: {exc}")

    url = created.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit"
    Path("client_doc_url.txt").write_text(url + "\n", encoding="utf-8")
    print(f"New weekly Google Doc published: {url}")
    return doc_id, url


def send_notification_email(doc_url):
    import requests as req
    pub = os.environ.get("MAILJET_API_KEY")
    priv = os.environ.get("MAILJET_SECRET_KEY")
    if not (pub and priv):
        raise RuntimeError("MAILJET_API_KEY and MAILJET_SECRET_KEY are required for the client-document notification.")
    recipients = []
    for key in ("REPORT_CLIENT_EMAIL", "REPORT_TO_EMAIL"):
        recipients += [{"Email": x.strip()} for x in os.environ.get(key, "").split(",") if "@" in x]
    if not recipients:
        raise RuntimeError("REPORT_CLIENT_EMAIL or REPORT_TO_EMAIL is required for notification.")
    sender = os.environ.get("MAILJET_FROM_EMAIL", "").strip()
    if not sender or "@" not in sender:
        raise RuntimeError("MAILJET_FROM_EMAIL is missing or invalid.")
    payload = {"Messages": [{
        "From": {"Email": sender, "Name": os.environ.get("MAILJET_FROM_NAME", "Master Builder").strip() or "Master Builder"},
        "To": recipients,
        "Subject": "Your Weekly Lagos & Abuja Property Market Snapshot",
        "HTMLPart": f"<p>This week's market snapshot document is ready.</p><p><a href='{doc_url}'>Open the report</a></p>",
    }]}
    resp = req.post("https://api.mailjet.com/v3.1/send", auth=(pub, priv), json=payload, timeout=30)
    resp.raise_for_status()
    print(f"Notification email accepted by Mailjet: HTTP {resp.status_code}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python client_doc_report.py <listings.csv>")
    raw = load_csv(sys.argv[1])
    listings = clean_rows(raw)
    if not listings:
        raise SystemExit("No validated listings with auditable source URLs; refusing to publish client report.")
    print(f"Client report input rows: {len(raw)}; validated rows: {len(listings)}")
    summary = build_summary(listings, [], sys.argv[1])
    docx_path = build_docx(listings, summary)
    print(f"DOCX created: {docx_path}")
    if os.environ.get("GOOGLE_OAUTH_TOKEN_JSON"):
        _, url = publish_google_doc(listings, summary)
        send_notification_email(url)
    else:
        print("GOOGLE_OAUTH_TOKEN_JSON not set — skipping Google Doc publish, DOCX only.")


if __name__ == "__main__":
    main()
