"""ChatGPT/Codex OAuth (PKCE) login, using the same public flow as the Codex CLI.

Tokens are stored in ~/.pyharness/auth.json (outside the project folder, so the
agent's file tools can never read them).
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .i18n import t

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # public Codex CLI client id
ISSUER = "https://auth.openai.com"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
SCOPE = "openid profile email offline_access"
STORE = Path.home() / ".pyharness" / "auth.json"
UA = "pyharness/0.1"


class AuthError(Exception):
    pass


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt_claims(token: str) -> dict:
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


class Auth:
    def __init__(self, store: Path = STORE):
        self.store = store
        self.lock = threading.RLock()
        self.lang = "en"  # language of messages; set by the app
        self.data = {}
        self._load()

    # ---- persistence -------------------------------------------------
    def _load(self):
        try:
            self.data = json.loads(self.store.read_text("utf-8"))
        except Exception:
            self.data = {}

    def _save(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.store)

    # ---- status ------------------------------------------------------
    def logged_in(self) -> bool:
        return bool(self.data.get("refresh_token") or self.data.get("access_token"))

    def who(self) -> str:
        c = jwt_claims(self.data.get("id_token", ""))
        return c.get("email") or c.get("name") or ""

    def logout(self):
        with self.lock:
            self.data = {}
            try:
                self.store.unlink()
            except OSError:
                pass

    # ---- HTTP helper -------------------------------------------------
    def _post(self, url, body: bytes, content_type: str) -> dict:
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": content_type, "User-Agent": UA, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise AuthError(t(self.lang, "auth.http", code=e.code, body=e.read().decode("utf-8", "replace")[:500]))
        except urllib.error.URLError as e:
            raise AuthError(t(self.lang, "auth.unreachable", reason=e.reason))

    def _apply_tokens(self, t: dict):
        for k in ("access_token", "refresh_token", "id_token"):
            if t.get(k):
                self.data[k] = t[k]
        claims = jwt_claims(self.data.get("id_token", "")) or jwt_claims(self.data.get("access_token", ""))
        acct = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
        if acct:
            self.data["account_id"] = acct
        self.data["obtained_at"] = int(time.time())
        self._save()

    # ---- login -------------------------------------------------------
    def login(self, log=print, open_browser=True, timeout=300):
        verifier = _b64url(secrets.token_bytes(64))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        state = secrets.token_hex(16)
        params = {
            "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
            "scope": SCOPE, "code_challenge": challenge, "code_challenge_method": "S256",
            "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true",
            "state": state, "originator": "codex_cli_rs",
        }
        url = f"{ISSUER}/oauth/authorize?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        result, done = {}, threading.Event()
        done_msg = t(self.lang, "auth.done_page")

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path != "/auth/callback" or q.get("state", [""])[0] != state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Bad request")
                    return
                result["code"] = q.get("code", [""])[0]
                result["error"] = q.get("error_description", q.get("error", [""]))[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(("<meta charset=utf-8><h3>" + done_msg + "</h3>").encode("utf-8"))
                done.set()

        try:
            srv = HTTPServer(("127.0.0.1", REDIRECT_PORT), H)
        except OSError as e:
            raise AuthError(t(self.lang, "auth.port", port=REDIRECT_PORT, err=e))
        srv.timeout = 1
        log(t(self.lang, "auth.open_url", url=url))
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        deadline = time.time() + timeout
        try:
            while not done.is_set() and time.time() < deadline:
                srv.handle_request()
        finally:
            srv.server_close()
        if not done.is_set():
            raise AuthError(t(self.lang, "auth.timeout"))
        if result.get("error") or not result.get("code"):
            raise AuthError(t(self.lang, "auth.failed", err=result.get("error") or t(self.lang, "auth.no_code")))
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": result["code"],
            "redirect_uri": REDIRECT_URI, "client_id": CLIENT_ID, "code_verifier": verifier,
        }).encode()
        with self.lock:
            self._apply_tokens(self._post(f"{ISSUER}/oauth/token", body, "application/x-www-form-urlencoded"))
        log(t(self.lang, "auth.logged_in", who=self.who()).strip())

    # ---- refresh / access --------------------------------------------
    def refresh(self, force=False):
        with self.lock:
            rt = self.data.get("refresh_token")
            if not rt:
                raise AuthError(t(self.lang, "auth.not_logged"))
            body = json.dumps({
                "client_id": CLIENT_ID, "grant_type": "refresh_token",
                "refresh_token": rt, "scope": "openid profile email",
            }).encode()
            self._apply_tokens(self._post(f"{ISSUER}/oauth/token", body, "application/json"))

    def token(self):
        """Return (access_token, account_id), refreshing when near expiry."""
        with self.lock:
            if not self.logged_in():
                raise AuthError(t(self.lang, "auth.not_logged"))
            exp = jwt_claims(self.data.get("access_token", "")).get("exp", 0)
            if self.data.get("refresh_token") and exp - time.time() < 120:
                self.refresh()
            return self.data["access_token"], self.data.get("account_id", "")
