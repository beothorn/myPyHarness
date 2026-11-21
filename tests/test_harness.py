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
                ag = Agent(d, FakeAuth(), "m", events.append, lambda s: asked.append(s) or True)
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
                ag2 = Agent(d, FakeAuth(), "m", events.append, lambda s: False)
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
        txt = status.format_status(a, None, "me@x.com", "gpt-a", "high", {"in": 5, "out": 7})
        for want in ("plano plus", "Janela de 5 horas: 37% usado · 63% disponível", "Janela semanal: 80% usado",
                     "gpt-a", "5 entrada · 7 saída"):
            self.assertIn(want, txt)
        b = {"rate_limits": {"primary": {"usedPercent": 10, "windowDurationMins": 300, "resetsAt": now + 60}}}
        self.assertIn("90% disponível", status.format_status(b, None, "", "m", "low", {}))
        self.assertIn("desconhecido", status.format_status({"x": 1}, None, "", "m", "low", {}))
        self.assertIn("Não foi possível", status.format_status(None, "boom", "", "m", "low", {}))


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

    def test_always_asks_even_in_auto_mode(self):
        marker = os.path.join(self.d.name, "marker.txt")
        call = {"name": "run_command", "call_id": "c", "arguments": json.dumps(
            {"command": "echo x> marker.txt", "explanation": "creates a file"})}
        prompts = []
        ag = Agent(self.d.name, FakeAuth(), "m", lambda e: None, lambda s: prompts.append(s) or False, mode="auto")
        out = ag._exec(call)
        self.assertEqual(len(prompts), 1)  # asked although mode == auto
        self.assertIn("creates a file", prompts[0])
        self.assertIn("echo x> marker.txt", prompts[0])
        self.assertIn("denied", out)
        self.assertFalse(os.path.exists(marker))  # denied -> never ran
        ag.approve = lambda s: True
        out = ag._exec(call)
        self.assertIn("exit code: 0", out)
        self.assertTrue(os.path.exists(marker))

    def test_write_tools_skip_prompt_in_auto_but_command_does_not(self):
        self.assertTrue(tools.TOOLS["run_command"]["always_ask"])
        self.assertFalse(tools.TOOLS["write_file"]["always_ask"])


class HtmlAndAgentsMdTests(unittest.TestCase):
    def _app(self, d, root=True):
        from pyharness.server import App
        proj = os.path.join(d, "proj")
        os.makedirs(proj, exist_ok=True)
        app = App(proj if root else None, "m", "auto", "low", os.path.join(d, "sess"))
        app.auth = app.agent.auth = FakeAuth()
        return app, proj

    def test_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            app, proj = self._app(d)
            ins = app.agent.instructions()
            self.assertIn("do NOT write Markdown", ins)
            self.assertIn("cdnjs.cloudflare.com", ins)
            self.assertNotIn("AGENTS.md", ins)
            with open(os.path.join(proj, "Agents.MD"), "w") as f:
                f.write("Use tabs.")
            self.assertIn("Use tabs.", app.agent.instructions())
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
                app = App(None, "m", "auto", "low", sess)
                app.auth = app.agent.auth = FakeAuth()
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
                app2 = App(None, "m", "auto", "low", sess)
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
