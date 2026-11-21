# myPyHarness

**A simple AI agent harness you can just drop into a folder and use.**
Pure Python standard library: nothing to install, no `pip`, no executables.

🇧🇷 Português: [README.pt.md](README.pt.md)

## Why

Some computers don't let you install software or run executables, yet they still let you run Python. Most agent tools (CLIs, desktop apps, Node/Electron stacks) are off the table there.

myPyHarness is the opposite: a handful of Python files you copy next to your project and start with `python harness.py`. It signs in with your own **ChatGPT account** (the same login the Codex CLI uses), so there is no API key to manage either.

## Features

- **Drop and use.** Copy the folder, run one command. Only Python 3.8+ is needed.
- **Sign in with ChatGPT.** One click in the browser; tokens live in your home folder, never in your project.
- **Works inside a folder you choose.** Anything outside it needs your explicit approval, every time, in a red dialog.
- **Browser UI or terminal.** A small local web page (default) or a plain `--cli` chat.
- **Pick the model and reasoning level** from the list your account can actually use, and press **Status** to see how much of your plan limits you have used.
- **Rich answers.** The model answers in HTML and may build interactive widgets: styled blocks, buttons, SVG charts, JavaScript. They run in an isolated sandbox: the widget code cannot reach the app, your files or the network.
- **A useful toolbox.** List, read, search, write and edit files; folder sizes; web search and page fetching; shell commands.
- **You stay in control.** Every write, edit, URL fetch and shell command asks first; there is no "auto-approve" switch. Commands show the command itself, a plain-language explanation and the folder. The agent is told what you decided. Reading, changing or running something **outside the working folder** is shown in red with a warning on top ("The agent wants to read content, make sure it is not sensitive content").
- **Sessions are saved** after every reply and can be resumed later from the start page.
- **`AGENTS.md` onboarding.** In a folder without one, the agent offers to interview you about the project and write it. If one exists, a new empty chat tells the model to read it first.
- **English and Brazilian Portuguese (`pt_br`).** Pick the language on the first screen; every dialog follows it, and so do the model's answers. The choice is remembered.
- **Full-width chat** with a "Thinking..." indicator while the agent works.
- **Clean or full view.** A **Show commands** toggle in the header (on by default) switches between the full view, to review exactly what was executed, and a clean view with only the messages exchanged. Permission dialogs that are waiting for you always stay visible. The choice is remembered in your browser.

## Quick start

1. Copy `harness.py` and the `pyharness/` folder to your machine.
2. Open a terminal in the directory where you want your sessions saved and run:

   ```
   python harness.py
   ```

   (On Windows, `py harness.py` also works.) Your browser opens the app.
3. On the start page, pick the language (English / Português (BR)), then:
   1. **Login**: sign in with your ChatGPT account.
   2. **Choose directory**: pick the project folder the agent may work in.
   3. **Start**: enabled once both are done.
4. Chat. Use the header to change model/level, **Status** for usage, **New chat** for a fresh chat, **Configuration** to go back to the start page.

Previous conversations appear under "Previous sessions" on the start page. They are stored as JSON in `myPyHarnessSessions/`, inside the directory you launched from.

## Options

| Option | What it does |
|---|---|
| `--dir PATH` | Pre-select the project folder (in `--cli`, defaults to the current directory) |
| `--cli` | Terminal chat instead of the web UI |
| `--model NAME` | Initial model (default: the first one your account offers; or env `HARNESS_MODEL`) |
| `--effort low\|medium\|high` | Initial reasoning level |
| `--lang en\|pt_br` | Language (the web UI remembers the last choice; default `en`) |
| `--port N` / `--no-browser` | Web UI port / don't open the browser |
| `--login` / `--logout` | Only sign in / sign out |

## Safety model

- **Folder boundary for file tools.** Every path is resolved (symlinks, junctions, `..`). Paths outside the chosen folder are refused unless you approve that specific access in a red dialog; the approval covers that one call. The harness's own code and the saved sessions stay read-only even then, and `~/.pyharness` (your login tokens) is never reachable.
- **Network.** `fetch_url` is GET-only and blocks localhost and private addresses, including on redirects.
- **Widgets.** Model-written HTML runs in a sandboxed iframe with an opaque origin and a CSP that blocks all network requests; scripts may load libraries only from cdnjs and jsDelivr.
- **Local UI.** It listens on `127.0.0.1` only, requires a random per-run token and checks the `Host` header.
- **Credentials.** Login tokens are stored in `~/.pyharness/auth.json`.
- **What is *not* sandboxed:** shell commands. They run with your permissions and can touch anything on the machine. Their only protection is your approval, so read the command itself, not just the explanation. The harness also scans commands for paths outside the working folder and turns the dialog red when it finds one, but that is best-effort (it cannot see paths a shell builds at run time): a normal-coloured command is not proof of safety. Also beware of prompt injection from web pages the agent reads.

## Things to know

- Not affiliated with OpenAI. Sign-in, model list and usage status use the same flow and undocumented endpoints as the Codex CLI, so they can change without notice. Use it according to the terms of your plan.
- Developed and tested on Linux. Windows is a goal but has not been exercised yet.
- Login needs `localhost:1455` free for a minute.
- Saved sessions contain your conversation history: treat them as private (they are git-ignored here).

## Development

```
python -m unittest discover -s tests
```

Layout: `harness.py` (entry point), `pyharness/` (`auth`, `llm`, `agent`, `tools`, `server` + `ui.html`, `sessions`, `status`), `tests/`.

## License

[Apache License 2.0](LICENSE).
