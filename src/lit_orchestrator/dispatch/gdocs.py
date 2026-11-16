"""Create a Google Doc from rendered text. The only code that talks to Google.

Uses the Drive v3 REST API directly through `requests`: one call to trade the
stored refresh token for an access token, one multipart upload per document.
Uploading text/plain with a Google Docs target MIME type makes Drive do the
conversion, so there is no Docs API formatting code to maintain.

Scope is drive.file, which only reaches files this app created. That is why
the destination folder must be created by scripts/google_auth.py: a folder
made by hand in the Drive UI is invisible to this scope.
"""

from __future__ import annotations

import json

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DOC_MIME = "application/vnd.google-apps.document"
_BOUNDARY = "offshoot-boundary-7f3a9c"


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    response = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if response.status_code != 200:
        # invalid_grant here usually means the refresh token expired: see README.
        raise RuntimeError(f"Google token refresh failed ({response.status_code}): {response.text}")
    return response.json()["access_token"]


def build_upload_body(name: str, text: str, folder_id: str) -> bytes:
    metadata = {"name": name, "mimeType": DOC_MIME, "parents": [folder_id]}
    return (
        f"--{_BOUNDARY}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{_BOUNDARY}\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{text}\r\n"
        f"--{_BOUNDARY}--\r\n"
    ).encode("utf-8")


def create_doc(access_token: str, name: str, text: str, folder_id: str) -> tuple[str, str]:
    """Create the Doc and return (file id, browser URL)."""
    response = requests.post(
        UPLOAD_URL,
        params={"uploadType": "multipart", "fields": "id,webViewLink"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={_BOUNDARY}",
        },
        data=build_upload_body(name, text, folder_id),
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Drive upload failed ({response.status_code}): {response.text}")
    body = response.json()
    return body["id"], body["webViewLink"]
