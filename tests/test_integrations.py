import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from mnemo import MemoryStore
from mnemo.extract import extract
from mnemo.hermes import MnemoMemoryProvider, install
from mnemo.http import make_handler
from mnemo.mcp import Server


class ExtractTests(unittest.TestCase):
    def test_extracts_preferences_rules_decisions(self):
        text = ("I prefer pnpm over npm. Can you fix the build? We decided to use SSE for live updates.\n"
                "Never force-push to main. What if we used Redis?")
        got = {(c.kind, c.content) for c in extract(text)}
        self.assertIn(("preference", "I prefer pnpm over npm."), got)
        self.assertIn(("decision", "We decided to use SSE for live updates."), got)
        self.assertIn(("procedure", "Never force-push to main."), got)
        self.assertEqual(len(got), 3)  # questions skipped


class StoreExtrasTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.s = MemoryStore(Path(self.d.name) / "m.db", embedder=None)

    def tearDown(self):
        self.s.close()
        self.d.cleanup()

    def test_feedback(self):
        m = self.s.remember("Deploys use Fly.io", scope="p", importance=0.15)
        self.assertAlmostEqual(self.s.feedback(m.id, True)["importance"], 0.25)
        r = self.s.feedback(m.id, False)
        r = self.s.feedback(m.id, False)
        self.assertTrue(r["flagged"])

    def test_conflicts(self):
        self.s.remember("The user's code editor is VS Code", scope="user")
        self.s.remember("The user's code editor is Neovim", scope="user")
        self.s.remember("Backups run nightly via restic", scope="user")
        pairs = self.s.conflicts("user")
        self.assertEqual(len(pairs), 1)
        self.assertIn("Neovim", pairs[0]["newer"]["content"])

    def test_find_and_exclude_kinds(self):
        self.s.remember("Talked about deploy pipeline", scope="p", kind="episode")
        f = self.s.remember("Deploy pipeline uses GitHub Actions", scope="p")
        self.assertEqual(self.s.find("deploy pipeline uses github actions!", scope="p").id, f.id)
        hits = self.s.recall("deploy pipeline", scope="p", exclude_kinds=["episode"])
        self.assertEqual([h.id for h in hits], [f.id])


class HermesProviderTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = str(Path(self.d.name) / "h.db")

    def tearDown(self):
        self.d.cleanup()

    def provider(self, **init):
        p = MnemoMemoryProvider(config={"db_path": self.db})
        self.assertTrue(p.is_available())
        p.initialize("sess-1", hermes_home=self.d.name, platform="cli", agent_identity="max", **init)
        return p

    def test_full_lifecycle(self):
        p = self.provider()
        self.assertIn("hermes/max", p.system_prompt_block())
        names = {t["name"] for t in p.get_tool_schemas()}
        self.assertIn("memory_remember", names)
        self.assertTrue(all("parameters" in t for t in p.get_tool_schemas()))

        out = json.loads(p.handle_tool_call("memory_remember", {"content": "Atlas uses PostgreSQL 16", "key": "atlas.db"}))
        self.assertTrue(out["result"].startswith("created"))
        p.sync_turn("I prefer terse answers without apologies. Please fix the Atlas migration.",
                    "Fixed the migration in 0042.", session_id="sess-1")
        p.on_memory_write("add", "user", "User lives in Tokyo")
        p.on_memory_write("replace", "user", "User lives in Osaka", {"previous_content": "User lives in Tokyo"})

        ctx = p.prefetch("where does the user live and how should I answer")
        self.assertIn("Osaka", ctx)
        self.assertNotIn("Tokyo", ctx)
        self.assertIn("terse answers", ctx)
        ctx = p.prefetch("atlas migration database")
        self.assertIn("PostgreSQL", ctx)
        self.assertIn("Related past conversation", ctx)
        self.assertEqual(p.prefetch("ok"), "")

        p.on_memory_write("remove", "user", "User lives in Osaka", {"previous_content": "User lives in Osaka"})
        self.assertNotIn("Osaka", p.prefetch("where does the user live"))
        self.assertIn("Saved to long-term memory",
                      p.on_pre_compress([{"role": "user", "content": "We decided to ship on Thursdays."}]))
        p.on_delegation("audit deps", "2 outdated packages", child_session_id="c1")
        p.shutdown()

    def test_subagent_is_read_only(self):
        p = self.provider(agent_context="subagent")
        out = json.loads(p.handle_tool_call("memory_remember", {"content": "should not save"}))
        self.assertIn("error", out)
        p.sync_turn("I prefer tabs", "ok")
        self.assertIn("No memories", json.loads(p.handle_tool_call("memory_recall", {"query": "tabs"}))["result"])
        p.shutdown()

    def test_install_layout(self):
        dest = install(self.d.name)
        init = (dest / "__init__.py").read_text()
        self.assertIn("register_memory_provider", init)
        self.assertTrue((dest / "mnemo" / "hermes.py").exists())
        self.assertTrue((dest / "plugin.yaml").exists())
        dest = install(self.d.name, link=True)  # re-install over a copy
        self.assertTrue((dest / "mnemo").is_symlink())


class HttpTests(unittest.TestCase):
    def test_http_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            store = MemoryStore(Path(d) / "m.db", embedder=None)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Server(store, "project/x"), "tok"))
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"

            def call(path, body=None, token="tok"):
                req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                             headers={"Authorization": f"Bearer {token}"})
                try:
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    with e:
                        return e.code, json.loads(e.read())

            self.assertEqual(call("/health")[0], 200)
            self.assertEqual(call("/health", token="bad")[0], 401)
            self.assertEqual(call("/tools/memory_remember", {"content": "Port is 4000"})[0], 200)
            code, body = call("/tools/memory_recall", {"query": "port"})
            self.assertEqual(code, 200)
            self.assertEqual(body["memories"][0]["content"], "Port is 4000")
            self.assertEqual(call("/tools/nope", {})[0], 404)
            self.assertEqual(call("/tools/memory_update", {"id": "missing", "content": "x"})[0], 400)
            httpd.shutdown()
            httpd.server_close()
            store.close()


if __name__ == "__main__":
    unittest.main()
