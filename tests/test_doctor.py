import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from teresis.doctor import clients, run_doctor, setup, tomllib


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.home = Path(self.d.name)
        (self.home / ".claude.json").write_text(json.dumps({"numStartups": 3}))
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text('model = "gpt-5"\n')

    def tearDown(self):
        self.d.cleanup()

    def test_json_clients_configured_and_preserved(self):
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["claude-code"]["status"], "configured")
        data = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(data["numStartups"], 3)
        self.assertIn("teresis", data["mcpServers"])
        self.assertIn("serve", data["mcpServers"]["teresis"]["args"])
        cursor = json.loads((self.home / ".cursor" / "mcp.json").read_text())
        self.assertIn("other", cursor["mcpServers"])
        self.assertIn("teresis", cursor["mcpServers"])

    @unittest.skipIf(tomllib is None, "Codex TOML verification needs a parser")
    def test_toml_appended_and_idempotent(self):
        setup(self.home)
        text = (self.home / ".codex" / "config.toml").read_text()
        self.assertIn('model = "gpt-5"', text)
        self.assertEqual(text.count("[mcp_servers.teresis]"), 1)
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["codex"]["status"], "already")
        self.assertEqual((self.home / ".codex" / "config.toml").read_text().count("[mcp_servers.teresis]"), 1)

    def test_unparsed_codex_config_is_left_untouched(self):
        config = self.home / ".codex" / "config.toml"
        before = config.read_bytes()
        with patch("teresis.doctor.tomllib", None):
            result = setup(self.home, only=["codex"])[0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(config.read_bytes(), before)

    @unittest.skipIf(tomllib is None, "Codex TOML verification needs a parser")
    def test_invalid_codex_config_is_left_untouched(self):
        config = self.home / ".codex" / "config.toml"
        config.write_text("broken = [")
        self.assertEqual(setup(self.home, only=["codex"])[0]["status"], "failed")
        self.assertEqual(config.read_text(), "broken = [")

    def test_dry_run_writes_nothing(self):
        rows = {r["client"]: r for r in setup(self.home, dry_run=True)}
        self.assertEqual(rows["claude-code"]["status"], "configured")
        self.assertNotIn("mcpServers", json.loads((self.home / ".claude.json").read_text()))
        self.assertNotIn("[mcp_servers.teresis]", (self.home / ".codex" / "config.toml").read_text())

    def test_only_filter_and_missing_clients(self):
        rows = {r["client"]: r for r in setup(self.home, only=["cursor", "hermes"])}
        self.assertEqual(set(rows), {"cursor", "hermes"})
        self.assertEqual(rows["hermes"]["status"], "skipped")

    def test_bad_json_is_reported_not_clobbered(self):
        (self.home / ".claude.json").write_text("{not json")
        rows = {r["client"]: r for r in setup(self.home)}
        self.assertEqual(rows["claude-code"]["status"], "failed")
        self.assertEqual((self.home / ".claude.json").read_text(), "{not json")

    def test_hermes_install_is_partial_and_keeps_the_profile(self):
        h = self.home / ".hermes"
        h.mkdir()
        config = h / "config.yaml"
        config.write_text("memory:\n  provider: existing\n")
        db = self.home / "shared.db"
        result = setup(self.home, db=db, only=["hermes"])[0]
        self.assertEqual(result["status"], "partial")
        self.assertIn(str(db), result["detail"])
        self.assertTrue((h / "plugins/teresis/plugin.yaml").is_file())
        self.assertEqual(config.read_text(), "memory:\n  provider: existing\n")
        self.assertFalse(next(c["ok"] for c in run_doctor(db, home=self.home)["checks"]
                              if c["name"] == "client:hermes"))

    def test_general_setup_preserves_existing_hermes_install(self):
        from teresis.hermes import install

        h = self.home / ".hermes"
        h.mkdir()
        config = h / "config.yaml"
        config.write_bytes(b"memory:\n  provider: existing\n")
        dest = install(h, link=True)
        link = dest / "teresis"
        original = os.readlink(link)
        before = config.read_bytes()
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                result = setup(self.home, db=self.home / "shared.db", only=["hermes"], dry_run=dry_run)[0]
                self.assertEqual(result["status"], "partial")
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), original)
                self.assertEqual(config.read_bytes(), before)
                self.assertIn("unchanged", result["detail"])

    def test_general_setup_preserves_native_hermes_install(self):
        h = self.home / ".hermes"
        dest = h / "plugins" / "teresis"
        dest.mkdir(parents=True)
        config = h / "config.yaml"
        config.write_bytes(b"memory:\n  provider: native\n")
        files = {"__init__.py": b"# native plugin\n", "plugin.yaml": b"name: native\n"}
        for name, content in files.items():
            (dest / name).write_bytes(content)
        before = config.read_bytes()
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                result = setup(self.home, db=self.home / "shared.db", only=["hermes"], dry_run=dry_run)[0]
                self.assertEqual(result["status"], "partial")
                for name, content in files.items():
                    self.assertEqual((dest / name).read_bytes(), content)
                self.assertFalse((dest / "teresis").exists())
                self.assertEqual(config.read_bytes(), before)
                self.assertIn("unchanged", result["detail"])

    def test_general_setup_preserves_dangling_hermes_plugin_link(self):
        dest = self.home / ".hermes" / "plugins" / "teresis"
        dest.parent.mkdir(parents=True)
        dest.symlink_to("missing-plugin", target_is_directory=True)
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                result = setup(self.home, db=self.home / "shared.db", only=["hermes"], dry_run=dry_run)[0]
                self.assertEqual(result["status"], "partial")
                self.assertTrue(dest.is_symlink())
                self.assertEqual(os.readlink(dest), "missing-plugin")
                self.assertIn("unchanged", result["detail"])

    def test_general_setup_refuses_symlinked_hermes_plugin_root(self):
        h = self.home / ".hermes"
        h.mkdir()
        target = self.home / "plugin-target"
        target.mkdir()
        (h / "plugins").symlink_to(target, target_is_directory=True)
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                result = setup(self.home, db=self.home / "shared.db", only=["hermes"], dry_run=dry_run)[0]
                self.assertEqual(result["status"], "failed")
                self.assertIn("symlinked Hermes plugin directory", result["detail"])
                self.assertEqual(list(target.iterdir()), [])

    def test_setup_pins_two_real_mcp_processes_to_the_same_database(self):
        pinned = self.home / "shared dir" / "service 🪴.db"
        unrelated = self.home / "wrong.db"
        # Claude and Cursor are always testable. Also exercise the actual Codex-generated
        # command, where a genuine TOML parser is available.
        target = "codex" if tomllib is not None else "claude-code"
        source = Path(__file__).resolve().parents[1] / "src"
        env = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(source), PATH=str(self.home / "empty-bin"),
                   XDG_DATA_HOME=str(self.home / "data"), PYTHONDONTWRITEBYTECODE="1",
                   TERESIS_DB=str(unrelated))
        for key in list(env):
            if key.startswith(("TERESIS_EMBED", "TERESIS_RERANK")):
                env.pop(key)
        cli = [sys.executable, "-B", "-m", "teresis"]
        rows = subprocess.run([*cli, "setup", "--only", f"cursor,{target}", "--db", str(pinned), "--json"],
                              env=env, text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual([r["status"] for r in json.loads(rows.stdout)], ["configured", "configured"])
        cursor = json.loads((self.home / ".cursor/mcp.json").read_text())["mcpServers"]["teresis"]
        if target == "codex":
            writer = tomllib.loads((self.home / ".codex/config.toml").read_text())["mcp_servers"]["teresis"]
        else:
            writer = json.loads((self.home / ".claude.json").read_text())["mcpServers"]["teresis"]

        def call_tool(entry, name, arguments, process_env):
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}},
            ]
            result = subprocess.run([entry["command"], *entry["args"]],
                                    env={**process_env, **entry.get("env", {})}, text=True,
                                    input="\n".join(map(json.dumps, messages)) + "\n",
                                    capture_output=True, timeout=10, check=True)
            response = json.loads(result.stdout.splitlines()[-1])["result"]
            self.assertFalse(response["isError"], response)
            return response["structuredContent"]

        nonce = "apricot orbit z27"
        scope = "project/quality"
        written = call_tool(writer, "memory_remember", {"content": nonce, "scope": scope}, env)
        read_env = {k: v for k, v in env.items() if k != "TERESIS_DB"}
        recalled = call_tool(cursor, "memory_recall", {"query": nonce, "scope": scope, "inherit": False}, read_env)
        self.assertEqual([m["id"] for m in recalled["memories"]], [written["id"]])
        self.assertFalse(unrelated.exists())
        self.assertFalse((self.home / "data/teresis/memory.db").exists())


class DoctorTests(unittest.TestCase):
    def test_healthy_on_fresh_db(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            db = home / "doctor.db"
            setup(home, db=db)  # An installed client must be configured for the DB under test.
            res = run_doctor(db, home=home)
            names = {c["name"]: c for c in res["checks"]}
            self.assertTrue(names["python"]["ok"])
            self.assertTrue(names["sqlite-fts5"]["ok"])
            self.assertTrue(names["store"]["ok"])
            self.assertTrue(names["graph"]["ok"])
            self.assertEqual(res["failed"], 0)
            self.assertTrue(res["ok"])

    def test_unconfigured_client_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
            res = run_doctor(home / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertFalse(claude["ok"])
            self.assertFalse(res["ok"])

    def test_reports_configured_clients(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
            res = run_doctor(Path(d) / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertFalse(claude["ok"])
            self.assertIn("teresis setup", claude["detail"])
            setup(home, db=Path(d) / "x.db")
            res = run_doctor(Path(d) / "x.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertTrue(claude["ok"])
            self.assertIn("agent not started", claude["detail"])
            res = run_doctor(Path(d) / "other.db", home=home)
            claude = next(c for c in res["checks"] if c["name"] == "client:claude-code")
            self.assertFalse(claude["ok"])

    def test_nonempty_unpinned_launcher_is_not_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            config = home / ".claude.json"
            config.write_text(json.dumps({"mcpServers": {"teresis": {"command": "/missing", "args": ["serve"]}}}))
            res = run_doctor(home / "x.db", home=home)
            self.assertFalse(res["ok"])
            self.assertFalse(next(c["ok"] for c in res["checks"] if c["name"] == "client:claude-code"))

    @unittest.skipIf(tomllib is None, "Codex TOML verification needs a parser")
    def test_disabled_codex_launcher_is_not_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            config = home / ".codex" / "config.toml"
            config.parent.mkdir()
            db = home / "shared.db"
            setup(home, db=db, only=["codex"])
            with config.open("a") as f:
                f.write('"enabled" = false\n')
            res = run_doctor(db, home=home)
            self.assertFalse(res["ok"])
            self.assertFalse(next(c["ok"] for c in res["checks"] if c["name"] == "client:codex"))

    def test_client_detection(self):
        with tempfile.TemporaryDirectory() as d:
            ids = {c.id for c in clients(Path(d))}
            self.assertEqual(ids, {"claude-code", "cursor", "codex", "hermes"})


if __name__ == "__main__":
    unittest.main()
