#!/usr/bin/env python3
"""pyharness entry point.  Usage:  python harness.py [--cli] [--login] [--dir PATH]"""
import argparse
import os
import sys

from pyharness import llm
from pyharness.agent import Agent
from pyharness.auth import Auth, AuthError
from pyharness.server import serve
from pyharness.sessions import FOLDER

DEFAULT_MODEL = os.environ.get("HARNESS_MODEL")  # None = pick from the account's model list


def run_cli(root, model, mode, effort):
    auth = Auth()
    if not auth.logged_in():
        print("Não está logado; iniciando login.")
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

    def approve(summary):
        print("\n--- aprovação necessária ---\n" + summary)
        return input("Permitir? [s/N] ").strip().lower() in ("s", "y")

    if not model:
        try:
            models = llm.fetch_models(auth)
            print("Modelos disponíveis: " + ", ".join(m["slug"] for m in models))
            model = models[0]["slug"]
        except Exception as e:
            sys.exit(f"Não foi possível obter a lista de modelos ({e}). Use --model NOME.")
    agent = Agent(root, auth, model, emit, approve, mode, effort, html=False)
    print(f"Pasta do projeto: {agent.sb.root}\nModelo: {model}. Comandos: /reset, /quit")
    while True:
        try:
            text = input("\nvocê> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("/quit", "/exit"):
            break
        if text == "/reset":
            agent.reset()
        elif text:
            agent.run(text)


def main():
    ap = argparse.ArgumentParser(description="Harness mínimo de agente para Codex")
    ap.add_argument("--dir", default=None, help="pasta do projeto (CLI: padrão diretório atual; interface web: pré-seleciona a pasta)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="padrão: o primeiro modelo disponível na sua conta")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--mode", default="ask", choices=["ask", "auto"], help="ask = pede confirmação para gravar e acessar URLs; comandos sempre pedem confirmação")
    ap.add_argument("--cli", action="store_true", help="chat no terminal em vez da interface web")
    ap.add_argument("--login", action="store_true", help="faz login com ChatGPT e sai")
    ap.add_argument("--logout", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.dir) if a.dir else None
    if root and not os.path.isdir(root):
        sys.exit(f"Não é uma pasta: {root}")
    try:
        if a.logout:
            Auth().logout()
            print("Sessão encerrada.")
        elif a.login:
            Auth().login()
        elif a.cli:
            run_cli(root or os.getcwd(), a.model, a.mode, a.effort)
        else:
            sessions_dir = os.path.join(os.getcwd(), FOLDER)  # inside the directory harness was launched from
            serve(root, a.model, a.mode, a.effort, sessions_dir, a.port, not a.no_browser)
    except AuthError as e:
        sys.exit(f"Erro de autenticação: {e}")


if __name__ == "__main__":
    main()
