"""Sandboxed tools. All file access goes through Sandbox.resolve()."""
import fnmatch
import html
import ipaddress
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_OUT = 30000
MAX_WRITE = 2_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
PKG_DIR = os.path.dirname(os.path.abspath(__file__))


class ToolError(Exception):
    pass


class Sandbox:
    def __init__(self, root, extra_protected=()):
        self.root = os.path.realpath(root)
        self.cancel = None  # threading.Event set by the agent; lets Stop interrupt a running command
        # The harness' own source is read-only to the agent, so it cannot rewrite its guard rails.
        self.protected = [PKG_DIR, os.path.join(os.path.dirname(PKG_DIR), "harness.py"),
                          *extra_protected]

    def _inside(self, real, base):
        a, b = os.path.normcase(real), os.path.normcase(base)
        try:
            return os.path.commonpath([a, b]) == b
        except ValueError:  # different drives on Windows
            return False

    def resolve(self, rel, write=False):
        if not isinstance(rel, str) or not rel or "\0" in rel:
            raise ToolError("invalid path")
        if os.name == "nt" and ":" in os.path.splitdrive(rel)[1]:
            raise ToolError("invalid path (alternate data streams not allowed)")
        p = rel if os.path.isabs(rel) else os.path.join(self.root, rel)
        real = os.path.realpath(p)  # resolves symlinks/junctions and '..'
        if not self._inside(real, self.root):
            raise ToolError(f"path is outside the project folder: {rel}")
        if write:
            for prot in self.protected:
                prot = os.path.realpath(prot)
                if real == prot or self._inside(real, prot):
                    raise ToolError("the harness' own files are protected from writes")
        return real

    def rel(self, real):
        return os.path.relpath(real, self.root).replace(os.sep, "/")


def _cap(s, n=MAX_OUT):
    return s if len(s) <= n else s[:n] + f"\n...[truncated, {len(s) - n} more chars]"


def _is_binary(path):
    with open(path, "rb") as f:
        return b"\0" in f.read(8192)


def _walk(sb, start):
    for d, dirs, files in os.walk(start):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            yield os.path.join(d, f)


# ---------------------------------------------------------------- file tools
def list_dir(sb, path="."):
    p = sb.resolve(path)
    if not os.path.isdir(p):
        raise ToolError("not a directory")
    out = []
    for name in sorted(os.listdir(p))[:500]:
        full = os.path.join(p, name)
        out.append(name + "/" if os.path.isdir(full) else f"{name}  ({os.path.getsize(full)} bytes)")
    return "\n".join(out) or "(empty)"


def read_file(sb, path, offset=1, limit=400):
    p = sb.resolve(path)
    if not os.path.isfile(p):
        raise ToolError("not a file")
    if _is_binary(p):
        raise ToolError("binary file")
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    offset, limit = max(1, int(offset)), max(1, int(limit))
    chunk = lines[offset - 1: offset - 1 + limit]
    body = "\n".join(f"{i}\t{l}" for i, l in enumerate(chunk, offset))
    tail = f"\n[showing lines {offset}-{offset + len(chunk) - 1} of {len(lines)}]" if chunk else "[no lines in range]"
    return _cap(body + tail)


def write_file(sb, path, content):
    p = sb.resolve(path, write=True)
    if len(content) > MAX_WRITE:
        raise ToolError("content too large")
    if os.path.isdir(p):
        raise ToolError("path is a directory")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return f"wrote {len(content)} chars to {sb.rel(p)}"


def edit_file(sb, path, old, new, replace_all=False):
    p = sb.resolve(path, write=True)
    if not os.path.isfile(p):
        raise ToolError("not a file")
    with open(p, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    n = text.count(old) if old else 0
    if n == 0:
        raise ToolError("'old' text not found (must match exactly, including whitespace)")
    if n > 1 and not replace_all:
        raise ToolError(f"'old' matches {n} times; add context or set replace_all")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new) if replace_all else text.replace(old, new, 1))
    return f"edited {sb.rel(p)} ({n if replace_all else 1} replacement)"


def find_files(sb, pattern):
    base = sb.resolve(".")
    out = []
    for f in _walk(sb, base):
        rel = sb.rel(f)
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            out.append(rel)
            if len(out) >= 300:
                break
    return "\n".join(out) or "no matches"


def grep(sb, pattern, path=".", include="*"):
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ToolError(f"bad regex: {e}")
    start = sb.resolve(path)
    files = [start] if os.path.isfile(start) else _walk(sb, start)
    out = []
    for f in files:
        if not fnmatch.fnmatch(os.path.basename(f), include):
            continue
        try:
            if os.path.getsize(f) > 2_000_000 or _is_binary(f):
                continue
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if rx.search(line):
                        out.append(f"{sb.rel(f)}:{i}: {line.rstrip()[:200]}")
                        if len(out) >= 100:
                            return "\n".join(out) + "\n[stopped at 100 matches]"
        except OSError:
            continue
    return "\n".join(out) or "no matches"


def _human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def dir_sizes(sb, path=".", depth=1, top=60):
    """Disk usage per sub-folder (like `du`), symlinks not followed, everything included (.git, node_modules...)."""
    start = sb.resolve(path)
    if not os.path.isdir(start):
        raise ToolError("not a directory")
    depth, top = max(1, min(int(depth), 6)), max(1, min(int(top), 300))
    sizes, counts, scanned, truncated = {}, {}, 0, False
    for d, dirs, files in os.walk(start):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        parts = [] if d == start else os.path.relpath(d, start).split(os.sep)
        key = (("/".join(parts[:depth]) + "/") if parts else None)
        for f in files:
            fp = os.path.join(d, f)
            try:
                if os.path.islink(fp):
                    continue
                sz = os.path.getsize(fp)
            except OSError:
                continue
            k = key or f
            sizes[k] = sizes.get(k, 0) + sz
            counts[k] = counts.get(k, 0) + 1
            scanned += 1
        if scanned > 300000:
            truncated = True
            break
    total = sum(sizes.values())
    rows = sorted(sizes.items(), key=lambda kv: -kv[1])[:top]
    out = [f"{_human(v):>10}  {k}" + (f"  ({counts[k]} files)" if k.endswith("/") else "") for k, v in rows]
    head = f"Total in {sb.rel(start) if start != sb.root else '.'}: {_human(total)} ({scanned} files)"
    if truncated:
        head += " [scan stopped early: too many files, sizes are partial]"
    return _cap(head + "\n" + "\n".join(out))


# ---------------------------------------------------------------- commands
def _console_encoding():
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            return "cp%d" % (k.GetConsoleOutputCP() or k.GetOEMCP())
        except Exception:
            pass
    return "utf-8"


def _kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def run_command(sb, command, explanation="", cwd=".", timeout=60):
    """Run a shell command. NOT sandboxed: the user's approval (asked before this runs) is the only guard."""
    if not isinstance(command, str) or not command.strip():
        raise ToolError("empty command")
    wd = sb.resolve(cwd)
    if not os.path.isdir(wd):
        raise ToolError("cwd is not a directory")
    timeout = max(1, min(int(timeout), 300))
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    try:
        p = subprocess.Popen(command, shell=True, cwd=wd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, **kw)
    except OSError as e:
        raise ToolError(f"could not start command: {e}")
    deadline, note, out = time.time() + timeout, "", b""
    while True:
        try:
            out, _ = p.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            stopped = sb.cancel is not None and sb.cancel.is_set()
            if stopped or time.time() > deadline:
                _kill_tree(p)
                note = "STOPPED by the user" if stopped else f"TIMED OUT after {timeout}s and was killed"
                try:
                    out, _ = p.communicate(timeout=5)
                except Exception:
                    out = b""
                break
    text = out.decode(_console_encoding(), "replace")
    if len(text) > MAX_OUT:
        text = "...[earlier output truncated]\n" + text[-MAX_OUT:]
    head = note or f"exit code: {p.returncode}"
    return f"{head}\n{text}" if text.strip() else head


def _command_prompt(a):
    return ("EXECUTAR COMANDO (sem sandbox: roda no seu computador com as suas permissões)\n\n"
            f"O que faz (explicação do modelo):\n{a.get('explanation') or '(sem explicação)'}\n\n"
            f"Comando:\n{a.get('command', '')}\n\n"
            f"Pasta: {a.get('cwd') or '.'}  ·  tempo máximo: {a.get('timeout') or 60}s\n"
            "⚠ A explicação foi escrita pelo modelo; confira o comando em si antes de permitir.")


# ---------------------------------------------------------------- network tools
def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ToolError("only http/https URLs are allowed")
    host = u.hostname
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror:
        # May only be resolvable by a corporate proxy; refuse only obvious local names.
        if host.lower() == "localhost" or host.lower().endswith(".localhost"):
            raise ToolError("local addresses are blocked")
        return
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ToolError("private/local network addresses are blocked")


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirect)
_UA = {"User-Agent": "Mozilla/5.0 (pyharness)"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.parts.append(d)


def fetch_url(sb, url):
    _check_url(url)
    try:
        with _opener.open(urllib.request.Request(url, headers=_UA), timeout=20) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read(1_500_000)
    except urllib.error.HTTPError as e:
        raise ToolError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise ToolError(f"request failed: {e.reason}")
    if not re.search(r"text|json|xml|javascript", ctype, re.I):
        return f"[non-text content: {ctype}, {len(raw)} bytes]"
    text = raw.decode("utf-8", "replace")
    if "html" in ctype.lower():
        p = _Text()
        p.feed(text)
        text = re.sub(r"\n\s*\n+", "\n\n", html.unescape("".join(p.parts))).strip()
    return _cap(text, 40000)


def web_search(sb, query):
    data = urllib.parse.urlencode({"q": query}).encode()
    try:
        req = urllib.request.Request("https://html.duckduckgo.com/html/", data=data, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise ToolError(f"search failed: {e}")
    strip = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    out = []
    for i, (href, title) in enumerate(links[:8]):
        m = re.search(r"uddg=([^&]+)", href)
        href = urllib.parse.unquote(m.group(1)) if m else href
        out.append(f"{i + 1}. {strip(title)}\n   {href}\n   {strip(snips[i]) if i < len(snips) else ''}")
    return "\n".join(out) or "no results"


# ---------------------------------------------------------------- registry
def _t(name, desc, props, required, fn, approval=None, always_ask=False):
    return {"name": name, "description": desc, "fn": fn, "approval": approval, "always_ask": always_ask,
            "schema": {"type": "function", "name": name, "description": desc, "strict": False,
                       "parameters": {"type": "object", "properties": props, "required": required}}}


S = {"type": "string"}
I = {"type": "integer"}

TOOLS = {t["name"]: t for t in [
    _t("list_dir", "List files in a directory of the project.", {"path": S}, [], list_dir),
    _t("read_file", "Read a text file with line numbers.", {"path": S, "offset": I, "limit": I}, ["path"], read_file),
    _t("write_file", "Create or overwrite a file in the project.", {"path": S, "content": S}, ["path", "content"],
       write_file, lambda a: f"GRAVAR {a.get('path')} ({len(a.get('content', ''))} caracteres)\n\n{a.get('content', '')[:1500]}"),
    _t("edit_file", "Replace exact text in a file. 'old' must match once unless replace_all.",
       {"path": S, "old": S, "new": S, "replace_all": {"type": "boolean"}}, ["path", "old", "new"], edit_file,
       lambda a: f"EDITAR {a.get('path')}\n--- antes\n{a.get('old', '')[:800]}\n+++ depois\n{a.get('new', '')[:800]}"),
    _t("dir_sizes", "Disk usage of each sub-folder/file in a folder, largest first (like du). depth=1 lists immediate children; use depth 2-3 to see nested folders.",
       {"path": S, "depth": I, "top": I}, [], dir_sizes),
    _t("run_command", "Run a shell command on the user's computer. The user is shown the command and your explanation and must approve it first; if they refuse you get an error saying so, otherwise you get the exit code and output. Non-interactive commands only (no stdin).",
       {"command": S, "explanation": {"type": "string", "description": "Plain-language explanation for the user of exactly what the command does and why."},
        "cwd": S, "timeout": {"type": "integer", "description": "seconds, default 60, max 300"}},
       ["command", "explanation"], run_command, _command_prompt, always_ask=True),
    _t("find_files", "Find files by glob pattern, e.g. '*.py' or 'src/*.js'.", {"pattern": S}, ["pattern"], find_files),
    _t("grep", "Regex search in files.", {"pattern": S, "path": S, "include": S}, ["pattern"], grep),
    _t("web_search", "Search the web (DuckDuckGo). Returns titles, URLs, snippets.", {"query": S}, ["query"], web_search),
    _t("fetch_url", "HTTP GET a public web page and return its text.", {"url": S}, ["url"], fetch_url,
       lambda a: f"ACESSAR URL {a.get('url')}"),
]}


def specs():
    return [t["schema"] for t in TOOLS.values()]
