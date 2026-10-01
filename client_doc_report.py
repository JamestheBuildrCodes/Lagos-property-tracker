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
GRAY = "666666"
HEADER_FILL = "D9D9D9"


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


def bedroom_breakdown(listings, node, txn_type):
    """Compatibility wrapper used by the narrative report builder."""
    return bedroom_rows(listings, node, txn_type)


def land_breakdown(listings, node):
    """Compatibility wrapper used by the narrative report builder."""
    return land_rows(listings, node)


DISCREPANCY_THRESHOLD_PCT = 15
SMALL_SAMPLE_THRESHOLD = 3
STALE_DAYS_THRESHOLD = 60


def _category_group(listings, node, txn_type, beds=None):
    group = []
    for row in clean_rows(listings):
        r = dict(row)
        if normalize_node(r.get("market_node") or r.get("location")) != node:
            continue
        if transaction_label(r) != txn_type:
            continue
        if txn_type != "land" and not is_apartment(r):
            continue
        if beds is not None and str(r.get("bedrooms")) != str(beds):
            continue
        if not fnum(r.get("asking_price_ngn")):
            continue
        if not (r.get("source_url") or "").strip().startswith(("https://", "http://")):
            continue
        group.append(r)
    return group


def _analysis_for_rows(rows, label):
    prices = [(fnum(r.get("asking_price_ngn")), r) for r in rows]
    prices = [(p, r) for p, r in prices if p]
    if not prices:
        return None
    by_source = {}
    for price, row in prices:
        by_source.setdefault(row.get("source") or "Unknown", []).append(price)
    ages = [fnum(r.get("listing_age_days")) for _, r in prices if fnum(r.get("listing_age_days")) is not None]
    return {
        "label": label,
        "median": statistics.median([p for p, _ in prices]),
        "count": len(prices),
        "source_medians": {src: statistics.median(vals) for src, vals in by_source.items()},
        "freshest_age_days": min(ages) if ages else None,
    }


def _category_analysis(listings, node, txn_type, beds=None):
    return _analysis_for_rows(_category_group(listings, node, txn_type, beds),
                              f"{beds} Bedroom" if beds is not None else "Land")


def _discrepancy_note(analysis, node):
    source_medians = analysis["source_medians"]
    if len(source_medians) < 2:
        return None
    ordered = sorted(source_medians.items(), key=lambda item: item[1])
    low_source, low_value = ordered[0]
    high_source, high_value = ordered[-1]
    if low_value <= 0:
        return None
    gap = round((high_value - low_value) / low_value * 100, 1)
    if gap <= DISCREPANCY_THRESHOLD_PCT:
        return None
    return (f"Source disagreement — {analysis['label']} in {node}: {high_source} has a median "
            f"asking price of {fmt_naira(high_value)}, compared with {fmt_naira(low_value)} on "
            f"{low_source}, a {gap}% difference. The platforms may contain different property "
            f"mixes or price points; this is a reason to compare the underlying listings, not "
            f"evidence by itself that either platform is wrong.")


def _caveat_notes(analysis):
    notes = []
    if analysis["count"] < SMALL_SAMPLE_THRESHOLD:
        count = analysis["count"]
        notes.append(f"{analysis['label']}: only {count} listing{'s' if count != 1 else ''} support this median. "
                     "Treat it as a rough reference point until a larger comparable sample is available.")
    age = analysis.get("freshest_age_days")
    if age is not None and age > STALE_DAYS_THRESHOLD:
        notes.append(f"{analysis['label']}: even the freshest listing behind this figure is {int(age)} days old, "
                     "so this is a softer reference point than recently updated categories.")
    return notes


def _city_standout(listings, nodes, city):
    values = {}
    for node in nodes:
        a = _category_analysis(listings, node, "rent", "2")
        if a:
            values[node] = a["median"]
    if len(values) < 2:
        return None
    low_node, low_value = min(values.items(), key=lambda item: item[1])
    high_node, high_value = max(values.items(), key=lambda item: item[1])
    if low_value <= 0:
        return None
    pct = round((high_value - low_value) / low_value * 100)
    return (f"For 2-bedroom rentals, {high_node} has a median asking rent about {pct}% above "
            f"{low_node} ({fmt_naira(high_value)} versus {fmt_naira(low_value)} per year). "
            f"This is the clearest current price spread across {city}'s tracked nodes with comparable data.")


def _coverage_summary(listings):
    all_nodes = LAGOS_NODES + ABUJA_NODES
    covered, beds_seen = set(), set()
    for node in all_nodes:
        for txn in ("rent", "sale"):
            for row in _category_group(listings, node, txn):
                covered.add(node)
                if row.get("bedrooms") not in (None, ""):
                    beds_seen.add(str(row["bedrooms"]))
        if _category_group(listings, node, "land"):
            covered.add(node)
    missing_nodes = [node for node in all_nodes if node not in covered]
    missing_beds = [f"{bed} Bedroom" for bed in range(1, 6) if str(bed) not in beds_seen]
    return covered, missing_nodes, missing_beds


def _research_table_rows(research):
    out = []
    for row in research or []:
        title = (row.get("title") or "").strip() or "Public research page"
        public_price = fnum(row.get("public_sale_price_ngn"))
        land_area = fnum(row.get("land_area_sqm"))
        units = fnum(row.get("size_units"))
        value = fmt_naira(public_price) if public_price else (
            f"{land_area:,.0f} sqm land area; no public sale price parsed" if land_area else
            f"{int(units):,} units; no public sale price parsed" if units else
            "Public market/project context; no comparable asking price parsed")
        updated = row.get("last_updated") or row.get("date_added") or row.get("date_scraped") or "date unavailable"
        out.append({
            "label": f"{row.get('market_node') or row.get('location') or 'Market'} — {title}",
            "value": value,
            "sample": "Public research; not a listing",
            "source_date": f"Estate Intel; {updated}",
            "link": row.get("url", ""),
        })
    return out


def _narrative_lines(listings, summary, research=None):
    lines = [
        ("h1", "How to Read This Report"),
        ("body", "Every price in the tables is a median calculated from validated, auditable asking-price listings in the current tracker—not a confirmed closed sale or rental transaction. The sample count is shown so you can judge how much weight to place on each figure; use View source to inspect a representative listing from that group."),
        ("body", "Source medians can differ because platforms may contain different property mixes, price points, and listing coverage. Where the observed difference exceeds 15%, the report calls it out beside the relevant table. Figures supported by fewer than three listings are marked as small samples; freshness caveats appear only when the source data actually contains an age older than 60 days."),
    ]
    for city, nodes in (("Lagos", LAGOS_NODES), ("Abuja", ABUJA_NODES)):
        lines.append(("h1", city))
        standout = _city_standout(listings, nodes, city)
        if standout:
            lines.append(("body", standout))
        for node in nodes:
            rents = bedroom_breakdown(listings, node, "rent")
            sales = bedroom_breakdown(listings, node, "sale")
            land = land_breakdown(listings, node)
            if not (rents or sales or land):
                continue
            lines.append(("h2", node))
            for txn, label, rows in (("rent", "Rental Market (per annum)", rents),
                                     ("sale", "Sales Market", sales), ("land", "Land", land)):
                if not rows:
                    continue
                lines.append(("h3", label))
                lines.append(("table", f"{node}_{txn}"))
                for item in rows:
                    import re
                    m = re.match(r"(\d+)\s+Bedroom", item["label"])
                    beds = m.group(1) if m and txn != "land" else None
                    analysis = _category_analysis(listings, node, txn, beds)
                    if analysis:
                        note = _discrepancy_note(analysis, node)
                        if note:
                            lines.append(("body", note))
                        for caveat in _caveat_notes(analysis):
                            lines.append(("body", caveat))
    lines.append(("h1", "What Stands Out This Week"))
    sig = summary.get("signals", {})
    for label, obj, caveat in [
        ("Most expensive area", sig.get("most_expensive"), "This describes the current tracked asking-price mix, not every property in the area."),
        ("Rental / investment screen", sig.get("investment") or sig.get("strongest_rental"), "Any yield proxy is indicative only; it is not net yield and excludes vacancy, fees, maintenance, and tax."),
        ("Buyer value screen", sig.get("buyer_value") or sig.get("best_relative_value"), "Relative value compares only the available sample; it does not guarantee a bargain."),
        ("Land price screen", sig.get("land_opportunity"), "Land conclusions depend on comparable land listings and usable size/price fields."),
    ]:
        if obj:
            lines.append(("bullet", f"{label}: {obj.get('market_node', 'not identified')}, supported by "
                         f"{obj.get('listing_count', 'an available')} tracked listings. {caveat}"))
    covered, missing_nodes, missing_beds = _coverage_summary(listings)
    coverage = f"Comparable rental, sale, or land data was available for {len(covered)} of 9 tracked nodes this week."
    if missing_nodes:
        coverage += f" Nodes with no usable comparable data: {', '.join(missing_nodes)}."
    lines.append(("bullet", coverage))
    lines.append(("h1", "Estate Intel — Public Research Context"))
    research_rows = _research_table_rows(research or [])
    if research_rows:
        lines.append(("body", f"The tracker collected {len(research_rows)} public Estate Intel research/project records. These provide context and links for further diligence; they are not comparable listing rows. Where a public page did not expose a price or size that could be parsed, this report says so rather than substituting a premium or guessed figure. No login or premium restriction is bypassed."))
        lines.append(("table", "estate_intel_public"))
    else:
        lines.append(("body", "No Estate Intel public-research records were returned in this run. That does not prove the platform has no data; check the scrape run report for access or parsing errors. Premium/login-gated content is not collected or bypassed."))
    lines.append(("h1", "What This Snapshot Covers — and What's Next"))
    cover = f"This snapshot covers validated, linked residential asking-price listings across {len(covered)} of the 9 tracked nodes in Lagos and Abuja, with rental, sale, and land tables shown only where usable comparable listings exist."
    if missing_beds:
        cover += f" No comparable records were available for: {', '.join(missing_beds)}."
    lines.append(("body", cover))
    lines.append(("body", "Next steps: inspect the linked source listings behind any decision-grade number, compare like-for-like property size and condition, and treat small-sample or stale categories as indicative rather than definitive."))
    return lines


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


def _iter_placeholder_paragraphs(docs, doc_id):
    """Return (start_index, end_index, marker) for each [[TABLE:key]] paragraph.

    Google Docs indexes are document-level UTF-16-style character positions.
    The marker is deliberately kept as a complete paragraph so the caller can
    replace the whole placeholder paragraph with a table at the same location.
    """
    document = docs.documents().get(documentId=doc_id).execute()
    placeholders = []
    body = document.get("body", {}).get("content", [])
    for element in body:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        parts = []
        for child in paragraph.get("elements", []):
            text_run = child.get("textRun")
            if text_run and "content" in text_run:
                parts.append(text_run["content"])
        paragraph_text = "".join(parts)
        if not paragraph_text.strip().startswith("[[TABLE:"):
            continue
        stripped = paragraph_text.strip()
        if not stripped.endswith("]]" ):
            continue
        marker = stripped
        if not marker.startswith("[[TABLE:"):
            continue
        start = element.get("startIndex")
        end = element.get("endIndex")
        if start is None or end is None:
            continue
        placeholders.append((start, end, marker))
    return placeholders


def publish_google_doc(listings, summary, research=None):
    """Create a new styled Google Doc using a human user's OAuth token."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    raw = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_JSON is required; service-account Drive quota is not suitable for new weekly documents.")
    info = json.loads(raw)
    required = ("refresh_token", "client_id", "client_secret", "token_uri")
    missing = [key for key in required if not info.get(key)]
    if missing:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_JSON is missing: " + ", ".join(missing))
    creds = Credentials.from_authorized_user_info(info, scopes=[
        "https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"])
    if not creds.valid:
        creds.refresh(Request())
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    folder_id = os.environ.get("GOOGLE_WEEKLY_REPORT_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("GOOGLE_WEEKLY_REPORT_FOLDER_ID is required.")
    title = f"Nigeria Real Estate Market Snapshot — {datetime.now(timezone.utc):%Y-%m-%d}"
    created = drive.files().create(body={"name": title, "mimeType": "application/vnd.google-apps.document",
        "parents": [folder_id]}, fields="id,webViewLink").execute()
    doc_id = created["id"]

    lines = [title, "Lagos & Abuja — Tracked Listings, Public Research & Current Asking Prices",
             f"Data captured {datetime.now(timezone.utc):%d %B %Y}", ""]
    table_data = {}
    for kind, value in _narrative_lines(listings, summary, research):
        if kind == "table":
            lines.append(f"[[TABLE:{value}]]")
            if value == "estate_intel_public":
                table_data[value] = _research_table_rows(research or [])
            else:
                node, txn = value.rsplit("_", 1)
                table_data[value] = bedroom_breakdown(listings, node, txn) if txn != "land" else land_breakdown(listings, node)
        elif kind == "bullet":
            lines.append("• " + value)
        else:
            lines.append(value)
    text = "\n".join(lines) + "\n"
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"location": {"index": 1}, "text": text}}]}).execute()

    heading1 = {"How to Read This Report", "Lagos", "Abuja", "What Stands Out This Week",
                "Estate Intel — Public Research Context", "What This Snapshot Covers — and What's Next",
                "Sources Used in This Report"}
    heading2 = set(LAGOS_NODES + ABUJA_NODES)
    heading3 = {"Rental Market (per annum)", "Sales Market", "Land"}
    requests = [{"updateTextStyle": {"range": {"startIndex": 1, "endIndex": len(text) + 1},
        "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"},
                      "fontSize": {"magnitude": 11, "unit": "PT"}},
        "fields": "weightedFontFamily,fontSize"}}]
    offset = 0
    for line in text.splitlines(True):
        raw_line = line.rstrip("\n")
        start, end = offset + 1, offset + 1 + len(raw_line)
        if raw_line == title:
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"namedStyleType": "TITLE", "alignment": "CENTER"}, "fields": "namedStyleType,alignment"}})
            requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end},
                "textStyle": {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": 28, "unit": "PT"},
                              "foregroundColor": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}}, "bold": False},
                "fields": "weightedFontFamily,fontSize,foregroundColor,bold"}})
        elif raw_line.startswith("Lagos & Abuja —"):
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"alignment": "CENTER"}, "fields": "alignment"}})
            requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end},
                "textStyle": {"fontSize": {"magnitude": 12, "unit": "PT"}}, "fields": "fontSize"}})
        elif raw_line.startswith("Data captured "):
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"alignment": "CENTER"}, "fields": "alignment"}})
            requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end},
                "textStyle": {"fontSize": {"magnitude": 10, "unit": "PT"},
                              "foregroundColor": {"color": {"rgbColor": {"red": .4, "green": .4, "blue": .4}}}},
                "fields": "fontSize,foregroundColor"}})
        elif raw_line in heading1 or raw_line in heading2 or raw_line in heading3:
            level = "HEADING_1" if raw_line in heading1 else "HEADING_2" if raw_line in heading2 else "HEADING_3"
            size = 16 if level == "HEADING_1" else 13 if level == "HEADING_2" else 12
            style = {"weightedFontFamily": {"fontFamily": "Times New Roman"}, "fontSize": {"magnitude": size, "unit": "PT"},
                     "foregroundColor": {"color": {"rgbColor": {"red": 46/255, "green": 116/255, "blue": 181/255}}}}
            fields = "weightedFontFamily,fontSize,foregroundColor"
            if level == "HEADING_3":
                style["bold"] = True
                fields += ",bold"
            requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"namedStyleType": level}, "fields": "namedStyleType"}})
            requests.append({"updateTextStyle": {"range": {"startIndex": start, "endIndex": end},
                "textStyle": style, "fields": fields}})
        offset += len(line)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    placeholders = sorted(_iter_placeholder_paragraphs(docs, doc_id), key=lambda item: item[0], reverse=True)
    for start, end, marker in placeholders:
        key = marker.replace("[[TABLE:", "").replace("]]", "")
        rows = table_data.get(key, [])
        if not rows:
            continue
        headers = ["Metric", "Value", "Sample", "Source & Date", "Link"]
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}},
            {"insertTable": {"location": {"index": start}, "rows": len(rows) + 1, "columns": len(headers)}}]}).execute()
        doc_now = docs.documents().get(documentId=doc_id).execute()
        tables = [el for el in doc_now.get("body", {}).get("content", []) if el.get("table")]
        table_el = min(tables, key=lambda el: abs(el["startIndex"] - start))
        cell_starts = []
        for ri, row in enumerate(table_el["table"]["tableRows"]):
            for ci, cell in enumerate(row["tableCells"]):
                els = cell.get("content", [{}])[0].get("paragraph", {}).get("elements", [])
                idx = els[0].get("startIndex") if els else cell["startIndex"] + 1
                cell_starts.append((ri, ci, idx))
        values = [headers] + [[r.get("label", ""), r.get("value", ""), r.get("sample", ""),
                               r.get("source_date", ""), "View source" if r.get("link") else "—"] for r in rows]
        fill = []
        for ri, ci, idx in sorted(cell_starts, key=lambda x: x[2], reverse=True):
            value = values[ri][ci]
            if not value:
                continue
            fill.append({"insertText": {"location": {"index": idx}, "text": value}})
            if ri == 0:
                fill.append({"updateTextStyle": {"range": {"startIndex": idx, "endIndex": idx + len(value)},
                    "textStyle": {"bold": True}, "fields": "bold"}})
            elif ci == 4 and rows[ri - 1].get("link"):
                fill.append({"updateTextStyle": {"range": {"startIndex": idx, "endIndex": idx + len(value)},
                    "textStyle": {"link": {"url": rows[ri - 1]["link"],
                                  "foregroundColor": {"color": {"rgbColor": {"red": .07, "green": .33, "blue": .8}}},
                                  "underline": True}, "fields": "link,foregroundColor,underline"}})
        if fill:
            docs.documents().batchUpdate(documentId=doc_id, body={"requests": fill}).execute()
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [{
            "updateTableCellStyle": {"tableRange": {"tableCellLocation": {"tableStartLocation": {"index": table_el["startIndex"]},
                "rowIndex": 0, "columnIndex": 0}, "rowSpan": 1, "columnSpan": 5},
                "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": {"red": 217/255, "green": 217/255, "blue": 217/255}}},
                                   "paddingTop": {"magnitude": 4, "unit": "PT"}, "paddingBottom": {"magnitude": 4, "unit": "PT"}},
                "fields": "backgroundColor,paddingTop,paddingBottom"}}]}).execute()
