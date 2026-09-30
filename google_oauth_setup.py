from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",
    SCOPES,
)

creds = flow.run_local_server(
    port=0,
    access_type="offline",
    prompt="consent",
)

with open("google_oauth_token.json", "w", encoding="utf-8") as f:
    f.write(creds.to_json())

print()
print("OAuth authorization successful.")
print("Token saved to google_oauth_token.json")
