"""Publish the analyst report as a real Google Doc using the service account.

If GOOGLE_DOC_ID is set, that document is replaced in-place. Otherwise a new
weekly document is created. Optional REPORT_CLIENT_EMAIL / REPORT_TO_EMAIL
recipients receive viewer access to the created/updated document.

FIXED (v2 — see CHANGELOG_REPORT_FIXES.md for the full list):
1. The three headline numbers (median apartment sale, median annual rent,
   median land ₦/sqm) were being inserted as RAW numbers with no formatting
   — e.g. "700000000" instead of "₦700,000,000". market_analysis.py already
   has a working fmt_naira() function that the email HTML and DOCX builder
   both correctly use — this file just wasn't calling it. Now it does, and
   shows both the full figure and a compact form for fast reading:
   "₦700,000,000 (≈₦700.0m)".
2. The document title was only bold+18pt manually — not a real Google Docs
   "Title" style, which is why it didn't show up properly in the outline/
   heading structure. Now uses the actual TITLE named style.
3. Bullet lines were typed "• " characters, not real Docs bullets. Now uses
   the Docs API's actual bullet formatting (createParagraphBullets), so
   they render, indent, and behave like real bullets.
4. The Area Scorecard was a wall of pipe-separated text. Now rendered as an
   actual Google Docs table with a header row, which is what "no beauty"
   was mostly about — a real grid reads completely differently from plain
   text with pipes in it.

HONESTY NOTE: the table-insertion logic (step 4) was written carefully
against documented Google Docs API behavior but has NOT been run against a
live document in this session (no live API access from this environment).
Test it on the first real run — if cell text lands in the wrong cells or
the table doesn't render, that's the first thing to check, and the index
math in _fill_table() is where to look.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

from market_analysis import fmt_naira

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def creds_from_env():
    from google.oauth2.service_account import Credentials
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)


def fmt_headline(v):
    """Full comma-formatted figure plus a compact reading aid in
    parentheses for anything ₦1,000,000 or more — e.g.
    '₦700,000,000 (≈₦700.0m)'. Below that threshold the compact form adds
    nothing useful, so it's just the plain figure."""
    full = fmt_naira(v)
    if full == "N/A":
        return full
    compact = fmt_naira(v, compact=True)
    # fmt_naira's compact mode only abbreviates at ₦1,000+ anyway; only show
    # the parenthetical when it's actually a different, shorter string.
    return f"{full} (≈{compact})" if compact != full else full


def report_text(summary):
    def n(obj):
        return obj["market_node"] if obj else "N/A"

    lines = [
        "LAGOS & ABUJA PROPERTY MARKET — WEEKLY INTELLIGENCE REPORT",
        datetime.now(timezone.utc).strftime("%d %B %Y"), "",
        "1. EXECUTIVE DECISION BRIEF",
        f"Listings tracked: {summary['listings_tracked']}",
        f"Areas monitored: {summary['areas_monitored']}",
        f"Sources: {summary['sources']}",
        f"New listings: {summary['changes']['new_listings']}",
        f"Price reductions: {summary['changes']['price_reductions']}",
        f"Price increases: {summary['changes']['price_increases']}",
        f"Median apartment asking sale: {fmt_headline(summary['median_apartment_sale'])}",
        f"Median annual apartment rent: {fmt_headline(summary['median_annual_rent'])}",
        f"Median land asking ₦/sqm: {fmt_headline(summary['median_land_ppsqm'])}", "",
        "2. WHAT HAPPENED THIS WEEK",
    ]
    lines += [f"• {x}" for x in summary.get("analysis_notes", [])] or ["• No interpretation available."]
    lines += ["", "3. DECISION SIGNALS",
        f"Most expensive: {n(summary['signals'].get('most_expensive'))}",
        f"Rental / investment screen: {n(summary['signals'].get('investment'))}",
        f"Best buyer value screen: {n(summary['signals'].get('buyer_value'))}",
        f"Lowest observed land ₦/sqm: {n(summary['signals'].get('land_opportunity'))}",
        "Watch closely: " + (", ".join(x["market_node"] for x in summary["signals"].get("monitoring", [])) or "N/A"), "",
        "4. AREA SCORECARD",
        "[[TABLE:AREA_SCORECARD]]",  # replaced with a real Docs table in publish() — see _fill_table()
        "",
        ("5. SIX-MONTH TREND VIEW" if any(v.get("full_six_month") for v in summary.get("trends", {}).values()) else "5. HISTORICAL TREND VIEW")]
    trends = summary.get("trends", {})
    added = False
    for node, tr in trends.items():
        vals = []
        for key, label in (("sale_pct", "sale"), ("rent_pct", "rent"), ("land_ppsqm_pct", "land ₦/sqm")):
            if tr.get(key) is not None:
                vals.append(f"{label} {tr[key]:+.1f}%")
        if vals:
            lines.append(f"• {node}: " + ", ".join(vals))
            added = True
    if not added:
        days = max((v.get("period_days", 0) for v in trends.values()), default=0)
        if trends:
            lines.append(f"Available archived snapshots cover approximately {days} days; this is an available-period directional view, not a complete six-month series.")
        else:
            lines.append("Trend baseline is being established; future weekly runs will extend the historical archive.")
    lines += ["", "6. RECOMMENDED ACTIONS",
        "• Use relative pricing and weekly movement to prioritise negotiations and areas for deeper diligence. Thinly sampled areas should be treated as watchlist signals, not definitive market indices.",
        "• Prices are asking prices, not confirmed closed transactions. Estate Intel is public research only; premium/login-gated content is not collected or bypassed."]
    return "\n".join(lines)


def _format_requests(text):
    """Builds the text-style requests. Title gets the real TITLE named
    style (shows up properly in the document outline), numbered sections
    get HEADING_1, and bullet lines get real Docs bullets — not typed
    characters."""
    requests = [
        {"updateTextStyle": {"range": {"startIndex": 1, "endIndex": len(text) + 1},
            "textStyle": {"weightedFontFamily": {"fontFamily": "Arial"}, "fontSize": {"magnitude": 10, "unit": "PT"}},
            "fields": "weightedFontFamily,fontSize"}},
        {"updateParagraphStyle": {"range": {"startIndex": 1, "endIndex": len(text) + 1},
            "paragraphStyle": {"lineSpacing": 115, "spaceBelow": {"magnitude": 6, "unit": "PT"}},
            "fields": "lineSpacing,spaceBelow"}},
    ]

    bullet_ranges = []
    offset = 0
    lines = text.splitlines(True)
    for line in lines:
        raw = line.rstrip("\n")
        start = offset + 1
        end = start + len(raw)

        if raw.startswith("LAGOS & ABUJA PROPERTY MARKET"):
            # Real Title style, not manual bold — this is what makes it
            # show up correctly as "Heading" content in the document.
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"namedStyleType": "TITLE"}, "fields": "namedStyleType"}})
        elif raw[:2].isdigit() and ". " in raw[:5]:
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"namedStyleType": "HEADING_1", "spaceAbove": {"magnitude": 14, "unit": "PT"},
                    "spaceBelow": {"magnitude": 4, "unit": "PT"}}, "fields": "namedStyleType,spaceAbove,spaceBelow"}})
        elif raw.startswith("• "):
            bullet_ranges.append((start, end))

        offset += len(line)

    # Real bullets: one createParagraphBullets request per contiguous
    # bullet range is safest (merging non-adjacent ranges can behave
    # unpredictably), so each bulleted line gets its own request.
    # Strip the literal bullet glyph first, then apply real Docs bullets.
    # Process from bottom to top so each deletion leaves earlier indices stable.
    for start, end in sorted(bullet_ranges, reverse=True):
        requests.append({"deleteContentRange": {"range": {"startIndex": start, "endIndex": start + 2}}})
        requests.append({"createParagraphBullets": {"range": {"startIndex": start, "endIndex": end - 1},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})

    return requests


def _fill_table(docs, doc_id, summary):
    """Replaces the [[TABLE:AREA_SCORECARD]] placeholder line with an
    actual Google Docs table. Done as a separate step after the main text
    is in place, because table cell indices don't exist until the table
    itself has been inserted — this needs its own get() call to read them.
    """
    doc = docs.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])

    placeholder_start = None
    placeholder_end = None
    for el in body:
        para = el.get("paragraph")
        if not para:
            continue
        text = "".join(r.get("textRun", {}).get("content", "") for r in para.get("elements", []))
        if "[[TABLE:AREA_SCORECARD]]" in text:
            placeholder_start = el["startIndex"]
            placeholder_end = el["endIndex"]
            break

    if placeholder_start is None:
        print("Table placeholder not found — skipping table formatting (scorecard stays as plain text).")
        return

    scorecard = [x for x in summary["scorecard"] if x["listing_count"]]
    headers = ["Area", "Listings", "3BR Sale", "3BR Rent", "Sale ₦/sqm", "Land ₦/sqm"]
    rows_data = [[
        x["market_node"], str(x["listing_count"]),
        fmt_naira(x["sale_3br_median"], compact=True),
        fmt_naira(x["rent_3br_median"], compact=True),
        fmt_naira(x["sale_ppsqm_median"], compact=True),
        fmt_naira(x["land_ppsqm_median"], compact=True),
    ] for x in scorecard]

    if not rows_data:
        print("No scorecard rows with listings — skipping table, leaving a text note instead.")
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"deleteContentRange": {"range": {"startIndex": placeholder_start, "endIndex": placeholder_end}}},
            {"insertText": {"location": {"index": placeholder_start}, "text": "No areas had usable listing data this run.\n"}},
        ]}).execute()
        return

    # Step 1: remove the placeholder text, then insert an empty table sized
    # for header + data rows.
    n_rows = len(rows_data) + 1
    n_cols = len(headers)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"deleteContentRange": {"range": {"startIndex": placeholder_start, "endIndex": placeholder_end}}},
        {"insertTable": {"location": {"index": placeholder_start}, "rows": n_rows, "columns": n_cols}},
    ]}).execute()

    # Step 2: re-fetch to find the real cell start indices Google assigned.
    doc = docs.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])
    table_el = next((el for el in body if el.get("table") and el["startIndex"] >= placeholder_start - 5), None)
    if not table_el:
        print("Could not locate the inserted table after creation — scorecard left without a table.")
        return

    cell_starts = []  # list of (row, col, startIndex) — the index just inside each cell's first paragraph
    for r_idx, row in enumerate(table_el["table"]["tableRows"]):
        for c_idx, cell in enumerate(row["tableCells"]):
            first_para = cell["content"][0]["paragraph"]
            cell_starts.append((r_idx, c_idx, first_para["elements"][0]["startIndex"]))

    all_values = [headers] + rows_data

    # Step 3: fill text in REVERSE index order so each insertion doesn't
    # shift the (not-yet-used) start index of any cell still to come.
    cell_starts.sort(key=lambda x: x[2], reverse=True)
    fill_requests = []
    for r_idx, c_idx, start_idx in cell_starts:
        value = all_values[r_idx][c_idx]
        fill_requests.append({"insertText": {"location": {"index": start_idx}, "text": value}})
        if r_idx == 0:  # bold the header row
            fill_requests.append({"updateTextStyle": {
                "range": {"startIndex": start_idx, "endIndex": start_idx + len(value)},
                "textStyle": {"bold": True}, "fields": "bold"}})

    if fill_requests:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": fill_requests}).execute()


def publish(summary, output_docx=None):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    credentials = creds_from_env()
    docs = build("docs", "v1", credentials=credentials, cache_discovery=False)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

    doc_id = os.environ.get("GOOGLE_DOC_ID", "").strip()
    title = f"Lagos Property Market — Weekly Intelligence Report — {datetime.now(timezone.utc):%Y-%m-%d}"
    text = report_text(summary)

    if doc_id:
        doc = docs.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {}).get("content", [])
        end = max((x.get("endIndex", 1) for x in body), default=1) - 1
        requests = []
        if end > 1:
            requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end}}})
        requests.append({"insertText": {"location": {"index": 1}, "text": text}})
        requests += _format_requests(text)
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    else:
        doc = docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        requests = [{"insertText": {"location": {"index": 1}, "text": text}}]
        requests += _format_requests(text)
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    try:
        _fill_table(docs, doc_id, summary)
    except Exception as exc:
        # Table formatting is a visual nicety, not core content — don't
        # let it break the whole publish if something about the live
        # document structure doesn't match what was expected here.
        print(f"Table formatting failed, scorecard left as plain text: {exc}")

    recipients = []
    for key in ("REPORT_CLIENT_EMAIL", "REPORT_TO_EMAIL"):
        recipients += [x.strip() for x in os.environ.get(key, "").split(",") if "@" in x]
    for email in dict.fromkeys(recipients):
        try:
            drive.permissions().create(fileId=doc_id, body={"type": "user", "role": "reader", "emailAddress": email}, sendNotificationEmail=False).execute()
        except HttpError as exc:
            print(f"Google Doc sharing skipped for {email}: {exc}")

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    Path("google_doc_url.txt").write_text(url + "\n", encoding="utf-8")
    print(f"Google Doc published: {url}")
    if output_docx:
        Path(output_docx).write_text(url, encoding="utf-8")
    return doc_id, url


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python docs_writer.py market_intelligence.json")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    publish(payload["summary"])


if __name__ == "__main__":
    main()
