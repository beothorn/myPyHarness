#!/usr/bin/env python3
"""myPyHarness entry point.  Usage:  python harness.py [--cli] [--login] [--dir PATH] [--lang en|pt_br]"""
import argparse
import os
import sys

from pyharness import __version__, i18n, llm
from pyharness.agent import Agent
from pyharness.auth import Auth, AuthError
from pyharness.server import serve
from pyharness.sessions import FOLDER

DEFAULT_MODEL = os.environ.get("HARNESS_MODEL")  # None = pick from the account's model list


def run_cli(root, model, effort, lang):
    tr = lambda key, **kw: i18n.t(lang, key, **kw)
    auth = Auth()
    auth.lang = lang
    if not auth.logged_in():
        print(tr("cli.login_start"))
        auth.login()

    def emit(e):
        t = e["type"]
        if t == "delta":
            print(e["text"], end="", flush=True)
        elif t == "message_end":
            print()
        elif t == "tool_call":
            print(f"  > {e['name']} {str(e['args'])[:200]}")
        elif t == "tool_result":
            print(f"    {e['output'][:300]!r}")
        elif t in ("info", "error"):
            print(f"[{t}] {e['text']}")

    def approve(summary, banner=None):
        print(tr("cli.approval"))
        if banner:
            print("!" * 60 + "\n" + tr("cli.warning") + banner + "\n" + "!" * 60)
        print(summary)
        return input(tr("cli.allow")).strip().lower() in ("s", "y")

    if not model:
        try:
            models = llm.fetch_models(auth)
            print(tr("cli.models", list=", ".join(m["slug"] for m in models)))
            model = models[0]["slug"]
        except Exception as e:
            sys.exit(tr("cli.no_models", err=e))
    agent = Agent(root, auth, model, emit, approve, effort, html=False, lang=lang)
    print(tr("cli.start", root=agent.sb.root, model=model))
    while True:
        try:
            text = input(tr("cli.prompt")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("/quit", "/exit"):
            break
        if text == "/reset":
            agent.reset()
        elif text:
            agent.run(text)


def main():
    ap = argparse.ArgumentParser(description="Minimal Codex agent harness")
    ap.add_argument("--dir", default=None, help="project folder (CLI: defaults to the current directory; web UI: pre-selects it)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="default: the first model your account offers")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--lang", default=None, choices=list(i18n.LANGS), help="interface/answer language (web UI remembers the last choice)")
    ap.add_argument("--version", action="version", version=f"myPyHarness {__version__}")
    ap.add_argument("--cli", action="store_true", help="terminal chat instead of the web UI")
    ap.add_argument("--login", action="store_true", help="sign in with ChatGPT and exit")
    ap.add_argument("--logout", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    lang = i18n.norm(a.lang)
    root = os.path.abspath(a.dir) if a.dir else None
    if root and not os.path.isdir(root):
        sys.exit(i18n.t(lang, "cli.not_dir", root=root))
    try:
        if a.logout:
            Auth().logout()
            print(i18n.t(lang, "cli.logged_out"))
        elif a.login:
            auth = Auth()
            auth.lang = lang
            auth.login()
        elif a.cli:
            run_cli(root or os.getcwd(), a.model, a.effort, lang)
        else:
            sessions_dir = os.path.join(os.getcwd(), FOLDER)  # inside the directory harness was launched from
            serve(root, a.model, a.effort, sessions_dir, a.port, not a.no_browser, a.lang)
    except AuthError as e:
        sys.exit(i18n.t(lang, "cli.auth_error", err=e))


if __name__ == "__main__":
    main()
