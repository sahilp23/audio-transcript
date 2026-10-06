"""A small Google Drive v3 client (website mode), using only the standard library.

The website signs in with the "drive.file" permission: it can only see and
change files it created itself, never the rest of your Drive. Everything lives
in one "Concall Player" folder that the website creates.

Auth: an OAuth refresh token (from Google sign-in, see webauth.py) is exchanged
for short-lived access tokens as needed.
"""

import json
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from . import __version__

API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDER = "application/vnd.google-apps.folder"
USER_AGENT = f"ConcallPlayer/{__version__}"
FILE_FIELDS = "id,name,mimeType,parents,appProperties,size,modifiedTime"
RESUMABLE_OVER = 5 * 1024 * 1024  # bigger files are uploaded in chunks


class DriveError(Exception):
    pass


class AuthExpired(DriveError):
    """The sign-in is no longer valid (revoked or expired): sign in again."""


def mime_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {
        ".json": "application/json", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg",
        ".wav": "audio/wav", ".aac": "audio/aac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
        ".webm": "audio/webm", ".flac": "audio/flac", ".pdf": "application/pdf", ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(ext, "application/octet-stream")


class Drive:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self._token: Optional[str] = None
        self._expires = 0.0
        self._lock = threading.Lock()

    # ---------- auth ----------

    def access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires - 120:
                return self._token
            body = urllib.parse.urlencode({
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token",
            }).encode()
            req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:200]
                if exc.code in (400, 401) and "invalid_grant" in detail:
                    raise AuthExpired("Google sign-in expired. Please sign in again.") from exc
                raise DriveError(f"Google sign-in failed ({exc.code}): {detail}") from exc
            self._token = data["access_token"]
            self._expires = time.time() + float(data.get("expires_in", 3600))
            return self._token

    # ---------- requests ----------

    def _request(self, method: str, url: str, body: bytes = None, headers: dict = None, timeout: float = 120):
        for attempt in range(4):
            req = urllib.request.Request(url, data=body, method=method, headers={
                "Authorization": f"Bearer {self.access_token()}", "User-Agent": USER_AGENT, **(headers or {})})
            try:
                return urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self._token = None  # access token expired early: refresh once
                    continue
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                detail = exc.read().decode(errors="replace")[:300]
                raise DriveError(f"Google Drive said {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise DriveError(f"Couldn't reach Google Drive: {exc}") from exc
        raise DriveError("Google Drive kept refusing the request")

    def _json(self, method: str, url: str, payload: dict = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json; charset=UTF-8"} if payload is not None else {}
        with self._request(method, url, body, headers) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    # ---------- files ----------

    def list_files(self, query: str = "trashed = false") -> list[dict]:
        """All files the app can see (drive.file: only the ones it created)."""
        out, page = [], None
        while True:
            params = {"q": query, "fields": f"nextPageToken,files({FILE_FIELDS})", "pageSize": "1000",
                      "spaces": "drive"}
            if page:
                params["pageToken"] = page
            data = self._json("GET", f"{API}/files?{urllib.parse.urlencode(params)}")
            out += data.get("files", [])
            page = data.get("nextPageToken")
            if not page:
                return out

    def create_folder(self, name: str, parent: Optional[str] = None, props: dict = None) -> str:
        meta = {"name": name, "mimeType": FOLDER, "appProperties": props or {}}
        if parent:
            meta["parents"] = [parent]
        return self._json("POST", f"{API}/files?fields=id", meta)["id"]

    def upload_bytes(self, name: str, data: bytes, parent: str, props: dict = None) -> str:
        boundary = "concall" + secrets.token_hex(8)
        meta = {"name": name, "parents": [parent], "appProperties": props or {}}
        body = b"".join([
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            json.dumps(meta).encode(),
            f"\r\n--{boundary}\r\nContent-Type: {mime_for(name)}\r\n\r\n".encode(),
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        with self._request("POST", f"{UPLOAD_API}/files?uploadType=multipart&fields=id", body,
                           {"Content-Type": f"multipart/related; boundary={boundary}"}) as r:
            return json.loads(r.read())["id"]

    def update_bytes(self, file_id: str, data: bytes, name: str) -> None:
        with self._request("PATCH", f"{UPLOAD_API}/files/{file_id}?uploadType=media&fields=id", data,
                           {"Content-Type": mime_for(name)}) as r:
            r.read()

    def start_resumable(self, name: str, parent: str, props: dict = None, size: Optional[int] = None,
                        origin: Optional[str] = None) -> str:
        """Begin a resumable upload; returns the session URL to PUT the bytes to.
        With `origin`, the browser at that address may upload to the session directly."""
        headers = {"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": mime_for(name)}
        if size is not None:
            headers["X-Upload-Content-Length"] = str(size)
        if origin:
            headers["Origin"] = origin
        meta = json.dumps({"name": name, "parents": [parent], "appProperties": props or {}}).encode()
        with self._request("POST", f"{UPLOAD_API}/files?uploadType=resumable&fields={FILE_FIELDS}", meta,
                           headers) as r:
            location = r.headers.get("Location")
        if not location:
            raise DriveError("Google Drive didn't start the upload")
        return location

    def upload_file(self, path: Path, name: str, parent: str, props: dict = None, file_id: Optional[str] = None) -> str:
        """Upload (or replace, with file_id) a file from disk; big files go in one resumable request."""
        size = path.stat().st_size
        if size <= RESUMABLE_OVER:
            data = path.read_bytes()
            if file_id:
                self.update_bytes(file_id, data, name)
                return file_id
            return self.upload_bytes(name, data, parent, props)
        if file_id:
            url = f"{UPLOAD_API}/files/{file_id}?uploadType=resumable&fields=id"
            with self._request("PATCH", url, b"", {"X-Upload-Content-Type": mime_for(name),
                                                   "X-Upload-Content-Length": str(size)}) as r:
                session = r.headers.get("Location")
        else:
            session = self.start_resumable(name, parent, props, size)
        with path.open("rb") as f:
            req = urllib.request.Request(session, data=f, method="PUT", headers={
                "Content-Length": str(size), "Content-Type": mime_for(name), "User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    return json.loads(r.read())["id"]
            except urllib.error.HTTPError as exc:
                raise DriveError(f"Upload to Google Drive failed ({exc.code})") from exc

    def download(self, file_id: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f".{threading.get_ident()}.download")
        try:
            with self._request("GET", f"{API}/files/{file_id}?alt=media", timeout=1800) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f, length=1024 * 1024)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)

    def delete(self, file_id: str) -> None:
        try:
            with self._request("DELETE", f"{API}/files/{file_id}") as r:
                r.read()
        except DriveError as exc:
            if "404" not in str(exc):
                raise
