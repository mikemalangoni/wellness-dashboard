"""Google OAuth 2.0 authentication for the Spine Log wellness dashboard."""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]

_BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = str(_BASE_DIR / "credentials.json")
TOKEN_FILE = str(_BASE_DIR / "token.json")


def get_credentials() -> Credentials:
    """Return valid OAuth credentials, refreshing or re-authorising as needed.

    On the first run this opens a browser tab for the user to grant access.
    The resulting token is saved to token.json so subsequent runs skip the
    browser step.
    """
    creds: Credentials | None = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())

    return creds
