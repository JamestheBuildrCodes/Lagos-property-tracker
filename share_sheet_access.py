"""Grant and verify the client's viewer access to the existing Google Sheet."""
from __future__ import annotations

import json
import os
import sys


def mask_email(value: str) -> str:
    if "@" not in value:
        return "(invalid email)"
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def main() -> int:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    email = os.environ.get("REPORT_CLIENT_EMAIL", "").strip()
    if not raw or not sheet_id or "@" not in email:
        raise SystemExit("GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, and a valid REPORT_CLIENT_EMAIL are required.")

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    existing = drive.permissions().list(
        fileId=sheet_id,
        fields="permissions(id,type,role,emailAddress,deleted)",
        supportsAllDrives=True,
    ).execute().get("permissions", [])

    permission = next(
        (
            item for item in existing
            if item.get("type") == "user"
            and str(item.get("emailAddress", "")).lower() == email.lower()
            and not item.get("deleted", False)
        ),
        None,
    )

    if permission is None:
        permission = drive.permissions().create(
            fileId=sheet_id,
            body={"type": "user", "role": "reader", "emailAddress": email},
            sendNotificationEmail=True,
            supportsAllDrives=True,
            fields="id,type,role,emailAddress",
        ).execute()
        print(f"Created viewer permission with notification enabled for {mask_email(email)}.")
    elif permission.get("role") not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
        permission = drive.permissions().update(
            fileId=sheet_id,
            permissionId=permission["id"],
            body={"role": "reader"},
            supportsAllDrives=True,
            fields="id,type,role,emailAddress",
        ).execute()
        print(f"Updated client permission for {mask_email(email)}.")

    verified = drive.permissions().list(
        fileId=sheet_id,
        fields="permissions(id,type,role,emailAddress,deleted)",
        supportsAllDrives=True,
    ).execute().get("permissions", [])
    match = next(
        (
            item for item in verified
            if item.get("type") == "user"
            and str(item.get("emailAddress", "")).lower() == email.lower()
            and not item.get("deleted", False)
        ),
        None,
    )
    if not match or match.get("role") not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
        raise RuntimeError(f"Google Drive did not confirm viewer access for {mask_email(email)}.")
    print(f"Verified Google Sheet access: role={match.get('role')}; recipient={mask_email(email)}.")
    print(f"Sheet URL: https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
