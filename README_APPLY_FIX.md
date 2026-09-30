# Lagos Property Tracker — complete fix patch

This patch is intended to overlay the existing `JamestheBuildrCodes/Lagos-property-tracker` repository. It is not a replacement project.

## Apply in Termux

1. Confirm the existing repository is clean before overlaying these files.
2. Unzip this archive into a temporary directory.
3. Copy the contents of `lagos_tracker_complete_fix/` into the repository root, preserving `.github/workflows/` and `tests/`.
4. Run `python -m py_compile *.py tests/*.py` and `python -m unittest discover -s tests -v`.
5. Review `git diff`, commit, and push `main`.
6. Only after verifying the required GitHub secrets, manually run **Actions → Nigeria Property Market Scan → Run workflow**. This starts the paid Zyte collection. Do not use `scraper.py` for local testing.

Required existing secrets include `ZYTE_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`, `REPORT_CLIENT_EMAIL`, `REPORT_TO_EMAIL`, `MAILJET_API_KEY`, `MAILJET_SECRET_KEY`, and `MAILJET_FROM_EMAIL`; `MAILJET_FROM_NAME` is optional. The sender must be active/validated in Mailjet.

The first live workflow run is still required to verify Google Docs API table insertion/styling and Mailjet delivery. Local tests do not claim live API verification.
