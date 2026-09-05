from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

READ_SCOPE = "inbox.read"
WRITE_SCOPE = "inbox.write"
DB_ENV = "INBOX_OAUTH_DB"
SECRET_ENV = "INBOX_OAUTH_SECRET"
GOOGLE_CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
GOOGLE_CLIENT_SECRET_ENV = "GOOGLE_OAUTH_CLIENT_SECRET"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PUBLIC_BASE_URL_ENV = "INBOX_PUBLIC_BASE_URL"
STATIC_CLIENT_ID_ENV = "INBOX_GEMINI_MCP_CLIENT_ID"
STATIC_CLIENT_SECRET_ENV = "INBOX_GEMINI_MCP_CLIENT_SECRET"
STATIC_REDIRECT_ENV = "INBOX_GEMINI_MCP_REDIRECT_URI"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _db_path() -> Path:
    return Path(os.getenv(DB_ENV, ".inbox_oauth.sqlite3"))


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.execute("CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, secret TEXT NOT NULL, redirect TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, client_id TEXT, redirect TEXT, challenge TEXT, scopes TEXT, expires INTEGER, used INTEGER DEFAULT 0)")
    conn.commit()
    return conn


def _secret() -> bytes:
    return os.getenv(SECRET_ENV, "dev-only-change-me").encode()


def _public_base(request: Request) -> str:
    return os.getenv(PUBLIC_BASE_URL_ENV, str(request.base_url).rstrip("/")).rstrip("/")


def _static_client() -> tuple[str, str, str] | None:
    client_id = os.getenv(STATIC_CLIENT_ID_ENV, "").strip()
    client_secret = os.getenv(STATIC_CLIENT_SECRET_ENV, "").strip()
    redirect = os.getenv(
        STATIC_REDIRECT_ENV,
        "https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-115205421030433667198-crumpled-resume-arbitrate_ngrok-free_dev",
    ).strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret, redirect


def _client(client_id: str | None) -> tuple[str, str] | None:
    if not client_id:
        return None
    static = _static_client()
    if static and hmac.compare_digest(static[0], client_id):
        return static[1], static[2]
    with _conn() as conn:
        row = conn.execute("SELECT secret,redirect FROM clients WHERE id=?", (client_id,)).fetchone()
    return (row[0], row[1]) if row else None


def _redirect_compatible(registered: str, requested: str) -> bool:
    if registered == requested:
        return True
    left, right = urllib.parse.urlsplit(registered), urllib.parse.urlsplit(requested)
    return bool(
        left.hostname in {"oauth-redirect.googleusercontent.com", "oauth-redirect-sandbox.googleusercontent.com"}
        and right.hostname in {"oauth-redirect.googleusercontent.com", "oauth-redirect-sandbox.googleusercontent.com"}
        and left.path == right.path
        and left.path.startswith("/r/user_bound_custom-mcp-")
    )


def _token(client_id: str, scopes: list[str]) -> str:
    payload = _b64(json.dumps({"sub": client_id, "scopes": scopes, "exp": int(time.time()) + 3600}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def validate_bearer(request: Request) -> tuple[str, set[str]] | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        payload, signature = header[7:].strip().split(".", 1)
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
        if int(data["exp"]) <= int(time.time()):
            return None
        return str(data["sub"]), set(data["scopes"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _google_exchange(code: str, redirect_uri: str, code_verifier: str) -> dict:
    body = urllib.parse.urlencode({"code": code, "client_id": os.getenv(GOOGLE_CLIENT_ID_ENV, ""), "client_secret": os.getenv(GOOGLE_CLIENT_SECRET_ENV, ""), "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": code_verifier}).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_ENDPOINT, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:  # nosec B310 - fixed Google HTTPS endpoint
        return json.loads(response.read())


async def metadata(request: Request) -> JSONResponse:
    base = _public_base(request)
    payload = {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token", "response_types_supported": ["code"], "grant_types_supported": ["authorization_code"], "token_endpoint_auth_methods_supported": ["none", "client_secret_post"] if _static_client() else ["none"], "scopes_supported": [READ_SCOPE, WRITE_SCOPE], "code_challenge_methods_supported": ["S256"]}
    if not _static_client():
        payload["registration_endpoint"] = f"{base}/oauth/register"
    return JSONResponse(payload)


async def protected_resource(request: Request) -> JSONResponse:
    base = _public_base(request)
    return JSONResponse({"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": [READ_SCOPE, WRITE_SCOPE]})


async def register(request: Request) -> JSONResponse:
    data = await request.json()
    redirects = data.get("redirect_uris") or []
    if not redirects or not all(isinstance(v, str) and v.startswith("http") for v in redirects):
        return JSONResponse({"error": "invalid_redirect_uris"}, status_code=400)
    client_id, client_secret = secrets.token_urlsafe(18), secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute("INSERT INTO clients VALUES (?,?,?)", (client_id, client_secret, redirects[0]))
    # Gemini registers as a public PKCE client. Do not return a secret while
    # advertising token_endpoint_auth_method=none; the generated value stays
    # server-side only so older confidential-client retries remain harmless.
    return JSONResponse({"client_id": client_id, "client_id_issued_at": int(time.time()), "redirect_uris": redirects, "response_types": ["code"], "grant_types": ["authorization_code"], "token_endpoint_auth_method": "none", "scope": f"{READ_SCOPE} {WRITE_SCOPE}"}, status_code=201)


async def authorize(request: Request):
    q = request.query_params
    if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        return JSONResponse({"error": "invalid_request", "error_description": "S256 PKCE is required"}, status_code=400)
    client = _client(q.get("client_id"))
    redirect_matches = bool(client and _redirect_compatible(client[1], q.get("redirect_uri", "")))
    if not redirect_matches:
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    state = secrets.token_urlsafe(24)
    scopes = q.get("scope", READ_SCOPE).split()
    if not set(scopes).issubset({READ_SCOPE, WRITE_SCOPE}):
        return JSONResponse({"error": "invalid_scope"}, status_code=400)
    # Preserve the URI from this authorization request. Gemini may use its
    # sandbox or production callback host; registration can contain either.
    # Gemini and Google are separate OAuth clients in this brokered flow. The
    # verifier Gemini sends to our token endpoint must validate Gemini's code,
    # while Google's authorization code must be exchanged with a distinct
    # verifier matching the PKCE challenge sent to Google.
    google_verifier = secrets.token_urlsafe(32)
    google_challenge = _b64(hashlib.sha256(google_verifier.encode()).digest())
    request.app.state.oauth_states[state] = {"client_id": q["client_id"], "redirect": q["redirect_uri"], "challenge": q["code_challenge"], "google_verifier": google_verifier, "scopes": scopes, "state": q.get("state", "")}
    params = {"client_id": os.getenv(GOOGLE_CLIENT_ID_ENV, ""), "redirect_uri": f"{_public_base(request)}/oauth/callback", "response_type": "code", "scope": "openid email profile", "access_type": "offline", "state": state, "code_challenge": google_challenge, "code_challenge_method": "S256"}
    return RedirectResponse(f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(params)}")


async def callback(request: Request):
    state = request.query_params.get("state", "")
    context = request.app.state.oauth_states.pop(state, None)
    if not context:
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    code = secrets.token_urlsafe(32)
    with _conn() as conn:
        conn.execute("INSERT INTO codes VALUES (?,?,?,?,?,?,0)", (code, context["client_id"], context["redirect"], context["challenge"], json.dumps({"scopes": context["scopes"], "google_code": request.query_params.get("code", ""), "google_verifier": context["google_verifier"]}), int(time.time()) + 300))
    target = context["redirect"] + "?" + urllib.parse.urlencode({"code": code, "state": context["state"]})
    return RedirectResponse(target)


async def token(request: Request) -> JSONResponse:
    form = await request.form()
    with _conn() as conn:
        client = _client(form.get("client_id"))
        row = conn.execute("SELECT client_id,redirect,challenge,scopes,expires,used FROM codes WHERE code=?", (form.get("code"),)).fetchone()
        supplied_secret = str(form.get("client_secret", ""))
        client_authenticated = not supplied_secret or bool(client and hmac.compare_digest(client[0], supplied_secret))
        if not client or not client_authenticated or not row or row[5] or row[4] < time.time() or not _redirect_compatible(row[1], str(form.get("redirect_uri", ""))):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        verifier = str(form.get("code_verifier", ""))
        if _b64(hashlib.sha256(verifier.encode()).digest()) != row[2]:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        google_data = json.loads(row[3])
        try:
            google_tokens = _google_exchange(google_data["google_code"], os.getenv(PUBLIC_BASE_URL_ENV, "").rstrip("/") + "/oauth/callback", google_data["google_verifier"])
        except Exception as exc:  # noqa: BLE001 - return provider error without leaking credentials
            return JSONResponse({"error": "google_token_exchange_failed", "detail": str(exc)}, status_code=502)
        conn.execute("UPDATE codes SET used=1 WHERE code=?", (form.get("code"),))
    scopes = google_data["scopes"]
    response = {"access_token": _token(row[0], scopes), "token_type": "Bearer", "expires_in": 3600, "scope": " ".join(scopes)}
    if isinstance(google_tokens, dict):
        for key in ("id_token", "refresh_token"):
            if google_tokens.get(key):
                response[key] = google_tokens[key]
    return JSONResponse(response)
