"""Google OAuth 2.0 authentication for the Spine Log wellness dashboard."""

import json
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

    In cloud deployments, credentials are loaded from Streamlit secrets
    (token_json key). Locally, falls back to token.json / credentials.json files.
    """
    # ── Cloud path: load from Streamlit secrets ────────────────────────────────
    try:
        import streamlit as st
        if "token_json" in st.secrets:
            token_data = json.loads(st.secrets["token_json"])
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
    except Exception:
        pass  # not running in Streamlit or no secrets file, fall through

    # ── CI / env var path: TOKEN_JSON environment variable ────────────────────
    token_json_env = os.environ.get("TOKEN_JSON")
    if token_json_env:
        token_data = json.loads(token_json_env)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    # ── Local path: read/write token.json ─────────────────────────────────────
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
