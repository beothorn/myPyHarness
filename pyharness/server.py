"""Local web UI (stdlib http.server). Bound to 127.0.0.1, protected by a random token."""
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agent import AGENTS_INTERVIEW, Agent, agents_md
from .auth import Auth
from . import llm, status
from .sessions import SessionStore

UI = (Path(__file__).parent / "ui.html").read_text("utf-8")
KEEP = {"user", "tool_call", "tool_result", "error", "info", "status"}  # events kept in the saved transcript


# The page CSP is inherited by the sandboxed srcdoc widget frames, so it must allow the same CDNs.
PAGE_CSP = ("default-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' data: blob:")


def browse(path):
    """List sub-folders of `path` (or the drive list on Windows when path is empty)."""
    if not path and os.name == "nt":
        drives = [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
        return {"path": "", "parent": None, "dirs": drives}
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        raise ValueError("not a folder")
    parent = os.path.dirname(path)
    if parent == path:
        parent = "" if os.name == "nt" else None
    dirs = []
    try:
        for n in sorted(os.listdir(path), key=str.lower):
            if os.path.isdir(os.path.join(path, n)):
                dirs.append(os.path.join(path, n))
    except OSError as e:
        raise ValueError(str(e))
    return {"path": path, "parent": parent, "dirs": dirs}


class App:
    def __init__(self, root, model, mode, effort, sessions_dir):
        self.auth = Auth()
        self.store = SessionStore(sessions_dir)
        self.events, self.lock = [], threading.RLock()
        self.approvals = {}
        self.busy = False
        self.started = False
        self.session = None
        self.transcript, self._abuf = [], ""
        self.token = secrets.token_urlsafe(24)
        self.models, self.models_error = None, None
        self.offer_agents = False
        self.agent = Agent(None, self.auth, model, self.emit, self.approve, mode, effort,
                           protect=[self.store.path])
        if root:
            self.agent.set_root(root)

    # ---- events / transcript -------------------------------------------
    def _push(self, ev):
        with self.lock:
            self.events.append(ev)

    def _flush(self):
        if self._abuf:
            self.transcript.append({"type": "assistant", "text": self._abuf})
            self._abuf = ""

    def emit(self, ev):
        with self.lock:
            self.events.append(ev)
            t = ev["type"]
            if not self.started:
                return
            if t == "delta":
                self._abuf += ev["text"]
                return
            self._flush()
            if t in KEEP:
                self.transcript.append(ev)
            elif t == "done":
                self.save()

    def save(self):
        with self.lock:
            if not self.session or not self.transcript:
                return
            self._flush()
            s = self.session
            s.update(root=self.agent.sb.root, history=self.agent.history, transcript=self.transcript)
            try:
                self.store.save(s)
            except OSError as e:
                self._push({"type": "error", "text": f"Não foi possível salvar a sessão: {e}"})

    def _enter(self, session):
        """Switch to `session` and replay its transcript to the UI."""
        with self.lock:
            self.session = session
            self.transcript = list(session.get("transcript", []))
            self.agent.history = list(session.get("history", []))
            self.started = True
            self._push({"type": "reset"})
            for ev in self.transcript:
                self._push(ev)

    # ---- actions ---------------------------------------------------------
    def approve(self, summary):
        aid = secrets.token_hex(6)
        slot = {"ev": threading.Event(), "allow": False}
        self.approvals[aid] = slot
        self.emit({"type": "approval", "id": aid, "text": summary})
        while not slot["ev"].wait(0.5):
            if self.agent.cancel.is_set():
                break
        self.approvals.pop(aid, None)
        self.emit({"type": "approval_done", "id": aid, "allow": slot["allow"]})
        return slot["allow"]

    def status(self):
        a = self.agent
        return {"logged_in": self.auth.logged_in(), "who": self.auth.who(), "model": a.model,
                "root": a.sb.root if a.sb else None, "mode": a.mode, "effort": a.effort, "offer_agents": self.offer_agents, "busy": self.busy,
                "started": self.started, "title": (self.session or {}).get("title", "")}

    def load_models(self, force=False):
        """Fetch the account's model list once; pick a valid model/effort if the current one isn't offered."""
        with self.lock:
            if self.models is not None and not force:
                return
            try:
                self.models, self.models_error = llm.fetch_models(self.auth), None
            except Exception as e:
                self.models, self.models_error = [], f"{type(e).__name__}: {e}"
                return
            a = self.agent
            cur = next((m for m in self.models if m["slug"] == a.model), None)
            if self.models and not cur:
                cur = self.models[0]
                a.model = cur["slug"]
            if cur and a.effort not in cur["efforts"]:
                a.effort = cur["default_effort"]

    def set_model(self, slug, effort):
        self.load_models()
        m = next((m for m in self.models or [] if m["slug"] == slug), None)
        if not m:
            raise ValueError("modelo indisponível para esta conta")
        self.agent.model = slug
        self.agent.effort = effort if effort in m["efforts"] else m["default_effort"]

    def show_status(self):
        payload = err = None
        try:
            payload = status.fetch_usage(self.auth)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        a = self.agent
        self.emit({"type": "status", "text": status.format_status(
            payload, err, self.auth.who(), a.model, a.effort, a.tokens)})

    # ---- AGENTS.md offer -------------------------------------------------------
    def _prefs_file(self):
        return os.path.join(self.store.path, "prefs.json")

    def _declined(self):
        try:
            with open(self._prefs_file(), encoding="utf-8") as f:
                return json.load(f).get("agents_declined", [])
        except (OSError, ValueError):
            return []

    def decline_agents(self):
        self.offer_agents = False
        root = self.agent.sb.root
        d = self._declined()
        if root not in d:
            try:
                os.makedirs(self.store.path, exist_ok=True)
                with open(self._prefs_file(), "w", encoding="utf-8") as f:
                    json.dump({"agents_declined": d + [root]}, f)
            except OSError:
                pass

    def create_agents(self):
        self.offer_agents = False
        return self.start_turn(AGENTS_INTERVIEW, display="Criar AGENTS.md")

    def check_ready(self, need_root=True):
        if self.busy:
            return "o agente está ocupado; pare-o antes"
        if not self.auth.logged_in():
            return "faça login primeiro"
        if need_root and not self.agent.sb:
            return "escolha um diretório primeiro"
        return None

    def new_session(self):
        self.save()
        root = self.agent.sb.root
        self.offer_agents = agents_md(root) is None and root not in self._declined()
        self._enter({"id": self.store.new_id(), "title": "", "created": time.time(),
                     "root": self.agent.sb.root, "history": [], "transcript": []})

    def resume(self, sid):
        s = self.store.load(sid)
        self.save()  # keep the current session before switching folders
        if not os.path.isdir(s.get("root", "")):
            raise ValueError("a pasta desta sessão não existe mais")
        self.agent.set_root(s["root"])
        self.offer_agents = False
        self._enter(s)

    def go_home(self):
        with self.lock:
            self.save()
            self.started = False
            self.offer_agents = False
            self.session, self.transcript = None, []
            self.agent.reset()
            self._push({"type": "reset"})

    def start_turn(self, text, display=None):
        if self.busy or not self.started:
            return False
        self.busy = True
        self.offer_agents = False  # any message means "let it go" for this session
        shown = display or text
        if not self.session.get("title"):
            self.session["title"] = shown[:60]
        self.emit({"type": "user", "text": shown})

        def go():
            try:
                self.agent.run(text)
            finally:
                self.busy = False

        threading.Thread(target=go, daemon=True).start()
        return True

    def start_login(self):
        def go():
            try:
                self.auth.login(log=lambda m: self.emit({"type": "info", "text": m}))
                self.emit({"type": "info", "text": "Login realizado com sucesso."})
            except Exception as e:
                self.emit({"type": "error", "text": f"Falha no login: {e}"})

        threading.Thread(target=go, daemon=True).start()


def make_handler(app, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", PAGE_CSP)
            self.end_headers()
            self.wfile.write(body)

        def _guard(self, token):
            # Host check blocks DNS rebinding; token blocks other local web pages / users.
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, {"error": "bad host"})
                return False
            if not secrets.compare_digest(token or "", app.token):
                self._send(403, {"error": "bad token"})
                return False
            return True

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/":
                if self._guard(q.get("t", [""])[0]):
                    self._send(200, UI.replace("__TOKEN__", app.token), "text/html")
                return
            if u.path not in ("/api/events", "/api/browse", "/api/sessions", "/api/models"):
                return self._send(404, {"error": "not found"})
            if not self._guard(self.headers.get("X-Token")):
                return
            if u.path == "/api/events":
                since = int(q.get("since", ["0"])[0])
                with app.lock:
                    evs = app.events[since:]
                self._send(200, {"events": evs, "next": since + len(evs), "status": app.status()})
            elif u.path == "/api/models":
                if not app.auth.logged_in():
                    return self._send(200, {"models": [], "error": "faça login primeiro"})
                app.load_models(force=q.get("refresh") == ["1"])
                self._send(200, {"models": app.models, "error": app.models_error})
            elif u.path == "/api/sessions":
                self._send(200, {"sessions": app.store.list(), "folder": app.store.path})
            else:
                try:
                    cur = app.agent.sb.root if app.agent.sb else ""
                    self._send(200, browse(q.get("path", [cur])[0]))
                except ValueError as e:
                    self._send(400, {"error": str(e)})

        def do_POST(self):
            if not self._guard(self.headers.get("X-Token")):
                return
            n = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            p = urlparse(self.path).path
            if p == "/api/send":
                text = str(body.get("text", "")).strip()
                ok = bool(text) and app.start_turn(text)
                return self._send(200 if ok else 409, {"ok": ok})
            if p == "/api/approve":
                slot = app.approvals.get(body.get("id"))
                if slot:
                    slot["allow"] = bool(body.get("allow"))
                    slot["ev"].set()
                return self._send(200, {"ok": bool(slot)})
            if p == "/api/stop":
                app.agent.cancel.set()
                return self._send(200, {"ok": True})
            if p == "/api/login":
                app.start_login()
                return self._send(200, {"ok": True})
            if p == "/api/mode":
                if body.get("mode") in ("ask", "auto"):
                    app.agent.mode = body["mode"]
                return self._send(200, {"ok": True})
            if p == "/api/model":
                try:
                    app.set_model(body.get("model"), body.get("effort"))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True})
            if p == "/api/agents":
                if not app.started or not app.agent.sb:
                    return self._send(409, {"error": "nenhuma sessão ativa"})
                if body.get("action") == "create":
                    ok = app.create_agents()
                    return self._send(200 if ok else 409, {"ok": ok})
                app.decline_agents()
                return self._send(200, {"ok": True})
            if p == "/api/status":
                app.show_status()
                return self._send(200, {"ok": True})
            if p == "/api/setroot":
                path = os.path.realpath(str(body.get("path", "")))
                if app.busy or app.started:
                    return self._send(409, {"error": "volte à configuração para trocar a pasta"})
                if not os.path.isdir(path):
                    return self._send(400, {"error": "não é uma pasta"})
                if os.path.dirname(path) == path:
                    return self._send(400, {"error": "escolha uma pasta, não a raiz do disco"})
                app.agent.set_root(path)
                return self._send(200, {"ok": True})
            if p in ("/api/start", "/api/resume"):
                resume = p == "/api/resume"
                err = app.check_ready(need_root=not resume)  # a resumed session brings its own folder
                if err:
                    return self._send(409, {"error": err})
                try:
                    app.resume(body.get("id")) if resume else app.new_session()
                except (ValueError, OSError, KeyError) as e:
                    return self._send(400, {"error": f"não foi possível abrir a sessão: {e}"})
                return self._send(200, {"ok": True})
            if p == "/api/home":
                if app.busy:
                    return self._send(409, {"error": "o agente está ocupado; pare-o antes"})
                app.go_home()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})

    return H


def serve(root, model, mode, effort, sessions_dir, port=8765, open_browser=True):
    app = App(root, model, mode, effort, sessions_dir)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, 0))
        port = httpd.server_address[1]
        httpd.RequestHandlerClass = make_handler(app, port)
    url = f"http://127.0.0.1:{port}/?t={app.token}"
    print(f"Sessões salvas em: {app.store.path}\nInterface: {url}\nCtrl+C para sair.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
