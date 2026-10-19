"""Create a durable authorized-user token for Google Docs publication.

Use a Google Cloud OAuth client of type Desktop app (installed application).
Do not use a Web application client with an empty/incorrect redirect URI.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

CLIENT_FILE = Path("client_secret.json")
TOKEN_FILE = Path("google_oauth_token.json")


def main():
    if not CLIENT_FILE.is_file():
        raise SystemExit(
            "client_secret.json was not found. Download the OAuth client JSON "
            "for a Google Cloud OAuth client whose application type is Desktop app."
        )

    try:
        config = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("client_secret.json is unreadable or invalid JSON.") from exc

    if "installed" not in config:
        if "web" in config:
            raise SystemExit(
                "The downloaded client is type Web application. This script uses "
                "InstalledAppFlow and a local callback, so a Web client with blank "
                "Authorized redirect URIs will fail with redirect_uri_mismatch. "
                "In Google Cloud Console → APIs & Services → Credentials, create "
                "an OAuth client ID with application type Desktop app, download its "
                "JSON, and save it as client_secret.json. Then rerun this script."
            )
        raise SystemExit(
            "client_secret.json has neither an 'installed' nor a 'web' client config. "
            "Download the OAuth client JSON directly from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_FILE),
        SCOPES,
    )
    creds = flow.run_local_server(
        host="localhost",
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Open this URL to authorize Google Docs access: {url}",
        success_message="Google OAuth authorization completed. You may close this browser tab.",
    )

    if not creds.refresh_token:
        raise SystemExit(
            "Google returned no refresh_token. Revoke this app's access from your "
            "Google Account security settings and rerun with prompt=consent."
        )

    TOKEN_FILE.write_text(creds.to_json() + "\n", encoding="utf-8")
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    required = ("refresh_token", "client_id", "client_secret", "token_uri")
    missing = [key for key in required if not saved.get(key)]
    if missing:
        TOKEN_FILE.unlink(missing_ok=True)
        raise SystemExit("Generated token is incomplete; missing: " + ", ".join(missing))

    print("OAuth authorization successful.")
    print(f"Token saved to {TOKEN_FILE}.")
    print("Next: copy the ENTIRE contents of google_oauth_token.json into the GitHub")
    print("repository secret GOOGLE_OAUTH_TOKEN_JSON. Never commit either JSON file.")
    print("The token contents are intentionally not printed to the terminal.")


if __name__ == "__main__":
    main()
