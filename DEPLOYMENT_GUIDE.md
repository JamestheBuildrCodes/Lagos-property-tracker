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
│ Layer 3 — Analyst Google Doc + DOCX archive │
│ Additional — New client snapshot Google Doc weekly │
└──────────────────────────────────────┘
        ↓
Archive + GitHub history
```

### Layer 1 — Executive Decision Brief

`executive_brief_YYYY-MM-DD.html` is sent by Mailjet. It contains the market
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

`Lagos_Abuja_Property_Market_Intelligence_YYYY-MM-DD.docx` is the archive copy. The
analyst report is published by `docs_writer.py`; `GOOGLE_DOC_ID` optionally lets
that existing analyst document be updated in place.

Separately, `client_doc_report.py` creates a **brand-new Google Doc every run**
for the client-preferred market snapshot. It never reads or reuses `GOOGLE_DOC_ID`.
The document uses Times New Roman, a black 28pt title, blue #2E74B5 city/area
headings, gray #D9D9D9 table headers, and clickable `View source` links. It then
sends a separate Mailjet notification email with the new document URL. It only
covers the nine real Lagos/Abuja tracked nodes; it does not invent Port Harcourt data.

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
| `MAILJET_API_KEY` | Executive email and new-document notification |
| `MAILJET_SECRET_KEY` | Mailjet secret key |
| `MAILJET_FROM_EMAIL` | Active/validated Mailjet sender address |
| `MAILJET_FROM_NAME` | Optional sender display name |
| `REPORT_TO_EMAIL` | Your internal verification email (CC) |

**Mailjet production sending:** `MAILJET_FROM_EMAIL` must be an active/validated Mailjet sender address. An individually validated Gmail/Outlook/Yahoo sender is supported; a custom domain is not required for this setup.
| `REPORT_CLIENT_EMAIL` | Client recipient (To) and Google Sheet/Doc Viewer |
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
10. publishes Layer 3 as the analyst Google Doc and archives its DOCX;
11. creates a new client snapshot Google Doc, grants viewer access, and sends its separate notification email;
12. commits the archive back to GitHub.

## Local checks

The scraper/discovery tests are intentionally runnable without installing the
native DOCX/XLSX stack on Android Termux:

```bash
python -m py_compile *.py
python -m unittest discover -s tests -v
```

GitHub Actions performs the full dependency install and generates XLSX/DOCX.


### Mailjet email delivery
Set these GitHub Actions secrets:
- `MAILJET_API_KEY` — Mailjet API key.
- `MAILJET_SECRET_KEY` — Mailjet secret key.
- `MAILJET_FROM_EMAIL` — active/validated Mailjet sender address.
- `MAILJET_FROM_NAME` — optional display name; defaults to `Master Builder`.
- `REPORT_CLIENT_EMAIL` — client recipient (To).
- `REPORT_TO_EMAIL` — internal verification recipient (Cc).

The workflow uses Mailjet Send API v3.1. No custom domain is required when using an individually validated sender address.


## First live client-document verification

The DOCX builder and report formatting have been exercised locally without network
access or Zyte credits. The Google Docs API table insertion and Mailjet notification
require a live workflow run to verify against the account. Run the workflow manually
from **Actions → Nigeria Property Market Scan → Run workflow** after confirming all
secrets above exist. Check that the log contains `New weekly Google Doc published:`
and `Notification email accepted by Mailjet`, then open the new URL and visually
confirm the table cells, gray header row, and clickable `View source` links. The
workflow now fails rather than reporting success if publishing/sharing/email fails.
