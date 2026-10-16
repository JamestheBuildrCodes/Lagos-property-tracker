# Lagos Property Tracker — complete fix patch

This patch is intended to overlay the existing `JamestheBuildrCodes/Lagos-property-tracker` repository. It is not a replacement project.

## Apply in Termux

1. Confirm the existing repository is clean before overlaying these files.
2. Unzip this archive into a temporary directory.
3. Copy the contents of `lagos_tracker_complete_fix/` into the repository root, preserving `.github/workflows/` and `tests/`.
4. Run `python -m py_compile *.py tests/*.py` and `python -m unittest discover -s tests -v`.
5. Review `git diff`, commit, and push `main`.
6. Only after verifying the required GitHub secrets, manually run **Actions → Nigeria Property Market Scan → Run workflow**. This starts the paid Zyte collection. Do not use `scraper.py` for local testing.

Required live secrets include `ZYTE_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`, `REPORT_CLIENT_EMAIL`, `REPORT_TO_EMAIL`, `MAILJET_API_KEY`, `MAILJET_SECRET_KEY`, and `MAILJET_FROM_EMAIL`; `GROQ_API_KEY` is optional and enables Groq interpretation/second-pass checks. `GOOGLE_OAUTH_TOKEN_JSON` is required for publishing the client-preferred weekly Google Doc into the consumer Gmail user's Drive folder. It must be a complete authorized-user token JSON containing `refresh_token`, `client_id`, `client_secret`, and `token_uri`; downloading the OAuth Web client JSON alone is not enough. If this secret is incomplete or revoked, the workflow can still email the DOCX attachment, but Google Doc publication will not succeed. The service account is separate and currently cannot access the configured folder (Drive returns 404) and lacks permission for the Docs API (403), so do not treat service-account fallback as a verified replacement. The workflow displays the sender as `Master Builder Inc.`. `MAILJET_FROM_EMAIL` must be the actual corporate sender address and must be approved in Mailjet; `REPORT_TO_EMAIL` is your internal Cc, and `REPORT_CLIENT_EMAIL` is the client To recipient.

The first live workflow run is still required to verify Google Docs API table insertion/styling and Mailjet delivery. Local tests do not claim live API verification.


## Fix the current Google Docs publication failure

The repository was checked against the latest GitHub Actions logs (15 October 2026). The latest report-delivery run succeeded at sending the enhanced DOCX by Mailjet, but it did **not** publish a Google Doc. The logs show two separate issues: the service account cannot access the configured folder (Drive 404 / Docs 403), and the OAuth authorized-user token is incomplete because it lacks a valid `refresh_token`.

1. In Google Cloud, keep the OAuth audience **External** and your Gmail account listed as a test user.
2. Open **APIs & Services → Credentials** (or **Google Auth Platform → Clients**) and open the existing OAuth **Web application** client.
3. If using Google's OAuth Playground to generate the authorized-user token, add `https://developers.google.com/oauthplayground` under **Authorized redirect URIs**, save, and wait a short time for the change to apply.
4. Open [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground). In settings, enable **Use your own OAuth credentials** and enter the existing Web client ID and client secret. Request these scopes: `https://www.googleapis.com/auth/drive` and `https://www.googleapis.com/auth/documents`. Authorize with the same Gmail account that can open the destination Drive folder. Exchange the authorization code for tokens and ensure the response includes a `refresh_token` (re-consent if Google does not return one).
5. In GitHub repository Settings → Secrets and variables → Actions, update `GOOGLE_OAUTH_TOKEN_JSON` with a single JSON object containing at least `refresh_token`, `client_id`, `client_secret`, and `token_uri` (normally `https://oauth2.googleapis.com/token`). Include the returned refresh token. Never commit or paste the token into a public issue or source file.
6. Manually run **Actions → Final Client Report Delivery → Run workflow**. This is a report-only workflow and does not spend Zyte scraping credits. Confirm the run reports a verified Google Doc in the configured folder, not `docx_attachment_fallback_no_google_doc`.

The configured destination folder ID is `1pwAwektfnA52XkHzTIDkLGLHG0q_R1t3`. Open that folder while signed in as the same Gmail account used for OAuth. If it does not open for that account, correct the folder ID or grant that account access before rerunning.
