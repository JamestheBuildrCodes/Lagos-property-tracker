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
headings, gray #D9D9D9 table headers, and clickable `View source` links. The
final executive email is sent only after the new Doc and verified Sheet are ready,
so the client receives one message with the interpretation plus the report and
Sheet links. It covers only the nine tracked Lagos/Abuja nodes; it does not invent
Port Harcourt data. Optional AI commentary interprets whitelisted aggregate metrics;
the deterministic narrative remains if the AI key is absent or the API fails.

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
| `REPORT_CLIENT_EMAIL` | Client recipient (To) and Google Sheet/Doc Viewer |
| `REPORT_TO_EMAIL` | Your internal verification email (Cc); not the sender address |
| `GOOGLE_DOC_ID` | Optional existing analyst Google Doc to update in place |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Sheets service-account credentials (Editor access to the existing Sheet required) |
| `GOOGLE_SHEET_ID` | Existing client data Sheet ID |
| `GOOGLE_OAUTH_TOKEN_JSON` | Required OAuth token for creating the new client-preferred Google Doc each week |
| `OPENAI_API_KEY` | Optional key for AI interpretation of aggregate metrics only; omit it to use free deterministic analysis |
| `OPENAI_MODEL` | Explicit compatible model name required only when enabling the optional paid API |

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

1. builds the deterministic source manifest and runs architecture/data-quality tests;
2. runs Zyte authentication/connectivity preflight;
3. collects current data, then applies quality gates and location validation;
4. compares against the previous archived snapshot, labelling absent URLs as "not observed" rather than confirming a sale or withdrawal;
5. builds the executive email, workbook and analyst report from the same aggregate analysis; optional AI commentary is produced only when `OPENAI_API_KEY` is configured;
6. mirrors the workbook into the existing Google Sheet and verifies its cells by readback;
7. publishes the analyst Google Doc and archives its DOCX;
8. creates a new client snapshot Google Doc and verifies its URL;
9. sends one final executive email to `REPORT_CLIENT_EMAIL`, copying `REPORT_TO_EMAIL`, with report and Sheet links;
10. verifies Mailjet's message-level acceptance receipt, archives outputs and commits the result.

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
- `MAILJET_FROM_NAME` — sender display name; defaults to `Master Builder Inc.`.
- `REPORT_CLIENT_EMAIL` — client To recipient.
- `REPORT_TO_EMAIL` — internal owner copy (Cc), not the sender.
- `OPENAI_API_KEY` — optional; without it, reports use deterministic analysis.
- `OPENAI_MODEL` — optional model override; the code default is `gpt-6-luna`.
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
