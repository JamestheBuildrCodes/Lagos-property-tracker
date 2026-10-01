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

from mailjet_sender import recipients_from_values, send_message

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

LAGOS_NODES = [
    "Banana Island",
    "Old Ikoyi",
    "Lekki Phase 1",
    "Victoria Island",
    "Eko Atlantic",
    "Ikeja GRA",
]

ABUJA_NODES = [
    "Asokoro",
    "Maitama",
    "Wuse",
]

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

    for beds, group in sorted(
        by_beds.items(),
        key=lambda x: fnum(x[0]) or 0,
    ):
        prices = [
            fnum(r.get("asking_price_ngn"))
            for r in group
            if fnum(r.get("asking_price_ngn"))
        ]

        if not prices:
            continue

        example = sorted(
            group,
            key=lambda r: r.get("date_scraped") or "",
            reverse=True,
        )[0]

        out.append(
            {
                "label": (
                    f"{beds} Bedroom — median asking "
                    f"{'rent' if txn_type == 'rent' else 'sale price'}"
                ),
                "value": fmt_naira(statistics.median(prices))
                + ("/yr" if txn_type == "rent" else ""),
                "sample": (
                    f"{len(prices)} listing"
                    f"{'s' if len(prices) != 1 else ''}"
                ),
                "source_date": (
                    f"{example.get('source', 'Unknown')}, "
                    f"{example.get('date_scraped', 'unknown date')}"
                ),
                "link": example.get("source_url", ""),
            }
        )

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

    prices = [
        fnum(r.get("asking_price_ngn"))
        for r in group
        if fnum(r.get("asking_price_ngn"))
    ]

    if not prices:
        return []

    example = sorted(
        group,
        key=lambda r: r.get("date_scraped") or "",
        reverse=True,
    )[0]

    return [
        {
            "label": "Land — median asking price",
            "value": fmt_naira(statistics.median(prices)),
            "sample": (
                f"{len(prices)} listing"
                f"{'s' if len(prices) != 1 else ''}"
            ),
            "source_date": (
                f"{example.get('source', 'Unknown')}, "
                f"{example.get('date_scraped', 'unknown date')}"
            ),
            "link": example.get("source_url", ""),
        }
    ]


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

        if not (
            r.get("source_url") or ""
        ).strip().startswith(("https://", "http://")):
            continue

        group.append(r)

    return group


def _analysis_for_rows(rows, label):
    prices = [
        (fnum(r.get("asking_price_ngn")), r)
        for r in rows
    ]

    prices = [
        (p, r)
        for p, r in prices
        if p
    ]

    if not prices:
        return None

    by_source = {}

    for price, row in prices:
        by_source.setdefault(
            row.get("source") or "Unknown",
            [],
        ).append(price)

    ages = [
        fnum(r.get("listing_age_days"))
        for _, r in prices
        if fnum(r.get("listing_age_days")) is not None
    ]

    return {
        "label": label,
        "median": statistics.median([p for p, _ in prices]),
        "count": len(prices),
        "source_medians": {
            src: statistics.median(vals)
            for src, vals in by_source.items()
        },
        "freshest_age_days": min(ages) if ages else None,
    }


def _category_analysis(listings, node, txn_type, beds=None):
    return _analysis_for_rows(
        _category_group(listings, node, txn_type, beds),
        f"{beds} Bedroom" if beds is not None else "Land",
    )


def _discrepancy_note(analysis, node):
    source_medians = analysis["source_medians"]

    if len(source_medians) < 2:
        return None

    ordered = sorted(
        source_medians.items(),
        key=lambda item: item[1],
    )

    low_source, low_value = ordered[0]
    high_source, high_value = ordered[-1]

    if low_value <= 0:
        return None

    gap = round(
        (high_value - low_value) / low_value * 100,
        1,
    )

    if gap <= DISCREPANCY_THRESHOLD_PCT:
        return None

    return (
        f"Source disagreement — {analysis['label']} in {node}: "
        f"{high_source} has a median asking price of "
        f"{fmt_naira(high_value)}, compared with "
        f"{fmt_naira(low_value)} on {low_source}, a {gap}% difference. "
        f"The platforms may contain different property mixes or price "
        f"points; this is a reason to compare the underlying listings, "
        f"not evidence by itself that either platform is wrong."
    )


def _caveat_notes(analysis):
    notes = []

    if analysis["count"] < SMALL_SAMPLE_THRESHOLD:
        count = analysis["count"]

        notes.append(
            f"{analysis['label']}: only {count} listing"
            f"{'s' if count != 1 else ''} support this median. "
            "Treat it as a rough reference point until a larger "
            "comparable sample is available."
        )

    age = analysis.get("freshest_age_days")

    if age is not None and age > STALE_DAYS_THRESHOLD:
        notes.append(
            f"{analysis['label']}: even the freshest listing behind "
            f"this figure is {int(age)} days old, so this is a softer "
            "reference point than recently updated categories."
        )

    return notes


def _city_standout(listings, nodes, city):
    values = {}

    for node in nodes:
        a = _category_analysis(
            listings,
            node,
            "rent",
            "2",
        )

        if a:
            values[node] = a["median"]

    if len(values) < 2:
        return None

    low_node, low_value = min(
        values.items(),
        key=lambda item: item[1],
    )

    high_node, high_value = max(
        values.items(),
        key=lambda item: item[1],
    )

    if low_value <= 0:
        return None

    pct = round(
        (high_value - low_value) / low_value * 100
    )

    return (
        f"For 2-bedroom rentals, {high_node} has a median asking "
        f"rent about {pct}% above {low_node} "
        f"({fmt_naira(high_value)} versus {fmt_naira(low_value)} "
        f"per year). This is the clearest current price spread "
        f"across {city}'s tracked nodes with comparable data."
    )


def _coverage_summary(listings):
    all_nodes = LAGOS_NODES + ABUJA_NODES
    covered = set()
    beds_seen = set()

    for node in all_nodes:
        for txn in ("rent", "sale"):
            for row in _category_group(listings, node, txn):
                covered.add(node)

                if row.get("bedrooms") not in (None, ""):
                    beds_seen.add(str(row["bedrooms"]))

        if _category_group(listings, node, "land"):
            covered.add(node)

    missing_nodes = [
        node
        for node in all_nodes
        if node not in covered
    ]

    missing_beds = [
        f"{bed} Bedroom"
        for bed in range(1, 6)
        if str(bed) not in beds_seen
    ]

    return covered, missing_nodes, missing_beds



def _research_table_rows(research):
    out = []

    for row in research or []:
        title = (
            (row.get("title") or "").strip()
            or "Public research page"
        )

        public_price = fnum(
            row.get("public_sale_price_ngn")
        )

        land_area = fnum(
            row.get("land_area_sqm")
        )

        units = fnum(
            row.get("size_units")
        )

        if public_price:
            value = fmt_naira(public_price)
        elif land_area:
            value = (
                f"{land_area:,.0f} sqm land area; "
                "no public sale price parsed"
            )
        elif units:
            value = (
                f"{int(units):,} units; "
                "no public sale price parsed"
            )
        else:
            value = (
                "Public market/project context; "
                "no comparable asking price parsed"
            )

        updated = (
            row.get("last_updated")
            or row.get("date_added")
            or row.get("date_scraped")
            or "date unavailable"
        )

        out.append(
            {
                "label": (
                    f"{row.get('market_node') or row.get('location') or 'Market'} "
                    f"— {title}"
                ),
                "value": value,
                "range": "—",
                "sample": "Public research; not a listing",
                "source": "Estate Intel",
                "as_of": updated,
                "link": row.get("url", ""),
            }
        )

    return out


def _source_breakdown_rows(listings, node, txn_type, beds=None):
    group = _category_group(
        listings,
        node,
        txn_type,
        beds,
    )

    by_source = {}

    for row in group:
        source = row.get("source") or "Unknown"
        by_source.setdefault(source, []).append(row)

    out = []

    for source, source_rows in sorted(
        by_source.items(),
        key=lambda item: item[0].lower(),
    ):
        prices = [
            fnum(r.get("asking_price_ngn"))
            for r in source_rows
        ]
        prices = [
            p
            for p in prices
            if p is not None and p > 0
        ]

        if not prices:
            continue

        latest = sorted(
            source_rows,
            key=lambda r: (
                r.get("date_scraped")
                or r.get("last_updated")
                or ""
            ),
            reverse=True,
        )[0]

        label = (
            f"{beds}-bedroom"
            if beds is not None
            else "Land"
        )

        out.append(
            {
                "label": label,
                "value": (
                    f"{fmt_naira(statistics.median(prices))} "
                    "(median)"
                ),
                "range": (
                    f"{fmt_naira(min(prices))} – "
                    f"{fmt_naira(max(prices))}"
                ),
                "sample": str(len(prices)),
                "source": source,
                "as_of": (
                    latest.get("date_scraped")
                    or latest.get("last_updated")
                    or "date unavailable"
                ),
                "link": latest.get("source_url", ""),
            }
        )

    return out


def _node_transaction_rows(listings, node, txn_type):
    out = []

    if txn_type == "land":
        return _source_breakdown_rows(
            listings,
            node,
            "land",
        )

    for beds in range(1, 6):
        out.extend(
            _source_breakdown_rows(
                listings,
                node,
                txn_type,
                str(beds),
            )
        )

    return out


def _table_has_rows(listings, node, txn_type):
    return bool(
        _node_transaction_rows(
            listings,
            node,
            txn_type,
        )
    )


def _narrative_lines(listings, summary, research=None):
    lines = [
        ("h1", "1. What This Report Is"),
        (
            "body",
            "This is the current weekly market report generated from "
            "validated, auditable listing-level observations collected "
            "for the live tracker. Each reported price is a median for "
            "the stated source and segment, with the observed range, "
            "listing count, source, and collection date shown so the "
            "figure can be checked rather than read in isolation.",
        ),
        (
            "body",
            "Important: every price in this report is an online asking "
            "price published by an agent, developer, or listing platform. "
            "It is not a confirmed closed rent or sale transaction. "
            "Advertised prices may be negotiated away from the published "
            "figure. Where client closed-deal data becomes available, it "
            "can be incorporated as a ground-truth comparison.",
        ),
        ("h1", "2. Coverage & Method"),
        (
            "bullet",
            "Locations: Banana Island, Old Ikoyi, Lekki Phase 1, "
            "Victoria Island, Eko Atlantic, Ikeja GRA, Asokoro, Maitama, "
            "and Wuse.",
        ),
        (
            "bullet",
            "Property types: validated flats/apartments and selected "
            "land; bedroom-level tables cover 1–5 bedrooms where usable "
            "comparable listings exist.",
        ),
        (
            "bullet",
            "Transaction types: annual rent, sale, and land sale.",
        ),
        (
            "bullet",
            "Live comparable sources: Nigeria Property Centre and "
            "PropertyPro.ng. Estate Intel is used only for public "
            "research/project context; premium or login-gated content "
            "is not bypassed.",
        ),
        (
            "bullet",
            "Method: source-by-source medians from listing-level "
            "asking prices, with observed min–max ranges and sample "
            "counts. Sources are kept separate because platforms can "
            "contain different property mixes and price points.",
        ),
        (
            "bullet",
            "Current validation checks source URLs and market-node "
            "evidence. Cross-source matching of the same physical "
            "property is not guaranteed in this weekly snapshot.",
        ),
    ]

    for city, nodes in (
        ("Lagos", LAGOS_NODES),
        ("Abuja", ABUJA_NODES),
    ):
        rentable = [
            node
            for node in nodes
            if _table_has_rows(
                listings,
                node,
                "rent",
            )
        ]

        if not rentable:
            continue

        lines.append(("h1", "3. Rental Market"))

        lines.append(("h2", city))

        for node in rentable:
            lines.append(
                (
                    "h3",
                    f"{node} — Flats/Apartments (per annum)",
                )
            )
            lines.append(
                ("table", f"{node}_rent")
            )

    for city, nodes in (
        ("Lagos", LAGOS_NODES),
        ("Abuja", ABUJA_NODES),
    ):
        salable = [
            node
            for node in nodes
            if _table_has_rows(
                listings,
                node,
                "sale",
            )
        ]

        if not salable:
            continue

        lines.append(("h1", "4. Sales Market"))
        lines.append(("h2", city))

        for node in salable:
            lines.append(
                (
                    "h3",
                    f"{node} — Flats/Apartments & Houses (sale)",
                )
            )
            lines.append(
                ("table", f"{node}_sale")
            )

            for beds in range(1, 6):
                analysis = _category_analysis(
                    listings,
                    node,
                    "sale",
                    str(beds),
                )
                if not analysis:
                    continue

                note = _discrepancy_note(
                    analysis,
                    node,
                )
                if note:
                    lines.append(("body", note))

    lines.append(
        (
            "h1",
            "5. Land Market — and Cross-Source Discrepancies",
        )
    )

    any_land = False

    for city, nodes in (
        ("Lagos", LAGOS_NODES),
        ("Abuja", ABUJA_NODES),
    ):
        land_nodes = [
            node
            for node in nodes
            if _table_has_rows(
                listings,
                node,
                "land",
            )
        ]

        if not land_nodes:
            continue

        any_land = True
        lines.append(("h2", city))

        for node in land_nodes:
            lines.append(
                (
                    "h3",
                    f"{node} — Land for sale",
                )
            )
            lines.append(
                ("table", f"{node}_land")
            )

            analysis = _category_analysis(
                listings,
                node,
                "land",
            )
            if analysis:
                note = _discrepancy_note(
                    analysis,
                    node,
                )
                if note:
                    lines.append(("body", note))

    if not any_land:
        lines.append(
            (
                "body",
                "No validated land-for-sale rows were returned for "
                "this snapshot.",
            )
        )

    wow = summary.get("week_on_week", {})

    lines.append(
        ("h1", "6. Data Quality Notes")
    )

    lines.append(
        (
            "bullet",
            "Asking price versus transaction price: these figures "
            "describe advertised prices, not confirmed completed deals.",
        )
    )

    lines.append(
        (
            "bullet",
            "Sample size: source-level listing counts are shown "
            "beside every comparable figure; thin samples should be "
            "treated as directional rather than definitive market rates.",
        )
    )

    lines.append(
        (
            "bullet",
            "Cross-source differences are retained and flagged where "
            "the observed source medians differ materially; this can "
            "reflect different inventory rather than an error by a source.",
        )
    )

    lines.append(
        (
            "bullet",
            "Deduplication: the same physical property may still appear "
            "on more than one platform. Cross-source matching remains a "
            "separate data-quality improvement.",
        )
    )

    lines.append(
        (
            "bullet",
            "Freshness: the report uses the collection date shown in "
            "each row and flags stale source observations rather than "
            "silently presenting them as current.",
        )
    )

    lines.append(
        ("h1", "7. What Happens Next")
    )

    changes = summary.get("changes", {})

    if any(changes.values()):
        lines.append(
            (
                "body",
                "Weekly pulse: "
                f"{changes.get('new_listings', 0)} new listings, "
                f"{changes.get('price_increases', 0)} price increases, "
                f"{changes.get('price_reductions', 0)} price reductions, "
                f"and {changes.get('delisted', 0)} delisted listings "
                "were recorded in the latest comparison where a prior "
                "snapshot was available.",
            )
        )

    if wow.get("available"):
        for item in wow.get("narrative", []):
            lines.append(("bullet", item))
    else:
        lines.append(
            (
                "body",
                "Week-on-week comparison will become more informative "
                "as the tracker retains additional dated snapshots.",
            )
        )

    lines.append(
        (
            "bullet",
            "Continue the weekly pulse: new listings, removed listings, "
            "price moves, sample growth, source health, and source "
            "discrepancies.",
        )
    )

    lines.append(
        (
            "bullet",
            "Build the monthly report from the same historical snapshots "
            "once enough observations exist for a stable month-on-month "
            "comparison.",
        )
    )

    lines.append(
        (
            "bullet",
            "Widen comparable samples, strengthen cross-source "
            "deduplication, and expand city coverage only after source "
            "accessibility and data quality are validated.",
        )
    )

    lines.append(
        (
            "body",
            "Port Harcourt is not currently tracked by the live "
            "validated scraper, so this report makes no Port Harcourt "
            "price claim. The system is structured so additional city/source "
            "adapters can be added without changing the reporting model.",
        )
    )

    lines.append(
        ("h1", "8. Sources & Definitions")
    )

    source_names = sorted(
        set(summary.get("source_names", []))
    )

    lines.append(
        (
            "bullet",
            "Live comparable listing sources: "
            + (
                ", ".join(source_names)
                if source_names
                else "none recorded"
            ),
        )
    )

    lines.append(
        (
            "body",
            "Estate Intel public-research pages are contextual "
            "references only and are not treated as comparable "
            "listing-price observations unless a public price is "
            "explicitly shown in the row.",
        )
    )

    if research:
        lines.append(
            (
                "h2",
                "Estate Intel — Public Research Context",
            )
        )
        lines.append(
            ("table", "estate_intel_public")
        )

    lines.append(
        (
            "body",
            "Definitions: asking price is the price published at the "
            "time of listing; median is the middle value in the ordered "
            "set and is less distorted by extreme outliers than a mean; "
            "the listing count (n) is the number of validated comparable "
            "rows supporting that source-level figure at collection time.",
        )
    )

    return lines


def build_docx(
    listings,
    summary,
    output=None,
    research=None,
):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    output = (
        output
        or f"Lagos_Property_Market_Snapshot_"
        f"{datetime.now(timezone.utc):%Y-%m-%d}.docx"
    )

    doc = Document()

    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Pt(48)
    section.left_margin = section.right_margin = Pt(52)

    def set_font(run, size, color=None):
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)

        if color:
            run.font.color.rgb = RGBColor.from_string(color)

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

    def h3(text):
        p = doc.add_paragraph(style="Heading 3")
        r = p.add_run(text)
        set_font(r, 12, BLUE)
        r.bold = True
        return p

    def body(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(text)
        set_font(r, 11)
        return p

    def bullet(text):
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(text)
        set_font(r, 11)
        return p

    def add_hyperlink(paragraph, url, label):
        rel = paragraph.part.relate_to(
            url,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True,
        )

        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rel)

        run = OxmlElement("w:r")
        props = OxmlElement("w:rPr")

        color = OxmlElement("w:color")
        color.set(qn("w:val"), "1155CC")

        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")

        props.append(color)
        props.append(underline)

        run.append(props)

        t = OxmlElement("w:t")
        t.text = label

        run.append(t)
        link.append(run)
        paragraph._p.append(link)

    def table(rows):
        if not rows:
            body(
                "No comparable rows were available for this section."
            )
            return

        t = doc.add_table(
            rows=1,
            cols=6,
        )
        t.style = "Table Grid"
        t.autofit = True

        headers = [
            "Segment",
            "Reported price",
            "Range",
            "Listings (n)",
            "Source",
            "As of",
        ]

        for i, label in enumerate(headers):
            cell = t.rows[0].cells[i]
            p = cell.paragraphs[0]
            r = p.add_run(label)
            r.bold = True
            set_font(r, 10)

            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:fill"), HEADER_FILL)
            cell._tc.get_or_add_tcPr().append(shd)

        for item in rows:
            cells = t.add_row().cells

            values = [
                item.get("label", ""),
                item.get("value", ""),
                item.get("range", "—"),
                item.get("sample", ""),
            ]

            for i, value in enumerate(values):
                p = cells[i].paragraphs[0]
                r = p.add_run(str(value))
                set_font(r, 9)

            p = cells[4].paragraphs[0]
            source = item.get("source", "") or "Unknown"

            if item.get("link"):
                add_hyperlink(
                    p,
                    item["link"],
                    source,
                )
            else:
                r = p.add_run(source)
                set_font(r, 9)

            p = cells[5].paragraphs[0]
            r = p.add_run(
                str(item.get("as_of", "date unavailable"))
            )
            set_font(r, 9)

        doc.add_paragraph()

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    r = title.add_run(
        "LAGOS PROPERTY MARKET INTELLIGENCE"
    )
    set_font(r, 20, "000000")
    r.bold = True

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER

    r = sub.add_run(
        "Weekly Market Report — Lagos & Abuja"
    )
    set_font(r, 13)
    r.bold = True

    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    r = date_p.add_run(
        f"Collection date: "
        f"{datetime.now(timezone.utc):%d %B %Y}  |  "
        f"Report version: Weekly-"
        f"{datetime.now(timezone.utc):%Y-%m-%d}  |  "
        "Prepared for: Client"
    )
    set_font(r, 10, GRAY)

    for kind, value in _narrative_lines(
        listings,
        summary,
        research,
    ):
        if kind == "h1":
            h1(value)
        elif kind == "h2":
            h2(value)
        elif kind == "h3":
            h3(value)
        elif kind == "body":
            body(value)
        elif kind == "bullet":
            bullet(value)
        elif kind == "table":
            if value == "estate_intel_public":
                table(
                    _research_table_rows(
                        research or []
                    )
                )
            else:
                node, txn = value.rsplit("_", 1)

                table(
                    _node_transaction_rows(
                        listings,
                        node,
                        txn,
                    )
                )

    doc.save(output)

    return output


def _oauth_services():
    """Build Docs/Drive clients using a human user's OAuth refresh token."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    raw = os.environ.get(
        "GOOGLE_OAUTH_TOKEN_JSON",
        "",
    ).strip()

    if not raw:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is missing"
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is not valid JSON"
        ) from exc

    required = (
        "refresh_token",
        "client_id",
        "client_secret",
        "token_uri",
    )

    missing = [
        key
        for key in required
        if not info.get(key)
    ]

    if missing:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is missing "
            "required fields: "
            + ", ".join(missing)
        )

    scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_authorized_user_info(
        info,
        scopes=scopes,
    )

    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError(
                "OAuth credentials are expired and have "
                "no refresh token"
            )

        creds.refresh(Request())

    return (
        build(
            "docs",
            "v1",
            credentials=creds,
            cache_discovery=False,
        ),
        build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        ),
    )


def _report_text(listings, summary):
    lines = [
        "Lagos & Abuja Property Market Snapshot",
        "Weekly Intelligence Report — Real Tracked Listings, Linked to Source",
        f"Data captured {datetime.now(timezone.utc):%d %B %Y}",
        "",
        "Every price below is an online asking price, not a confirmed closed transaction.",
    ]

    for city, nodes in (
        ("Lagos", LAGOS_NODES),
        ("Abuja", ABUJA_NODES),
    ):
        lines += ["", city]

        for node in nodes:
            rent = bedroom_rows(
                listings,
                node,
                "rent",
            )

            sale = bedroom_rows(
                listings,
                node,
                "sale",
            )

            land = land_rows(
                listings,
                node,
            )

            if not (rent or sale or land):
                continue

            lines += ["", node]

            for title, rows in (
                ("Rental Market (per annum)", rent),
                ("Sales Market", sale),
                ("Land", land),
            ):
                if not rows:
                    continue

                lines += [
                    title,
                    "Metric | Value | Sample | Source & Date | Link",
                ]

                for row in rows:
                    lines.append(
                        " | ".join(
                            [
                                row["label"],
                                row["value"],
                                row["sample"],
                                row["source_date"],
                                row.get("link", ""),
                            ]
                        )
                    )

    lines += [
        "",
        "What Stands Out This Week",
    ]

    sig = summary.get("signals", {})

    for label, obj in [
        (
            "Most expensive area",
            sig.get("most_expensive"),
        ),
        (
            "Strongest rental/yield screen",
            sig.get("investment"),
        ),
        (
            "Best buyer value screen",
            sig.get("buyer_value"),
        ),
        (
            "Lowest observed land ₦/sqm",
            sig.get("land_opportunity"),
        ),
    ]:
        lines.append(
            f"• {label}: "
            f"{obj['market_node'] if obj else 'Not enough data yet'}"
        )

    lines += [
        "",
        "Sources Used in This Report",
        ", ".join(
            summary.get("source_names", [])
        )
        or "No sources recorded",
    ]

    return "\n".join(lines) + "\n"


def _iter_placeholder_paragraphs(docs, doc_id):
    """Find [[TABLE:key]] placeholder paragraphs in a Google Doc.

    Returns:
        list[tuple[int, int, str]]:
            (start_index, end_index, marker)
    """
    document = (
        docs.documents()
        .get(documentId=doc_id)
        .execute()
    )

    placeholders = []

    for element in document.get(
        "body",
        {},
    ).get(
        "content",
        [],
    ):
        paragraph = element.get("paragraph")

        if not paragraph:
            continue

        text_parts = []

        for child in paragraph.get(
            "elements",
            [],
        ):
            text_run = child.get("textRun")

            if text_run and "content" in text_run:
                text_parts.append(
                    text_run["content"]
                )

        paragraph_text = "".join(
            text_parts
        ).strip()

        if not paragraph_text.startswith(
            "[[TABLE:"
        ):
            continue

        if not paragraph_text.endswith(
            "]]"
        ):
            continue

        start_index = element.get(
            "startIndex"
        )

        end_index = element.get(
            "endIndex"
        )

        if (
            start_index is None
            or end_index is None
        ):
            continue

        placeholders.append(
            (
                start_index,
                end_index,
                paragraph_text,
            )
        )

    return placeholders


def publish_google_doc(
    listings,
    summary,
    research=None,
):
    """Create a new styled Google Doc using a human user's OAuth token."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    raw = os.environ.get(
        "GOOGLE_OAUTH_TOKEN_JSON",
        "",
    ).strip()

    if not raw:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is required; "
            "service-account Drive quota is not suitable "
            "for new weekly documents."
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is not valid JSON"
        ) from exc

    required = (
        "refresh_token",
        "client_id",
        "client_secret",
        "token_uri",
    )

    missing = [
        key
        for key in required
        if not info.get(key)
    ]

    if missing:
        raise RuntimeError(
            "GOOGLE_OAUTH_TOKEN_JSON is missing: "
            + ", ".join(missing)
        )

    creds = Credentials.from_authorized_user_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ],
    )

    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError(
                "OAuth credentials are expired and have "
                "no refresh token"
            )

        creds.refresh(Request())

    docs = build(
        "docs",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )

    drive = build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )

    folder_id = os.environ.get(
        "GOOGLE_WEEKLY_REPORT_FOLDER_ID",
        "",
    ).strip()

    if not folder_id:
        raise RuntimeError(
            "GOOGLE_WEEKLY_REPORT_FOLDER_ID is required."
        )

    title = (
        "LAGOS PROPERTY MARKET INTELLIGENCE — "
        f"{datetime.now(timezone.utc):%Y-%m-%d}"
    )

    created = (
        drive.files()
        .create(
            body={
                "name": title,
                "mimeType": "application/vnd.google-apps.document",
                "parents": [folder_id],
            },
            fields="id,webViewLink",
        )
        .execute()
    )

    doc_id = created["id"]

    lines = [
        title,
        "Weekly Market Report — Lagos & Abuja",
        (
            f"Collection date: {datetime.now(timezone.utc):%d %B %Y}  |  "
            f"Report version: Weekly-{datetime.now(timezone.utc):%Y-%m-%d}  |  "
            "Prepared for: Client"
        ),
        "",
    ]

    table_data = {}

    for kind, value in _narrative_lines(
        listings,
        summary,
        research,
    ):
        if kind == "table":
            lines.append(
                f"[[TABLE:{value}]]"
            )

            if value == "estate_intel_public":
                table_data[value] = (
                    _research_table_rows(
                        research or []
                    )
                )
            else:
                node, txn = value.rsplit(
                    "_",
                    1,
                )

                table_data[value] = _node_transaction_rows(
                    listings,
                    node,
                    txn,
                )

        elif kind == "bullet":
            lines.append(
                "• " + value
            )

        else:
            lines.append(value)

    text = "\n".join(lines) + "\n"

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {
                            "index": 1
                        },
                        "text": text,
                    }
                }
            ]
        },
    ).execute()

    heading1 = {
        "1. What This Report Is",
        "2. Coverage & Method",
        "3. Rental Market",
        "4. Sales Market",
        "5. Land Market — and Cross-Source Discrepancies",
        "6. Data Quality Notes",
        "7. What Happens Next",
        "8. Sources & Definitions",
    }

    heading2 = {
        "Lagos",
        "Abuja",
        "Estate Intel — Public Research Context",
    }

    heading3 = {
        f"{node} — Flats/Apartments (per annum)"
        for node in LAGOS_NODES + ABUJA_NODES
    } | {
        f"{node} — Flats/Apartments & Houses (sale)"
        for node in LAGOS_NODES + ABUJA_NODES
    } | {
        f"{node} — Land for sale"
        for node in LAGOS_NODES + ABUJA_NODES
    }

    requests = [
        {
            "updateTextStyle": {
                "range": {
                    "startIndex": 1,
                    "endIndex": len(text) + 1,
                },
                "textStyle": {
                    "weightedFontFamily": {
                        "fontFamily": "Times New Roman"
                    },
                    "fontSize": {
                        "magnitude": 11,
                        "unit": "PT",
                    },
                },
                "fields": (
                    "weightedFontFamily,fontSize"
                ),
            }
        }
    ]

    offset = 0

    for line in text.splitlines(True):
        raw_line = line.rstrip("\n")

        start = offset + 1
        end = (
            offset
            + 1
            + len(raw_line)
        )

        if raw_line == title:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end + 1,
                        },
                        "paragraphStyle": {
                            "namedStyleType": "TITLE",
                            "alignment": "CENTER",
                        },
                        "fields": (
                            "namedStyleType,alignment"
                        ),
                    }
                }
            )

            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "textStyle": {
                            "weightedFontFamily": {
                                "fontFamily": "Times New Roman"
                            },
                            "fontSize": {
                                "magnitude": 28,
                                "unit": "PT",
                            },
                            "foregroundColor": {
                                "color": {
                                    "rgbColor": {
                                        "red": 0,
                                        "green": 0,
                                        "blue": 0,
                                    }
                                }
                            },
                            "bold": False,
                        },
                        "fields": (
                            "weightedFontFamily,"
                            "fontSize,"
                            "foregroundColor,"
                            "bold"
                        ),
                    }
                }
            )

        elif raw_line.startswith(
            "Weekly Market Report —"
        ):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end + 1,
                        },
                        "paragraphStyle": {
                            "alignment": "CENTER"
                        },
                        "fields": "alignment",
                    }
                }
            )

            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "textStyle": {
                            "fontSize": {
                                "magnitude": 12,
                                "unit": "PT",
                            }
                        },
                        "fields": "fontSize",
                    }
                }
            )

        elif raw_line.startswith(
            "Data captured "
        ):
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end + 1,
                        },
                        "paragraphStyle": {
                            "alignment": "CENTER"
                        },
                        "fields": "alignment",
                    }
                }
            )

            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "textStyle": {
                            "fontSize": {
                                "magnitude": 10,
                                "unit": "PT",
                            },
                            "foregroundColor": {
                                "color": {
                                    "rgbColor": {
                                        "red": 0.4,
                                        "green": 0.4,
                                        "blue": 0.4,
                                    }
                                }
                            },
                        },
                        "fields": (
                            "fontSize,"
                            "foregroundColor"
                        ),
                    }
                }
            )

        elif (
            raw_line in heading1
            or raw_line in heading2
            or raw_line in heading3
        ):
            level = (
                "HEADING_1"
                if raw_line in heading1
                else (
                    "HEADING_2"
                    if raw_line in heading2
                    else "HEADING_3"
                )
            )

            size = (
                16
                if level == "HEADING_1"
                else 13
                if level == "HEADING_2"
                else 12
            )

            style = {
                "weightedFontFamily": {
                    "fontFamily": "Times New Roman"
                },
                "fontSize": {
                    "magnitude": size,
                    "unit": "PT",
                },
                "foregroundColor": {
                    "color": {
                        "rgbColor": {
                            "red": 46 / 255,
                            "green": 116 / 255,
                            "blue": 181 / 255,
                        }
                    }
                },
            }

            fields = (
                "weightedFontFamily,"
                "fontSize,"
                "foregroundColor"
            )

            if level == "HEADING_3":
                style["bold"] = True
                fields += ",bold"

            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end + 1,
                        },
                        "paragraphStyle": {
                            "namedStyleType": level
                        },
                        "fields": "namedStyleType",
                    }
                }
            )

            requests.append(
                {
                    "updateTextStyle": {
                        "range": {
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "textStyle": style,
                        "fields": fields,
                    }
                }
            )

        offset += len(line)

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    placeholders = sorted(
        _iter_placeholder_paragraphs(
            docs,
            doc_id,
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    for start, end, marker in placeholders:
        key = (
            marker
            .replace("[[TABLE:", "")
            .replace("]]", "")
        )

        rows = table_data.get(
            key,
            [],
        )

        if not rows:
            continue

        headers = [
            "Segment",
            "Reported price",
            "Range",
            "Listings (n)",
            "Source",
            "As of",
        ]

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": start,
                                "endIndex": end,
                            }
                        }
                    },
                    {
                        "insertTable": {
                            "location": {
                                "index": start
                            },
                            "rows": len(rows) + 1,
                            "columns": len(headers),
                        }
                    },
                ]
            },
        ).execute()

        doc_now = (
            docs.documents()
            .get(documentId=doc_id)
            .execute()
        )

        tables = [
            el
            for el in doc_now.get(
                "body",
                {},
            ).get(
                "content",
                [],
            )
            if el.get("table")
        ]

        if not tables:
            continue

        table_el = min(
            tables,
            key=lambda el: abs(
                el["startIndex"] - start
            ),
        )

        cell_starts = []

        for ri, row in enumerate(
            table_el["table"]["tableRows"]
        ):
            for ci, cell in enumerate(
                row["tableCells"]
            ):
                els = (
                    cell.get(
                        "content",
                        [{}],
                    )[0]
                    .get(
                        "paragraph",
                        {},
                    )
                    .get(
                        "elements",
                        [],
                    )
                )

                idx = (
                    els[0].get("startIndex")
                    if els
                    else cell["startIndex"] + 1
                )

                cell_starts.append(
                    (ri, ci, idx)
                )

        values = [headers] + [
            [
                r.get("label", ""),
                r.get("value", ""),
                r.get("range", "—"),
                r.get("sample", ""),
                r.get("source", "Unknown"),
                r.get("as_of", "date unavailable"),
            ]
            for r in rows
        ]

        fill = []

        for ri, ci, idx in sorted(
            cell_starts,
            key=lambda x: x[2],
            reverse=True,
        ):
            value = values[ri][ci]

            if not value:
                continue

            fill.append(
                {
                    "insertText": {
                        "location": {
                            "index": idx
                        },
                        "text": value,
                    }
                }
            )

            if ri == 0:
                fill.append(
                    {
                        "updateTextStyle": {
                            "range": {
                                "startIndex": idx,
                                "endIndex": (
                                    idx + len(value)
                                ),
                            },
                            "textStyle": {
                                "bold": True
                            },
                            "fields": "bold",
                        }
                    }
                )

            elif (
                ci == 4
                and rows[ri - 1].get("link")
            ):
                fill.append(
                    {
                        "updateTextStyle": {
                            "range": {
                                "startIndex": idx,
                                "endIndex": (
                                    idx + len(value)
                                ),
                            },
                            "textStyle": {
                                "link": {
                                    "url": rows[
                                        ri - 1
                                    ]["link"]
                                },
                                "foregroundColor": {
                                    "color": {
                                        "rgbColor": {
                                            "red": 0.07,
                                            "green": 0.33,
                                            "blue": 0.8,
                                        }
                                    }
                                },
                                "underline": True,
                            },
                            "fields": (
                                "link,"
                                "foregroundColor,"
                                "underline"
                            ),
                        }
                    }
                )

        if fill:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": fill
                },
            ).execute()

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "updateTableCellStyle": {
                            "tableRange": {
                                "tableCellLocation": {
                                    "tableStartLocation": {
                                        "index": table_el[
                                            "startIndex"
                                        ]
                                    },
                                    "rowIndex": 0,
                                    "columnIndex": 0,
                                },
                                "rowSpan": 1,
                                "columnSpan": 6,
                            },
                            "tableCellStyle": {
                                "backgroundColor": {
                                    "color": {
                                        "rgbColor": {
                                            "red": 217 / 255,
                                            "green": 217 / 255,
                                            "blue": 217 / 255,
                                        }
                                    }
                                },
                                "paddingTop": {
                                    "magnitude": 4,
                                    "unit": "PT",
                                },
                                "paddingBottom": {
                                    "magnitude": 4,
                                    "unit": "PT",
                                },
                            },
                            "fields": (
                                "backgroundColor,"
                                "paddingTop,"
                                "paddingBottom"
                            ),
                        }
                    }
                ]
            },
        ).execute()

    recipients = []

    for key in (
        "REPORT_CLIENT_EMAIL",
        "REPORT_TO_EMAIL",
    ):
        recipients.extend(
            x.strip()
            for x in os.environ.get(
                key,
                "",
            ).split(",")
            if "@" in x
        )

    for email in dict.fromkeys(recipients):
        try:
            drive.permissions().create(
                fileId=doc_id,
                body={
                    "type": "user",
                    "role": "reader",
                    "emailAddress": email,
                },
                sendNotificationEmail=True,
            ).execute()

        except HttpError as exc:
            print(
                f"Warning: document created, but sharing "
                f"with {email} failed: {exc}"
            )

    url = (
        created.get("webViewLink")
        or f"https://docs.google.com/document/d/{doc_id}/edit"
    )

    Path(
        "client_doc_url.txt"
    ).write_text(
        url + "\n",
        encoding="utf-8",
    )

    print(
        f"New weekly Google Doc published: {url}"
    )

    return doc_id, url



def send_notification_email(doc_url):
    recipients = recipients_from_values(
        os.environ.get("REPORT_CLIENT_EMAIL", ""),
        os.environ.get("REPORT_TO_EMAIL", ""),
    )

    send_message(
        to=recipients,
        subject="Your Weekly Lagos & Abuja Property Market Snapshot",
        text_body=(
            "This week's market snapshot document is ready.\n\n"
            f"Open the report: {doc_url}"
        ),
        html_body=(
            "<p>This week's market snapshot document is ready.</p>"
            f"<p><a href='{doc_url}'>Open the report</a></p>"
        ),
        layer="client-doc",
    )
def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python client_doc_report.py "
            "<listings.csv> [estateintel_research.csv] [changes.csv]"
        )

    raw = load_csv(
        sys.argv[1]
    )

    listings = clean_rows(raw)

    if not listings:
        raise SystemExit(
            "No validated listings with auditable source URLs; "
            "refusing to publish client report."
        )

    research_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "none"
    )

    research = (
        load_csv(research_path)
        if (
            research_path.lower() != "none"
            and Path(research_path).exists()
        )
        else []
    )

    print(
        f"Client report input rows: {len(raw)}; "
        f"validated rows: {len(listings)}; "
        f"Estate Intel public research rows: {len(research)}"
    )

    changes_path = (
        sys.argv[3]
        if len(sys.argv) > 3
        else "none"
    )

    changes = (
        load_csv(changes_path)
        if (
            changes_path.lower() != "none"
            and Path(changes_path).exists()
        )
        else []
    )

    summary = build_summary(
        listings,
        changes,
        sys.argv[1],
    )

    if research:
        summary["source_names"] = sorted(
            set(
                summary.get(
                    "source_names",
                    [],
                )
            )
            | {"Estate Intel"}
        )

    docx_path = build_docx(
        listings,
        summary,
        research=research,
    )

    print(
        f"DOCX created: {docx_path}"
    )

    if os.environ.get(
        "GOOGLE_OAUTH_TOKEN_JSON"
    ):
        _, url = publish_google_doc(
            listings,
            summary,
            research=research,
        )

        send_notification_email(url)

    else:
        print(
            "GOOGLE_OAUTH_TOKEN_JSON not set — "
            "skipping Google Doc publish, DOCX only."
        )


if __name__ == "__main__":
    main()