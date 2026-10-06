"""Website mode: "Sign in with Google", limited to your own email address(es).

Signing in also gives the site permission to keep calls in a "Concall Player"
folder in your Google Drive (the drive.file permission: only files the site
created itself). Google returns a long-lived refresh token; it's kept only in an
encrypted, HttpOnly cookie in your browser, so the server stores nothing and
can go to sleep and wake up without losing your sign-in.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from . import __version__, config

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email https://www.googleapis.com/auth/drive.file"
SESSION_COOKIE = "concall_session"
STATE_COOKIE = "concall_oauth_state"
SESSION_DAYS = 180
OPEN_PATHS = ("/auth/", "/static/", "/api/ping", "/favicon")


class SignInError(Exception):
    pass


def configured() -> Optional[str]:
    """None if website mode is fully set up, else what's missing."""
    missing = [name for name, value in (
        ("GOOGLE_CLIENT_ID", config.GOOGLE_CLIENT_ID), ("GOOGLE_CLIENT_SECRET", config.GOOGLE_CLIENT_SECRET),
        ("ALLOWED_EMAILS", config.ALLOWED_EMAILS), ("SECRET_KEY", config.SECRET_KEY),
        ("PUBLIC_URL", config.PUBLIC_URL)) if not value]
    if missing:
        return "Missing settings on the host: " + ", ".join(missing) + "."
    if not config.GOOGLE_CLIENT_ID.endswith(".apps.googleusercontent.com"):
        return ("GOOGLE_CLIENT_ID doesn't look right: it should end in .apps.googleusercontent.com. "
                "Copy the Client ID again from Google Cloud → Google Auth Platform → Clients.")
    return None


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(("concall:" + config.SECRET_KEY).encode()).digest())
    return Fernet(key)


def seal(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def unseal(token: Optional[str], max_age: int) -> Optional[dict]:
    if not token:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(_fernet().decrypt(token.encode(), ttl=max_age))
    except (InvalidToken, ValueError):
        return None


def redirect_uri() -> str:
    return config.PUBLIC_URL + "/auth/callback"


def login_url(state: str) -> str:
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # we need a refresh token to keep Drive working
        "prompt": "consent",  # Google only returns a refresh token when it asks
        "include_granted_scopes": "true",
        "state": state,
    })


def new_state() -> tuple[str, str]:
    """(state for Google, sealed cookie value that must come back with it)."""
    state = secrets.token_urlsafe(24)
    return state, seal({"state": state})


def _post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "User-Agent": f"ConcallPlayer/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise SignInError(f"Google refused the sign-in ({exc.code}): {exc.read().decode(errors='replace')[:200]}")


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                "User-Agent": f"ConcallPlayer/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def finish(code: str, state: str, state_cookie: Optional[str]) -> str:
    """Complete the Google sign-in; returns the sealed session cookie value."""
    expected = (unseal(state_cookie, 900) or {}).get("state")
    if not expected or not secrets.compare_digest(expected, state or ""):
        raise SignInError("The sign-in took too long or was started in another tab. Please try again.")
    tokens = _post_form(TOKEN_URL, {
        "code": code, "client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    info = _get_json(USERINFO_URL, tokens["access_token"])
    email = str(info.get("email", "")).lower()
    if not info.get("email_verified") or email not in config.ALLOWED_EMAILS:
        raise SignInError(f"{email or 'This Google account'} isn't allowed to use this Concall Player.")
    if "drive.file" not in tokens.get("scope", ""):
        raise SignInError("Please allow access to Google Drive (tick the box on Google's page), so your calls "
                          "can be saved there.")
    if not tokens.get("refresh_token"):
        raise SignInError("Google didn't grant lasting access. Please sign in again.")
    return seal({"email": email, "rt": tokens["refresh_token"], "at": time.time()})


def session(cookie: Optional[str]) -> Optional[dict]:
    data = unseal(cookie, SESSION_DAYS * 86400)
    if not data or data.get("email") not in config.ALLOWED_EMAILS or not data.get("rt"):
        return None
    return data


def is_open(path: str) -> bool:
    return path == "/auth" or any(path.startswith(p) for p in OPEN_PATHS)
