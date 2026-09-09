"""
Lagos Property Price Tracker — Change Detector v0.1
Compares this week's scraped CSV to last week's and flags:
  - price changes on listings that appear in both (matched by URL)
  - new listings that weren't there last time
  - listings that disappeared (rented/sold/delisted)

Usage:
    python detect_changes.py lagos_listings_2026-08-14.csv lagos_listings_2026-08-21.csv

Outputs a CHANGES report (printed + saved to changes_<date>.csv) that
email_report.py reads to build the actual email.
"""

import csv
import sys
from datetime import datetime

PRICE_CHANGE_THRESHOLD_PCT = 5  # flag anything moving more than this


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row.get("source_url") or row.get("listing_url"): row for row in csv.DictReader(f)}


def detect_changes(old_path, new_path):
    old_data = load_csv(old_path)
    new_data = load_csv(new_path)

    changes = []

    for url, new_row in new_data.items():
        old_row = old_data.get(url)
        if old_row is None:
            changes.append({
                "type": "new_listing",
                "location": new_row.get("location") or new_row.get("market_node", "N/A"),
                "bedrooms": new_row.get("bedrooms", "-"),
                "title": new_row.get("title", "Listing"),
                "old_price": None,
                "new_price": new_row.get("asking_price_ngn") or new_row.get("price_ngn"),
                "pct_change": None,
                "listing_url": url,
            })
            continue

        old_price = old_row.get("asking_price_ngn") or old_row.get("price_ngn")
        new_price = new_row.get("asking_price_ngn") or new_row.get("price_ngn")
        if old_price and new_price and old_price != new_price:
            old_price_i, new_price_i = int(old_price), int(new_price)
            pct = round(((new_price_i - old_price_i) / old_price_i) * 100, 1)
            if abs(pct) >= PRICE_CHANGE_THRESHOLD_PCT:
                changes.append({
                    "type": "price_change",
                    "location": new_row.get("location") or new_row.get("market_node", "N/A"),
                    "bedrooms": new_row.get("bedrooms", "-"),
                    "title": new_row.get("title", "Listing"),
                    "old_price": old_price_i,
                    "new_price": new_price_i,
                    "pct_change": pct,
                    "listing_url": url,
                })

    for url, old_row in old_data.items():
        if url not in new_data:
            changes.append({
                "type": "delisted",
                "location": old_row.get("location") or old_row.get("market_node", "N/A"),
                "bedrooms": old_row.get("bedrooms", "-"),
                "title": old_row.get("title", "Listing"),
                "old_price": old_row.get("asking_price_ngn") or old_row.get("price_ngn"),
                "new_price": None,
                "pct_change": None,
                "listing_url": url,
            })

    return changes


def run():
    if len(sys.argv) != 3:
        print("Usage: python detect_changes.py <previous.csv> <current.csv>")
        sys.exit(1)

    old_path, new_path = sys.argv[1], sys.argv[2]
    changes = detect_changes(old_path, new_path)

    print(f"Found {len(changes)} changes:")
    for c in changes:
        print(f"  [{c['type']}] {c['location']} {c['bedrooms']}BR — {c['title']} "
              f"({c['old_price']} -> {c['new_price']})")

    out_file = f"changes_{datetime.now().strftime('%Y-%m-%d')}.csv"
    if changes:
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=changes[0].keys())
            writer.writeheader()
            writer.writerows(changes)
        print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    run()
