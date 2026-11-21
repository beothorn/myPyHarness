import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pyharness import llm, tools  # noqa: E402
from pyharness.agent import Agent  # noqa: E402
from pyharness.tools import Sandbox, ToolError  # noqa: E402


class FakeAuth:
    def logged_in(self):
        return True

    def who(self):
        return "t@example.com"

    def token(self):
        return "tok", "acct"

    def refresh(self, force=False):
        pass


class ImportTests(unittest.TestCase):
    def test_all_modules_import(self):
        import importlib
        for m in ("auth", "llm", "tools", "agent", "server"):
            importlib.import_module("pyharness." + m)


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.sb = Sandbox(os.path.join(self.d.name, "proj"))
        os.makedirs(self.sb.root)
        self.outside = os.path.join(self.d.name, "secret.txt")
        with open(self.outside, "w") as f:
            f.write("secret")

    def test_blocks_escape(self):
        for p in ("../secret.txt", self.outside, "a/../../secret.txt"):
            with self.assertRaises(ToolError):
                tools.read_file(self.sb, p)
            with self.assertRaises(ToolError):
                tools.write_file(self.sb, p, "x")

    def test_blocks_symlink_escape(self):
        try:
            os.symlink(self.outside, os.path.join(self.sb.root, "link"))
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks")
        with self.assertRaises(ToolError):
            tools.read_file(self.sb, "link")
        with self.assertRaises(ToolError):
            tools.write_file(self.sb, "link", "x")

    def test_sibling_prefix_not_inside(self):
        sib = self.sb.root + "_evil"
        os.makedirs(sib)
        with self.assertRaises(ToolError):
            tools.write_file(self.sb, sib + "/f.txt", "x")

    def test_write_read_edit_grep(self):
        tools.write_file(self.sb, "sub/a.txt", "hello\nworld\n")
        self.assertIn("world", tools.read_file(self.sb, "sub/a.txt"))
        tools.edit_file(self.sb, "sub/a.txt", "world", "there")
        self.assertIn("sub/a.txt:2", tools.grep(self.sb, "there"))
        self.assertIn("sub/a.txt", tools.find_files(self.sb, "*.txt"))
        with self.assertRaises(ToolError):
            tools.edit_file(self.sb, "sub/a.txt", "nope", "x")

    def test_dir_sizes(self):
        tools.write_file(self.sb, "big/a.bin", "x" * 5000)
        tools.write_file(self.sb, "big/deep/b.bin", "x" * 3000)
        tools.write_file(self.sb, "small/c.txt", "x" * 10)
        tools.write_file(self.sb, "top.txt", "x" * 100)
        out = tools.dir_sizes(self.sb)
        self.assertIn("Total in .: 7.9 KB", out)
        lines = out.splitlines()[1:]
        self.assertIn("big/", lines[0])  # largest first, deep files rolled up
        self.assertIn("(2 files)", lines[0])
        self.assertTrue(any("top.txt" in l for l in lines))
        self.assertIn("big/deep/", tools.dir_sizes(self.sb, depth=2))
        with self.assertRaises(ToolError):
            tools.dir_sizes(self.sb, "..")

    def test_protects_harness_source(self):
        with self.assertRaises(ToolError):
            Sandbox(os.path.dirname(tools.PKG_DIR)).resolve("pyharness/tools.py", write=True)

    def test_ssrf_blocked(self):
        for u in ("http://127.0.0.1/", "http://localhost:8000", "http://169.254.169.254/", "file:///etc/passwd"):
            with self.assertRaises(ToolError):
                tools.fetch_url(self.sb, u)


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class FakeBackend(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeBackend.requests.append((dict(self.headers), self.path))
        out = json.dumps({"models": [
            {"slug": "hidden-one", "visibility": "hide"},
            {"slug": "gpt-b", "display_name": "B", "priority": 2, "default_reasoning_level": "high",
             "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]},
            {"slug": "gpt-a", "priority": 1, "supported_reasoning_levels": ["low", "medium", "xhigh"]},
        ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeBackend.requests.append((dict(self.headers), body))
        has_result = any(i.get("type") == "function_call_output" for i in body["input"])
        if not has_result:
            out = sse(
                {"type": "response.output_item.done", "item": {
                    "type": "function_call", "id": "fc_1", "name": "write_file", "call_id": "c1",
                    "arguments": json.dumps({"path": "hi.txt", "content": "hi"})}},
                {"type": "response.completed", "response": {"usage": {}}})
        else:
            out = sse(
                {"type": "response.output_text.delta", "delta": "Done"},
                {"type": "response.output_item.done", "item": {
                    "type": "message", "id": "m1", "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done", "annotations": []}]}},
                {"type": "response.completed", "response": {"usage": {}}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(out)


class AgentLoopTest(unittest.TestCase):
    def test_end_to_end(self):
        srv = HTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        orig = llm.BASE_URL
        llm.BASE_URL = base
        events = []
        try:
            with tempfile.TemporaryDirectory() as d:
                asked = []
                ag = Agent(d, FakeAuth(), "m", events.append, lambda s, b=None: asked.append(s) or True)
                ag.run("make a file")
                self.assertEqual(open(os.path.join(d, "hi.txt")).read(), "hi")
                self.assertEqual(len(asked), 1)  # write needed approval
                self.assertEqual(events[-1]["type"], "done")
                self.assertFalse([e for e in events if e["type"] == "error"])
                hdr, body = FakeBackend.requests[0]
                self.assertEqual({k.lower(): v for k, v in hdr.items()}["chatgpt-account-id"], "acct")
                self.assertFalse(body["store"])
                # replayed history must not contain server ids
                replay = FakeBackend.requests[1][1]["input"]
                self.assertTrue(all("id" not in i for i in replay))

                # denial path: file must not be written
                ag2 = Agent(d, FakeAuth(), "m", events.append, lambda s, b=None: False)
                os.remove(os.path.join(d, "hi.txt"))
                ag2.run("again")
                self.assertFalse(os.path.exists(os.path.join(d, "hi.txt")))
        finally:
            llm.BASE_URL = orig
            srv.shutdown()


class ModelsAndStatusTests(unittest.TestCase):
    def test_fetch_models(self):
        srv = HTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ms = llm.fetch_models(FakeAuth(), f"http://127.0.0.1:{srv.server_address[1]}")
        finally:
            srv.shutdown()
        self.assertEqual([m["slug"] for m in ms], ["gpt-a", "gpt-b"])  # hidden skipped, sorted by priority
        self.assertEqual(ms[0]["efforts"], ["low", "medium", "xhigh"])
        self.assertEqual(ms[0]["default_effort"], "medium")
        self.assertEqual(ms[1]["default_effort"], "high")
        self.assertIn("client_version=", FakeBackend.requests[-1][1])

    def test_status_formats(self):
        from pyharness import status
        now = time.time()
        a = {"plan_type": "plus", "rate_limit": {
            "primary_window": {"used_percent": 37, "limit_window_seconds": 18000, "reset_at": now + 4500},
            "secondary_window": {"used_percent": 80.5, "limit_window_seconds": 604800, "reset_after_seconds": 90000}}}
        txt = status.format_status(a, None, "me@x.com", "gpt-a", "high", {"in": 5, "out": 7}, "en")
        for want in ("plan plus", "5-hour window: 37% used · 63% available", "Weekly window: 80% used",
                     "gpt-a", "5 in · 7 out", "renews in 1h 14min"):
            self.assertIn(want, txt)
        pt = status.format_status(a, None, "me@x.com", "gpt-a", "high", {"in": 5, "out": 7}, "pt_br")
        for want in ("plano plus", "Janela de 5 horas: 37% usado · 63% disponível", "Janela semanal: 80% usado",
                     "5 entrada · 7 saída", "renova em 1h 14min"):
            self.assertIn(want, pt)
        b = {"rate_limits": {"primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": now + 60}}}
        self.assertIn("90% available", status.format_status(b, None, "", "m", "low", {}, "en"))
        self.assertIn("90% disponível", status.format_status(b, None, "", "m", "low", {}, "pt_br"))
        self.assertIn("Unknown response format", status.format_status({"x": 1}, None, "", "m", "low", {}, "en"))
        self.assertIn("Não foi possível", status.format_status(None, "boom", "", "m", "low", {}, "pt_br"))


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.sb = Sandbox(self.d.name)

    def tearDown(self):
        self.d.cleanup()

    def test_runs_and_reports_exit_code(self):
        out = tools.run_command(self.sb, "echo hello", "says hello")
        self.assertIn("exit code: 0", out)
        self.assertIn("hello", out)
        out = tools.run_command(self.sb, "echo oops 1>&2 && exit 3", "fails")
        self.assertIn("exit code: 3", out)
        self.assertIn("oops", out)  # stderr is captured too

    def test_runs_in_project_folder(self):
        cmd = "cd" if os.name == "nt" else "pwd"
        self.assertIn(os.path.realpath(self.d.name), tools.run_command(self.sb, cmd, "where am i"))
        os.mkdir(os.path.join(self.d.name, "sub"))
        self.assertIn("sub", tools.run_command(self.sb, cmd, "x", cwd="sub"))
        with self.assertRaises(ToolError):
            tools.run_command(self.sb, cmd, "x", cwd="..")  # working dir must stay inside the project

    @unittest.skipIf(os.name == "nt", "posix sleep")
    def test_timeout_kills(self):
        t = time.time()
        out = tools.run_command(self.sb, "echo start; sleep 20", "slow", timeout=1)
        self.assertLess(time.time() - t, 8)
        self.assertIn("TIMED OUT", out)
        self.assertIn("start", out)  # partial output kept

    @unittest.skipIf(os.name == "nt", "posix sleep")
    def test_stop_button_interrupts(self):
        self.sb.cancel = threading.Event()
        threading.Timer(0.7, self.sb.cancel.set).start()
        self.assertIn("STOPPED", tools.run_command(self.sb, "sleep 20", "slow", timeout=60))

    def test_command_always_asks_and_denial_never_runs(self):
        marker = os.path.join(self.d.name, "marker.txt")
        call = {"name": "run_command", "call_id": "c", "arguments": json.dumps(
            {"command": "echo x> marker.txt", "explanation": "creates a file"})}
        prompts = []
        ag = Agent(self.d.name, FakeAuth(), "m", lambda e: None, lambda s, b=None: prompts.append((s, b)) or False)
        out = ag._exec(call)
        self.assertEqual(len(prompts), 1)
        text, banner = prompts[0]
        self.assertIn("creates a file", text)
        self.assertIn("echo x> marker.txt", text)
        self.assertIsNone(banner)  # inside the working folder: normal colour
        self.assertIn("denied", out)
        self.assertFalse(os.path.exists(marker))  # denied -> never ran
        ag.approve = lambda s, b=None: True
        out = ag._exec(call)
        self.assertIn("exit code: 0", out)
        self.assertTrue(os.path.exists(marker))


class HtmlAndAgentsMdTests(unittest.TestCase):
    def _app(self, d, root=True):
        from pyharness.server import App
        proj = os.path.join(d, "proj")
        os.makedirs(proj, exist_ok=True)
        app = App(proj if root else None, "m", "low", os.path.join(d, "sess"), "en")
        app.auth = app.agent.auth = FakeAuth()
        return app, proj

    def test_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            app, proj = self._app(d)
            ins = app.agent.instructions(empty_chat=True)
            self.assertTrue(ins.startswith("LANGUAGE: always reply to the user in English"))  # language comes first
            self.assertIn("do NOT write Markdown", ins)
            self.assertIn("cdnjs.cloudflare.com", ins)
            self.assertNotIn("read it with read_file", ins)  # no file -> nothing to read
            with open(os.path.join(proj, "Agents.MD"), "w") as f:
                f.write("Use tabs.")
            first = app.agent.instructions(empty_chat=True)
            self.assertIn("empty chat", first)
            self.assertIn("read it with read_file", first)
            self.assertLess(first.index("read it with read_file"), first.index("do NOT write Markdown"))  # prepended
            self.assertNotIn("Use tabs.", first)  # the model reads the file itself
            self.assertNotIn("read it with read_file", app.agent.instructions(empty_chat=False))  # only for empty chats
            app.agent.html = False
            self.assertNotIn("sandboxed iframe", app.agent.instructions())
            self.assertIn("plain text", app.agent.instructions())

    def test_offer_and_decline(self):
        with tempfile.TemporaryDirectory() as d:
            app, proj = self._app(d)
            app.new_session()
            self.assertTrue(app.offer_agents)
            app.decline_agents()
            self.assertFalse(app.offer_agents)
            app2, _ = self._app(d)  # new process, same sessions folder
            app2.new_session()
            self.assertFalse(app2.offer_agents)  # remembered
        with tempfile.TemporaryDirectory() as d:
            app, proj = self._app(d)
            with open(os.path.join(proj, "AGENTS.md"), "w") as f:
                f.write("x")
            app.new_session()
            self.assertFalse(app.offer_agents)  # already has one

    def test_message_dismisses_offer(self):
        with tempfile.TemporaryDirectory() as d:
            app, proj = self._app(d)
            app.new_session()
            app.agent.run = lambda t: None
            app.start_turn("oi")
            self.assertFalse(app.offer_agents)

    def test_widget_sandbox_settings(self):
        from pyharness import server
        ui = server.UI
        self.assertIn('setAttribute("sandbox","allow-scripts")', ui)
        self.assertNotIn("allow-same-origin", ui)
        self.assertIn("connect-src 'none'", ui)  # widget CSP blocks all network requests
        self.assertIn("default-src 'none'", ui)
        self.assertIn("cdnjs.cloudflare.com", server.PAGE_CSP)  # inherited by srcdoc frames
        self.assertNotIn("connect-src 'none'", server.PAGE_CSP)


class OutsideFolderTests(unittest.TestCase):
    """Anything outside the working folder gets a red dialog (banner) and needs explicit approval."""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.proj = os.path.join(self.d.name, "proj")
        os.makedirs(self.proj)
        self.other = os.path.join(self.d.name, "other")
        os.makedirs(self.other)
        with open(os.path.join(self.other, "note.txt"), "w") as f:
            f.write("outside content")
        self.prompts = []
        self.answer = True
        self.ag = Agent(self.proj, FakeAuth(), "m", lambda e: None,
                        lambda s, b=None: self.prompts.append((s, b)) or self.answer, lang="en")

    def tearDown(self):
        self.d.cleanup()

    def call(self, name, **args):
        return self.ag._exec({"name": name, "call_id": "c", "arguments": json.dumps(args)})

    def test_read_outside_is_red_and_needs_approval(self):
        path = os.path.join(self.other, "note.txt")
        self.answer = False
        out = self.call("read_file", path=path)
        self.assertIn("denied", out)
        self.assertNotIn("outside content", out)
        text, banner = self.prompts[-1]
        self.assertEqual(banner, "The agent wants to read content, make sure it is not sensitive content")
        self.assertIn(path, text)
        self.answer = True
        self.assertIn("outside content", self.call("read_file", path=path))
        for tool, extra in (("list_dir", {"path": self.other}), ("grep", {"pattern": "outside", "path": self.other}),
                            ("dir_sizes", {"path": self.other})):
            self.prompts.clear()
            self.call(tool, **extra)
            self.assertIsNotNone(self.prompts[0][1], tool)

    def test_approval_applies_to_one_call_only(self):
        path = os.path.join(self.other, "note.txt")
        self.call("read_file", path=path)
        self.assertFalse(self.ag.sb.allow_outside)
        with self.assertRaises(ToolError):
            tools.read_file(self.ag.sb, path)  # direct use is still refused

    def test_inside_reads_do_not_prompt(self):
        with open(os.path.join(self.proj, "a.txt"), "w") as f:
            f.write("hi")
        self.call("read_file", path="a.txt")
        self.call("list_dir")
        self.assertEqual(self.prompts, [])

    def test_write_outside_is_red(self):
        target = os.path.join(self.other, "new.txt")
        self.answer = False
        self.call("write_file", path=target, content="x")
        self.assertFalse(os.path.exists(target))
        self.assertIn("outside the working folder", self.prompts[-1][1])
        self.answer = True
        self.call("write_file", path="../other/new.txt", content="x")  # '..' is outside too
        self.assertTrue(os.path.exists(target))
        self.prompts.clear()
        self.call("write_file", path="inside.txt", content="x")  # inside: normal colour
        self.assertEqual(len(self.prompts), 1)
        self.assertIsNone(self.prompts[0][1])

    def test_symlink_out_of_project_is_red(self):
        try:
            os.symlink(self.other, os.path.join(self.proj, "link"))
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks")
        self.call("read_file", path="link/note.txt")
        self.assertIsNotNone(self.prompts[-1][1])

    def test_harness_files_and_credentials_stay_protected_even_if_approved(self):
        out = self.call("write_file", path=os.path.join(tools.PKG_DIR, "evil.py"), content="x")
        self.assertIn("protected", out)
        self.assertFalse(os.path.exists(os.path.join(tools.PKG_DIR, "evil.py")))
        home = os.path.join(self.d.name, "home")
        os.makedirs(os.path.join(home, ".pyharness"))
        secret = os.path.join(home, ".pyharness", "auth.json")
        with open(secret, "w") as f:
            f.write("TOKEN")
        old = os.environ.get("HOME"), os.environ.get("USERPROFILE")
        os.environ["HOME"] = os.environ["USERPROFILE"] = home
        try:
            ag = Agent(self.proj, FakeAuth(), "m", lambda e: None, lambda s, b=None: True)
        finally:
            for k, v in zip(("HOME", "USERPROFILE"), old):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        out = ag._exec({"name": "read_file", "call_id": "c", "arguments": json.dumps({"path": secret})})
        self.assertIn("never accessible", out)
        self.assertNotIn("TOKEN", out)

    def test_command_heuristic(self):
        sb = self.ag.sb
        out = lambda c, cwd=None: sb.command_outside_paths(c, cwd or sb.root)
        self.assertTrue(out("cat ../other/note.txt"))
        self.assertTrue(out("cat " + os.path.join(self.other, "note.txt")))
        self.assertTrue(out("echo hi > ../x.txt"))
        self.assertTrue(out('type "C:\\Windows\\win.ini"') or os.name != "nt")
        if os.name != "nt":
            self.assertTrue(out("cat /etc/passwd"))
            self.assertTrue(out("cat ~/.ssh/id_rsa"))
            self.assertTrue(out("cat $HOME/.bashrc"))
        for harmless in ("echo hello", "ls -la", "python -m unittest", "curl https://example.com/a/b",
                         "sed -n '/foo/p' a.txt", "echo hi > /dev/null", "git log --oneline", "ls sub/.."):
            self.assertEqual(out(harmless), [], harmless)

    def test_command_outside_gets_red_banner_normal_commands_do_not(self):
        self.call("run_command", command="echo hello", explanation="says hello")
        self.assertIsNone(self.prompts[-1][1])  # web requests and commands stay the normal colour
        self.call("run_command", command="cat ../other/note.txt", explanation="reads a file")
        self.assertIn("outside the working folder", self.prompts[-1][1])
        self.call("run_command", command="echo hi", explanation="x", cwd="../other")
        self.assertIsNotNone(self.prompts[-1][1])
        self.prompts.clear()
        self.call("fetch_url", url="http://127.0.0.1/")  # asks (normal colour) even though it is then refused
        self.assertEqual(len(self.prompts), 1)
        self.assertIsNone(self.prompts[0][1])


class LanguageTests(unittest.TestCase):
    def test_every_key_exists_in_both_languages_with_same_placeholders(self):
        import string
        from pyharness import i18n
        en, pt = i18n.M["en"], i18n.M["pt_br"]
        self.assertEqual(set(en), set(pt))
        for k in en:
            f = lambda s: sorted(x[1] for x in string.Formatter().parse(s) if x[1])
            self.assertEqual(f(en[k]), f(pt[k]), k)
            self.assertNotEqual(en[k], pt[k], k)  # actually translated

    def test_language_instruction_and_prompts_follow_the_language(self):
        with tempfile.TemporaryDirectory() as d:
            for lang, want_rule, want_cmd, want_banner in (
                    ("en", "reply to the user in English", "RUN COMMAND", "wants to read content"),
                    ("pt_br", "Brazilian Portuguese", "EXECUTAR COMANDO", "quer ler conteúdo")):
                prompts = []
                ag = Agent(d, FakeAuth(), "m", lambda e: None, lambda s, b=None: prompts.append((s, b)) or False, lang=lang)
                self.assertTrue(ag.instructions().startswith("LANGUAGE:"))
                self.assertIn(want_rule, ag.instructions().split("\n")[0])
                ag._exec({"name": "run_command", "call_id": "c", "arguments": json.dumps({"command": "echo", "explanation": "x"})})
                self.assertIn(want_cmd, prompts[-1][0])
                ag._exec({"name": "read_file", "call_id": "c", "arguments": json.dumps({"path": os.path.dirname(d)})})
                self.assertIn(want_banner, prompts[-1][1])

    def test_language_choice_is_saved_and_restored(self):
        from pyharness.server import App
        with tempfile.TemporaryDirectory() as d:
            sess = os.path.join(d, "sess")
            app = App(None, "m", "low", sess)
            self.assertEqual(app.lang, "en")  # default
            app.set_lang("pt_br")
            self.assertEqual((app.agent.lang, app.auth.lang), ("pt_br", "pt_br"))
            with self.assertRaises(ValueError):
                app.set_lang("fr")
            self.assertEqual(App(None, "m", "low", sess).lang, "pt_br")  # remembered
            self.assertEqual(App(None, "m", "low", sess, "en").lang, "en")  # explicit --lang wins

    def test_approval_event_carries_banner(self):
        from pyharness.server import App
        with tempfile.TemporaryDirectory() as d:
            app = App(None, "m", "low", os.path.join(d, "sess"), "en")
            res = []
            th = threading.Thread(target=lambda: res.append(app.approve("text", "careful!")))
            th.start()
            for _ in range(100):
                ev = [e for e in app.events if e["type"] == "approval"]
                if ev:
                    break
                time.sleep(0.02)
            self.assertEqual((ev[0]["danger"], ev[0]["banner"]), (True, "careful!"))
            app.approvals[ev[0]["id"]]["allow"] = True
            app.approvals[ev[0]["id"]]["ev"].set()
            th.join(3)
            self.assertEqual(res, [True])
            th = threading.Thread(target=lambda: app.approve("plain"))
            th.start()
            time.sleep(0.2)
            self.assertFalse([e for e in app.events if e["type"] == "approval"][-1]["danger"])
            aid = [e for e in app.events if e["type"] == "approval"][-1]["id"]
            app.approvals[aid]["ev"].set()
            th.join(3)

    def test_ui_has_both_languages_and_requested_layout(self):
        from pyharness import server
        ui = server.UI
        self.assertIn('data-lang="en"', ui)
        self.assertIn('data-lang="pt_br"', ui)
        self.assertIn("Thinking...", ui)
        self.assertIn("Pensando...", ui)
        self.assertNotIn('id="mode"', ui)  # approval-mode dropdown removed
        self.assertNotIn("max-width:900px", ui)  # chat fills the whole width
        self.assertIn(".ap.danger", ui)
        self.assertIn('id="showcmds" checked', ui)  # "show commands" toggle is on by default
        self.assertIn("#log.clean .t.tool", ui)  # clean view hides tool lines...
        self.assertNotIn("#log.clean .ap{", ui)  # ...but never a pending permission dialog
        for k in ("allow", "deny", "offer_text", "thinking", "placeholder", "dlg_hint", "show_cmds", "show_cmds_tip"):
            self.assertIn(k + ":", ui.split("pt_br:{")[0])  # present in en...
            self.assertIn(k + ":", ui.split("pt_br:{")[1])  # ...and in pt_br


class SessionTests(unittest.TestCase):
    def test_save_and_resume(self):
        import time
        from pyharness.server import App
        srv = HTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        orig = llm.BASE_URL
        llm.BASE_URL = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            with tempfile.TemporaryDirectory() as d:
                proj = os.path.join(d, "proj")
                sess = os.path.join(proj, "myPyHarnessSessions")  # inside the project on purpose
                os.makedirs(proj)
                app = App(None, "m", "low", sess, "en")
                app.auth = app.agent.auth = FakeAuth()
                app.agent.approve = lambda s, b=None: True  # writes always ask now
                self.assertIsNotNone(app.check_ready())  # no directory yet
                app.agent.set_root(proj)
                self.assertIsNone(app.check_ready())
                app.new_session()
                self.assertTrue(app.start_turn("make a file"))
                for _ in range(100):
                    if not app.busy:
                        break
                    time.sleep(0.05)
                files = os.listdir(sess)
                self.assertEqual(len(files), 1)
                saved = json.load(open(os.path.join(sess, files[0]), encoding="utf-8"))
                self.assertEqual(saved["title"], "make a file")
                self.assertEqual(saved["transcript"][0]["type"], "user")
                self.assertTrue(any(t["type"] == "assistant" and t["text"] == "Done" for t in saved["transcript"]))

                # the agent must not be able to tamper with saved sessions
                with self.assertRaises(ToolError):
                    tools.write_file(app.agent.sb, "myPyHarnessSessions/x.json", "{}")

                # fresh app (simulates restart) resumes it
                app2 = App(None, "m", "low", sess, "en")
                app2.auth = app2.agent.auth = FakeAuth()
                self.assertEqual(app2.store.list()[0]["title"], "make a file")
                app2.resume(saved["id"])
                self.assertTrue(app2.started)
                self.assertEqual(app2.agent.sb.root, os.path.realpath(proj))
                self.assertEqual(app2.agent.history, saved["history"])
                replay = app2.events[app2.events.index({"type": "reset"}) + 1:]
                self.assertEqual([e["type"] for e in replay], [t["type"] for t in saved["transcript"]])
                with self.assertRaises(ValueError):
                    app2.store.load("../evil")
        finally:
            llm.BASE_URL = orig
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
