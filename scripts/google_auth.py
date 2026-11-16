"""One-time Google setup. Run locally, never in CI.

Prerequisite: in Google Cloud Console create a project, enable the Google
Drive API, configure the OAuth consent screen, and create an OAuth client of
type "Desktop app". Put its id and secret in .env as GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET. Then:

    python scripts/google_auth.py

It opens a browser for consent, then prints GOOGLE_REFRESH_TOKEN and
GOOGLE_DRIVE_FOLDER_ID to copy into .env and into the repo's Actions secrets.

The folder is created here, by this app, because the drive.file scope cannot
see a folder you make by hand in the Drive UI.
"""

from __future__ import annotations

import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from lit_orchestrator import config

SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_NAME = "Offshoot drafts"


def main() -> None:
    config.load_env()
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.")

    state = secrets.token_urlsafe(16)
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received.update({key: values[0] for key, values in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Offshoot is authorised. You can close this tab.")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)  # port 0: any free port
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPE, "state": state,
        # offline + consent is what makes Google return a refresh token.
        "access_type": "offline", "prompt": "consent",
    })
    print("Opening a browser. If it does not open, visit:\n" + url)
    webbrowser.open(url)
    while "code" not in received and "error" not in received:
        server.handle_request()
    server.server_close()
    if received.get("state") != state or "code" not in received:
        sys.exit(f"Authorisation failed: {received.get('error', 'state mismatch')}")

    token = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": client_id, "client_secret": client_secret, "code": received["code"],
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    })
    token.raise_for_status()
    tokens = token.json()

    folder = requests.post(
        "https://www.googleapis.com/drive/v3/files", timeout=30,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
    )
    folder.raise_for_status()

    print(f'\nCreated the Drive folder "{FOLDER_NAME}". Add these to .env and to Actions secrets:\n')
    print(f"GOOGLE_REFRESH_TOKEN={tokens['refresh_token']}")
    print(f"GOOGLE_DRIVE_FOLDER_ID={folder.json()['id']}")


if __name__ == "__main__":
    main()
