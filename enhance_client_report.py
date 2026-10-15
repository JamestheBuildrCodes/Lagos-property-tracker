"""Final client-report quality assurance and chart enhancement.

Runs after client_doc_report.py. It does not silently delete statistical outliers:
it records them for review, adds sample-aware charts and appends evidence/methodology.
Claude commentary is optional; deterministic calculations remain authoritative.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
from docx import Document
from docx.shared import Inches, Pt, RGBColor

from market_analysis import clean_rows, fnum, normalize_node, transaction_label, is_apartment

NODES = [
    "Banana Island", "Old Ikoyi", "Lekki Phase 1", "Victoria Island",
    "Eko Atlantic", "Ikeja GRA", "Asokoro", "Maitama", "Wuse",
]
MIN_CHART_SAMPLE = 3


def load_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return clean_rows(list(csv.DictReader(handle)))


def num(row, *keys):
    for key in keys:
        value = fnum(row.get(key))
        if value is not None:
            return value
    return None


def node_of(row):
    return normalize_node(row.get("market_node") or row.get("location"))


def comparable_rows(rows, txn):
    result = []
    for row in rows:
        if transaction_label(row) != txn:
            continue
        if txn != "land" and not is_apartment(row):
            continue
        if not str(row.get("source_url") or "").startswith(("https://", "http://")):
            continue
        price = num(row, "asking_price_ngn")
        if price is None or price <= 0:
            continue
        item = dict(row)
        item["_price"] = price
        result.append(item)
    return result


def data_quality_audit(rows):
    findings = []
    buckets = defaultdict(list)
    for row in rows:
        txn = transaction_label(row)
        node = node_of(row)
        beds = str(row.get("bedrooms") or "unspecified")
        if txn not in {"rent", "sale", "land"} or not node:
            continue
        if txn != "land" and not is_apartment(row):
            continue
        price = num(row, "asking_price_ngn")
        if price is None or price <= 0:
            continue
        buckets[(node, txn, beds)].append((price, row))

    for (node, txn, beds), values in sorted(buckets.items()):
        prices = [x[0] for x in values]
        median = statistics.median(prices)
        if len(prices) >= 2 and min(prices) > 0:
            spread = max(prices) / min(prices)
            if spread >= 10:
                low_price, low_row = min(values, key=lambda item: item[0])
                high_price, high_row = max(values, key=lambda item: item[0])
                findings.append({
                    "priority": "high",
                    "type": "wide_price_spread_review",
                    "market_node": node,
                    "transaction": txn,
                    "bedrooms": beds,
                    "min_asking_price_ngn": low_price,
                    "max_asking_price_ngn": high_price,
                    "spread_ratio": round(spread, 2),
                    "source_url": high_row.get("source_url", ""),
                    "source": high_row.get("source", "Unknown"),
                    "reason": "Segment maximum is at least 10x its minimum. Check rent period, sale/rent classification, bedroom count, bulk listing, location and possible extraction/price-unit error. Do not delete solely because it is an outlier.",
                })
        if len(prices) >= 2 and min(prices) > 0:
            spread = max(prices) / min(prices)
            if spread >= 10:
                low_price, low_row = min(values, key=lambda item: item[0])
                high_price, high_row = max(values, key=lambda item: item[0])
                findings.append({
                    "priority": "high",
                    "type": "wide_price_spread_review",
                    "market_node": node,
                    "transaction": txn,
                    "bedrooms": beds,
                    "min_asking_price_ngn": low_price,
                    "max_asking_price_ngn": high_price,
                    "spread_ratio": round(spread, 2),
                    "source_url": high_row.get("source_url", ""),
                    "source": high_row.get("source", "Unknown"),
                    "reason": "Segment maximum is at least 10x its minimum. Check rent period, sale/rent classification, bedroom count, bulk listing, location and possible extraction/price-unit error. Do not delete solely because it is an outlier.",
                })
        if len(prices) >= 3 and median > 0:
            outliers = [(p, r) for p, r in values if p >= median * 10 or p <= median / 10]
            for price, row in outliers:
                findings.append({
                    "priority": "high",
                    "type": "price_outlier_review",
                    "market_node": node,
                    "transaction": txn,
                    "bedrooms": beds,
                    "asking_price_ngn": price,
                    "segment_median_ngn": median,
                    "ratio_to_median": round(price / median, 2),
                    "source": row.get("source", "Unknown"),
                    "source_url": row.get("source_url", ""),
                    "reason": "Price is at least 10x above or below the segment median; verify property type, period, unit, currency and source text. Not automatically excluded.",
                })
        for price, row in values:
            if txn == "rent" and price >= 100_000_000:
                findings.append({
                    "priority": "high",
                    "type": "rent_period_or_price_review",
                    "market_node": node,
                    "transaction": txn,
                    "bedrooms": beds,
                    "asking_price_ngn": price,
                    "source": row.get("source", "Unknown"),
                    "source_url": row.get("source_url", ""),
                    "reason": "Annual rent above ₦100m is possible for exceptional properties but must be checked against the listing text and monthly/annual period before comparison.",
                })
            if txn == "land":
                size = num(row, "size_sqm", "land_area_sqm")
                unit = num(row, "price_per_sqm_ngn")
                if size and size > 0:
                    calculated = price / size
                    if unit and abs(unit - calculated) > max(1, calculated * 0.05):
                        findings.append({
                            "priority": "high",
                            "type": "land_unit_price_mismatch",
                            "market_node": node,
                            "asking_price_ngn": price,
                            "size_sqm": size,
                            "captured_price_per_sqm_ngn": unit,
                            "recalculated_price_per_sqm_ngn": round(calculated, 2),
                            "source": row.get("source", "Unknown"),
                            "source_url": row.get("source_url", ""),
                            "reason": "Captured unit price differs by more than 5% from total asking price divided by plot size.",
                        })
    return findings


def make_chart(path, title, ylabel, labels, values, counts):
    if not values:
        return False
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(labels, values)
    ax.set_title(title, loc="left", fontsize=13, pad=14)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", labelrotation=28)
    for bar, value, count in zip(bars, values, counts):
        ax.annotate(f"n={count}", (bar.get_x() + bar.get_width()/2, bar.get_height()),
                    xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
    ax.grid(axis="y", alpha=0.22)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return True


def build_charts(rows, out_dir):
    charts = []
    groups = defaultdict(list)
    for row in comparable_rows(rows, "rent"):
        groups[(node_of(row), str(row.get("bedrooms") or "?"))].append(row["_price"])
    selected = [(k, v) for k, v in groups.items() if len(v) >= MIN_CHART_SAMPLE]
    selected.sort(key=lambda kv: (kv[0][0], int(kv[0][1]) if kv[0][1].isdigit() else 99))
    selected = selected[:12]
    if selected:
        path = out_dir / "client_chart_rent.png"
        if make_chart(path, "Annual asking rent by location and bedrooms",
                      "Asking rent (NGN/year)",
                      [f"{n}\n{b} bed" for (n, b), _ in selected],
                      [statistics.median(v) for _, v in selected],
                      [len(v) for _, v in selected]):
            charts.append((path, "Annual asking rent by location and bedroom count"))
    groups = defaultdict(list)
    for row in comparable_rows(rows, "sale"):
        groups[(node_of(row), str(row.get("bedrooms") or "?"))].append(row["_price"])
    selected = [(k, v) for k, v in groups.items() if len(v) >= MIN_CHART_SAMPLE]
    selected.sort(key=lambda kv: (kv[0][0], int(kv[0][1]) if kv[0][1].isdigit() else 99))
    selected = selected[:12]
    if selected:
        path = out_dir / "client_chart_sale.png"
        if make_chart(path, "Apartment asking sale prices by location and bedrooms",
                      "Asking sale price (NGN)",
                      [f"{n}\n{b} bed" for (n, b), _ in selected],
                      [statistics.median(v) for _, v in selected],
                      [len(v) for _, v in selected]):
            charts.append((path, "Apartment asking sale prices by location and bedroom count"))
    groups = defaultdict(list)
    for row in comparable_rows(rows, "land"):
        size = num(row, "size_sqm", "land_area_sqm")
        if size and size > 0:
            groups[node_of(row)].append(num(row, "asking_price_ngn") / size)
    selected = [(k, v) for k, v in groups.items() if k and len(v) >= MIN_CHART_SAMPLE]
    selected.sort(key=lambda kv: kv[0])
    if selected:
        path = out_dir / "client_chart_land.png"
        if make_chart(path, "Land asking price per square metre",
                      "Asking price (NGN/sqm)", [k for k, _ in selected],
                      [statistics.median(v) for _, v in selected],
                      [len(v) for _, v in selected]):
            charts.append((path, "Land asking price per square metre"))
    return charts


def ai_commentary(summary):
    """Optional Claude call; never use model output to calculate or overwrite figures."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return {
            "provider": "deterministic_fallback",
            "commentary": "Use this snapshot as an asking-price and listing-availability signal, not as a record of completed transactions. Give greatest weight to categories with at least five comparable listings, inspect flagged outliers against the original listing, and treat gaps as missing coverage rather than evidence of no supply."
        }
    payload = {
        "date": summary["report_date"],
        "validated_listing_count": summary["validated_listing_count"],
        "category_samples": summary["category_samples"],
        "quality_findings": summary["quality_findings"][:25],
        "coverage_notes": [
            "The tracker currently covers six Lagos nodes and three Abuja nodes.",
            "Institutional research is contextual and is not mixed into listing-level medians.",
            "Do not invent trends, closed prices, yields, forecasts, causes, or unprovided facts.",
            "State sample sizes and uncertainty; recommend checking original listing links.",
        ],
    }
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            "max_tokens": 700,
            "temperature": 0,
            "system": "You are a cautious Nigerian real-estate market research analyst. Write concise, actionable client commentary using only supplied evidence. Never calculate or invent numbers. Clearly separate observed listing data from interpretation. Mention material limitations.",
            "messages": [{"role": "user", "content": "Write 3-5 concise bullet points of market commentary based only on this JSON:\n" + json.dumps(payload, ensure_ascii=False)}],
        },
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    text = "\n".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text").strip()
    if not text:
        raise RuntimeError("Claude returned no text commentary")
    return {"provider": "anthropic", "model": body.get("model"), "commentary": text}


def append_section(docx_path, rows, findings, charts, commentary, audit_path):
    doc = Document(str(docx_path))
    doc.add_page_break()
    doc.add_heading("Charts, Data Quality & Decision Notes", level=1)
    p = doc.add_paragraph()
    p.add_run("Reporting date: ").bold = True
    p.add_run(datetime.now(timezone.utc).strftime("%d %B %Y") + " (UTC)")
    doc.add_paragraph(
        "Charts use validated asking listings from the current snapshot. They are not closed-sale evidence, "
        "a full-market census, or a forecast. Charts are shown only where the comparable segment has at least "
        f"{MIN_CHART_SAMPLE} listings; the n label is the sample size."
    )
    doc.add_heading("Market commentary and practical actions", level=2)
    for line in commentary.get("commentary", "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if line:
            doc.add_paragraph(line, style="List Bullet")
    if not commentary.get("commentary"):
        doc.add_paragraph("No AI commentary was returned. Use the data-quality and sample-size notes below.")
    for path, title in charts:
        doc.add_heading(title, level=2)
        doc.add_picture(str(path), width=Inches(6.2))
    doc.add_heading("Data quality exceptions requiring source review", level=2)
    if findings:
        doc.add_paragraph(
            f"{len(findings)} potential issue(s) were flagged. These are review prompts, not automatic deletions; "
            "confirm the original listing, property type, location, price period, currency, plot size and unit before use."
        )
        table = doc.add_table(rows=1, cols=5)
        table.style = "Light Shading Accent 1"
        headers = ["Priority / issue", "Area / category", "Observed value", "Reason", "Source"]
        for cell, text in zip(table.rows[0].cells, headers):
            cell.text = text
        for item in findings[:40]:
            row = table.add_row().cells
            row[0].text = f"{item.get('priority','review').upper()}\n{item.get('type','')}"
            row[1].text = f"{item.get('market_node','Unknown')} / {item.get('transaction','')}"
            val = item.get("asking_price_ngn")
            row[2].text = f"₦{val:,.0f}" if isinstance(val, (int, float)) else str(val or "—")
            row[3].text = item.get("reason", "")
            row[4].text = item.get("source_url", "")[:180]
    else:
        doc.add_paragraph("No high-priority outlier or land-unit mismatch was detected by the current deterministic checks. This does not guarantee every listing is correct.")
    doc.add_heading("Source and methodology notes", level=2)
    for note in [
        "Live comparable listing sources currently represented by the pipeline: Nigeria Property Centre and PropertyPro, subject to the sources present in this run.",
        "Estate Intel public research is contextual and must not be mixed into listing-level asking-price medians. Premium or login-gated content is not collected.",
        "Knight Frank Nigeria research may be used for contextual triangulation only after confirming the publication period and definitions; it is not a live listing feed.",
        "Cushman & Wakefield Nigeria/Lagos residential comparable coverage has not been verified. Do not present unrelated global or data-centre research as residential evidence.",
        "The status of any Estate Intel paid/commercial arrangement is unconfirmed and must be confirmed directly with the account owner/vendor.",
        "Current tracked location coverage: six Lagos nodes (Banana Island, Old Ikoyi, Lekki Phase 1, Victoria Island, Eko Atlantic, Ikeja GRA) and three Abuja nodes (Asokoro, Maitama, Wuse). Port Harcourt is not yet included in this client report's equivalent node-level series.",
        "One listing is an observation, not a meaningful range or stable median. Samples below five should be treated as thin. Listing prices are asking prices, not completed transaction prices.",
        "Reporting schedule: Monday 08:00 Africa/Lagos. A configured schedule is not proof of inbox delivery; provider receipts and actual recipient confirmation must be checked after each run.",
    ]:
        doc.add_paragraph(note, style="List Bullet")
    doc.save(str(docx_path))


def main():
    import sys
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python enhance_client_report.py listings.csv client_report.docx")
    csv_path, docx_path = Path(sys.argv[1]), Path(sys.argv[2])
    rows = load_rows(csv_path)
    findings = data_quality_audit(rows)
    groups = defaultdict(list)
    for row in rows:
        txn = transaction_label(row)
        if txn not in {"rent", "sale", "land"}:
            continue
        if txn != "land" and not is_apartment(row):
            continue
        price = num(row, "asking_price_ngn")
        if price and price > 0:
            key = f"{node_of(row)} | {txn} | {row.get('bedrooms') or 'unspecified'} bed"
            groups[key].append(price)
    summary = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "validated_listing_count": len(rows),
        "category_samples": {k: {"count": len(v), "median_asking_price_ngn": statistics.median(v)} for k, v in sorted(groups.items())},
        "quality_findings": findings,
    }
    try:
        commentary = ai_commentary(summary)
    except Exception as exc:
        commentary = {
            "provider": "deterministic_fallback_after_api_error",
            "error": f"{type(exc).__name__}: {exc}",
            "commentary": "Use this snapshot as an asking-price and listing-availability signal, not as evidence of completed transactions. Verify flagged outliers against original source text, prioritize segments with larger comparable samples, and treat missing coverage as unknown rather than zero supply."
        }
    charts = build_charts(rows, docx_path.parent)
    append_section(docx_path, rows, findings, charts, commentary, Path("client_report_quality_audit.json"))
    Path("client_report_quality_audit.json").write_text(json.dumps({
        **summary, "commentary_provider": commentary.get("provider"),
        "commentary_model": commentary.get("model"),
        "commentary_error": commentary.get("error"),
        "charts_inserted": [str(p) for p, _ in charts],
        "docx": str(docx_path),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "docx": str(docx_path),
        "validated_rows": len(rows),
        "quality_findings": len(findings),
        "charts_inserted": len(charts),
        "commentary_provider": commentary.get("provider"),
    }, indent=2))


if __name__ == "__main__":
    main()
