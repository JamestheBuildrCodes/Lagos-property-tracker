# Client-preferred weekly report — change log

## Implemented

- Added `client_doc_report.py` as a separate report path. Each invocation calls the Google Docs create endpoint and never reuses `GOOGLE_DOC_ID`.
- Matches the supplied reference's Times New Roman typography, black 28pt title, blue `#2E74B5` city/area headings, gray `#D9D9D9` table header, and clickable `View source` links.
- Only computes summary rows from validated node-consistent listings and only publishes a price row when it has a real HTTP(S) source listing URL.
- Uses the repository's existing `MAILJET_API_KEY`, `MAILJET_SECRET_KEY`, `MAILJET_FROM_EMAIL`, `MAILJET_FROM_NAME`, `REPORT_CLIENT_EMAIL`, and `REPORT_TO_EMAIL` secret names.
- Fails the workflow if the new Google Doc cannot be published/shared or the separate notification email is not accepted.
- Fixed `docs_writer.py` headline currency, real Google Docs Title/Heading styles, actual bullets (removing the literal bullet glyphs), and a real Area Scorecard table.
- Fixed XLSX headline currency and column-aware integer/percentage number formats without letting a later generic formatter overwrite the scorecard formats.
- Hardened `scraper.py` card extraction against shared page containers and promotional/alert UI copy.
- Kept the existing node-consistency quality layer and honest available-period vs. six-month history labels.
- Added a separate workflow step after the existing report publication; the existing executive email and Google Sheet layers remain in place.

## Local verification

- Python compile check: passed.
- Unit tests: 29 passed.
- Report bundle built locally from the existing archived snapshot.
- Client DOCX built locally from the existing archived snapshot; it contained `View source` hyperlinks and the gray table header.
- XLSX headline values rendered as comma-formatted naira and scorecard percentage columns retained explicit `%` formats.
- No scraper was run and no Zyte credits were consumed.

## Not yet verified live

The Google Docs API table creation/styling and Mailjet delivery cannot be certified from offline/local tests. The first manual GitHub Actions run must verify the published Google Doc visually and confirm the notification email. The workflow is configured to fail if those steps fail.
