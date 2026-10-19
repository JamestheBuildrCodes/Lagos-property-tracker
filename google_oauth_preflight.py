"""Validate Google OAuth and Docs/Drive write access without exposing credentials."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def main() -> int:
    raw = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", "").strip()
    folder_id = os.environ.get("GOOGLE_WEEKLY_REPORT_FOLDER_ID", "").strip()
    if not raw:
        raise SystemExit("GOOGLE_OAUTH_TOKEN_JSON is missing from GitHub Actions secrets.")
    if not folder_id:
        raise SystemExit("GOOGLE_WEEKLY_REPORT_FOLDER_ID is missing.")

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("GOOGLE_OAUTH_TOKEN_JSON is not valid JSON.") from exc
    if not isinstance(info, dict):
        raise SystemExit("GOOGLE_OAUTH_TOKEN_JSON must be a JSON object.")

    nested = info.get("installed") or info.get("web") or {}
    if isinstance(nested, dict):
        info = {**nested, **info}

    required = ("refresh_token", "client_id", "client_secret", "token_uri")
    missing = [key for key in required if not info.get(key)]
    if missing:
        raise SystemExit(
            "OAuth secret is a client-credentials JSON or incomplete token. "
            "Missing authorized-user fields: " + ", ".join(missing) +
            ". Re-authorize the Google account and store the resulting token JSON, "
            "not just the downloaded client_secret.json."
        )

    creds = Credentials.from_authorized_user_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    try:
        if not creds.valid:
            creds.refresh(Request())
    except Exception as exc:
        # Print the error class and Google's safe error text, never the token.
        raise SystemExit(
            f"OAuth refresh failed ({type(exc).__name__}): {exc}. "
            "Check the OAuth client ID/secret, consent-screen test-user status, "
            "and whether the refresh token was revoked or expired."
        ) from exc

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    test_id = None
    try:
        folder = drive.files().get(
            fileId=folder_id, fields="id,name,mimeType,capabilities(canAddChildren)"
        ).execute()
        if folder.get("mimeType") != "application/vnd.google-apps.folder":
            raise SystemExit("GOOGLE_WEEKLY_REPORT_FOLDER_ID does not identify a Drive folder.")
        if folder.get("capabilities", {}).get("canAddChildren") is False:
            raise SystemExit(
                "OAuth account can see the target folder but cannot create files in it. "
                "Share the folder with the OAuth Google account as Editor or correct the folder ID."
            )

        created = drive.files().create(
            body={
                "name": "TEMP — Google OAuth publication preflight",
                "mimeType": "application/vnd.google-apps.document",
                "parents": [folder_id],
            },
            fields="id",
        ).execute()
        test_id = created["id"]
        marker = "Google OAuth Docs/Drive write preflight passed."
        docs.documents().batchUpdate(
            documentId=test_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": marker}}]},
        ).execute()
        result = docs.documents().get(documentId=test_id).execute()
        body_text = "".join(
            run.get("textRun", {}).get("content", "")
            for element in result.get("body", {}).get("content", [])
            for paragraph in [element.get("paragraph", {})]
            for run in paragraph.get("elements", [])
        )
        if marker not in body_text:
            raise SystemExit("Google Doc was created, but content read-back verification failed.")
        print("Google OAuth refresh: PASS")
        print("Drive target folder access: PASS")
        print("Create Google Doc: PASS")
        print("Write and read-back verification: PASS")
        print("Temporary document cleanup: pending")
    finally:
        if test_id:
            try:
                drive.files().delete(fileId=test_id).execute()
                print("Temporary document cleanup: PASS")
            except Exception as exc:
                print(
                    "WARNING: temporary preflight document could not be deleted "
                    f"({type(exc).__name__}); delete it manually in the target folder."
                )
    print("Google OAuth / Docs preflight completed at " + datetime.now(timezone.utc).isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
