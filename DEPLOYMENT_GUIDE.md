# Lagos Property Market Intelligence — Deployment Guide

This is a single GitHub Actions pipeline that produces all three intelligence
layers from the same normalized market snapshot.

## Architecture

```text
Canonical discovery manifest
        ↓
Transport validation + collection
        ↓
Normalized current snapshot
        ↓
Market analysis engine
        ↓
┌──────────────────────────────────────┐
│ Layer 1 — Executive email            │
│ Layer 2 — Existing Google Sheet      │
│ Layer 3 — Google Doc + DOCX archive │
└──────────────────────────────────────┘
        ↓
Archive + GitHub history
```

### Layer 1 — Executive Decision Brief

`executive_brief_YYYY-MM-DD.html` is sent by Resend. It contains the market
snapshot, key market signals and decision signals. It intentionally does not
send the entire raw listing table.

### Layer 2 — Decision Data Room

`market_intelligence_YYYY-MM-DD.xlsx` is the canonical workbook and is mirrored
into the **existing Google Sheet**. Tabs:

- Executive Summary
- Area Scorecard
- Current Listings
- Weekly Changes
- Estate Intel Public
- Methodology

### Layer 3 — Analyst Report

`Lagos_Property_Market_Intelligence_YYYY-MM-DD.docx` is the archive copy. The
same report is published as a real Google Doc by `docs_writer.py`. Set
`GOOGLE_DOC_ID` to update an existing report in place; leave it blank to create
a new weekly Google Doc.

## Coverage

Nine monitored nodes:

- Banana Island
- Old Ikoyi
- Lekki Phase 1
- Victoria Island
- Eko Atlantic
- Ikeja GRA
- Asokoro
- Maitama
- Wuse

Asset coverage:

- apartment sales: 1–5BR;
- apartment rentals: 1–5BR;
- residential land: asking price, size and ₦/sqm where available;
- Estate Intel public research;
- current data targeted to the latest 31 days;
- six-month directional trends from archived snapshots.

All property prices are **asking prices**, not confirmed closed transactions.

## Secrets

Set these GitHub Actions repository secrets:

| Secret | Purpose |
|---|---|
| `ZYTE_API_KEY` | PropertyPro/Estate Intel browser HTML |
| `RESEND_API_KEY` | Executive email |
| `REPORT_TO_EMAIL` | Primary email recipient (comma-separated is supported) |
| `REPORT_CLIENT_EMAIL` | Optional client recipient and Google Sheet/Doc Viewer |
| `GOOGLE_DOC_ID` | Optional Google Doc to update in place; blank creates a new Doc |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Existing Google Sheet authentication |
| `GOOGLE_SHEET_ID` | Existing Sheet ID |

For the Google Sheet, share the existing spreadsheet with the service account's
`client_email` as **Editor**. Do not create a replacement spreadsheet.

The current project Sheet ID is:

`1xz79MzD65u8Z77exhNz4DWyOXFopsP6obZKtCbsy-ss`

If Google authentication returns `invalid_grant: account not found`, the service
account key is stale/invalid or the account no longer exists. Replace the
GitHub secret with a fresh key from the active service account and keep the same
Sheet ID.

## GitHub Actions

The workflow installs production dependencies on Ubuntu/Python 3.11, not on
Termux. It then:

1. builds the deterministic manifest;
2. runs architecture/security tests;
3. runs Zyte preflight;
4. collects current data;
5. validates the normalized snapshot;
6. detects listing changes and metric-level week-on-week movement;
7. builds the executive email, polished workbook and analyst report from one analysis pass;
8. sends Layer 1 to the configured distribution;
9. mirrors and styles the existing Layer 2 Google Sheet and can grant the client Viewer access;
10. publishes Layer 3 as a real Google Doc and archives the DOCX;
11. commits the archive back to GitHub.

## Local checks

The scraper/discovery tests are intentionally runnable without installing the
native DOCX/XLSX stack on Android Termux:

```bash
python -m py_compile *.py
python -m unittest discover -s tests -v
```

GitHub Actions performs the full dependency install and generates XLSX/DOCX.
